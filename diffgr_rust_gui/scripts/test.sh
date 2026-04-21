#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

release=0
check=0
fmt=0
locked=0
test_name=""

usage() {
  cat <<'EOF'
Usage: scripts/test.sh [--release] [--check] [--fmt] [--locked] [-- <test-name>]

Runs cargo test --all-targets. Optional --check and --fmt run cargo check/fmt first.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) release=1 ;;
    --check) check=1 ;;
    --fmt) fmt=1 ;;
    --locked) locked=1 ;;
    --) shift; test_name="${1:-}"; break ;;
    -h|--help) usage; exit 0 ;;
    *) test_name="$1" ;;
  esac
  shift
done

common=()
if [[ $locked -eq 1 ]]; then common+=(--locked); fi

if [[ $fmt -eq 1 ]]; then
  echo "+ cargo fmt --all -- --check"
  cargo fmt --all -- --check
fi

if [[ $check -eq 1 ]]; then
  echo "+ cargo check --all-targets ${common[*]}"
  cargo check --all-targets "${common[@]}"
fi

test_args=(test --all-targets "${common[@]}")
if [[ $release -eq 1 ]]; then test_args+=(--release); fi
if [[ -n "$test_name" ]]; then test_args+=("$test_name"); fi

echo "+ cargo ${test_args[*]}"
cargo "${test_args[@]}"
