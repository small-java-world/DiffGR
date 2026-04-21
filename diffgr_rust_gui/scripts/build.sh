#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

profile="release"
clean=0
run_after=0
run_tests=0
run_check=0
locked=0

usage() {
  cat <<'EOF'
Usage: scripts/build.sh [--release|--debug] [--clean] [--check] [--test] [--locked] [--run]

Rust/Cargo build wrapper. The actual build command is cargo build.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) profile="release" ;;
    --debug) profile="debug" ;;
    --clean) clean=1 ;;
    --check) run_check=1 ;;
    --test) run_tests=1 ;;
    --locked) locked=1 ;;
    --run) run_after=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

common=()
if [[ $locked -eq 1 ]]; then common+=(--locked); fi

if [[ $clean -eq 1 ]]; then
  echo "+ cargo clean"
  cargo clean
fi

if [[ $run_check -eq 1 ]]; then
  echo "+ cargo check --all-targets ${common[*]}"
  cargo check --all-targets "${common[@]}"
fi

if [[ $run_tests -eq 1 ]]; then
  echo "+ cargo test --all-targets ${common[*]}"
  cargo test --all-targets "${common[@]}"
fi

build_args=(build "${common[@]}")
if [[ "$profile" == "release" ]]; then build_args+=(--release); fi

echo "+ cargo ${build_args[*]}"
cargo "${build_args[@]}"

exe="target/$profile/diffgr_gui"
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) exe="$exe.exe" ;;
esac

echo "Built: $ROOT/$exe"
if [[ $run_after -eq 1 ]]; then
  "$ROOT/$exe"
fi
