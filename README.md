# DiffGR

DiffGR は、大きい差分を「レビューしやすい単位」に分割し、レビュー状態とコメントを JSON に蓄積するためのツールセットです。  
このリポジトリでは、生成・分割・AIブラッシュアップ・対話レビュー・HTML共有までを一通り実行できます。

## 1. できること

- Git の `base` / `feature` から `*.diffgr.json` を生成
- 変更を仮想PR（グループ）に自動分割
- AI 提案（rename/move）で分割をブラッシュアップ
- Textual アプリでレビュー状態とコメントを編集
- HTML レポートを出力し、ローカルサーバ経由で `reviews` を直接保存

## 2. リポジトリ構成

- `scripts/`: 実行用 CLI
- `diffgr/`: コア実装（生成、分割、UI、HTML、AI連携）
- `docs/アプリの使い方.md`: 実運用向けの詳細手順
- `DiffGR_v1_仕様書.md`: DiffGR JSON 形式の仕様
- `samples/`: サンプル入力/出力
- `tests/`: `unittest` ベースのテスト

## 3. セットアップ

```powershell
cd F:\diffgr
python -m pip install -r requirements.txt
```

依存:

- `rich`
- `textual`
- `rapidfuzz`
- `diff-match-patch`

## 4. 最短クイックスタート

```powershell
# 1) 生成→自動分割→分割名改善（1コマンド）
python scripts\prepare_review.py `
  --base samples/ts20-base `
  --feature samples/ts20-feature-5pr `
  --output samples/diffgr/ts20-5pr.review.diffgr.json `
  --title "DiffGR review bundle"

# 2) Textual UI で確認
python scripts\view_diffgr_app.py samples/diffgr/ts20-5pr.review.diffgr.json --ui textual

# 3) HTML レポート共有（直接保存あり）
python scripts\serve_diffgr_report.py `
  --input samples/diffgr/ts20-5pr.review.diffgr.json `
  --group all `
  --open
```

## 5. 標準ワークフロー

### 5.1 DiffGR を生成

```powershell
python scripts\generate_diffgr.py `
  --base <base_ref> `
  --feature <feature_ref> `
  --output out\work\01.diffgr.json `
  --title "DiffGR Review Bundle"
```

### 5.2 自動分割

```powershell
python scripts\autoslice_diffgr.py `
  --base <base_ref> `
  --feature <feature_ref> `
  --input out\work\01.diffgr.json `
  --output out\work\02.autosliced.diffgr.json
```

### 5.3 分割名改善 + AI入力プロンプト作成

```powershell
python scripts\refine_slices.py `
  --input out\work\02.autosliced.diffgr.json `
  --output out\work\03.refined.diffgr.json `
  --write-prompt out\work\03.refine-prompt.md
```

## 6. AIブラッシュアップ込みワークフロー

AI には `slice_patch.json`（rename/move）を作らせ、最後に適用します。

```powershell
# 1) AIにパッチJSONを作らせる
python scripts\run_agent_cli.py `
  --config agent_cli.toml `
  --prompt out\work\03.refine-prompt.md `
  --output out\work\04.slice_patch.json `
  --interactive

# 2) 適用
python scripts\apply_slice_patch.py `
  --input out\work\03.refined.diffgr.json `
  --patch out\work\04.slice_patch.json `
  --output out\work\05.ai-refined.diffgr.json

# 3) 確認
python scripts\view_diffgr_app.py out\work\05.ai-refined.diffgr.json --ui textual
```

補足:

- `run_agent_cli.py` は `agent_cli.toml` の設定と、対応 CLI（Codex または Claude）が必要です。
- `slice_patch.json` が不正な場合は `apply_slice_patch.py` で失敗します。

## 7. Textual アプリの要点

起動:

```powershell
python scripts\view_diffgr_app.py <path-to.diffgr.json> --ui textual
```

主要操作:

- `Space`: done/undone トグル（`reviewed` <-> `unreviewed`）
- `Shift+Space`: done（`reviewed`）
- `Backspace` または `1`: undone（`unreviewed`）
- `m`: コメント編集（行選択時は行コメント）
- `o`: 実ファイルを外部エディタで開く
- `t`: 設定画面（`editor mode` 設定）
- `d`: グループ差分レポート表示切替
- `v`: チャンク詳細表示切替（compact / side-by-side）
- `s`: 保存
- `h`: HTML エクスポート

`o` のエディタ設定:

- `editor mode`: `auto` / `vscode` / `cursor` / `default-app` / `custom`
- 設定保存先: `~/.diffgr/viewer_settings.json`  
  もしくは環境変数 `DIFFGR_VIEWER_SETTINGS` で指定したパス

## 8. HTML レポート

### 8.1 静的HTMLを出力

```powershell
python scripts\export_diffgr_html.py `
  --input out\work\05.ai-refined.diffgr.json `
  --group all `
  --output out\reports\review.html `
  --open
```

### 8.2 ローカルサーバで直接保存

```powershell
python scripts\serve_diffgr_report.py `
  --input out\work\05.ai-refined.diffgr.json `
  --group all `
  --open
```

この方式では、HTML の `Save to App` で `reviews` が元 JSON に直接保存されます。

## 9. 主な CLI 一覧

- `scripts/generate_diffgr.py`: DiffGR 生成
- `scripts/autoslice_diffgr.py`: 自動分割
- `scripts/refine_slices.py`: 分割名改善 + AIプロンプト出力
- `scripts/check_virtual_pr_coverage.py`: 仮想PR割当が全chunkを網羅しているか検査（AI修正プロンプト生成可）
- `scripts/run_agent_cli.py`: AI で slice patch 生成
- `scripts/apply_slice_patch.py`: slice patch 適用
- `scripts/split_group_reviews.py`: 仮想PR単位のレビューファイル分割
- `scripts/merge_group_reviews.py`: 分割レビューファイルの結果を本体へマージ
- `scripts/rebase_reviews.py`: コード修正後の新DiffGRへレビュー状態を引き継ぐ（未変更は維持、変更はneedsReReview）
- `scripts/summarize_diffgr.py`: DiffGR JSON の進捗/網羅/出所（SHA含む）をサマリ表示
- `scripts/impact_report.py`: old/new 差分で「影響がある group / 影響がない group」を見える化（Markdown/JSON出力）
- `scripts/prepare_review.py`: 生成〜改善まで一括
- `scripts/view_diffgr_app.py`: 対話ビューア（`textual` / `prompt`）
- `scripts/export_diffgr_html.py`: 静的HTML出力
- `scripts/serve_diffgr_report.py`: HTML + 保存APIサーバ

## 10. 複数レビュア運用（仮想PR単位）

レビュアごとに担当グループを分けたい場合は、先に分割してからレビューし、最後にマージします。

```powershell
# 0) 事前チェック（未割当や重複があれば直す）
python scripts\check_virtual_pr_coverage.py --input out\work\05.ai-refined.diffgr.json

# 1) 仮想PR単位に分割
python scripts\split_group_reviews.py `
  --input out\work\05.ai-refined.diffgr.json `
  --output-dir out\reviewers

# 2) 各レビュアが担当ファイルを Textual でレビュー
python scripts\view_diffgr_app.py out\reviewers\01-<group>.diffgr.json --ui textual

# 3) 全員分を本体へマージ
python scripts\merge_group_reviews.py `
  --base out\work\05.ai-refined.diffgr.json `
  --input-glob "out/reviewers/*.diffgr.json" `
  --output out\work\06.merged-reviews.diffgr.json
```

注意:

- `--input-glob` には `*.diffgr.json` を使ってください（`manifest.json` は含めない）。
- 同じ chunk を複数ファイルが更新した場合、後から読み込んだファイルの内容で上書きされます。

## 11. 網羅チェック + AI修正（未割当/重複の自動修正）

`check_virtual_pr_coverage.py` が `2` で終了した場合、`--write-prompt` で AI 修正用の Markdown を作れます。

```powershell
python scripts\check_virtual_pr_coverage.py `
  --input out\work\05.ai-refined.diffgr.json `
  --write-prompt out\work\coverage-fix-prompt.md

python scripts\run_agent_cli.py `
  --config agent_cli.toml `
  --prompt out\work\coverage-fix-prompt.md `
  --output out\work\coverage-fix.slice_patch.json `
  --interactive

python scripts\apply_slice_patch.py `
  --input out\work\05.ai-refined.diffgr.json `
  --patch out\work\coverage-fix.slice_patch.json `
  --output out\work\05b.coverage-fixed.diffgr.json
```

## 12. レビュー後にコード修正した場合（再レビュー最小化）

レビューコメントを反映してコードを修正すると、chunk id が変わるため「前回の reviewed をそのまま使えない」ことがあります。  
`rebase_reviews.py` を使うと、`fingerprints.stable` ベースで同一chunkを認識し、未変更は `reviewed` を維持しつつ、変更されたものだけを `needsReReview` にできます。
さらに既定で、結果JSONの `meta.x-reviewHistory` にrebase履歴、`meta.x-impactScope` に影響範囲（影響あり/なしgroup）を記録します。
`meta.x-impactScope.coverageNew` は **rebase後の出力JSON** を基準に計算されます。

```powershell
# 1) 新しい差分スナップショットを作る（例: prepare_review を再実行）
python scripts\prepare_review.py `
  --base <base_ref> `
  --feature <new_feature_ref> `
  --output out\work\r2.review.diffgr.json `
  --title "DiffGR Review Bundle (round2)"

# 2) 前回レビュー済みの state を新スナップショットへ引き継ぐ
python scripts\rebase_reviews.py `
  --old out\work\05.ai-refined.diffgr.json `
  --new out\work\r2.review.diffgr.json `
  --output out\work\r2.rebased.diffgr.json

# 3) 網羅チェック（未割当/重複があれば修正）
python scripts\check_virtual_pr_coverage.py --input out\work\r2.rebased.diffgr.json
```

必要なら `--similarity-threshold` を下げると、テキストが少し変わったchunkも「同一とみなして needsReReview」に寄せられます。

## 13. よくあるハマりどころ

- Textual が起動しない  
  `python -m pip install -r requirements.txt` を再実行し、`--ui prompt` でも動くか確認してください。

- `t` で `textual` に切り替えたい  
  `t` は外部エディタ設定用です。UI切替は起動時の `--ui textual` です。

- `o` で VS Code が開かない  
  `t` で `editor mode=vscode` にして保存し、`code --version` が通ることを確認してください。

- HTML で保存が効かない  
  静的 HTML では自動保存されません。`serve_diffgr_report.py` 経由で開くか、`--save-reviews-url` を設定してください。

## 14. 参照ドキュメント

- 実運用手順: `docs/アプリの使い方.md`
- 仕様: `DiffGR_v1_仕様書.md`

## 15. レビュー成果物の Git 運用（別repo推奨）

本体コード repo を汚さず、複数レビュアでも衝突しにくくするために、`*.diffgr.json`（レビュー成果物）は別repoに集約する運用を推奨します。

- 1 bundle = 1差分スナップショット（`bundle.diffgr.json`）
- レビューアは group（仮想PR）単位に分割された `reviewers/*.diffgr.json` だけ編集してコミット（PR推奨）
- 取りまとめが `merge_group_reviews.py` で `merged.diffgr.json` を生成してコミット
- コード修正後は `rebase_reviews.py` で未変更は `reviewed` 維持、変更だけ `needsReReview` に寄せる

```mermaid
flowchart LR
  Code["本体コード repo"] -->|"prepare_review.py（出力先を別repoに）"| Bundle["<bundle-base.diffgr.json>"]
  Bundle -->|"split_group_reviews.py"| Reviewers["reviewers/*.diffgr.json"]
  Reviewers -->|"merge_group_reviews.py"| Merged["merged.diffgr.json"]
  Merged -->|"コード修正後"| Rebase["rebase_reviews.py"] --> Round2["rebased.diffgr.json"]
```

詳細: `docs/review_repo_workflow.md`

## 16. ライセンス

`LICENSE` を参照してください。
