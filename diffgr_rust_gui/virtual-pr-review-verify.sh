#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
exec $PYTHON_BIN "$ROOT/tools/verify_virtual_pr_review.py" "$@"
