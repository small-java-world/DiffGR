#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  else
    python_bin="python"
  fi
fi
args=("$ROOT/tools/verify_python_parity.py" --compile --smoke)
if [[ "${1:-}" == "--json" ]]; then
  args+=(--json)
  shift
fi
if [[ "${1:-}" == "--pytest" ]]; then
  args+=(--pytest)
  shift
fi
# shellcheck disable=SC2086
$python_bin "${args[@]}" "$@"
