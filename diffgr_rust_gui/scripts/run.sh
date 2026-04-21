#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

release=0
build=0
no_build=0
low_memory=0
args=()

usage() {
  cat <<'EOF'
Usage: scripts/run.sh [--release] [--build|--no-build] [--low-memory] [diffgr.json] [--state review.state.json]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release=1 ;;
    --build) build=1 ;;
    --no-build) no_build=1 ;;
    --low-memory) low_memory=1 ;;
    -h|--help) usage; exit 0 ;;
    *) args+=("$1") ;;
  esac
  shift
done

profile="debug"
if [[ $release -eq 1 ]]; then profile="release"; fi
exe="target/$profile/diffgr_gui"
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) exe="$exe.exe" ;;
esac

if [[ $build -eq 1 || ( $no_build -eq 0 && ! -x "$exe" && ! -f "$exe" ) ]]; then
  build_args=(build)
  if [[ $release -eq 1 ]]; then build_args+=(--release); fi
  echo "+ cargo ${build_args[*]}"
  cargo "${build_args[@]}"
fi

if [[ $low_memory -eq 1 ]]; then export DIFFGR_LOW_MEMORY=1; fi
"$ROOT/$exe" "${args[@]}"
