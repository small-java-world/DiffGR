#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD=${PYTHON:-python3}
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --deep) ARGS+=(--strict) ;;
    *) ARGS+=("$arg") ;;
  esac
done
exec ${PYTHON_CMD} "$ROOT/tools/verify_self_review.py" "${ARGS[@]}"
