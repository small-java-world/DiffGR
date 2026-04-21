#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD=${PYTHON:-python3}
exec ${PYTHON_CMD} "$ROOT/tools/verify_gui_completion.py" "$@"
