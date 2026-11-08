#!/usr/bin/env bash
set -euo pipefail
GILBEOT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [[ -x "$GILBEOT_ROOT/.venv-linux/bin/python" ]]; then
  GILBEOT_PYTHON="$GILBEOT_ROOT/.venv-linux/bin/python"
else
  GILBEOT_PYTHON="${JEJU_PYTHON:-python3}"
  echo "Optional E5 runtime has not been installed; run bash setup_ubuntu.sh for full semantic search." >&2
fi
if ! command -v "$GILBEOT_PYTHON" >/dev/null 2>&1; then
  echo "Python is not available. See README Ubuntu setup." >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
cd -- "$GILBEOT_ROOT"
exec "$GILBEOT_PYTHON" "$GILBEOT_ROOT/center_app.py" "$@"
