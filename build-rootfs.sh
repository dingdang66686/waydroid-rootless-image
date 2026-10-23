#!/bin/sh
# Convenience wrapper for build-rootfs.py.
exec python3 "$(dirname "$0")/build-rootfs.py" "$@"
