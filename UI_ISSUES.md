# DiffGR Rust GUI 改善分析：Python版との比較

> Python製のTextual TUI (`diffgr/viewer_textual.py`, 3825行) を Rust/egui GUI (`diffgr_rust_gui/src/app.rs`, 6206行) に移植中。
> Python版の機能を徹底調査し、Rust版との差分・問題点をすべて洗い出した記録。

## 分類

- **[MISSING]** Python版にあってRust版にない機能
- **[UI-BAD]** Rust版のUI設計上の問題（Python版より悪い）
- **[UX-BAD]** 操作性・体験の問題

---

## 1. 機能の欠落（MISSING）

### 1-1. 差分表示

- **[MISSING] シンタックスハイライト**
  Python版はPygments統合で言語別カラーリング・複数テーマ対応（github-dark, one-dark, nord, dracula, monokai等）。
  Rust版は単色のadd/delete色のみ。コードの可読性が根本的に低い。

- **[MISSING] Old/New幅比率調整**
  Python版は `Alt+Left/Alt+Right` でサイドバイサイドのold/new列幅比率をリアルタイム変更可能。
  Rust版は固定。ファイルによってold/newのコード量が大きく違うのに対応できない。

- **[MISSING] コンテキスト行フォーカス（Focus Changes）モード**
  Python版は `z` キーで「変更行のみ表示・コンテキスト行を非表示」を瞬時トグル。
  Rust版はComboBoxで「変更行のみ/変更周辺/全行」を選ぶ操作で、直感的でなくワンタッチで切り替えられない。

- **[MISSING] グループレポートモード**
  Python版は `d` キーでグループ全体のdiff（割り当てられた全チャンク）を1画面に一覧表示できる。
  Rust版は1チャンクずつしか見られない。グループ全体の変更を俯瞰する手段がない。

### 1-2. ペイン・レイアウト操作

- **[MISSING] ペイン幅のマウスドラッグ変更**
  Python版はPaneSplitter（分割線）をドラッグして左右ペイン比率を自由に調整できる。
  Rust版は左列260px・中列380px固定。解像度やコンテンツに合わせられない。

- **[MISSING] ペイン幅のキーボード調整**
  Python版は `[` / `]` キーで左ペインを5%単位で拡縮。マウス不要。
  Rust版は不可。

- **[MISSING] ズームイン/アウト**
  Python版は `=` / `-` でフォントスケールを変更。
  Rust版はなし。

### 1-3. チャンク・グループ選択操作

- **[MISSING] 複数チャンク範囲選択**
  Python版は `Shift+Up/Down`（範囲選択）、`k/j`（選択拡張）、`x`（トグル選択）、`Ctrl+A`（表示中全選択）、`Esc`（選択解除）で精密な複数選択が可能。
  Rust版は単一選択のみ。一括操作ボタンは常に「表示中の全チャンク」に適用されてしまう。

- **[MISSING] チャンク一覧の `sel` 列（チェックボックス列）**
  Python版のChunks DataTableには複数選択状態を示すチェックボックス列がある。
  Rust版は選択中かどうかの視覚的表現が行のハイライトのみ。

- **[MISSING] `header`（hunk header）列**
  Python版のChunks DataTableにはhunk headerフィールド（`class Auth:` `def login():` 等）が列表示される。
  Rust版のチャンクリストにはheaderがなく、どのクラス/関数の変更かが分からない。

### 1-4. Groups・グループ管理

- **[MISSING] Groups DataTableの `pending` カウント列**
  Python版は未レビュー＋再レビュー必要を合算した「pending」件数を列表示する。
  Rust版はプログレスバーのみで、「何件残っているか」が数字で分からない。

- **[MISSING] Groups DataTableの `brief`（Handoffステータス）列**
  Python版はHandoffのステータス（draft/ready/acknowledged/stale）をグループ一覧で即視認できる。
  Rust版はHandoffタブを開かないと確認不可。

- **[MISSING] グループ操作のキーバインド**
  Python版は `n`（新規グループ）/ `e`（グループ名変更）/ `a`（チャンク割当）/ `u`（チャンク解除）/ `g`（Groupsへフォーカス）/ `c`（Chunksへフォーカス）/ `l`（Linesへフォーカス）で素早く操作できる。
  Rust版は対応する操作がUIに分散し、マウス操作が多く必要。

### 1-5. GroupBrief（Review Handoff）

- **[MISSING] フォームベースの構造化編集**
  Python版のGroupBriefModalはフィールドが分かれている：
  - summary（概要）
  - focusPoints（確認ポイント、1行1項目）
  - testEvidence（テスト証跡、1行1項目）
  - knownTradeoffs（既知の trade-off）
  - questionsForReviewer（レビュアーへの質問）
  - mentions（メンション列）
  Rust版は巨大な1テキストエディタに全フィールドが混在しており、構造が失われ記入しにくい。

- **[MISSING] GroupBrief表示・承認モーダル（GroupBriefViewerModal）**
  Python版はGroupBriefViewerModalで「Handoffを読みながら差し戻しコメントを書いて承認/却下」を1モーダル内で完結できる。
  Rust版はHandoffタブとApprovalタブを行き来する必要があり、操作が分断される。

- **[MISSING] `acknowledgedBy` 承認履歴表示**
  誰がいつ承認し、何のノートを残したかの履歴（actor/at/note）がRust版のUIで見当たらない。

### 1-6. State操作

- **[MISSING] selection token単位のstate-apply**
  Python版は `state-apply` で「何を引き継ぐか」をトークン単位で選択可能（4種類のplan: handoffs/reviews/ui/all）。
  Rust版のMergeは粗く、細かい選択適用ができない。

- **[MISSING] impact-apply-preview / impact-apply**
  Python版は旧→新DiffGRへのimpact分析結果を元に「どのレビュー・Handoffを引き継ぐか」を選択的に適用（`Ctrl+Shift+D`でpreview、`Ctrl+Alt+M`でapply）。
  Rust版はImpactタブで計算表示まではできるが、適用操作が限定的。

- **[MISSING] state bind/unbind**
  Python版は `Ctrl+B`/`Ctrl+U` でセッション中のデフォルトstate fileを明示的にbind/unbindできる。
  Rust版の「State保存先」設定は近いが、bind/unbindの概念が明示的でない。

### 1-7. エディタ連携

- **[MISSING] 行番号指定でエディタを開く**
  Python版は「実ファイルを開く」で該当行番号まで指定してVS Code/Cursor等を起動する（`code --goto path:line`）。
  Rust版は行番号指定なし。ファイルは開くが該当行まで飛べない。

- **[MISSING] エディタモード設定**
  Python版はsettingsでeditorMode（auto/vscode/cursor/default-app/custom）とカスタムコマンドを設定可能。
  Rust版はシステムデフォルトのみ。

### 1-8. UI設定・永続化

- **[MISSING] UI density設定**
  Python版は compact/normal/comfortable の3段階でUI密度を切り替えられる。
  Rust版は「コンパクト行」チェックボックスのみ（2段階）。

- **[MISSING] 設定モーダル（Settings Dialog）**
  Python版は `t` キーで設定モーダルを呼び出し、6項目（editorMode, customEditorCommand, diffSyntax, diffSyntaxTheme, uiDensity, autoWrap）を一覧編集できる。
  Rust版は設定がトップバーのチェックボックス群に分散しており、全体像が把握しにくい。

---

## 2. UI設計の問題（UI-BAD）

### 2-1. トップバーが過密・複雑

- **[UI-BAD] 3行のトップバー**
  DiffGRパス入力・Stateパス入力・作業ルート設定が3行に並び、画面上部の約1/4を占領している。
  Python版はHeader（タイトル/ステータス）とFooter（キーバインドヒント）だけで必要最小限。
  ファイル操作UIが常時表示されている必要はなく、大半の操作後は邪魔になる。

- **[UI-BAD] チェックボックスの氾濫**
  トップバー3行目に9個のチェックボックスが横並び：
  state自動保存、レビュー済みで次へ、ちらつき抑制、滑らかスクロール、検索遅延適用、読込/保存を別スレッド、超長行省略、コンパクト行、UI状態記憶
  どれをオンにすれば良いか分からない。設定の性質（常設/一時/パフォーマンス）が混在している。

- **[UI-BAD] トップバーにタブジャンプボタンが並んでいる**
  「Coverage」「Impact」「Approval」「仮想PR」「ヘルプ」ボタンがトップバー1行目に存在するが、これらはタブ切り替えで到達できる（タブが12個あるのに加えてボタンまで用意して冗長）。

### 2-2. タブ設計の失敗

- **[UI-BAD] 12個のタブ**
  Diff / Review / Handoff / Layout / Coverage / Impact / Approval / VirtualPr / Tools / Diagnostics / Summary / State
  タブが多すぎて何がどこにあるか分からない。Python版は画面を汚さずキーバインドで必要な操作を直接呼び出す設計。

- **[UI-BAD] タブ名が英語混じりで不統一**
  "VirtualPr"、"Handoff"、"Diagnostics" など英語表記と、"仮想PR" などの日本語表記が揺れている。

- **[UI-BAD] Diagnosticsタブが同列に並ぶ**
  フレームタイムやキャッシュ統計などの開発者向け診断情報がユーザー向けタブと同列に並んでいる。通常使用では不要で混乱を招く。

### 2-3. チャンクリストのUI

- **[UI-BAD] hunk headerが表示されない**
  チャンク行にはステータス・ID・サイズ・行範囲・ファイルパスのみ。
  `def login():` や `class Auth:` のようなheaderがないため、何の変更かがファイルパスだけで判断するしかない。

- **[UI-BAD] 54〜66pxの固定行高**
  Python版DataTableの低い行高に比べて縦スペースの消費が大きく、同時に見えるチャンク数が少ない。

- **[UI-BAD] フィルタUIが2行で複雑**
  ドロップダウン（状態フィルタ）・ソートComboBox・テキスト欄（Pathフィルタ）・テキスト欄（検索）・チェックボックス・クリアボタンが2行に並ぶ。
  Python版は1行の単一テキスト入力で「ファイル名/チャンク名/ヘッダ/ステータス」を統合フィルタリング。

### 2-4. Groupsパネルのレイアウト

- **[UI-BAD] 数字が見えない**
  「グループ名 + プログレスバー + タグ」のみ。Python版のtotal/pending/reviewed/ignored/brief status列表示に対し、残件数が数字で一切分からない。

- **[UI-BAD] プログレスバーだけでは状態が分かりにくい**
  "X/Y reviewed" のバーでは、pending（未レビュー＋再レビュー必要）の件数が分からない。残タスクの重さが判断できない。

### 2-5. 差分表示エリア

- **[UI-BAD] シンタックスハイライトなし**
  コード差分の読みやすさが根本的に低い。`+`/`-` の緑/赤だけでは言語構文が見えない。

- **[UI-BAD] サイドバイサイドの幅調整不可**
  old側とnew側の列幅が固定。コードの量が偏っているファイルで読みにくい。

- **[UI-BAD] Diff内検索UIが混雑**
  検索欄(180px) + 前の変更/次の変更 + 前の検索/次の検索 + diffコピー + 選択コピー が1行に並び、どのボタンが何をするか分かりにくい。

### 2-6. GroupBrief（Handoff）タブ

- **[UI-BAD] 全フィールドを1テキストエリアで管理**
  summary/focusPoints/testEvidence/knownTradeoffs/questionsForReviewer が1つの巨大なテキストエリアに混在。
  構造がなく、フィールドの意味・順番がドキュメントを読まないと分からない。

- **[UI-BAD] HandoffとApprovalが完全分離**
  「HandoffブリーフのどこがOKか」を見ながら承認/差し戻しできない。
  Handoffタブ→内容確認→Approvalタブ→操作 という往復が必要。

### 2-7. Approvalタブ

- **[UI-BAD] Reviewer入力欄がApprovalタブ内**
  毎回Reviewer名を入力する必要がある。アプリ設定またはログインで固定すべき。

---

## 3. 操作性・体験の問題（UX-BAD）

### 3-1. キーボードショートカット

- **[UX-BAD] Python版45+キーに対しRust版は約12キー**
  Python版でキーボードで完結できた操作の大半がRust版ではマウス操作に退行している。
  主要な欠落：`g`（Groupsへ）/ `c`（Chunksへ）/ `l`（Linesへ）/ `z`（フォーカスモード）/ `b`（Brief編集）/ `p`（Brief表示）/ `n`（新規グループ）/ `e`（グループ名変更）/ `a`（割当）/ `u`（解除）/ `=/-`（ズーム）/ `[/]`（ペイン拡縮）/ `Shift+T`（テーマ切替）

- **[UX-BAD] `/` でフィルタへのフォーカスがない**
  Python版は `/` で即座にフィルタ欄へ。Rust版は `Ctrl+F` だが操作感が重い。

### 3-2. チャンクナビゲーション

- **[UX-BAD] 一括操作の粒度が粗い**
  Rust版の一括操作（レビュー済み/再レビュー/無視）は常に「フィルタ中の全チャンク」に適用される。
  Python版は選択したチャンクだけに適用できる。誤操作リスクが高い。

- **[UX-BAD] グループをまたいだ `N` ジャンプ**
  `N`（次の未完了）がグループ絞り込み中でも全体の未完了に飛ぶことがある。

### 3-3. ワークフローの断絶

- **[UX-BAD] レビュー→Handoff作成のフローが不自然**
  チャンクをDiffタブでレビューしながらHandoffブリーフを書こうとすると、Diffタブ↔Handoffタブを何度も行き来する必要がある。
  Python版は `b` キーで直接モーダル呼び出し、どこにいても編集できる。

- **[UX-BAD] レビューコメントと差分が同時に見えない**
  Diff（Diffタブ）とコメント（ReviewタブのTextEdit）が別タブに分かれており、差分を見ながらコメントを書けない。
  Python版は右ペイン上部のMeta欄にチャンク情報+コメントが表示され、下部のLines差分と同時閲覧可能。

- **[UX-BAD] 行コメント編集エリアが見えにくい**
  Diffタブ最下部に行コメントエディタがあるが、スクロールしないと見えず、コメントを書いているのか分かりにくい。

### 3-4. 視覚的フィードバック

- **[UX-BAD] 保存状態インジケータが小さい**
  トップバーの黄/緑LEDが小さく見落としやすい。未保存状態の気づきが遅れる。

- **[UX-BAD] ステータス変更のフィードバックが乏しい**
  チャンクのステータスを変更してもチャンク行の色が変わる程度で、変更が反映されたことへの確信が薄い。

- **[UX-BAD] エラーはステータスバーの1行のみ**
  操作失敗時にステータスバー最下部に1行表示されるだけ。重要なエラーが見落とされやすい。

### 3-5. 初期起動・ファイル読み込み

- **[UX-BAD] 起動直後に何をすればいいか分からない**
  Python版はTextualのFooterにキーバインドが常時表示される。Rust版は「F1でヘルプ」のみで、新規ユーザーが最初に何をすれば良いか分からない。

- **[UX-BAD] 最近使ったファイル一覧が目立たない**
  「開く」ボタン押下後のファイルダイアログに埋もれている。直接リストとして表示すべき。

### 3-6. 設定

- **[UX-BAD] 設定の全体像が見えない**
  チェックボックスがトップバーに分散しているため、「今どの設定がオンで何がオフか」を一覧確認できない。

- **[UX-BAD] テーマ切り替えのコストが高い**
  Python版の `Shift+T` でのトグルに比べ、Rust版のComboBox操作は手数が多い。

---

## 優先度マトリクス

| 優先度 | 問題 | ユーザー影響 | 実装コスト |
|--------|------|------------|----------|
| 🔴 最高 | シンタックスハイライト | 差分の読みやすさが根本的に違う | 中（syntect等） |
| 🔴 最高 | GroupBriefのフォーム化 | Handoff品質が劣化 | 中 |
| 🔴 最高 | Groups列の拡充（pending数値/brief status） | グループ状態の即視認不可 | 低 |
| 🔴 最高 | ペイン幅調整（ドラッグ/`[`/`]`キー） | 画面に合わせられない | 中 |
| 🟠 高 | チャンクリストへのheader列追加 | どの関数の変更か分からない | 低 |
| 🟠 高 | 複数チャンク選択 | 一括操作が粗い | 中 |
| 🟠 高 | キーバインド拡充（g/c/z/b/p/n/e/a等） | キーボード操作効率の大幅低下 | 低 |
| 🟠 高 | トップバーの整理（チェックボックス→設定モーダル） | 認知負荷が高い | 中 |
| 🟠 高 | タブ数削減（12→6以下） | 迷子になる | 中 |
| 🟡 中 | 行番号指定でエディタを開く | コードジャンプが不便 | 低 |
| 🟡 中 | グループレポートモード | グループ全体俯瞰が不可 | 中 |
| 🟡 中 | 設定モーダル（`t`キー） | 設定UIが散在 | 低 |
| 🟡 中 | フィルタの統合化（1入力欄） | フィルタUIが複雑 | 低 |
| 🟡 中 | HandoffとApprovalの統合（モーダル化） | ワークフローの断絶 | 中 |
| 🟡 中 | Old/New幅比率調整 | サイドバイサイドが不便 | 低 |
| 🟢 低 | Zoom +/- | 補助機能 | 低 |
| 🟢 低 | Impact apply selection tokens | 高度な運用機能 | 高 |
| 🟢 低 | acknowledgedBy履歴表示 | 補助情報 | 低 |

---

## 実装タスク一覧（優先順）

関連ファイル：
- `diffgr_rust_gui/src/app.rs`（メインUI、全描画ロジック 6200行）
- `diffgr_rust_gui/src/model.rs`（データモデル）
- `diffgr_rust_gui/src/ops.rs`（ビジネスロジック）

---

## 🔴 最高優先度

### Task 1: 右ペインのレイアウト再設計

**現状：** Diffタブ・Reviewタブが別タブに分離。差分を見ながらコメントを書けない。

**目標：** チャンク選択時、右ペインを上下分割する。
- 上部（固定高 約100px）: チャンクステータス選択 + コメント入力欄（`draw_chunk_status_editor` + `draw_chunk_comment_editor`）
- 下部（残り全体）: Diffツールバー + Diff表示 + 行コメント入力（`draw_diff_toolbar` + `draw_diff_lines` + `draw_line_comment_editor`）

**実装箇所：** `draw_detail()` (app.rs:2838) の `DetailTab::Diff` / `DetailTab::Review` ブランチを統合。
`ui.split_vertical()` または `ui.vertical()` で上下に分ける。
`DetailTab::Diff` と `DetailTab::Review` は削除またはマージ。タブは残りの機能（Handoff/Coverage/Approval/VirtualPr/Tools/概要）のみに。

---

### Task 2: Groupsパネルに数値列を追加

**現状：** グループ名＋プログレスバーのみ。残件数が数字で見えない。

**目標：** グループ行に `pending`（未+再レビュー件数）と `brief status`（draft/ready/acknowledged/stale）を数値・バッジで表示。

**実装箇所：** `draw_groups()` (app.rs:2727) のグループ行描画部分。
`GroupMetrics` 構造体（model.rs）に `pending` フィールドが既にあるか確認し、なければ `needs_re_review + unreviewed` で計算。
グループ行に `ui.label(format!("未:{}", pending))` を追加。
`GroupBriefDraft.status` をバッジ表示（"ready" → 緑, "draft" → 黄 など）。

---

### Task 3: ペイン幅をドラッグで変更できるようにする

**現状：** Groups列 260px・Chunks列 380px 固定（定数 `GROUPS_COLUMN_WIDTH` / `CHUNKS_COLUMN_WIDTH`）。

**目標：** 列間にドラッグ可能なセパレータを追加し、幅をユーザーが変更できるようにする。変更後の幅は `AppConfig` に保存して再起動後も維持。

**実装箇所：** `draw_main()` の3カラムレイアウト部分。
`AppConfig`（app.rs の設定構造体）に `groups_col_width: f32` / `chunks_col_width: f32` を追加。
列間に `ui.separator()` ではなく egui の `resize` パネルを使う。
または、`[` / `]` キーで `groups_col_width` を±20pxする簡易実装でも可。

---

### Task 4: GroupBriefを構造化フォームで編集

**現状：** summary/focusPoints/testEvidence等が1テキストエリアに混在。構造が失われ記入しにくい。

**目標：** フィールドごとに分けたフォームで編集できるようにする。

| フィールド | UI部品 |
|-----------|--------|
| status | ComboBox（draft/ready/acknowledged/stale）|
| summary | TextEdit（3行）|
| focusPoints | TextEdit（複数行、1行1項目）|
| testEvidence | TextEdit（複数行、1行1項目）|
| knownTradeoffs | TextEdit（複数行、1行1項目）|
| questionsForReviewer | TextEdit（複数行、1行1項目）|
| mentions | TextEdit（1行、スペース区切り）|

**実装箇所：** `draw_group_brief_editor()` を全面改修。
`GroupBriefDraft` 構造体（model.rs）のフィールドを確認し、不足があれば追加。

---

### Task 5: シンタックスハイライト（差分表示）

**現状：** 差分は緑/赤の単色のみ。言語構文が見えない。

**目標：** ファイル拡張子からシンタックスハイライトを適用する。

**依存ライブラリ：** `syntect`（Rustのシンタックスハイライトクレート）を `Cargo.toml` に追加。
または軽量な `tree-sitter` ベースのハイライト。

**実装箇所：** `draw_diff_lines()` の行描画部分。
`Chunk.file_path` の拡張子を見て言語を特定し、`syntect` でトークン化してegui の `RichText` にカラーを付ける。
ハイライト結果はチャンク単位でキャッシュする（diffキャッシュに統合）。

---

## 🟠 高優先度

### Task 6: チャンクリストに `header` 列を追加

**現状：** チャンク行にステータス・ID・サイズ・ファイルパスのみ。関数名等が見えない。

**目標：** チャンク行に `Chunk.header`（hunk header: `class Auth:` / `def login():` 等）を小テキストで表示。

**実装箇所：** `draw_chunks()` (app.rs:2767) のチャンク行描画部分。
`Chunk` 構造体（model.rs）に `header: Option<String>` フィールドがあるか確認。
`ui.small(header)` をファイルパスの下に追加。

---

### Task 7: キーバインド拡充

**現状：** 約12ショートカット。Python版の45+に対して大幅に少ない。

**目標：** 以下を追加する。

| キー | 動作 |
|------|------|
| `/` | フィルタ入力欄にフォーカス |
| `z` | 変更行のみ表示をトグル（context_mode切り替え） |
| `b` | 選択グループのHandoffタブを開く |
| `p` | Handoff内容をモーダルで表示（読み取り専用） |
| `n`（Chunks未選択時） | 新規グループ作成 |
| `e` | 選択グループ名変更 |
| `[` | Groups列幅を-20px |
| `]` | Groups列幅を+20px |
| `Shift+T` | テーマをトグル（OS→ダーク→ライト→OS） |
| `t` | 設定モーダルを開く |

**実装箇所：** `update()` 内のキー処理部分（`ctx.input(|i| ...)` のブロック）。

---

### Task 8: トップバーの整理（チェックボックスを設定モーダルへ移動）

**現状：** トップバー3行目に9個のチェックボックスが横並び。

**目標：** トップバー3行目を廃止し、設定ボタン（⚙）1つに集約。クリックで設定モーダルを開く。
モーダル内容：
- editorMode: ComboBox（auto/vscode/cursor/default-app/custom）
- customEditorCommand: TextEdit
- diffSyntax: Checkbox（シンタックスハイライトON/OFF）※Task 5実装後
- uiDensity: ComboBox（compact/normal）
- autoWrap: Checkbox
- state自動保存: Checkbox
- レビュー済みで次へ: Checkbox
- 読込/保存を別スレッド: Checkbox（上級者向け）

**実装箇所：** `draw_top_bar()` の3行目を削除し、`draw_settings_modal()` を新規実装。
`AppConfig` に `editor_mode`, `custom_editor_cmd` を追加。

---

### Task 9: タブを6個以下に削減

**現状：** 12タブ（Diff/Review/Handoff/Layout/Coverage/Impact/Approval/VirtualPr/Tools/診断/概要/State）。

**目標：** Task 1でDiff+Reviewを統合後、残りのタブを整理する。

推奨構成（6タブ）：
1. **レビュー**（旧Diff+Review統合）
2. **Handoff**（グループブリーフ）
3. **承認**（旧Approval）
4. **分析**（旧Coverage+Impact+VirtualPrを1タブ内でセクション分け）
5. **概要**（旧Summary）
6. **Tools**（旧Tools+Diagnostics+State）

**実装箇所：** `draw_detail()` (app.rs:2838) のタブ列挙と `DetailTab` enum (app.rs:202)。

---

## 🟡 中優先度

### Task 10: 行番号指定でエディタを開く

**現状：** 「実ファイルを開く」でファイルを開くが行番号指定なし。

**目標：** 選択チャンクの新側開始行（`chunk.new.start`）を指定してエディタを起動。
- VS Code: `code --goto {path}:{line}`
- Cursor: `cursor --goto {path}:{line}`
- デフォルト: そのまま（行番号指定不可）

**実装箇所：** `draw_chunk_status_editor()` の「実ファイルを開く」ボタン処理（`ops::open_file`関連）。
`AppConfig.editor_mode`（Task 8で追加）を参照してコマンドを切り替える。

---

### Task 11: フィルタ入力欄を1行に統合

**現状：** Pathフィルタ・全文検索・ステータスドロップダウン・ソートComboBoxが2行。

**目標：** 1つのテキスト入力で `ファイルパス/ステータス/ID/内容` を統合フィルタリング。
プレースホルダ: `"ファイル名 / ステータス / チャンクID / 本文で絞り込み..."`

`status:reviewed` `file:auth` のようなプレフィックス構文でも可。ステータスドロップダウンは別途残してもよい。

**実装箇所：** `draw_filters()` の入力欄統合。`apply_filter_inputs_now()` の統合フィルタロジック追加。

---

### Task 12: グループレポートモード

**現状：** 1チャンクずつしか差分を見られない。

**目標：** グループを選択した状態でグループ全体の差分を縦に連結して1画面で表示するモード。
`d` キーまたはトグルボタンで切り替え。

**実装箇所：** `draw_detail()` に新しいモード分岐を追加。
選択グループの全チャンクを `visible_cache` から取得し、差分行を連結してスクロール表示する。
チャンク境界に区切り線（ファイルパス＋行番号）を挿入。
