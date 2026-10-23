# B: build a patched rootfs from `system.img` + `vendor.img`

This is the supported rootfs builder.  It does **not** build an ARM translation
layer: `libndk`/`houdini` is an external overlay that you apply on top of the
output (or in a later image layer).

## Input

| input | format |
| --- | --- |
| `--system PATH` | raw ext4 `system.img` (Android sparse is converted with `simg2img`) |
| `--vendor PATH` | raw ext4 `vendor.img` (same) |
| `--sha256-system` / `--sha256-vendor` | optional expected checksums; mismatch aborts |
| `--source-date-epoch` | tar mtime (default `$SOURCE_DATE_EPOCH` or `0`) |

The system and vendor images must be a matched pair; their `ro.build.version.sdk`
is checked.

## Output

`--out DIR` is an output bundle; an existing directory is only replaced with
`--force`, and only after a complete build:

```
DIR/
  rootfs/          patched rootfs tree
                   (system partition root; vendor.img contents under vendor/)
  manifest.json    schema 1: inputs, checksums, android props, patches, output stats
  rootfs.tar       only with --tar; deterministic for `podman import`
```

`manifest.json` records:

- input paths/sha256/size;
- `android.sdk`, `vendor_sdk`, system/vendor fingerprints, `abilist`;
- patches applied (`bpfloader`, `zygote_priority`, `keychords`) and warnings;
- output file count/bytes, tar sha256/size;
- `source_date_epoch`.

## Usage

```sh
./image/build-rootfs.sh \
    --system /usr/share/waydroid-extra/images/system.img \
    --vendor /usr/share/waydroid-extra/images/vendor.img \
    --out build-rootfs --tar --force

# Turn the patched rootfs into the OCI image the runtime boots:
podman import build-rootfs/rootfs.tar localhost/waydroid:13
```

Then point the runtime at that tag (for example
`WAYDROID_IMAGE=localhost/waydroid:13 ./install-rootless.sh install`, or set
`podman_image` in `waydroid.cfg`).

The tar is reproducible for a fixed input: two builds produced the same
`tar_sha256` (`--sort=name --numeric-owner --owner=0 --group=0 --mtime=@SDE`).

## Patches applied to the rootfs

- `system/etc/init/bpfloader.rc`: replace eBPF loading with
  `setprop bpf.progs_loaded 1`.
- `system/etc/init/hw/init.zygote64_32.rc`: remove `priority -N` (fails without
  `CAP_SYS_NICE` in the initial namespace).
- `system/system_ext/etc/init/init.lineage-system_ext.rc`: remove `keycodes`
  (keychord watcher blocks on a desktop input FIFO).

The expected zygote rc file is required (the build fails if the input is not a
supported Waydroid image); missing optional files are recorded as warnings.

## What is not here

- **ARM translation layer.**  `libndk_translation` prebuilts and the ten `ro.*`
  properties are your overlay; they are not read or copied by this builder.
- **OCI publishing.**  The output is a rootfs bundle; `podman import`/`buildah`
  and registry push/sign are the next pipeline stage.
- **SELinux/xattr/capabilities.**  Rootless extraction drops them (the legacy
  image path does the same); the container runs with `label=disable`.

## Future: A (direct OCI from the Android build)

AOSP has no `system.tar`/Docker target, but `make target-files-package` emits
`SYSTEM/`, `VENDOR/`, ... plus `META/*_filesystem_config.txt` (per-file
uid/gid/mode/caps).  A later pipeline can apply `fs_config` to a tar and import
it directly, avoiding the `system.img` extract; the runtime patches would move
into the device/product tree.  This is recorded for later; B is the current
supported path.
