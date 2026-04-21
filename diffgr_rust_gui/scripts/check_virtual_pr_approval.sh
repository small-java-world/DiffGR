#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${DIFFGR_COMPAT_PYTHON:-}" == "1" || "${DIFFGR_COMPAT_PYTHON:-}" == "true" ]]; then
  exec "$ROOT/compat-python.sh" check_virtual_pr_approval "$@"
fi
if [[ $# -gt 0 && "$1" == "--compat-python" ]]; then
  shift
  exec "$ROOT/compat-python.sh" check_virtual_pr_approval "$@"
fi
exec "$ROOT/diffgrctl.sh" check-virtual-pr-approval "$@"
