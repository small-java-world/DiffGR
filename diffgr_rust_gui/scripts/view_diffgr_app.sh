#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${DIFFGR_COMPAT_PYTHON:-}" == "1" || "${DIFFGR_COMPAT_PYTHON:-}" == "true" ]]; then
  exec "$ROOT/compat-python.sh" view_diffgr_app "$@"
fi
if [[ $# -gt 0 && "$1" == "--compat-python" ]]; then
  shift
  exec "$ROOT/compat-python.sh" view_diffgr_app "$@"
fi
exec "$ROOT/diffgrctl.sh" view-diffgr-app "$@"
