#!/usr/bin/env bash
# Thin wrapper for the cross-platform Python installer.
#
# Prefer running install.py directly:
#   python3 skills/install.py --all
#
# This wrapper exists so the existing macOS/Linux command
# (``.skills/install.sh``) keeps working while the canonical implementation
# lives in one place.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$REPO_ROOT/skills/install.py"

if [[ ! -f "$INSTALLER" ]]; then
    echo "Installer not found at $INSTALLER" >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "python not found on PATH. Install Python 3.10+ and retry." >&2
    exit 1
fi

exec "$PY" "$INSTALLER" "$@"
