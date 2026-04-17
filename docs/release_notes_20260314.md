# Release Notes 2026-03-14

## State Workflow

- Prompt UI に `state-apply` を追加し、selection token 単位で external state を部分適用できるようにした
- `state-diff` は key ごとの preview と selection token を表示する
- `state-merge` は full merge として残し、summary と warning 件数を返す
- Prompt UI に `impact-merge-preview` / `impact-apply-preview` / `impact-apply` を追加し、old/new DiffGR と state から rebased handoff / selection plan の preview と apply を行えるようにした

## Textual

- top bar に current state source を表示
- `Ctrl+B` / `Ctrl+U` で state bind / unbind
- `Ctrl+D` で diff report modal を表示
- `Ctrl+Alt+D` で full merge preview modal を表示
- `Ctrl+M` で full merge
- `Ctrl+Shift+M` で selection token 単位の selective apply
- `Ctrl+Shift+D` で impact-aware preview を表示
- `Ctrl+Alt+M` で impact selection plan の direct preview / apply を実行
- `@handoffs / @reviews / @ui / @all` による impact plan 展開を追加し、source mismatch / mixed input を防ぐ validation を入れた

## HTML

- toolbar に `Diff State` / `Apply Selected State` / `state source` 表示を追加
- `Import State` 後の baseline を保持し、`Diff State` と selective apply の基準に使う
- `threadState.__files:<file_path>` を含む selection token を HTML 側でも扱えるようにした
- `--state` 付き export / serve 時は initial state source label を埋め込む
- `Impact Preview` に `Selection Plans` を追加し、current source が一致するときだけ `Apply These Tokens` を有効化した
- `Apply Selected State` は `Preview -> Apply` の 2 段階にし、impact plan row から direct preview / apply modal へ進めるようにした
- empty plan は hard error ではなく no-op preview として扱う

## CLI

- `scripts/diff_diffgr_state.py --tokens-only` を追加
- `scripts/apply_diffgr_state_diff.py` を追加し、selection token 単位で state を適用できるようにした
- `scripts/preview_rebased_merge.py --tokens-only <plan>` を追加
- `scripts/apply_diffgr_state_diff.py --impact-old --impact-new --impact-plan` を追加し、impact selection plan を shortcut で preview / apply できるようにした

## Core

- `diff_review_states()` が preview と selection token を返す
- merge preview / impact preview の report を `Source / Change Summary / Warnings / Group Brief Changes / State Diff` 基準で揃え、impact preview では `Impact / Affected Briefs / Selection Plans` を追加する
- `apply_review_state_selection()` を追加
- `threadState.__files` を file-level token として扱う契約を固定
- merge warning の section summary helper を追加
- `build_impact_selection_plans()` と `preview_impact_apply()` を追加し、impact preview から rebased selective apply までを共通 helper で扱えるようにした

## Docs

- `README.md`
- `docs/アプリの使い方.md`
- `docs/review_repo_workflow.md`
- 本 release note
