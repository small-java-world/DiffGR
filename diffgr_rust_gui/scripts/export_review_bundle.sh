#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${DIFFGR_COMPAT_PYTHON:-}" == "1" || "${DIFFGR_COMPAT_PYTHON:-}" == "true" ]]; then
  exec "$ROOT/compat-python.sh" export_review_bundle "$@"
fi
if [[ $# -gt 0 && "$1" == "--compat-python" ]]; then
  shift
  exec "$ROOT/compat-python.sh" export_review_bundle "$@"
fi
exec "$ROOT/diffgrctl.sh" export-review-bundle "$@"
