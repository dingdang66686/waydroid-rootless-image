#!/usr/bin/env bash
#
# fetch-prebuilts.sh - (re)create image/prebuilts, the libndk ARM translation
# layer that the "arm" image target copies into /system.
#
# The files come from Google's ndk_translation prebuilt as repackaged by
# waydroid_script (stuff/ndk.py), pinned to the Android 13 revision:
#
#   repo    https://github.com/supremegamers/vendor_google_proprietary_ndk_translation-prebuilt
#   commit  68734c52556d3d7a6db34c603dd9276915c29f2f   ("chromeos_zork R136")
#   zip md5 0b2207c490fcb400aa5c87fcf0d52d38             (waydroid_script's check)
#
# These are proprietary Google binaries.  They are not part of waydroid-rootless
# and only ever go into a locally built image; see README.md.
#
# Usage:  ./fetch-prebuilts.sh [destination]   (default: image/prebuilts)
#         ./fetch-prebuilts.sh --check         (verify against prebuilts.sha256)
#
# GitHub itself is often unreachable behind this sandbox's allowlist; the
# GITCLONE_MIRROR below is tried first when set.
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "--check" ]]; then
    cd "${2:-$HERE/prebuilts}"
    exec sha256sum -c "$HERE/prebuilts.sha256"
fi

DEST="${1:-$HERE/prebuilts}"
COMMIT="68734c52556d3d7a6db34c603dd9276915c29f2f"
GITCLONE_MIRROR="${GITCLONE_MIRROR:-https://gitclone.com/github.com/supremegamers/vendor_google_proprietary_ndk_translation-prebuilt}"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/ndkpre.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

say() { printf '[prebuilts] %s\n' "$*" >&2; }

clone() {
    local url="$1" i
    for i in 1 2 3 4 5; do
        say "git clone --depth 1 $url (attempt $i)"
        if git clone --depth 1 -q "$url" "$TMP/src" 2>/dev/null; then return 0; fi
        rm -rf "$TMP/src"; sleep 3
    done
    return 1
}

if [[ -n "${GITCLONE_MIRROR:-}" ]] && clone "$GITCLONE_MIRROR"; then
    :
elif clone "https://github.com/supremegamers/vendor_google_proprietary_ndk_translation-prebuilt"; then
    :
else
    echo "could not clone the prebuilt repo (try GITCLONE_MIRROR=...)" >&2
    exit 1
fi

say "checking out $COMMIT"
git -C "$TMP/src" fetch -q --depth 1 origin "$COMMIT"
git -C "$TMP/src" checkout -q "$COMMIT"

# The repository's prebuilts/ directory *is* the content of /system.
[[ -d "$TMP/src/prebuilts" ]] || { echo "unexpected repo layout" >&2; exit 1; }
rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$TMP/src/prebuilts/." "$DEST/"

say "wrote $(find "$DEST" -type f | wc -l) files, $(du -sh "$DEST" | cut -f1)"

( cd "$DEST" && find . -type f | LC_ALL=C sort | xargs sha256sum ) > "$HERE/prebuilts.sha256"
say "wrote $HERE/prebuilts.sha256; verify with $0 --check"
