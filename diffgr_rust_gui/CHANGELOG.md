# 0.4.1 - UT depth expansion

- UT depth regression guards を追加しました。
- Added `tests/ut_depth_quality_more_ut.rs`, `tests/gui_review_flow_contract_more_ut.rs`, `tests/virtual_pr_regression_more_ut.rs`, and `tests/cli_wrapper_ci_contract_more_ut.rs`.
- Static Rust UT count is now 1,192 tests with a 1,180-test matrix gate.
- Added `tools/verify_ut_depth.py`, `ut-depth.ps1`, `ut-depth.sh`, `windows/ut-depth-windows.ps1`, and `UT_DEPTH_AUDIT.json`.
- Strengthened checks for GUI review flow, virtual PR review gate regressions, CLI aliases/options, Windows/shell wrappers, and UT matrix quality.

## 0.3.7 - self-review, GUI diagnostics, and UT gate hardening

- Added consolidated self-review gates for Python parity, GUI completion, and UT coverage.
- Added `診断` tab and `性能HUD` to inspect frame time, slow frames, volatile caches, and pending background I/O.
- Added bounded chunk-row cache pruning to keep large review sessions from growing volatile cache indefinitely.
- Added `diffgrctl quality-review` / `self-review` / `gui-quality` aliases and Windows/shell wrappers.
- Added `tools/verify_self_review.py` and `tools/verify_gui_completion.py`.
- Expanded UT coverage and raised the UT matrix gate for quality self-review and GUI completion.

## 0.3.6 - rendering and responsiveness pass

- Added background DiffGR loading so large JSON parsing does not block the egui UI thread.
- Moved state auto-save to a background worker with revision checks so new edits are not marked saved by an older save job.
- Changed chunk row rendering cache from eager full-row construction to on-demand `BTreeMap<usize, ChunkRow>` rows for visible virtual-scroll ranges.
- Added debounced Path/search filtering with Enter for immediate apply, reducing full-diff searches while typing.
- Added virtualized read-only text rendering for State JSON and state diff/merge previews.
- Added long diff-line clipping to avoid layout stalls on minified/generated files.
- Added `滑らかスクロール`, `検索を遅延適用`, `読込/自動保存を別スレッド`, and `超長行を省略描画` GUI switches.
- Added `--smooth-scroll`, `--no-background-io`, `DIFFGR_SMOOTH_SCROLL`, and `DIFFGR_NO_BACKGROUND_IO` controls.
- Added `Run Smooth.cmd` and Windows `run-windows.ps1 -Smooth/-NoBackgroundIO` support.
- Added `tests/render_responsiveness_ut.rs`, bringing the static UT matrix to 471 Rust tests and 11 categories.

## 0.3.5 - UT hardening pass

- Expanded Rust UT coverage from 182 tests to 430 tests.
- Added `tests/model_regression_more_ut.rs` for state normalization, line comments, group briefs, coverage, approvals, report writing, and backup behavior.
- Added `tests/ops_regression_more_ut.rs` for diff parsing, chunk splitting, slice/layout patching, state selection, bundle verification, rebase options, impact formatting, and approval operations.
- Added `tests/cli_surface_deep_ut.rs` with one test for every Python-compatible CLI option plus command alias coverage.
- Added `tests/wrapper_contract_deep_ut.rs` with one contract test per Python script wrapper plus Windows/shell compatibility checks.
- Updated `UT_MATRIX.json` to 10 categories with a 420-test minimum gate.

# Changelog

## 0.3.4 - UT coverage expansion

- Expanded Rust UT coverage to 182 tests across model, ops, state, reporting, bundle, approval, rebase, parity, and wrapper asset categories.
- Added pure operation tests for unified diff parsing, binary/meta-only changes, chunk splitting, change fingerprints, slice patching, and atomic write helpers.
- Added state tests for normalization, extract/apply roundtrip, merge precedence, selection tokens, nested `threadState.__files`, previews, and stable state fingerprints.
- Added reporting/bundle tests for summaries, coverage prompt limits, reviewability hotspots, HTML options, bundle manifest verification, topology warnings, and split/merge group review workflows.
- Added approval/rebase tests for forced approvals, request changes, approval fingerprint invalidation, strong/stable/similar rebase mapping, line-comment carry rules, stale handoff invalidation, history metadata, impact markdown, and Python-compatible rebase counters.
- Added static asset tests for Python parity manifests, functional scenario coverage, Windows/shell wrappers, and compatibility layer source audit.
- Added `UT_MATRIX.json`, `tools/verify_ut_matrix.py`, `ut-matrix.ps1`, `ut-matrix.sh`, `windows/ut-matrix-windows.ps1`, and `UT Matrix Verify.cmd`.
- Fixed an HTML save-state widget fallback string that would prevent Rust compilation.

## 0.3.1

- Tightened Python app parity from “feature names exist” to “Python-compatible aliases/options/wrappers exist”.
- Added `diffgrctl` aliases matching original script names, such as `generate-diffgr`, `view-diffgr`, `export-review-bundle`, and `check-virtual-pr-coverage`.
- Added `scripts/*.ps1` and `scripts/*.sh` wrappers named after the original Python scripts.
- Added `diffgrctl parity-audit`, `windows/parity-audit-windows.ps1`, and `Python Parity Audit.cmd`.
- Added Python-style defaults for generate/autoslice/refine/run-agent, stdout extract-state behavior, Python bundle output flags, input glob merge, and Python view filters.
- Added CLI parity UT for audit coverage, view filtering, state extraction, bundle path outputs, and HTML export options.
- Matched Python HTML export/server options more closely: `--group`, `--title`, `--save-state-url`, `--save-state-label`, `--impact-old`, and `--impact-state`.
- Added coverage prompt limit handling for `--max-chunks-per-group` and `--max-problem-chunks`.
- Added rebase review history metadata handling for `--history-*` options.

## 0.3.0

- Added `src/ops.rs` with Rust implementations for Python `scripts/*.py` style operations: generate, autoslice, refine, slice/layout patching, state extract/apply/diff/merge/token apply, split/merge group reviews, impact/rebase, HTML export/server, bundle export/verify, approval, coverage, reviewability, and summaries.
- Added `diffgrctl` CLI binary so Windows PowerShell/cmd and shell users can run Python-equivalent operations through Cargo.
- Added GUI `Tools` tab for generation, state extraction, HTML/bundle export, coverage/reviewability reports, AI prompt generation, layout/slice patch apply, group review merge, rebase state, impact, and approval JSON output.
- Added Windows and shell wrappers: `diffgrctl.ps1`, `windows/diffgrctl-windows.ps1`, `DiffGR Tools.cmd`, `diffgrctl.sh`, and `scripts/diffgrctl.sh`.
- Updated Windows packaging to include both `diffgr_gui.exe` and `diffgrctl.exe`.
- Added `tests/ops_parity.rs` for Python parity operations including state, layout, bundle verify, HTML, coverage, rebase, impact, and approval workflows.
- Updated `PYTHON_PARITY.md`, README, WINDOWS, and TESTING docs to mark Python app parity through GUI + CLI rather than GUI-only replacement.

## 0.2.0

- Added Python Textual parity features in the native GUI: group create/rename/delete, chunk assign/unassign, layout patch apply, coverage check, coverage AI-fix prompt, group review split export, state diff/merge, impact preview, HTML export, and approval/request-changes/revoke workflow.
- Added approval report Markdown/JSON generation and GUI verification panel.
- Added SHA-256 based approval fingerprints compatible with the Python approval model's stable chunk fingerprint approach.
- Added unit tests for layout editing, coverage, layout patches, state diff/merge, split export, HTML export, impact preview, and approval invalidation.
- Kept layout edits out of state-only autosave so external `review.state.json` cannot hide unsaved DiffGR layout changes.

## 0.1.3

- Added `概要` detail tab with status counts and per-file review progress.
- Added Markdown review summary copy/export.
- Added visible-chunk bulk status operations: reviewed, needs re-review, unreviewed, ignored.
- Added status-change undo with batch-aware `Ctrl+Z`.
- Added safer JSON/Markdown writing through a completed temporary file and short-lived restore file on Windows-style replacement fallback.
- Added `--low-memory` direct CLI flag in addition to `DIFFGR_LOW_MEMORY`.
- Added `windows/doctor-windows.ps1`, `doctor.ps1`, `Doctor.cmd`, and `Package Windows.cmd`.
- Added `examples/multi_file.diffgr.json` for manual verification.
- Added unit/integration tests for status counts, file summaries, Markdown report generation/export, parent directory creation, and `--low-memory` parsing.

## 0.1.2

- Added Windows build/test/run wrappers and cross-shell wrappers.
- Added lightweight rendering, virtual scrolling, low-memory mode, and flicker mitigation.
- Added review state overlay, line comments, group handoff editing, search/filtering, recent files, and basic UT coverage.

## 0.3.2 - Complete Python parity compatibility layer

- Vendored the original Python DiffGR app under `compat/python` for strict behavior parity.
- Added `-CompatPython` / `--compat-python` support to every historical script wrapper.
- Added `PYTHON_PARITY_MANIFEST.json` generated from the Python argparse definitions.
- Added `PYTHON_COMPATIBILITY.md`, `COMPLETE_PARITY_AUDIT.md`, and Python compatibility smoke scripts.
- Tightened native Rust CLI parity for state overlay, state diff text output, coverage output/failure, split manifest naming, and state apply validation.

## Native parity gate update

- Added `tools/verify_native_parity.py` and `NATIVE_PYTHON_PARITY_AUDIT.json`.
- Added Windows/shell native parity verification wrappers.
- Added native Rust support for rebase parity options: `--keep-new-groups`, `--no-line-comments`, `--impact-grouping`.
- Added Python-compatible rebase summary counters and source-level native parity tests.

## Native functional parity gate

- Added `NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json` covering all 31 Python script-equivalent operations.
- Added `tools/verify_functional_parity.py`, which runs native Rust `diffgrctl` and bundled Python compatibility scripts against the same fixtures and compares semantic output shape.
- Added Windows/shell wrappers: `native-functional-parity.ps1`, `native-functional-parity.sh`, `windows/native-functional-parity-windows.ps1`, and `Native Functional Parity Verify.cmd`.
- Updated README / TESTING / WINDOWS / parity docs with the three-gate parity claim: Python source strict parity, native command/option parity, and native functional parity.

## 0.3.8 - Diff readability review

- Diffタブの自己レビュー結果を反映し、統合表示だけでなく左右比較表示を追加しました。
- `全行` / `変更行のみ` / `変更周辺` の表示モードを追加し、巨大chunkでも文脈つきで読みやすくしました。
- Diff内検索、前/次の変更ジャンプ、前/次の検索ジャンプ、表示中diffコピー、選択行コピーを追加しました。
- add/delete/search/selected/comment の視認性を上げるため、diff行に背景ハイライトを追加しました。
- Diffタブ内で行コメントを直接編集できるようにしました。
- `tests/diff_readability_ut.rs` を追加し、diff表示・検索・左右比較・文脈表示の静的UTを追加しました。

## 0.3.9 - Word-level diff viewer

- Diff タブに `行内差分` と `賢く対応付け` を追加しました。
- delete/add の対応行を類似度でペアリングし、単語・記号単位で変更箇所に背景ハイライトを付けます。
- 巨大行では word diff を自動的にスキップし、従来の行単位表示へフォールバックします。
- `src/diff_words.rs` と `tests/word_level_diff_ut.rs` を追加し、word-level LCS、tokenize、類似行ペアリング、GUIマーカーを検査します。
- UT matrix の下限を 760 tests に引き上げました。


## 0.4.0 - Virtual PR review gate

- Added a dedicated `仮想PR` GUI tab for merge/approval readiness review.
- Added readiness score, blocker/warning list, next-action list, high-risk chunk queue, group readiness, and file hotspots.
- Added `diffgrctl virtual-pr-review` / `review-gate` with JSON, Markdown, reviewer prompt, and `--fail-on-blockers`.
- Added cached `VirtualPrReportCache` so the gate is recomputed only when review state changes.
- Added `src/vpr.rs` and `tests/vpr_review_ut.rs`; UT matrix now tracks the virtual PR review gate.
