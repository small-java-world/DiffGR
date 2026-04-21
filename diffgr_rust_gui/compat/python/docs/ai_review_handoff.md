# AI による Review Handoff 自動生成ガイド

このドキュメントは、AI（Claude など）に Review Handoff（`groupBriefs`）を自動生成させるためのガイドです。
人間が手動で `b` キーや `Edit Handoff` ボタンで入力する代わりに、AI にコードを読ませて引き継ぎコメントを書いてもらう手順を説明します。

---

## 1. 全体の流れ

```
diffgr.json を読む
    ↓
AI にグループごとのチャンク差分を渡す
    ↓
AI が state JSON (groupBriefs) を出力する
    ↓
apply_diffgr_state.py で diffgr.json に適用する
    ↓
Textual UI / HTML レポートで確認する
```

---

## 2. AI に渡す情報

AI には以下の情報を渡します。`summarize_diffgr.py` と `diffgr.json` 本体から取得できます。

### 2-1. グループ一覧と割り当てチャンク

```bash
python3 scripts/summarize_diffgr.py --input your.diffgr.json
```

グループID・グループ名・チャンク数が一覧表示されます。

### 2-2. 各グループの差分本文

`diffgr.json` の `chunks[]` と `assignments` から、グループごとのチャンク差分を抽出して渡します。
各チャンクの以下のフィールドが重要です：

| フィールド | 内容 |
|---|---|
| `filePath` | 変更されたファイルのパス |
| `header` | 変更箇所のヘッダ（関数名など） |
| `lines[]` | 差分行（`kind: add/delete/context`、`text`） |

---

## 3. AI への指示（プロンプトテンプレート）

以下をそのまま AI に渡してください。`{...}` の部分を実際の情報に置き換えます。

````
以下は DiffGR 形式のコードレビュー差分データです。
グループごとに Review Handoff を日本語で作成し、後述の JSON フォーマットで出力してください。

## グループ一覧

{summarize_diffgr.py の出力をここに貼る}

## 各グループの差分

{diffgr.json の groups[] と chunks[] の内容をここに貼る}

---

## 出力フォーマット

以下の JSON を出力してください。グループIDは diffgr.json の groups[].id と一致させること。

```json
{
  "groupBriefs": {
    "<group-id>": {
      "status": "ready",
      "summary": "このグループで何をしたかを2〜3文で説明（レビュアが最初に読む）",
      "focusPoints": [
        "レビュアに特に見てほしい点（複数可）"
      ],
      "testEvidence": [
        "テストや動作確認の証跡（省略可）"
      ],
      "knownTradeoffs": [
        "既知のトレードオフや将来課題（省略可）"
      ],
      "questionsForReviewer": [
        "レビュアに判断を仰ぎたい点（省略可）"
      ]
    }
  }
}
```

注意：
- すべてのグループに対して出力すること
- summary は必須。他のフィールドは内容がなければ空配列 [] でよい
- status は "ready"（引き継ぎ完了）を基本とする
- JSON のみを出力し、前後に説明文を入れないこと
````

---

## 4. AI の出力例

```json
{
  "groupBriefs": {
    "g-auth": {
      "status": "ready",
      "summary": "JWT の有効期限を env 変数経由で設定可能にし、リフレッシュトークンを新規実装しました。SECRET の参照を process.env 直接参照から型安全な env.jwtSecret に統一しています。",
      "focusPoints": [
        "verifyToken の失敗時に logger.warn を追加（以前はサイレント）",
        "RefreshToken の revoke は revokedAt フラグで管理（物理削除なし）"
      ],
      "testEvidence": [
        "jwt.test.ts で sign / verify / invalid token の3ケースをカバー"
      ],
      "knownTradeoffs": [
        "RevofreshToken の有効性確認は毎回 DB を参照するため、高頻度アクセス時はキャッシュを検討"
      ],
      "questionsForReviewer": [
        "JWT_EXPIRY_SECONDS のデフォルト 900秒（15分）は要件と合っているか確認をお願いします"
      ]
    },
    "g-api": {
      "status": "ready",
      "summary": "タスク作成・削除に Zod バリデーションと権限チェックを追加しました。DELETE は所有者以外が操作すると 403 を返すよう変更しています。",
      "focusPoints": [
        "POST / のバリデーションエラーは 400 + errors 配列で返す（以前はスルーしていた）",
        "DELETE /:id に所有者チェックを追加（403 Forbidden）"
      ],
      "testEvidence": [],
      "knownTradeoffs": [],
      "questionsForReviewer": [
        "タスクの status フィールドは open / in_progress / done の3値ですが、追加が必要な値はありますか？"
      ]
    }
  }
}
```

---

## 5. 生成した state JSON を適用する

AI の出力を `handoff.state.json` として保存し、以下のコマンドで適用します。

```bash
# diffgr.json 本体に直接書き込む場合
python3 scripts/apply_diffgr_state.py \
  --input your.diffgr.json \
  --state handoff.state.json \
  --output your.diffgr.json

# 外部 state ファイルとして分離管理する場合（既存の state.json にマージ）
python3 scripts/merge_diffgr_state.py \
  --base out/state/review-state.json \
  --input handoff.state.json \
  --output out/state/review-state.json
```

---

## 6. 適用結果の確認

```bash
# Textual UI で確認（グループを選択して b キーで内容を確認）
python3 scripts/view_diffgr_app.py your.diffgr.json --ui textual

# または HTML レポートで確認（Edit Handoff ボタン）
python3 scripts/export_diffgr_html.py \
  --input your.diffgr.json \
  --output out/report.html \
  --open
```

---

## 7. groupBriefs の各フィールド仕様

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `status` | string | 推奨 | `draft` / `ready` / `acknowledged` / `stale` |
| `summary` | string | 必須 | 変更の概要（2〜3文） |
| `focusPoints` | string[] | 任意 | 特に見てほしい点 |
| `testEvidence` | string[] | 任意 | テスト・動作確認の証跡 |
| `knownTradeoffs` | string[] | 任意 | 既知のトレードオフ・将来課題 |
| `questionsForReviewer` | string[] | 任意 | レビュアへの質問 |
| `mentions` | string[] | 任意 | メンションするユーザ名（例: `@alice`） |

`status` の意味：

| 値 | 意味 |
|---|---|
| `draft` | 作成中（デフォルト） |
| `ready` | 引き継ぎ完了・レビュア確認待ち |
| `acknowledged` | レビュア確認済み |
| `stale` | コード変更により内容が古くなった |

---

## 8. 運用のコツ

- **差分が大きいグループほど AI が効果的**。50行以上の変更があるグループは AI に任せると漏れが少ない
- **AI の出力は必ず人間がレビュー**してから `status: "ready"` にする。誤情報が含まれることがある
- AI に渡す差分が長すぎる場合は、グループ単位で分割してリクエストする
- `questionsForReviewer` に「確認不要な質問」が入りやすいので、適宜削除する
