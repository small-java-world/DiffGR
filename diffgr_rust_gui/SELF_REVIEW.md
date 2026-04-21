# DiffGR Rust GUI self review

This package is reviewed against three goals: Python application parity, native GUI completion, and unit-test coverage.

## Verdict

- Python application parity is covered by the normal native Rust GUI/CLI path plus the strict `compat/python` fallback.
- GUI completion is improved by diagnostics, performance HUD, bounded volatile caches, background loading/saving, virtual scrolling, and low-memory/smooth-scroll launch modes.
- Unit-test assets are expanded and checked by `UT_MATRIX.json` and the consolidated self-review gates.

The strict compatibility layer keeps the original Python source/support files so exact legacy behavior can still be executed with `-CompatPython`, `--compat-python`, or `DIFFGR_COMPAT_PYTHON=1`.

## Windows gates

```powershell
.\windows\self-review-windows.ps1 -Json -Strict
.\windows\quality-review-windows.ps1 -Json -Deep
.\windows\gui-completion-verify-windows.ps1 -Json -CheckSubgates
.\windows\ut-matrix-windows.ps1 -Json
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```

## Shell gates

```bash
./self-review.sh --json --strict
./quality-review.sh --json --deep
./completion-review.sh --json --check-subgates
./ut-matrix.sh --json
./test.sh --fmt --check
./build.sh --test
```

## GUI completion checks

The GUI now includes a `診断` tab and a `性能HUD` toggle. These show frame-time average, frame-time peak, slow-frame count, visible chunk count, cached chunk-row count, state preview line count, and pending background I/O jobs.

The `Tools` tab includes a `自己レビュー / 品質ゲート` section that exposes the same gate commands from inside the GUI.

## Remaining risk

The static self-review gates do not replace `cargo test --all-targets` or a Windows release build. Run the Cargo gates locally on Windows before release.


## Virtual PR review self-check

The self-review now includes a virtual PR review gate. A complete review should confirm: coverage is OK, pending/re-review chunks are handled, approval is valid, handoff fields are filled, high-risk chunks have been inspected, and the reviewer prompt can be copied for human or AI follow-up.
