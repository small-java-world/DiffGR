# Testing

## このプロジェクトのテスト方針

GUIそのものは目視確認が必要な部分がありますが、重くなりやすい・壊れやすいロジックは `model` と小さな helper に寄せて UT で確認できるようにしています。

追加済みテストの主な対象:

- DiffGR JSON の必須キー / format / version 検証
- groups / chunks / assignments の読み取り
- add/delete 件数の事前計算
- review status の切替
- chunk comment / line comment の追加・削除・prune
- selected line anchor の state 保存・復元
- state JSON の正規化と overlay
- groupBriefs の pipe-list 入出力
- metrics の reviewed / pending / ignored / unassigned 集計
- statusCounts / fileSummaries / Markdown review report の生成
- full document / state JSON / Markdown report 書き込みと backup / 一時ファイル経由保存
- CLI 引数解析: `diffgr.json --state review.state.json`
- GUI helper: 検索、近傍 `review.state.json` 検出、status sort key
- public API integration workflow
- group 作成 / rename / assign / unassign
- virtual PR coverage check と coverage修正prompt
- layout patch JSON 適用
- state diff / merge preview
- group review split export と HTML export
- impact preview
- approval / request changes / revoke / approval report

## Windows

```powershell
# UT
.\test.ps1

# check + UT
.\test.ps1 -Check

# fmt check + check + UT
.\test.ps1 -Fmt -Check

# UT後にrelease build
.\build.ps1 -Test

# env check + fmt/check/test + release build
.\windows\ci-windows.ps1

# doctor: 環境診断 + fmt/check/test/build
.\doctor.ps1 -Deep
```

PowerShell 実行ポリシーで止まる場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test.ps1 -Check
```

## cmd

```cmd
Test.cmd
Check Test Build.cmd
```

## Git Bash / WSL / Linux / macOS

```bash
./test.sh
./test.sh --check
./test.sh --fmt --check
./build.sh --test
./build.sh --release
```

## Cargo 直打ち

```bash
cargo test --all-targets
cargo check --all-targets
cargo fmt --all -- --check
cargo build --release
```

## 特定テストだけ実行

```powershell
.\test.ps1 -TestName review_state_roundtrips
```

```bash
./test.sh -- review_state_roundtrips
```

Cargo 直打ち:

```bash
cargo test review_state_roundtrips
```

## 注意

この実行環境では Rust toolchain が無い場合があります。その場合、ローカル Windows で `cargo test --all-targets` を実行してください。スクリプトはすべて最終的に Cargo を呼んでいるため、エラーは Cargo のログを見れば追えます。


## 追加確認ポイント

- `examples/multi_file.diffgr.json` は概要タブ、Markdownサマリ、一括ステータス変更の手動確認に使えます。
- `Ctrl+Z` は「ステータス変更」のUndoです。コメント本文のUndoはテキストエディタ側の通常Undoに任せています。
- 保存処理は一時ファイルを書き切ってから置き換えます。UTでは親ディレクトリ作成と report/state 書き込みを確認しています。

## Python parity / diffgrctl の確認

この版では `tests/ops_parity.rs` と `tests/python_parity_cli.rs` を追加し、Python scripts 相当の中核ロジックと Python互換CLI入口を Rust 側で確認します。

追加対象:

- Git diff text -> DiffGR JSON 生成
- review.state.json 抽出/適用
- layout patch 適用
- slice patch rename
- state diff / merge / selection token apply
- group review split
- review bundle export / verify
- HTML report生成
- coverage / reviewability report
- rebase state
- impact report
- approval / request changes

CLI の手動smoke例:

```powershell
.\diffgrctl.ps1 parity-audit --json
.\diffgrctl.ps1 summarize-diffgr --input .\examples\multi_file.diffgr.json --json
.\diffgrctl.ps1 check-virtual-pr-coverage --input .\examples\multi_file.diffgr.json --json
.\diffgrctl.ps1 extract-diffgr-state --input .\examples\multi_file.diffgr.json --output .\out\review.state.json
.\diffgrctl.ps1 export-diffgr-html --input .\examples\multi_file.diffgr.json --state .\out\review.state.json --output .\out\review.html --group all --title "DiffGR Review" --save-state-url /api/state
.\diffgrctl.ps1 export-review-bundle --input .\examples\multi_file.diffgr.json --output-dir .\out\smoke-bundle
.\diffgrctl.ps1 verify-review-bundle --bundle .\out\smoke-bundle\bundle.diffgr.json --state .\out\smoke-bundle\review.state.json --manifest .\out\smoke-bundle\review.manifest.json
```

Windows wrapper の一括smoke:

```powershell
.\windows\parity-smoke-windows.ps1
.\windows\parity-audit-windows.ps1 -Json
```

Rust toolchain がある環境では、最終確認は次で行ってください。

```powershell
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```

## Strict Python compatibility gate

Use this when the requirement is "all existing Python-app functionality remains
available" rather than only native Rust workflow coverage.

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
```

```bash
./compat-python-verify.sh --json
```

The gate checks:

- byte-for-byte presence of all non-cache files from the original Python app,
- wrappers for all 31 historical `scripts/*.py` entries,
- `py_compile` for vendored Python package, scripts, and tests,
- smoke execution of summary/state/coverage commands through the compatibility layer.

Run the original Python pytest suite too when dependencies are installed:

```powershell
.\windows\python-compat-verify-windows.ps1 -Pytest
```

```bash
./compat-python-verify.sh --pytest
```

## Native parity gate

```powershell
.\native-parity-verify.ps1 -Json -CheckCompat
```

または:

```bash
./native-parity-verify.sh --json --check-compat
```

この gate は Python `scripts/*.py` 31本、Python CLI option 80件、Windows/shell wrapper、rebase 系の native option を検査します。

## Native functional Python parity smoke

`native-parity-verify` checks command/option coverage. `native-functional-parity` goes further: it runs all 31 Python-script-equivalent operations once through bundled Python compatibility and once through native Rust `diffgrctl`, then compares semantic output shape.

Windows:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json
```

Shell:

```bash
./native-functional-parity.sh --json
```

Static matrix only, no Rust execution:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -List
```

Use the three parity gates together when claiming Python-app-equivalent coverage:

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\native-functional-parity-windows.ps1 -Json
```

Compat-only dry run for the functional matrix:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -CompatOnly
```

This requires Python dependencies from `compat/python/requirements.txt`; the viewer scenarios import `rich`.

## UT coverage matrix

この版では UT を大きく増やし、`UT_MATRIX.json` と `tools/verify_ut_matrix.py` でカテゴリ別のテスト不足を静的に検査できます。Cargo が無い環境でも、少なくともテスト資産の欠け・カテゴリ不足・重複テスト名を確認できます。

```powershell
.\windows\ut-matrix-windows.ps1 -Json
```

```bash
./ut-matrix.sh --json
```

現在の matrix gate は 16カテゴリ / 1,192 Rust tests を対象にしています。Native CLI option surface 121件、Windows/shell wrapper contract 41件、model regression 42件、ops regression 44件も含めて確認します。

| カテゴリ | 対象 |
|---|---|
| model workflow and GUI startup | document model、レビュー状態、Markdown report、起動引数 |
| layout state coverage parity | group/layout編集、coverage、groupBrief、line comment |
| generation and patch operations | unified diff parser、chunk split、fingerprint、slice patch、atomic write |
| state diff merge selection | state正規化、merge precedence、selection token、nested thread files |
| reports bundle split merge | summary、reviewability、HTML、bundle verify、split/merge group reviews |
| approval impact rebase | approve/request changes、fingerprint invalidation、rebase、impact |
| python parity gates and wrappers | manifest、functional scenarios、Windows/shell wrapper、compat layer |
| diffgrctl CLI behavior | summarize/state/apply/merge/coverage/view-app/layout の実CLI smoke |

Rust toolchain がある環境での最終確認はこれです。

```powershell
.\windows\ut-matrix-windows.ps1 -Json
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```

## Rendering / responsiveness UT gate 0.3.6

The rendering pass adds a dedicated static UT file:

```powershell
.\windows\ut-matrix-windows.ps1 -Json
cargo test --test render_responsiveness_ut
```

It checks that large-file responsiveness features remain wired in: background document loading, background auto-save, debounced search filters, on-demand chunk row cache, virtualized State JSON rendering, long-line clipping, smooth-scroll repaint controls, and Windows `-Smooth` / `-NoBackgroundIO` wrapper switches.

## Consolidated self-review UT gates

Use these gates before release:

```powershell
.\windows\self-review-windows.ps1 -Json -Strict
.\windows\quality-review-windows.ps1 -Json -Deep
.\windows\gui-completion-verify-windows.ps1 -Json -CheckSubgates
.\windows\ut-matrix-windows.ps1 -Json
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```

`UT_MATRIX.json` now includes a `quality self review and GUI completion` category that checks the diagnostics tab, performance HUD, bounded chunk-row cache, self-review tools, native CLI self-review command, wrappers, and audit JSON files.


### Diff readability UT

`tests/diff_readability_ut.rs` は、Diffタブの読みやすさに関する静的UTです。主に以下を確認します。

- 統合表示 / 左右比較表示
- 全行 / 変更行のみ / 変更周辺
- Diff内検索と前後ジャンプ
- 変更行ジャンプ
- 表示中diffコピーと選択行コピー
- add/delete/search/selected の背景ハイライト
- Diffタブ内の line comment 編集導線

### Word-level diff UT

`tests/word_level_diff_ut.rs` と `src/diff_words.rs` は、行内 word diff の tokenization、LCS segment、類似行ペアリング、GUI表示マーカーを検査します。静的ゲートは次で確認できます。

```powershell
.\windows\ut-matrix-windows.ps1 -Json
```

Cargo が利用できる環境では次も実行してください。

```powershell
cargo fmt --all -- --check
cargo test --all-targets
```


## Virtual PR review gate tests

`tests/vpr_review_ut.rs` covers the new virtual PR readiness model: blocker detection, approval/coverage gates, risk scoring, file hotspots, group readiness, JSON output, Markdown output, reviewer prompt output, and GUI/CLI surface markers. The UT matrix requires the `virtual PR review gate` category to pass.

```powershell
.\windows\ut-matrix-windows.ps1 -Json
cargo test vpr_gate --all-targets
```

Virtual PR gate static verifier:

```powershell
.\virtual-pr-review-verify.ps1 -Json
.\windows\virtual-pr-review-verify-windows.ps1 -Json
```


## UT depth gate

`tools/verify_ut_depth.py` は UT 拡充の追加ゲートです。`tests/ut_depth_quality_more_ut.rs`、`tests/gui_review_flow_contract_more_ut.rs`、`tests/virtual_pr_regression_more_ut.rs`、`tests/cli_wrapper_ci_contract_more_ut.rs` の4本を確認し、UT matrix の合計が **1,180** tests 以上であることを確認します。Cargo 実行前でも、テスト資産の欠け・カテゴリ不足・GUI/仮想PR/CLI wrapper 契約の欠けを検出できます。

```powershell
.\windows\ut-depth-windows.ps1 -Json
```

```bash
./ut-depth.sh --json
```

最終確認では引き続き次を通します。

```bash
cargo test --all-targets
cargo check --all-targets
```
