#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -a PYTHON_CMD <<< "${PYTHON:-/usr/bin/python3}"
exec "${PYTHON_CMD[@]}" "$ROOT/tools/verify_ut_depth.py" "$@"
