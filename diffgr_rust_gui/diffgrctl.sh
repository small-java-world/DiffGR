#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Legacy wrapper marker: scripts/diffgrctl.sh
BIN="$SCRIPT_DIR/target/release/diffgrctl"
if [[ -x "$BIN" ]]; then
  exec "$BIN" "$@"
fi
exec cargo run --quiet --bin diffgrctl -- "$@"
