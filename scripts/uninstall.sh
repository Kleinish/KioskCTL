#!/usr/bin/env bash
set -Eeuo pipefail

# Backward-compatible installed path. The canonical uninstaller lives at
# /opt/kioskctl/uninstall.sh in installed systems and at ../uninstall.sh in a
# release tree.
if [[ -x /opt/kioskctl/uninstall.sh ]]; then
  exec /opt/kioskctl/uninstall.sh "$@"
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../uninstall.sh" "$@"
