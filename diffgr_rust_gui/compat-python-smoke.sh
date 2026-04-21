#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAMPLE="$ROOT/examples/multi_file.diffgr.json"
"$ROOT/scripts/summarize_diffgr.sh" --compat-python --input "$SAMPLE" --json >/dev/null
"$ROOT/scripts/extract_diffgr_state.sh" --compat-python --input "$SAMPLE" >/dev/null
"$ROOT/scripts/check_virtual_pr_coverage.sh" --compat-python --input "$SAMPLE" --json >/dev/null || test "$?" = 2
printf 'compat-python smoke passed\n'
