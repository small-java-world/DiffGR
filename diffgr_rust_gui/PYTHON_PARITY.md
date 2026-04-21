# Python DiffGR app parity

この版は、既存 Python アプリを **Rust GUI + Rust CLI + Windows/shell wrapper** に置き換えるための parity 版です。

- `diffgr_gui`: ネイティブ GUI。Textual UI のレビュー操作を GUI として置き換えます。
- `diffgrctl`: Python `scripts/*.py` 相当の CLI。
- `scripts/*.ps1` / `scripts/*.sh`: 旧 Python script 名に近い互換 wrapper。
- `windows/*.ps1` / `*.cmd`: Windows で build / test / run / parity smoke を直接使う入口。

Cargo が本体です。`.ps1` / `.cmd` / `.sh` は Cargo と `diffgrctl` を呼ぶ薄いラッパーです。

## Parity audit

```powershell
.\diffgrctl.ps1 parity-audit
.\diffgrctl.ps1 parity-audit --json
.\windows\parity-smoke-windows.ps1
```

shell:

```bash
./diffgrctl.sh parity-audit
./scripts/generate_diffgr.sh --base main --feature HEAD --output out/review.diffgr.json
```

## Python script 対応表

| Python script / 機能 | Rust 側の入口 | 互換 wrapper | 対応 |
|---|---|---|---:|
| `generate_diffgr.py` | `diffgrctl generate` / `generate-diffgr` | `scripts/generate_diffgr.ps1` / `.sh` | 対応 |
| `autoslice_diffgr.py` | `diffgrctl autoslice` / `autoslice-diffgr` | `scripts/autoslice_diffgr.ps1` / `.sh` | 対応 |
| `refine_slices.py` | `diffgrctl refine` / `refine-slices` | `scripts/refine_slices.ps1` / `.sh` | 対応 |
| `prepare_review.py` | `diffgrctl prepare` / `prepare-review` | `scripts/prepare_review.ps1` / `.sh` | 対応 |
| `run_agent_cli.py` | `diffgrctl run-agent` / `run-agent-cli` | `scripts/run_agent_cli.ps1` / `.sh` | 対応 |
| `apply_slice_patch.py` | `diffgrctl apply-slice-patch` | `scripts/apply_slice_patch.ps1` / `.sh` | 対応 |
| `apply_diffgr_layout.py` | `diffgrctl apply-layout` / `apply-diffgr-layout` | `scripts/apply_diffgr_layout.ps1` / `.sh` | 対応 |
| `view_diffgr.py` | `diffgrctl view` / `view-diffgr` | `scripts/view_diffgr.ps1` / `.sh` | 対応 |
| `view_diffgr_app.py --ui textual` | `diffgr_gui` / `diffgrctl view-app` | `scripts/view_diffgr_app.ps1` / `.sh` | 対応 |
| `export_diffgr_html.py` | `diffgrctl export-html` / `export-diffgr-html` | `scripts/export_diffgr_html.ps1` / `.sh` | 対応。`--group` / `--title` / `--save-state-url` / `--save-state-label` / impact preview 対応 |
| `serve_diffgr_report.py` | `diffgrctl serve-html` / `serve-diffgr-report` | `scripts/serve_diffgr_report.ps1` / `.sh` | 対応。`--group` / `--title` / `/api/state` 保存 / impact preview 対応 |
| `extract_diffgr_state.py` | `diffgrctl extract-state` / `extract-diffgr-state` | `scripts/extract_diffgr_state.ps1` / `.sh` | 対応 |
| `apply_diffgr_state.py` | `diffgrctl apply-state` / `apply-diffgr-state` | `scripts/apply_diffgr_state.ps1` / `.sh` | 対応 |
| `diff_diffgr_state.py` | `diffgrctl diff-state` / `diff-diffgr-state` | `scripts/diff_diffgr_state.ps1` / `.sh` | 対応 |
| `merge_diffgr_state.py` | `diffgrctl merge-state` / `merge-diffgr-state` | `scripts/merge_diffgr_state.ps1` / `.sh` | 対応 |
| `apply_diffgr_state_diff.py` | `diffgrctl apply-state-diff` / `apply-diffgr-state-diff` | `scripts/apply_diffgr_state_diff.ps1` / `.sh` | 対応 |
| `split_group_reviews.py` | `diffgrctl split-group-reviews` | `scripts/split_group_reviews.ps1` / `.sh` | 対応 |
| `merge_group_reviews.py` | `diffgrctl merge-group-reviews` | `scripts/merge_group_reviews.ps1` / `.sh` | 対応 |
| `impact_report.py` | `diffgrctl impact-report` | `scripts/impact_report.ps1` / `.sh` | 対応 |
| `preview_rebased_merge.py` | `diffgrctl preview-rebased-merge` | `scripts/preview_rebased_merge.ps1` / `.sh` | 対応 |
| `rebase_diffgr_state.py` | `diffgrctl rebase-state` / `rebase-diffgr-state` | `scripts/rebase_diffgr_state.ps1` / `.sh` | 対応 |
| `rebase_reviews.py` | `diffgrctl rebase-reviews` | `scripts/rebase_reviews.ps1` / `.sh` | 対応。`--history-*` metadata 対応 |
| `export_review_bundle.py` | `diffgrctl export-bundle` / `export-review-bundle` | `scripts/export_review_bundle.ps1` / `.sh` | 対応 |
| `verify_review_bundle.py` | `diffgrctl verify-bundle` / `verify-review-bundle` | `scripts/verify_review_bundle.ps1` / `.sh` | 対応 |
| `approve_virtual_pr.py` | `diffgrctl approve` / `approve-virtual-pr` | `scripts/approve_virtual_pr.ps1` / `.sh` | 対応 |
| `request_changes.py` | `diffgrctl request-changes` | `scripts/request_changes.ps1` / `.sh` | 対応 |
| `check_virtual_pr_approval.py` | `diffgrctl check-approval` / `check-virtual-pr-approval` | `scripts/check_virtual_pr_approval.ps1` / `.sh` | 対応 |
| `check_virtual_pr_coverage.py` | `diffgrctl coverage` / `check-virtual-pr-coverage` | `scripts/check_virtual_pr_coverage.ps1` / `.sh` | 対応。prompt 件数上限オプション対応 |
| `summarize_diffgr.py` | `diffgrctl summarize` / `summarize-diffgr` | `scripts/summarize_diffgr.ps1` / `.sh` | 対応 |
| `summarize_diffgr_state.py` | `diffgrctl summarize-state` / `summarize-diffgr-state` | `scripts/summarize_diffgr_state.ps1` / `.sh` | 対応 |
| `summarize_reviewability.py` | `diffgrctl reviewability` / `summarize-reviewability` | `scripts/summarize_reviewability.ps1` / `.sh` | 対応 |

## 追加で合わせた互換点

- Python script と同じ `--input` / `--output` / `--state` / `--base` / `--feature` / `--group` / `--all` / `--json` 系のオプション名を維持。
- `generate`、`autoslice`、`refine`、`run-agent` は Python 版と同じデフォルトパスを持つ互換モードを追加。
- `extract-state` は Python 版同様、`--output` なしなら stdout に JSON を出します。
- `export-bundle` は Rust 版の `--output-dir` に加えて、Python 版の `--bundle-out` / `--state-out` / `--manifest-out` に対応。
- `merge-group-reviews` は `--input` / `--input-dir` / `--input-glob` に対応。
- `view-diffgr` は Python 版の `--group` / `--chunk` / `--status` / `--file` / `--max-lines` / `--show-patch` / `--json` を受けます。
- `impact-report` は Python 版に合わせ、通常は Markdown、`--json` 時は JSON を出します。
- `approve-virtual-pr` / `request-changes` は Python 版同様 `--group` または `--all` を要求します。
- `check-virtual-pr-approval` は `--repo` / `--base` / `--feature` の all-or-nothing 検証と `--strict-full-check` を受けます。

## GUIで置き換えたレビュー操作

| Python Textual / prompt の操作 | Rust GUI |
|---|---|
| DiffGR JSON閲覧 | ファイルを開く / ドラッグ&ドロップ / 最近使ったファイル |
| review.state.json overlay / bind | `State保存先…` / `新規State` / 自動検出 |
| chunk status / chunk comment / line comment | `Review` タブ |
| groupBrief / handoff編集 | `Handoff` タブ |
| group create / rename / delete | `Layout` タブ |
| chunk assign / unassign | `Layout` タブ |
| layout patch JSON apply | `Layout` / `Tools` |
| virtual PR coverage check | `Coverage` タブ |
| coverage修正AI prompt | `Coverage` / `Tools` |
| split / merge group reviews | `Layout` / `Tools` |
| state diff / merge / selection token apply | `State JSON` / `Tools` / CLI |
| impact preview / impact apply plan | `Impact` / `Tools` / CLI |
| HTML / bundle / approval reports | `概要` / `Approval` / `Tools` |
| Textual key操作 | GUIボタン・ショートカット・一括操作・Undo |

## 同等性の注意

- 見た目、HTML DOM、Textual特有のキー割り当ては byte-for-byte clone ではありません。Rust GUI ではネイティブ操作として置き換えています。
- AI CLI は外部コマンド依存です。Rust版は prompt/schema/timeout/clipboard と JSON patch 正規化を提供します。
- 既存 Python script の入口は `diffgrctl` の alias と `scripts/*.ps1` / `scripts/*.sh` で保持しています。
- Rust実ビルドとUTはローカル環境で `cargo test --all-targets` または `.	est.ps1 -Check` を実行してください。

## Strict compatibility layer

The native Rust CLI/GUI remains the primary implementation.  This archive also
contains `compat/python`, a vendored copy of the original Python app, so every
historical `scripts/*.py` command can be run exactly through:

- PowerShell: `scripts/<name>.ps1 -CompatPython ...`
- shell: `scripts/<name>.sh --compat-python ...`
- environment: `DIFFGR_COMPAT_PYTHON=1`

This means parity has two layers: native Rust coverage for normal use, and exact
Python compatibility coverage for edge cases, old output comparisons, and the
old Python test-suite semantics.

## 追加: native parity gate

この版では `NATIVE_PYTHON_PARITY.md` / `NATIVE_PYTHON_PARITY_AUDIT.json` / `tools/verify_native_parity.py` を追加し、Python `scripts/*.py` 31本と CLI option 80件が native Rust 側で欠けていないことを検査できるようにした。

特に前版で native Rust 側の棚卸しが弱かった rebase 系は、`--keep-new-groups`、`--no-line-comments`、`--impact-grouping` を追加し、`rebase_state_with_options` / `rebase_reviews_document_with_options` へ集約した。
