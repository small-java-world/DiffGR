# DiffGR P0 実装タスク
_作成日: 2026-03-13 (Asia/Tokyo)_

## 1. 目的

この文書は、DiffGR 改善提案のうち `P0` をそのまま実装に移すためのローカル作業メモです。  
対象は、`Review Handoff` や HTML 再編に進む前に直しておくべき基盤部分です。

P0 の狙いは次の 4 点です。

- autoslice の誤 group 化リスクを下げる
- rebase の rename / move 耐性を上げる
- 複数レビュア運用で review 情報が消えるリスクを下げる
- save / state 境界を整理して次段の拡張余地を作る

---

## 2. 優先順位

1. autoslice fingerprint 修正
2. rename-aware rebase
3. review merge の field-wise 化
4. save API の state 境界整理
5. Textual index / cache の下地
6. commit truncation の warning / fail-fast 化
7. schema 境界の明文化

この順にしている理由は、まず `レビュー結果の正しさ` に直結する箇所を先に直すためです。

---

## 3. タスク一覧

| ID | タスク | 主対象ファイル | 目的 | 完了条件 |
| --- | --- | --- | --- | --- |
| P0-1 | autoslice fingerprint 修正 | `diffgr/autoslice.py` | fingerprint collision を減らす | `header` 差分と blank-line only change が fingerprint に反映される |
| P0-2 | rename-aware rebase | `diffgr/review_rebase.py` | rename / move 後も review continuity を維持する | rename only は carry、rename + edit は `needsReReview` に寄る |
| P0-3 | review merge の field-wise 化 | `diffgr/review_split.py` | 複数レビュアの comment 消失を防ぐ | line comment が後勝ちで消えない |
| P0-4 | save API の state 境界整理 | `scripts/serve_diffgr_report.py` | `reviews` 以外の state を足せる入口を作る | `/api/state` を正規 endpoint にして state payload へ寄せられる |
| P0-5 | Textual index / cache の下地 | `diffgr/viewer_textual.py` | 不要な全走査を減らす | group 切替・status 変更で不要な再計算が減る |
| P0-6 | commit truncation 可視化 | `diffgr/autoslice.py` と CLI | silent truncate をなくす | warning または fail-fast で利用者が気づける |
| P0-7 | schema 境界の明文化 | docs / 仕様書 | bundle/state の責務を固定する | 後続実装で置き場判断がぶれない |

---

## 4. 実装タスク詳細

### P0-1 autoslice fingerprint 修正

**対象**

- `diffgr/autoslice.py`

**変更内容**

- `_change_fingerprint_from_parts()` の payload に `header` を含める
- `change_fingerprint_for_chunk()` で blank-line only add/delete を保持する
- `change_fingerprints_for_diff_text()` でも同じ基準に揃える

**完了条件**

- header が違う同内容 hunk は別 fingerprint になる
- blank-line only change が fingerprint に残る

**確認項目**

- unit test: header 差分ケース
- unit test: blank-line only change ケース

---

### P0-2 rename-aware rebase

**対象**

- `diffgr/review_rebase.py`

**変更内容**

- `contentStable` ベースの match を追加する
- `same filePath only` の similarity 依存を弱める
- rename-aware な候補探索を追加する
- match 強度ごとに `reviewed` / `needsReReview` の carry policy を明示する

**完了条件**

- rename のみなら `reviewed` を carry できる
- rename + 軽微変更なら `needsReReview` に寄る

**確認項目**

- fixture: rename only
- fixture: rename + edit

---

### P0-3 review merge の field-wise 化

**対象**

- `diffgr/review_split.py`

**変更内容**

- `status` の precedence を定義する
- `comment` の merge 方針を定義する
- `lineComments` を anchor 単位の append merge にする
- 将来 `groupBriefs` を同じ merge 流儀で扱えるように寄せる

**完了条件**

- 2 reviewer の line comment が両方残る
- status conflict が定義した precedence で解決される

**確認項目**

- unit test: lineComments merge
- unit test: status conflict merge

---

### P0-4 save API の state 境界整理

**対象**

- `scripts/serve_diffgr_report.py`

**変更内容**

- payload 正規化を `reviews` 専用から state 全体対応へ寄せる
- `/api/state` を正規 endpoint にする
- 将来 `groupBriefs`, `analysisState`, `threadState` を足せる入口を作る

**完了条件**

- 既存の HTML 保存が壊れない
- state 拡張に必要な payload 形が定義される

**確認項目**

- existing reviews payload
- extended state payload

---

### P0-5 Textual index / cache の下地

**対象**

- `diffgr/viewer_textual.py`

**変更内容**

- `chunk_id -> group_ids` cache
- `group_id -> metrics` cache
- dirty invalidate の仕組み
- report rows cache の下地

**完了条件**

- group 切替と status 更新時の不要な再計算が減る
- 既存 UI 挙動を壊さない

**確認項目**

- manual regression
- logging / profiling による再計算回数確認

---

### P0-6 commit truncation 可視化

**対象**

- `diffgr/autoslice.py`
- autoslice を呼ぶ CLI

**変更内容**

- `max_commits` 超過時に warning を返す or 表示する
- 必要なら `--fail-on-truncate` を追加する
- CLI 側で warning を見える化する

**完了条件**

- truncation が silent で起きない
- 利用者が warning か fail のどちらかで気づける

**確認項目**

- CLI test: warning
- CLI test: fail-fast option

---

### P0-7 schema 境界の明文化

**対象**

- docs
- `DiffGR_v1_仕様書.md` も必要なら更新

**変更内容**

- bundle の責務を書く
- review state の責務を書く
- `groupBriefs` の位置付けを書く
- save / split / merge / rebase の対象境界を書く

**完了条件**

- 実装者が `どこに置くべきか` で迷わない
- P1 以降の設計判断が揺れにくい

**確認項目**

- 文書レビュー

---

## 5. 受け入れテストの最小セット

### autoslice

- 同一 file・同一 add/delete・異なる header の 2 hunk が別 fingerprint になる
- blank-line only change が fingerprint から落ちない

### rebase

- rename のみで内容同一なら `reviewed` が carry される
- rename + 軽微変更なら `needsReReview` になる

### merge

- 2 reviewer の line comment が両方残る
- status conflict が precedence で解決される

### save

- `/api/state` で `reviews` と `groupBriefs` を保存できる
- `groupBriefs` を含む payload を受けられる下地がある

---

## 6. 実装チェックリスト

### P0 全体

- [ ] autoslice の fingerprint collision リスクを下げる
- [ ] rebase の rename / move 耐性を上げる
- [ ] merge の comment 消失リスクを下げる
- [ ] save の state 境界を整理する
- [ ] Textual の全走査箇所を減らす
- [ ] schema 境界を文書で固定する

### autoslice

- [ ] `_change_fingerprint_from_parts()` に `header` を含めた
- [ ] blank-line only add/delete を保持した
- [ ] truncation warning を入れた
- [ ] 必要なら fail-fast option を追加した
- [ ] header 差分ケースの test を追加した
- [ ] blank-line only ケースの test を追加した

### rebase

- [ ] `contentStable` match を追加した
- [ ] `same filePath only` を緩和した
- [ ] rename-aware 候補探索を追加した
- [ ] carry policy を match 強度ごとに整理した
- [ ] rename only fixture を追加した
- [ ] rename + edit fixture を追加した

### merge

- [ ] `status` precedence を定義した
- [ ] `comment` merge 方針を決めた
- [ ] `lineComments` append merge を実装した
- [ ] conflict test を追加した

### save / state

- [ ] payload 正規化を state 方向へ拡張した
- [ ] `/api/state` を正規 endpoint にした
- [ ] `groupBriefs` を載せられる下地を作った
- [ ] existing payload test を通した

### Textual

- [ ] `chunk_id -> group_ids` cache を入れた
- [ ] `group_id -> metrics` cache を入れた
- [ ] dirty invalidate を入れた
- [ ] 手動回帰確認をした

### docs

- [ ] bundle の責務を書いた
- [ ] review state の責務を書いた
- [ ] `groupBriefs` の責務を書いた
- [ ] save / split / merge / rebase の境界を書いた

---

## 7. P0 完了の定義

P0 完了は、単にコードが入った状態ではなく、次の状態を指します。

- autoslice の誤 group 化リスクが現状より明確に下がっている
- rename / move を含む再レビュー運用で state carry の信頼性が上がっている
- 複数レビュア運用で comment 消失が起きにくくなっている
- `Review Handoff` を入れるための保存境界が見えている
