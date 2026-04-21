# AI による DiffGR 全自動作成ガイド

このドキュメントは、AI（Claude など）に git diff から DiffGR を一から作成させるためのガイドです。
グループ設計・チャンク割り当て・Review Handoff の記述・HTML レポート出力まで、AI が一括で行う手順を説明します。

---

## 1. 全体の流れ

```
git diff (base..feature)
    ↓
generate_diffgr.py でチャンク抽出
    ↓
summarize_diffgr.py でチャンク一覧を AI に渡す
    ↓
AI がグループ設計・チャンク割り当て・Review Handoff を出力（layout.json）
    ↓
apply_diffgr_layout.py で diffgr.json に適用
    ↓
export_diffgr_html.py で HTML レポートを生成
    ↓
ブラウザで確認
```

---

## 2. Step 1 — diffgr.json の生成

`generate_diffgr.py` でリポジトリの git diff からチャンクを抽出します。
この時点では全チャンクが 1 グループ（`g-all`）にまとまっています。

```bash
python3 scripts/generate_diffgr.py \
  --repo /path/to/repo \
  --base main \
  --feature feature/my-branch \
  --title "My PR title" \
  --output out/pr.diffgr.json
```

---

## 3. Step 2 — AI に渡す情報

### 3-1. チャンク一覧の取得

```bash
python3 scripts/summarize_diffgr.py --input out/pr.diffgr.json
```

グループ数・チャンク数・カバレッジが表示されます。

### 3-2. 各チャンクの差分本文

`diffgr.json` の `chunks[]` を AI に渡します。各チャンクの重要フィールド：

| フィールド | 内容 |
|---|---|
| `id` | チャンクの一意 ID（SHA256）。グループ割り当てに使用 |
| `filePath` | 変更ファイルのパス |
| `old` / `new` | 変更前後の行範囲 `{start, count}` |
| `lines[]` | 差分行（`kind: add/delete/context`、`text`、`oldLine`、`newLine`） |

> チャンク数が多い場合は `chunks[]` の `id` と `filePath`（+ 先頭数行）だけを抽出して渡してもよい。

---

## 4. Step 3 — AI へのプロンプトテンプレート

以下をそのまま AI に渡してください。`{...}` の部分を実際の情報に置き換えます。

````
以下は DiffGR 形式のコードレビュー差分データです。
グループ設計・チャンク割り当て・Review Handoff を一括で作成し、後述の JSON フォーマットで出力してください。

## サマリー

{summarize_diffgr.py の出力をここに貼る}

## チャンク一覧（id・filePath・header）

{diffgr.json の chunks[] から id, filePath, old, new, lines の先頭5行程度を抽出して貼る}

---

## 出力フォーマット

以下の JSON を出力してください。

```json
{
  "groups": [
    {
      "id": "<kebab-case の英数字 ID。例: g-auth>",
      "name": "<レビュアに見せるグループ名（日本語可）>",
      "order": 1,
      "tags": ["任意タグ"]
    }
  ],
  "assignments": {
    "<group-id>": ["<chunk-id>", "<chunk-id>"]
  },
  "groupBriefs": {
    "<group-id>": {
      "status": "ready",
      "summary": "このグループで何をしたかを2〜3文で説明",
      "focusPoints": ["レビュアに特に見てほしい点"],
      "testEvidence": ["テストや動作確認の証跡（省略可）"],
      "knownTradeoffs": ["既知のトレードオフ（省略可）"],
      "questionsForReviewer": ["レビュアへの質問（省略可）"]
    }
  }
}
```

注意：
- すべてのチャンクをいずれかのグループに割り当てること（重複割り当て不可）
- group id は kebab-case の英数字のみ（例: g-auth, g-api-routes）
- assignments の値はチャンクの id（SHA256 文字列）をそのままコピーすること
- すべてのグループに groupBriefs を記述すること
- JSON のみを出力し、前後に説明文を入れないこと
````

---

## 5. AI の出力例

```json
{
  "groups": [
    { "id": "g-auth", "name": "認証", "order": 1, "tags": ["backend"] },
    { "id": "g-api",  "name": "API ルート", "order": 2, "tags": ["backend"] },
    { "id": "g-frontend", "name": "フロントエンド", "order": 3, "tags": ["frontend"] }
  ],
  "assignments": {
    "g-auth": [
      "a1b2c3d4e5f6...",
      "f6e5d4c3b2a1..."
    ],
    "g-api": [
      "1234567890ab..."
    ],
    "g-frontend": [
      "abcdef012345..."
    ]
  },
  "groupBriefs": {
    "g-auth": {
      "status": "ready",
      "summary": "JWT の有効期限を env 変数経由で設定可能にし、リフレッシュトークンを新規実装しました。",
      "focusPoints": ["verifyToken の失敗時に logger.warn を追加"],
      "testEvidence": ["jwt.test.ts で sign / verify / invalid の 3 ケースをカバー"],
      "knownTradeoffs": [],
      "questionsForReviewer": ["JWT_EXPIRY_SECONDS のデフォルト 900秒は要件と合っているか確認をお願いします"]
    },
    "g-api": {
      "status": "ready",
      "summary": "タスク作成・削除に Zod バリデーションと権限チェックを追加しました。",
      "focusPoints": ["DELETE /:id に所有者チェックを追加（403 Forbidden）"],
      "testEvidence": [],
      "knownTradeoffs": [],
      "questionsForReviewer": []
    },
    "g-frontend": {
      "status": "ready",
      "summary": "タスク一覧画面に楽観的 UI 更新を導入し、削除後の再フェッチを廃止しました。",
      "focusPoints": ["useOptimisticDelete フックの rollback ロジック"],
      "testEvidence": [],
      "knownTradeoffs": ["ネットワークエラー時のロールバック UI は未実装"],
      "questionsForReviewer": []
    }
  }
}
```

---

## 6. AI の出力を適用する

AI の出力を `layout.json` として保存し、以下のコマンドで適用します。

```bash
python3 scripts/apply_diffgr_layout.py \
  --input out/pr.diffgr.json \
  --layout layout.json \
  --output out/pr.diffgr.json
```

`apply_diffgr_layout.py` は以下を一括で処理します：

| フィールド | 処理内容 |
|---|---|
| `groups` | diffgr.json の `groups[]` を置き換える |
| `assignments` | diffgr.json の `assignments{}` を置き換える |
| `groupBriefs` | diffgr.json の `groupBriefs{}` をマージ（追記）する |

適用後、`summarize_diffgr.py` で割り当て漏れやエラーがないか確認してください。

```bash
python3 scripts/summarize_diffgr.py --input out/pr.diffgr.json
```

`Coverage: ok=True unassigned=0` になっていれば OK です。

---

## 7. HTML レポートの出力

```bash
# 全グループをまとめて出力（レビュアに渡す場合はこちら）
python3 scripts/export_diffgr_html.py \
  --input out/pr.diffgr.json \
  --output out/report.html \
  --open

# 特定グループだけ出力
python3 scripts/export_diffgr_html.py \
  --input out/pr.diffgr.json \
  --group g-auth \
  --output out/report-auth.html \
  --open
```

---

## 8. 完全な一括実行スクリプト例

```bash
#!/bin/bash
set -e

REPO=/path/to/repo
BASE=main
FEATURE=feature/my-branch
TITLE="My PR"
OUT=out/pr.diffgr.json

# 1. チャンク生成
python3 scripts/generate_diffgr.py \
  --repo "$REPO" --base "$BASE" --feature "$FEATURE" \
  --title "$TITLE" --output "$OUT"

# 2. AI 向け情報を表示（コピーしてプロンプトに貼る）
python3 scripts/summarize_diffgr.py --input "$OUT"

# --- ここで AI にプロンプトを渡して layout.json を作成 ---

# 3. レイアウト適用
python3 scripts/apply_diffgr_layout.py \
  --input "$OUT" --layout layout.json --output "$OUT"

# 4. 確認
python3 scripts/summarize_diffgr.py --input "$OUT"

# 5. HTML 出力
python3 scripts/export_diffgr_html.py \
  --input "$OUT" --output out/report.html --open
```

---

## 9. 各フィールドの仕様

### groups[]

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `id` | string | 必須 | kebab-case の英数字 ID（例: `g-auth`） |
| `name` | string | 必須 | グループ表示名（日本語可） |
| `order` | number | 推奨 | 表示順（1 始まり） |
| `tags` | string[] | 任意 | 任意のタグ（例: `["backend", "security"]`） |

### assignments{}

```json
{
  "<group-id>": ["<chunk-id>", "<chunk-id>", ...]
}
```

- キーはグループ ID
- 値はチャンク ID の配列（diffgr.json の `chunks[].id` と完全一致する SHA256 文字列）
- 1 チャンクは 1 グループにのみ割り当て可能
- 未割り当てチャンクがあると `apply_diffgr_layout.py` が警告を出す

### groupBriefs{}

`docs/ai_review_handoff.md` の「7. groupBriefs の各フィールド仕様」を参照。

---

## 10. 運用のコツ

- **チャンク数が多い場合**は `chunks[]` の `id` と `filePath`（+ `lines` 先頭数行）だけを渡すと token 節約できる
- **グループ数の目安**は 3〜8 個。多すぎるとレビュアが迷う
- **AI の出力は必ず人間が確認**してから `status: "ready"` にする
- 割り当てミスは `summarize_diffgr.py` の `unassigned` / `unknownChunks` 欄で検出できる
- `groupBriefs` だけ後から追記したい場合は `docs/ai_review_handoff.md` のワークフローを使う
