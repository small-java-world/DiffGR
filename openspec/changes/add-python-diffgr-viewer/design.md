# Design: Python DiffGR Viewer CLI

## Context

`DiffGR` は JSON 形式で差分 (`chunks`)・レビュー割当 (`assignments`)・レビュー状態 (`reviews`) を保持する。  
現状リポジトリには生成スクリプト (`scripts/generate_diffgr.py`) はあるが、閲覧のための Python CLI がない。

本設計は、`.diffgr.json` を端末で読みやすく表示する最小実用ビューアを定義する。

## Goals

- Python 単体で `DiffGR v1` を読み込み、内容を人間可読表示できる。
- まずは CUI（テキスト出力）で、レビュー運用に必要な情報を最短で確認できる。
- `sample/ts20-base` と `sample/ts20-feature-5pr` 由来の生成ファイルを問題なく表示できる。

## Non-Goals

- GUI/Web UI の提供
- 差分編集・レビュー状態の書き戻し
- 厳密な JSON Schema バリデータ実装（本機能では軽量整合性チェックまで）

## Scope

- 追加対象: `scripts/view_diffgr.py`
- 入力: `*.diffgr.json`
- 出力: 標準出力テキスト（UTF-8）
- 対応OS: Windows / Linux / macOS（`python` 実行環境）

## User Scenarios

1. 全体把握  
`python scripts/view_diffgr.py out/sample-ts20.diffgr.json`  
-> タイトル、作成日時、chunk数、group数、coverage を表示。

2. グループ単位確認  
`python scripts/view_diffgr.py out/sample-ts20.diffgr.json --group g-all`  
-> group 内 chunk の要約一覧を表示。

3. 1 chunk 深掘り  
`python scripts/view_diffgr.py out/sample-ts20.diffgr.json --chunk <chunk_id>`  
-> header/範囲/line records を表示。

4. 状態フィルタ  
`python scripts/view_diffgr.py out/sample-ts20.diffgr.json --status needsReReview`  
-> 指定状態の chunk のみ抽出表示。

## CLI Interface

### Command

```bash
python scripts/view_diffgr.py <diffgr_json_path> [options]
```

### Options

- `--group <group_id>`: 指定 group の chunk を表示
- `--chunk <chunk_id>`: 指定 chunk 詳細を表示
- `--status <unreviewed|reviewed|ignored|needsReReview>`: 状態で絞り込み
- `--file <substring>`: `filePath` 部分一致で絞り込み
- `--max-lines <N>`: chunk 詳細表示時の最大行数（既定: 120）
- `--show-patch`: `patch` があれば末尾に表示（既定は非表示）
- `--json`: 表示結果を viewer向け整形JSONで出力（デバッグ用）

### Exit Codes

- `0`: 正常終了
- `1`: 入力ファイル不正 / JSON解析失敗 / 必須キー欠落
- `2`: 指定フィルタに一致なし（操作上の非致命エラー）

## Data Contract (Reader Side)

### 必須トップレベル

- `format == "diffgr"`
- `version == 1`
- `meta`, `groups`, `chunks`, `assignments`, `reviews`

### Viewerが行う整合性チェック

- `groups[].id` 一意
- `chunks[].id` 一意
- `assignments` の group キーが `groups[].id` に存在
- `assignments` 内 chunk ID が `chunks[].id` に存在
- `reviews` キーが `chunks[].id` に存在

不整合は警告として収集し、表示ヘッダに件数を出す（致命的でない限り継続表示）。

## Rendering Design

### 1. Summary Block

表示順:

1. `meta.title`
2. `meta.createdAt`
3. source (`type/base/head`)
4. chunk数 / group数 / review件数
5. coverage:
   - `Unassigned`
   - `Reviewed`
   - `Pending`
   - `Tracked`
   - `CoverageRate`

coverage 定義は `DiffGR_v1_仕様書.md` の集合定義に従う。

### 2. Group List Block

`groups` を `order` 昇順（未設定は末尾）で表示し、各 group の chunk 件数を併記。

### 3. Chunk List Block

1行要約フォーマット:

`<status> <chunk_id:12> <filePath> old(start,count) new(start,count) <header?>`

`status` 色分け（ANSI対応端末のみ）:

- `reviewed`: 緑
- `needsReReview`: 黄
- `unreviewed`: 白
- `ignored`: 暗色

### 4. Chunk Detail Block

- chunk metadata (`id`, `filePath`, `old/new`, `header`, `fingerprints`)
- `lines[]` を順序通り表示
  - `context`: `" " + text`
  - `add`: `"+" + text`
  - `delete`: `"-" + text`
  - `meta`: `"\\" + text`
- 行番号列: `oldLine | newLine | content`

## Internal Architecture

`scripts/view_diffgr.py` は単一ファイルだが、責務を関数分割する。

- `load_document(path) -> dict`
- `validate_document(doc) -> list[str]`（警告リスト）
- `build_indexes(doc) -> dict`（group/chunk/review索引）
- `compute_metrics(doc) -> dict`
- `filter_chunks(...) -> list[chunk]`
- `render_summary(...)`
- `render_groups(...)`
- `render_chunks(...)`
- `render_chunk_detail(...)`
- `main(argv) -> int`

## Error Handling

- JSON パース失敗: `stderr` に原因出力、終了コード `1`
- `format/version` 不一致: エラー終了 `1`
- `--group/--chunk` 未存在: メッセージ出力、終了コード `2`
- `lines` 異常（型不整合など）: 警告出力して該当 chunk をスキップ

## Performance

- 想定: 数千 chunk まで
- 処理方針: 単純ロード + インメモリ索引（O(n)）
- 画面出力はフィルタ後データのみに限定

## Security

- 入力はローカル JSON のみ（外部通信なし）
- `patch` 表示はデフォルトOFF（機密情報露出を抑止）
- 例外メッセージにトークン/環境変数を含めない

## Testing Plan

### Unit-level

- `compute_metrics` の算出テスト（`ignored` 除外を含む）
- `filter_chunks` の組み合わせテスト（group + status + file）
- `validate_document` の不整合検出テスト

### Integration-level

- `scripts/generate_diffgr.py` で作成した `out/sample-ts20.diffgr.json` を入力
- 正常系:
  - 全体表示
  - `--group g-all`
  - `--status reviewed`（0件時の扱い）
- 異常系:
  - 不正JSON
  - `format != diffgr`
  - 存在しない chunk 指定

## Rollout Plan

1. `scripts/view_diffgr.py` 実装
2. README に実行例追記
3. サンプル生成 (`generate_diffgr.py`) と表示の往復確認
4. 運用フィードバック後に `--json` / 色表示改善

## Open Questions

- `reviews` が空のとき、`status` 初期値を常に `unreviewed` で表示する運用で確定するか。
- `--show-patch` の既定を OFF のまま固定するか（セキュリティ優先）。
- 長い `filePath` の省略表示ルール（末尾優先/中間省略）を固定するか。
