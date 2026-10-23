# waydroid-rootless: boot the Android image with rootless podman.
#
#   localhost/waydroid-base:13      ./rootfs as an image (podman import, build.sh)
#   localhost/waydroid-tweaked:13   base + the rootless runtime overrides
#   localhost/waydroid-arm64:13     tweaked + the libndk ARM translation layer
#
# Build them with ./build.sh and boot them with
#
#     WD_ROOTFS_IMAGE=localhost/waydroid-arm64:13 ./run.sh -d
#
# Every instruction below is a COPY on purpose.  The Android rootfs cannot run a
# single program before its APEXes are mounted: /system/bin/sh is a bionic
# binary whose interpreter /system/bin/linker64 is a symlink into
# /apex/com.android.runtime/bin/, which is an empty directory on disk and only
# gets a filesystem when init mounts the flattened APEXes.  (Verified: a clean
#
#     podman run localhost/waydroid-base:13 /system/bin/sh -c 'echo hi'
#
# fails with "exec container process (missing dynamic library?)".)  So there is
# no RUN to be had here -- neither sed, nor chmod, nor any /system/bin tool --
# and build.sh derives the handful of changed files on the host instead.  That
# also keeps the build free of any additional base image to pull.

ARG BASE=localhost/waydroid-base:13

# ---- rootless runtime overrides --------------------------------------
# The three files run.sh would otherwise bind in on every run.  They are pure
# file content (no host state), so they belong in the image; run.sh carries the
# long explanation for each one and build.sh shows how they are derived.
FROM ${BASE} AS tweaked
COPY build/tweaks/ /

# ---- libndk ARM translation layer -------------------------------------
# Google's ndk_translation prebuilts -- the Android 13 "chromeos_zork R136"
# drop that waydroid_script also installs -- under /system, plus the "ro.*"
# properties that switch the native bridge on.  The prebuilts are proprietary
# and are *not* part of waydroid-rootless: they only live in this local image.
# See README.md and fetch-prebuilts.sh.
FROM tweaked AS arm
COPY prebuilts/ /system/
COPY build/armprops/ /
