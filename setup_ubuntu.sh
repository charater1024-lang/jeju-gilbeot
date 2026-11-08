#!/usr/bin/env bash
set -euo pipefail
GILBEOT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
GILBEOT_PYTHON="${JEJU_PYTHON:-python3}"
if ! command -v "$GILBEOT_PYTHON" >/dev/null 2>&1; then
  echo "Python3.12 is required. Ubuntu24.04: sudo apt install python3 python3-venv" >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
exec "$GILBEOT_PYTHON" "$GILBEOT_ROOT/scripts/install_linux_runtime.py" "$@"
