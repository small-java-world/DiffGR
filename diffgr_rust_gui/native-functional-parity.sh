#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# PYTHON may include flags, e.g. PYTHON='python3 -S'.
read -r -a PYTHON_CMD <<< "${PYTHON:-python3}"
exec "${PYTHON_CMD[@]}" "$SCRIPT_DIR/tools/verify_functional_parity.py" "$@"
