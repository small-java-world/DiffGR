#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYROOT="$ROOT/compat/python"
if [[ $# -lt 1 ]]; then
  echo "usage: compat-python.sh <python-script-name> [args...]" >&2
  exit 2
fi
script="$1"; shift
script="${script%.py}.py"
path="$PYROOT/scripts/$script"
if [[ ! -f "$path" ]]; then
  echo "compat Python script not found: $path" >&2
  exit 2
fi
python_bin="${PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if command -v py >/dev/null 2>&1; then
    python_bin="py -3"
  elif command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python"
  fi
fi
export PYTHONPATH="$PYROOT${PYTHONPATH:+:$PYTHONPATH}"
# shellcheck disable=SC2086
exec $python_bin "$path" "$@"
