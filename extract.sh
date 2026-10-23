#!/bin/bash
# Extract Waydroid system.img / vendor.img into a plain directory tree.
# Runs entirely as the unprivileged user (fuse2fs), so every extracted file is
# owned by the user -> appears as uid 0 inside the keep-id container.
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-/usr/share/waydroid-extra/images}"
ROOTFS="$BASE/rootfs"
MNT="$BASE/tmp/mnt"

mkdir -p "$ROOTFS" "$MNT"

log() { printf '[extract] %s\n' "$*"; }

# preserve mode/timestamps/links only.
# - ownership: we WANT every file owned by the unprivileged user (= uid 0 in container)
# - xattr / context: security.selinux cannot be set as non-root -> must be dropped
#   (cp -a implies --preserve=all, which includes both xattr and SELinux context)
CP=(cp -a --no-preserve=ownership,xattr,context)

if [ -e "$ROOTFS/system/build.prop" ]; then
    log "system already extracted, skipping"
else
    log "mounting system.img via fuse2fs"
    fuse2fs -o ro,fakeroot "$SRC/system.img" "$MNT"
    log "copying system -> $ROOTFS"
    "${CP[@]}" "$MNT/." "$ROOTFS/"
    fusermount3 -u "$MNT"
    log "system done"
fi

if [ -e "$ROOTFS/vendor/build.prop" ]; then
    log "vendor already extracted, skipping"
else
    log "mounting vendor.img via fuse2fs"
    fuse2fs -o ro,fakeroot "$SRC/vendor.img" "$MNT"
    mkdir -p "$ROOTFS/vendor"
    log "copying vendor -> $ROOTFS/vendor"
    "${CP[@]}" "$MNT/." "$ROOTFS/vendor/"
    fusermount3 -u "$MNT"
    log "vendor done"
fi

log "sizes:"
du -sh "$ROOTFS" "$ROOTFS/system" "$ROOTFS/vendor" 2>/dev/null || true
log "OK"
