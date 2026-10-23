#!/usr/bin/env python3
#
# build-rootfs.py - input: raw (or sparse) system.img + vendor.img
#                   output: patched rootfs tree + manifest.json (+ optional tar)
#
# This is the "B" pipeline: extract the Android images, apply the rootless
# runtime patches to the tree, and leave a rootfs that can be imported into an
# OCI image (`podman import out/rootfs.tar <tag>`).  It deliberately does not
# know about the ARM translation layer: that is a separate overlay.
#
# Output layout:
#   <out>/
#     rootfs/          patched rootfs (system partition root; vendor/ from vendor.img)
#     manifest.json    inputs, checksums, patches, output stats
#     rootfs.tar       only with --tar; deterministic (owner 0, sorted, SOURCE_DATE_EPOCH)
#
# Exit status is non-zero on any error; the output directory is replaced
# atomically only after a complete build (use --force to replace an existing
# output).

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BPFLOADER_RC = """\
# installed by the rootless build: a rootless container cannot load eBPF, so
# publish the property (and the attached programs) its consumers wait for.
on load_bpf_programs
    setprop bpf.progs_loaded 1
"""


def log(msg):
    print("[build-rootfs] " + msg, flush=True)


def run(cmd, **kwargs):
    log("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_brief(path):
    try:
        return subprocess.run(["file", "-b", str(path)], capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return ""


def is_sparse(path):
    return "Android sparse image" in file_brief(path)


def is_ext4(path):
    if not shutil.which("dumpe2fs"):
        return True
    return subprocess.run(["dumpe2fs", "-h", str(path)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def prop(path, key):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1]
    except OSError:
        pass
    return ""


def unmount(mnt):
    for cmd in (["fusermount3", "-u", mnt], ["fusermount", "-u", mnt],
                ["umount", mnt]):
        tool = shutil.which(cmd[0])
        if tool:
            subprocess.run([tool] + cmd[1:], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def extract_with_fuse(image, dst):
    if not (shutil.which("fuse2fs") and os.path.exists("/dev/fuse")):
        return False
    mnt = dst.parent / (dst.name + ".mnt")
    mnt.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)
    try:
        run(["fuse2fs", "-o", "ro,fakeroot", str(image), str(mnt)])
        run(["cp", "-a", "--no-preserve=ownership,xattr,context",
             str(mnt) + "/.", str(dst) + "/"])
        return True
    except subprocess.CalledProcessError:
        log("fuse2fs/cp failed; will fall back to debugfs")
        return False
    finally:
        unmount(mnt)
        shutil.rmtree(mnt, ignore_errors=True)


def extract_with_debugfs(image, dst):
    if not shutil.which("debugfs"):
        raise SystemExit("need fuse2fs (+/dev/fuse) or debugfs (e2fsprogs)")
    dst.mkdir(parents=True, exist_ok=True)
    run(["debugfs", "-R", "rdump / {}".format(dst), str(image)])


def extract_image(image, dst, scratch):
    image = Path(image)
    if not image.is_file():
        raise SystemExit("input image not found: {}".format(image))
    brief = file_brief(image)
    raw = None
    try:
        if is_sparse(image):
            if not shutil.which("simg2img"):
                raise SystemExit("{} is a sparse image; install simg2img".format(image))
            raw = Path(scratch) / (dst.name + ".raw")
            run(["simg2img", str(image), str(raw)])
            image = raw
        if not is_ext4(image):
            raise SystemExit("{} is not an ext4 image ({}).".format(image, brief))
        if extract_with_fuse(image, dst):
            return
        if dst.exists():
            shutil.rmtree(dst)
        extract_with_debugfs(image, dst)
    finally:
        if raw is not None:
            raw.unlink(missing_ok=True)


def fix_permissions(root):
    run(["find", str(root), "-xdev", "-type", "f", "!", "-perm", "-o=r",
         "-exec", "chmod", "a+rX", "{}", "+"])
    run(["find", str(root), "-xdev", "-type", "d", "!", "-perm", "-o=x",
         "-exec", "chmod", "a+X", "{}", "+"])


def patch_rootfs(root):
    patches = {}
    warnings = []

    bpf = root / "system/etc/init/bpfloader.rc"
    bpf.parent.mkdir(parents=True, exist_ok=True)
    bpf.write_text(BPFLOADER_RC, encoding="utf-8")
    patches["bpfloader"] = "replaced"

    zygote = root / "system/etc/init/hw/init.zygote64_32.rc"
    if not zygote.is_file():
        raise SystemExit("missing {}; the input is not a supported Waydroid "
                         "system image".format(zygote.relative_to(root)))
    lines = zygote.read_text(encoding="utf-8", errors="ignore").splitlines(True)
    kept = [line for line in lines
            if not re.match(r"^\s*priority\s+-\d+\s*$", line)]
    zygote.write_text("".join(kept), encoding="utf-8")
    removed = len(lines) - len(kept)
    patches["zygote_priority"] = "removed {} line(s)".format(removed)
    if removed == 0:
        warnings.append("no 'priority -N' line found in init.zygote64_32.rc")

    keychord = root / "system/system_ext/etc/init/init.lineage-system_ext.rc"
    if keychord.is_file():
        lines = keychord.read_text(encoding="utf-8", errors="ignore").splitlines(True)
        kept = [line for line in lines
                if not re.match(r"^\s*keycodes(\s|$)", line)]
        keychord.write_text("".join(kept), encoding="utf-8")
        removed = len(lines) - len(kept)
        patches["keychords"] = "removed {} line(s)".format(removed)
        if removed == 0:
            warnings.append("no 'keycodes' line found in init.lineage-system_ext.rc")
    else:
        patches["keychords"] = "file absent"
        warnings.append("init.lineage-system_ext.rc not present")

    return patches, warnings


def output_stats(root):
    files = 0
    size = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            files += 1
            try:
                size += os.lstat(path).st_size
            except OSError:
                pass
    return {"files": files, "bytes": size}


def write_tar(root, tar_path, epoch):
    run(["tar", "--sort=name", "--numeric-owner", "--owner=0", "--group=0",
         "--mtime=@{}".format(epoch), "-C", str(root), "-cf", str(tar_path), "."])


def main():
    here = Path(__file__).resolve().parent
    default_images = Path("/usr/share/waydroid-extra/images")
    parser = argparse.ArgumentParser(
        description="Build a patched Waydroid rootfs from system.img/vendor.img")
    parser.add_argument("--system", default=str(default_images / "system.img"),
                        help="raw or sparse system image")
    parser.add_argument("--vendor", default=str(default_images / "vendor.img"),
                        help="raw or sparse vendor image")
    parser.add_argument("--out", default=str(here / "build-rootfs"),
                        help="output bundle directory")
    parser.add_argument("--tar", action="store_true",
                        help="also write a deterministic rootfs.tar for podman import")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing output directory")
    parser.add_argument("--sha256-system", default="",
                        help="expected sha256 of the system image")
    parser.add_argument("--sha256-vendor", default="",
                        help="expected sha256 of the vendor image")
    parser.add_argument("--source-date-epoch", default=os.environ.get("SOURCE_DATE_EPOCH", "0"),
                        help="mtime for the tar (default: $SOURCE_DATE_EPOCH or 0)")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.exists() and not args.force:
        raise SystemExit("{} exists; use --force to replace it".format(out))
    if not re.match(r"^\d+$", args.source_date_epoch):
        raise SystemExit("--source-date-epoch must be a Unix timestamp")

    log("system: {}".format(args.system))
    log("vendor: {}".format(args.vendor))
    log("output: {}".format(out))

    system_sha = sha256(args.system)
    vendor_sha = sha256(args.vendor)
    if args.sha256_system and system_sha != args.sha256_system:
        raise SystemExit("system sha256 mismatch: {} != {}".format(
            system_sha, args.sha256_system))
    if args.sha256_vendor and vendor_sha != args.sha256_vendor:
        raise SystemExit("vendor sha256 mismatch: {} != {}".format(
            vendor_sha, args.sha256_vendor))

    # The build needs room for the new rootfs (+ tar) and, with --force, for
    # the previous output until the atomic rename.  Abort early with a clear
    # message instead of failing at tar time on a small tmpfs.
    input_size = os.path.getsize(args.system) + os.path.getsize(args.vendor)
    copies = 2 if args.tar else 1
    if out.exists() and args.force:
        copies *= 2
    need = int(input_size * copies * 1.1)
    out.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out.parent).free
    log("free space: {:.1f} GiB (need ~{:.1f} GiB)".format(
        free / 2**30, need / 2**30))
    if free < need:
        raise SystemExit(
            "not enough space on {}: {:.1f} GiB free, need ~{:.1f} GiB; "
            "choose --out on a larger filesystem".format(
                out.parent, free / 2**30, need / 2**30))

    tmp = Path(str(out) + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    root = tmp / "rootfs"

    try:
        log("extracting system image")
        extract_image(args.system, root, tmp)
        log("extracting vendor image")
        extract_image(args.vendor, root / "vendor", tmp)
        fix_permissions(root)

        log("applying rootless patches")
        patches, warnings = patch_rootfs(root)

        sdk = (prop(root / "system/build.prop", "ro.build.version.sdk")
               or prop(root / "build.prop", "ro.build.version.sdk"))
        vendor_sdk = (prop(root / "vendor/build.prop", "ro.vendor.build.version.sdk")
                      or prop(root / "vendor/build.prop", "ro.build.version.sdk"))
        if sdk and vendor_sdk and sdk != vendor_sdk:
            raise SystemExit("system/vendor SDK mismatch: {} vs {}".format(
                sdk, vendor_sdk))
        system_fp = (prop(root / "system/build.prop", "ro.system.build.fingerprint")
                     or prop(root / "system/build.prop", "ro.build.fingerprint"))
        vendor_fp = (prop(root / "vendor/build.prop", "ro.vendor.build.fingerprint")
                     or prop(root / "vendor/build.prop", "ro.build.fingerprint"))
        abilist = (prop(root / "system/build.prop", "ro.system.product.cpu.abilist")
                   or prop(root / "system/build.prop", "ro.product.cpu.abilist")
                   or prop(root / "vendor/build.prop", "ro.vendor.product.cpu.abilist"))

        stats = output_stats(root)
        manifest = {
            "schema": 1,
            "tool": {
                "name": "build-rootfs",
                "source_date_epoch": int(args.source_date_epoch),
            },
            "generated": datetime.now(timezone.utc).isoformat(),
            "layout": "system partition root; vendor.img contents under vendor/",
            "inputs": {
                "system": {
                    "path": str(Path(args.system).resolve()),
                    "sha256": system_sha,
                    "size": os.path.getsize(args.system),
                },
                "vendor": {
                    "path": str(Path(args.vendor).resolve()),
                    "sha256": vendor_sha,
                    "size": os.path.getsize(args.vendor),
                },
            },
            "android": {
                "sdk": sdk,
                "vendor_sdk": vendor_sdk,
                "system_fingerprint": system_fp,
                "vendor_fingerprint": vendor_fp,
                "abilist": abilist,
            },
            "patches": patches,
            "warnings": warnings,
            "output": {
                "rootfs": "rootfs",
                "files": stats["files"],
                "bytes": stats["bytes"],
            },
        }

        if args.tar:
            tar = tmp / "rootfs.tar"
            log("writing {}".format(tar))
            write_tar(root, tar, args.source_date_epoch)
            manifest["output"]["tar"] = "rootfs.tar"
            manifest["output"]["tar_sha256"] = sha256(tar)
            manifest["output"]["tar_size"] = tar.stat().st_size

        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        log("manifest: {}".format(tmp / "manifest.json"))

        if out.exists():
            shutil.rmtree(out)
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    log("done: {}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
