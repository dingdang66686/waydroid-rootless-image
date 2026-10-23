# waydroid-rootless-image

[![image](https://github.com/dingdang66686/waydroid-rootless-image/actions/workflows/image.yml/badge.svg)](https://github.com/dingdang66686/waydroid-rootless-image/actions/workflows/image.yml)

Build and publish the bootable OCI image for the
[rootless Waydroid podman backend](https://github.com/dingdang66686/waydroid-rootless).

The builder takes a matched `system.img` + `vendor.img` pair, applies the
rootless runtime patches to the rootfs, and emits:

```
out/
  rootfs/          patched rootfs (system partition root; vendor.img under vendor/)
  manifest.json    input checksums, Android props, patches, output stats
  rootfs.tar       deterministic tar for podman import (--tar)
```

The contract is documented in [BUILD.md](BUILD.md).  The published image is the
**plain patched x86_64 rootfs**; `libndk`/ARM translation is an external overlay,
not part of this build.

The runtime lives in
[dingdang66686/waydroid-rootless](https://github.com/dingdang66686/waydroid-rootless).

## Published image

```sh
podman pull ghcr.io/dingdang66686/waydroid-rootless-image:13
```

Tags produced by CI:

- `13` — the default Android 13 image
- `sha-<short-sha>` — immutable build tag
- `latest` — only for `main`

Point the runtime at it with `podman_image` in `waydroid.cfg`, or install with
`WAYDROID_IMAGE=ghcr.io/dingdang66686/waydroid-rootless-image:13` (see the
runtime repository).  If the GHCR package is private, `podman login ghcr.io`
first.

## Local build

Requirements: `podman`, `e2fsprogs` (`debugfs`) or `fuse2fs` + `/dev/fuse`,
`tar`, and about 7 GB free (rootfs + tar + image import).

```sh
./build-rootfs.sh \
    --system /usr/share/waydroid-extra/images/system.img \
    --vendor /usr/share/waydroid-extra/images/vendor.img \
    --out build-rootfs --tar --force

podman import build-rootfs/rootfs.tar localhost/waydroid:13
```

Use `--sha256-system` / `--sha256-vendor` to pin the inputs, and
`SOURCE_DATE_EPOCH` to control the tar mtime.  Both raw and Android-sparse ext4
images are accepted (`simg2img` is used for sparse inputs).

The legacy `extract.sh` + `build.sh` + `Containerfile` chain is kept as an
optional image/ARM example; the CI and the supported path use
`build-rootfs.{py,sh}`.  The ARM prebuilts are proprietary and are not committed
or built here.

## GitHub Actions / GHCR

The workflow is [`.github/workflows/image.yml`](.github/workflows/image.yml).
It runs on pushes to `main` (builder/workflow changes), tags `v*`, and
`workflow_dispatch`, then imports the rootfs and pushes the tags above to
`ghcr.io/${{ github.repository }}`.

The default image source is the pinned CachyOS `waydroid-image` package:

```text
waydroid-image 1:20.0.20260510-1 (x86_64)
https://us.cachyos.org/repo/x86_64/cachyos/waydroid-image-1:20.0.20260510-1-x86_64.pkg.tar.zst
sha256 f5a1238050d6e58184748143c86e35dd6ed5ae6dc3851f7a0dd83743d676d3b4
```

The workflow extracts `usr/share/waydroid-extra/images/{system,vendor}.img`
from that package.  Override the source in either of two ways:

| repository variable / secret | meaning |
| --- | --- |
| `WAYDROID_IMAGE_PACKAGE_URL` | package URL (`.pkg.tar.zst`) |
| `WAYDROID_IMAGE_PACKAGE_SHA256` | package checksum (optional for custom URLs) |
| `WAYDROID_SYSTEM_URL` + `WAYDROID_VENDOR_URL` | direct raw ext4 images; both must be set |
| `WAYDROID_SYSTEM_SHA256` + `WAYDROID_VENDOR_SHA256` | optional direct-image checksums |

For a manual run, the same values are available as `workflow_dispatch` inputs
(`package_url`, `package_sha256`, `system_url`, `vendor_url`,
`system_sha256`, `vendor_sha256`, `tag`).  Inputs take precedence over
variables, then secrets, then the pinned default.

The workflow needs the repository's `GITHUB_TOKEN` with `packages: write`; it
logs in to `ghcr.io` as `${{ github.actor }}`.  The GHCR package follows the
repository visibility (public here); if it is ever switched to private, set it
public once in the package settings or `podman login ghcr.io` before pulling.

The CachyOS package is GPL-3.0-only; the image contains LineageOS/Waydroid
artefacts from that package.  Check the licensing that applies to your
distribution before publishing the image publicly.

## Files

- `build-rootfs.py` / `build-rootfs.sh` — supported builder
- `BUILD.md` — input/output/manifest contract
- `extract.sh` — optional legacy plain-rootfs extraction
- `build.sh`, `Containerfile`, `fetch-prebuilts.sh` — optional legacy image/ARM
  example (not used by CI)
- `.github/workflows/image.yml` — build + GHCR publish

## License

GPL-3.0-only; see [LICENSE](LICENSE).
