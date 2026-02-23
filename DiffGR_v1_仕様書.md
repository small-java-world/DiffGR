# DiffGR v1 仕様書（画像ベース再構成）

Status: Stable (v1)

本書は、提示された画像（`IMG_1047.jpg`〜`IMG_1057.jpg`）から読み取れる内容をもとに再構成した `DiffGR v1` の詳細仕様です。  
`DiffGR` は、コード差分（主に unified diff の hunk）を、レビュー用グルーピングとレビュー状態つきで自己完結 JSON として表現する形式です。

## 1. 設計目標

- 1つの大きい PR を機能単位の小さいレビュー片（slice）に分割してレビューしやすくする。
- ファイル単体で持ち運べるオフラインレビューを可能にする（リポジトリアクセス不要）。
- すべての変更が何らかの slice に割り当てられ、レビューされていることを追跡しやすくする。

### 1.1 非目標（v1）

- 完全な before/after ファイル内容の再構築（`DiffGR` は full file ではなく hunk 中心）。
- すべてのケースで完全な patch 再適用保証（`patch` は補助的）。
- GitHub/GitLab など提供元ごとの取得方式の標準化（ホスト非依存）。

## 2. 準拠キーワード

`MUST` / `MUST NOT` / `SHOULD` / `SHOULD NOT` / `MAY` は RFC 2119 の意味で解釈する。

## 3. ファイル命名とエンコーディング

- 推奨拡張子: `*.diffgr.json`
- エンコーディング: `UTF-8`
- 改行: `\n` 推奨（`CRLF` の許容は必要）

## 4. トップレベル JSON オブジェクト

### 4.1 必須フィールド

`DiffGR v1` 文書は以下を持つ JSON object でなければならない。

- `format` (string, MUST): `"diffgr"`
- `version` (integer, MUST): `1`
- `meta` (object, MUST): §5
- `groups` (array, MUST): §6
- `chunks` (array, MUST): §7
- `assignments` (object, MUST): §8
- `reviews` (object, MUST): §9

### 4.2 任意フィールド

- `patch` (string, OPTIONAL): unified diff テキスト（§10）

### 4.3 不明フィールド / 拡張ポイント

- consumer（viewer/validator）は、トップレベルだけでなく任意の object 階層で未知フィールドを無視しなければならない。
- producer は拡張フィールドを追加してよい。
- 拡張フィールド名は `x-` プレフィックスを推奨する。

## 5. `meta` オブジェクト

`meta` は object。

- `title` (string, REQUIRED): 人間可読タイトル
- `createdAt` (string, REQUIRED): ISO-8601 timestamp（例: `"2026-02-21T12:34:56Z"`）
- `source` (object, OPTIONAL): 差分の出所
  - `type` (string, REQUIRED if source present): 例 `"github_pr"` / `"git_patch"` / `"example"` / ...
  - `url` (string, OPTIONAL): source URL
  - `base` (string, OPTIONAL): base ref（branch/SHA）
  - `head` (string, OPTIONAL): head ref（branch/SHA）
  - `baseSha` (string, OPTIONAL): base の解決済み commit SHA（40桁 hex 推奨）
  - `headSha` (string, OPTIONAL): head の解決済み commit SHA（40桁 hex 推奨）
  - `mergeBaseSha` (string, OPTIONAL): `git merge-base base head` の SHA（`git diff base...head` の基準）
  - `description` (string, OPTIONAL)
- `notes` (string, OPTIONAL): 自由記述

consumer は `title` を目立つ形で表示すべき。

### 5.1 推奨拡張: レビュー修正履歴と影響範囲

`DiffGR v1` は未知フィールドを許容するため、レビュー運用では以下の拡張を推奨する。

- `meta.x-reviewHistory` (array, OPTIONAL): レビュー運用イベント履歴
  - 例: `rebase_reviews.py` 実行結果、担当再割当、手動判断メモ
  - 推奨要素（object）:
    - `type` (string): 例 `rebase`
    - `at` (string): ISO-8601 timestamp
    - `from` / `to` (object): 対象 snapshot の参照情報（path/title/source）
    - `result` (object): match 統計や `needsReReview` 件数など
    - `impactScope` (object): 影響あり/影響なし group 情報
- `meta.x-impactScope` (object, OPTIONAL): 最新の影響範囲サマリ
  - `grouping` (string): `old` / `new`
  - `impactedGroups` / `unaffectedGroups` (array)
  - `newOnlyChunkIds` / `oldOnlyChunkIds` (array)
  - `coverageNew` (object): 新snapshotの未割当/重複など
  - 実運用では `coverageNew` は「rebase後に保存された出力JSON」を基準に算出することを推奨
  - 大規模差分では履歴肥大化防止のため、`changedChunkIds` などID配列をサンプリングし
    `*Truncated` カウンタ（例: `changedChunkIdsTruncated`）を併記してよい

運用上の意図:

- 「どの修正ラウンドで、どの仮想PRが影響を受けたか」を JSON 単体で追跡可能にする
- 影響なし group のレビュアへ不要な再レビュー依頼を避ける

## 6. `groups`

### 6.1 Group object

各 group は object:

- `id` (string, REQUIRED): 一意 ID
- `name` (string, REQUIRED): 表示名
- `order` (integer, OPTIONAL): 並びヒント（小さい順）
- `tags` (array of strings, OPTIONAL): 任意ラベル

制約:

- `groups[].id` は一意。
- `id` は安定であるべき（編集で変えない）。

### 6.2 Reserved group IDs

以下の group ID は予約される:

- `unassigned`

規則:

- `groups[].id` に `unassigned` を使用してはならない。
- `assignments` のキーに `unassigned` を使用してはならない。
- `unassigned` は仮想 group としてのみ扱う。

## 7. `chunks`

### 7.1 Chunk object

各 chunk は object:

- `id` (string, REQUIRED): 一意 chunk ID
- `filePath` (string, REQUIRED): diff の「new 側」パス
- `old` (object, REQUIRED): 旧側 range（§7.2）
- `new` (object, REQUIRED): 新側 range（§7.2）
- `header` (string, OPTIONAL): hunk header（関数名など）
- `lines` (array, REQUIRED): 行レコード列（§7.3）
- `fingerprints` (object, OPTIONAL): `{ "stable": "<sha256-hex>", "strong": "<sha256-hex>" }`

制約:

- `chunks[].id` は一意。
- `chunks[].id` は大文字小文字を区別する不透明文字列として扱う（形式制約なし）。

`fingerprints` を使う場合の規則:

- `stable` と `strong` は 64 桁小文字16進（SHA-256 hex）でなければならない。
- `stable` は位置非依存 fingerprint（行番号や range の違いで変化しない）。
- `strong` は位置依存 fingerprint（行番号や range の違いを含めて変化する）。

推奨計算方法（再現性のため）:

- `stable`: `filePath` と `lines[].{kind,text}` のみを使って canonical JSON を作り、UTF-8 バイト列の SHA-256 を取る。
- `strong`: `filePath`、`old`、`new`、`header`、`lines[].{kind,text,oldLine,newLine}` を使って canonical JSON を作り、UTF-8 バイト列の SHA-256 を取る。

### 7.2 Range object（`old`, `new`）

- `start` (integer, REQUIRED): 1-based 開始行（メタデータ専用 chunk では 0 可）
- `count` (integer, REQUIRED): 行数（`>= 0`）

通常 hunk 由来では `start >= 1` かつ `count >= 1` を推奨。  
メタデータ専用 chunk では `start = 0`, `count = 0`。

### 7.3 Line record

`lines[]` の各要素は object:

- `kind` (string, REQUIRED): `"context"` / `"add"` / `"delete"` / `"meta"`
- `text` (string, REQUIRED): unified diff prefix を除いた本文
- `oldLine` (integer or null, REQUIRED): 旧側行番号
- `newLine` (integer or null, REQUIRED): 新側行番号

行番号規則（通常 hunk）:

- `context`: `oldLine` と `newLine` は整数
- `add`: `oldLine = null`, `newLine` は整数
- `delete`: `oldLine` は整数, `newLine = null`
- `meta`: 両方 null 許容

`lines[]` は順序付き列として表示すべき。

### 7.4 内部整合性（推奨）

producer は次を保つべき:

- hunk 内で `oldLine` は `context`/`delete` で +1 進行
- hunk 内で `newLine` は `context`/`add` で +1 進行
- 最初の `context`/`delete` 行の `oldLine` は `old.start` と一致
- 最初の `context`/`add` 行の `newLine` は `new.start` と一致

consumer は検証してよいが、手編集などによる逸脱には寛容であるべき。

### 7.5 メタデータ専用 chunk（hunk なし）

rename-only / mode-only / binary diff など hunk を持たない変更を落とさないための表現。  
表現規則:

- `old` は `{ "start": 0, "count": 0 }` でなければならない。
- `new` は `{ "start": 0, "count": 0 }` でなければならない。
- `lines` は空配列 `[]` でなければならない。

補足:

- メタデータ詳細（rename 先、mode 情報、binary 情報など）は拡張フィールド（例: `x-meta`）で保持してよい。

## 8. `assignments`

`assignments` は Group ID -> Chunk ID 配列のマップ:

```json
"assignments": {
  "g-login": ["f1fb5185636e", "ab12cd34ef56"],
  "g-auth": ["deadbeefcafe"]
}
```

規則:

- `assignments` のキーは既存 `groups[].id` に対応すること。
- 参照される chunk ID は `chunks[].id` に存在すること。
- `assignments` のキーに予約 ID `unassigned` を使ってはならない。
- 1つの chunk ID は高々1つの group にしか出現してはならない（違反は文書不正）。
- validator は重複割り当てを検出した場合、エラーとして報告しなければならない。

意味:

- assignment はレビュー slice を表す。
- group は複数ファイルの chunk を含んでよい。
- 単純なカバレッジ追跡と整合性確保のため、1 chunk は高々1 group にのみ割り当てる。
- 未割り当て chunk はどの assignment 配列にも現れない `chunks[]`。
- viewer は `unassigned` 仮想 group を算出してよい。

## 9. `reviews`

`reviews` は Chunk ID -> review record のマップ。

### 9.1 Review record

- `status` (string, REQUIRED): `"unreviewed"` / `"reviewed"` / `"ignored"` / `"needsReReview"`
- `reviewer` (string, OPTIONAL)
- `reviewedAt` (string, OPTIONAL): ISO-8601 timestamp
- `notes` (string, OPTIONAL)

整合性規則:

- `reviews` の各キー（chunk ID）は `chunks[].id` に存在しなければならない。
- `status = "reviewed"` の場合、`reviewedAt` は存在しなければならない。
- `reviewedAt` が存在する場合、ISO-8601 UTC timestamp（末尾 `Z`）を推奨する。

### 9.2 既定状態

chunk ID が `reviews` に存在しない場合、`"unreviewed"` と見なす。

### 9.3 状態の意味

- `unreviewed`: 未レビュー
- `reviewed`: レビュー済み（当該スナップショット）
- `ignored`: カバレッジ計算から除外（生成物やノイズ差分など）
- `needsReReview`: 以前レビュー済みだが変更/不確実のため再確認要

### 9.4 状態遷移（規範）

許可される遷移:

- `unreviewed -> reviewed | ignored`
- `reviewed -> needsReReview | ignored | reviewed`
- `needsReReview -> reviewed | ignored | needsReReview`
- `ignored -> unreviewed | reviewed | ignored`

規則:

- 上記以外の遷移は行ってはならない。
- `reviewed` への遷移時、producer は `reviewedAt` を更新すべき。
- `reviewed` から他状態へ遷移しても、監査目的で `reviewedAt`/`reviewer` を保持してよい。
- 既存 `reviewed` chunk が内容変更された場合（`fingerprints.strong` が変化）、producer は `needsReReview` へ遷移させるべき。

## 10. 任意 `patch` フィールド

- 同一変更セットに対応する unified diff を含めてよい。
- 含む場合は妥当な unified diff であるべき。
- `diff --git`, `index`, `---/+++` など file header を含んでよい。
- export/apply（例: `git apply`）に使ってよいが、正本は `chunks[]`。
- `patch` と `chunks[]` の内容が矛盾する場合、consumer/validator は警告を出すべき。
- 矛盾時でも canonical data は常に `chunks[]` とし、`patch` を優先してはならない。

## 11. 派生メトリクス（coverage）

`assignments` と `reviews` から次を算出する。

定義（`C` は全 chunk ID 集合）:

- `status(c)`: `reviews[c].status`。`reviews` に無ければ `"unreviewed"`。
- `Assigned = union(assignments[g])`（全 group `g` の割当集合）
- `UnassignedSet = C - Assigned`
- `IgnoredSet = { c in C | status(c) = "ignored" }`
- `TrackedSet = C - IgnoredSet`
- `ReviewedSet = { c in TrackedSet | status(c) = "reviewed" }`
- `PendingSet = { c in TrackedSet | status(c) in {"unreviewed","needsReReview"} }`

標準メトリクス:

- `Unassigned = |UnassignedSet|`
- `Reviewed = |ReviewedSet|`
- `Pending = |PendingSet|`
- `Tracked = |TrackedSet|`
- `CoverageRate = if Tracked == 0 then 1.0 else Reviewed / Tracked`

典型 policy 例:

- `Unassigned == 0`
- `Pending == 0`

`DiffGR` 自体は policy を強制しない（ツール/リンタ側の責務）。

## 12. 前方/後方互換

- v1 consumer は `format != "diffgr"` または `version != 1` を拒否しなければならない。
- v1 consumer は未知フィールドを無視すべき。
- producer は v1 内で既存フィールドの意味を変えるべきでない。

## 13. セキュリティ / プライバシー

- proprietary code を含み得るため機密成果物として扱う。
- export 前に secrets のマスキングを検討する。
- binary diff は巨大バイナリ埋め込みよりメタデータ専用 chunk を優先する。

## 14. 最小有効例（v1）

```json
{
  "format": "diffgr",
  "version": 1,
  "meta": { "title": "Example", "createdAt": "2026-02-22T00:00:00Z" },
  "groups": [{ "id": "g1", "name": "Slice 1", "order": 1, "tags": ["UI"] }],
  "chunks": [{
    "id": "0123456789ab",
    "filePath": "App/Foo.swift",
    "old": {"start": 1, "count": 1},
    "new": {"start": 1, "count": 2},
    "header": "func foo()",
    "lines": [
      {"kind":"context","text":"func foo() {","oldLine":1,"newLine":1},
      {"kind":"add","text":"  print(\"hi\")","oldLine":null,"newLine":2},
      {"kind":"context","text":"}","oldLine":2,"newLine":3}
    ]
  }],
  "assignments": { "g1": ["0123456789ab"] },
  "reviews": { "0123456789ab": { "status": "unreviewed" } }
}
```
