#!/usr/bin/env bash
# Download and unpack python-build-standalone into src-tauri/resources/python
# Usage: ./resources/scripts/fetch_python.sh macos aarch64
set -euo pipefail
OS="${1:-}"
ARCH="${2:-}"
if [[ -z "$OS" || -z "$ARCH" ]]; then
  echo "Usage: $0 <linux|macos|windows> <arch e.g. aarch64|x86_64>" >&2
  exit 1
fi
echo "Placeholder: integrate python-build-standalone for $OS $ARCH (see project plan)." >&2
exit 0
