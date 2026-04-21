# DiffGR Review GUI

DiffGR JSON をレビューするための Rust / egui ネイティブ GUI です。Windows では PowerShell / cmd から、Git Bash / WSL / Linux / macOS では shell から、そのまま `cargo build` / `cargo test` を呼べるラッパーを同梱しています。

## 重要: ビルドの本体は Rust/Cargo

`.ps1`、`.cmd`、`.sh` は「便利な入口」です。実際に行っていることは次の Cargo コマンドです。

```powershell
cargo test --all-targets
cargo build --release
cargo run -- .\examples\minimal.diffgr.json
```

Windows ではパス解決、exe の有無チェック、低負荷起動、実行ポリシー回避、配布 zip 作成を楽にするために `windows/*.ps1` と `*.cmd` を用意しています。

## Windows ですぐ使う

PowerShell でプロジェクト直下に移動して実行します。

```powershell
.\windows\check-windows-env.ps1
.\windows\run-windows.ps1 -Diffgr .\examples\minimal.diffgr.json
```

ルート直下の短い入口も使えます。

```powershell
.\run.ps1 -Diffgr .\examples\minimal.diffgr.json
.\build.ps1 -Test
.\test.ps1 -Check
```

PowerShell の実行ポリシーで止まる場合は、次の形式で実行してください。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\run-windows.ps1 -Diffgr .\examples\minimal.diffgr.json
```

エクスプローラーからは、`Run DiffGR Review.cmd`、`Build Release.cmd`、`Test.cmd`、`Check Test Build.cmd` をダブルクリックできます。

## UT / 開発確認

追加済みの UT は、モデル層、state 正規化、レビュー状態、line comment、groupBrief、ファイル保存、CLI 引数解析、検索補助、近傍 state 検出、公開 API の integration workflow をカバーします。

```powershell
# Windows / PowerShell
.\test.ps1
.\test.ps1 -Check
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
.\windows\ci-windows.ps1
```

```bash
# Git Bash / WSL / Linux / macOS
./test.sh
./test.sh --check
./build.sh --test
./build.sh --release
```

Cargo を直接使う場合:

```bash
cargo test --all-targets
cargo check --all-targets
cargo build --release
```

詳細は `TESTING.md` を見てください。

## Windows スクリプト

| ファイル | 用途 |
|---|---|
| `build.ps1` | ルート直下の build wrapper。中で `windows/build-windows.ps1` を呼びます |
| `test.ps1` | ルート直下の test wrapper。中で `windows/test-windows.ps1` を呼びます |
| `run.ps1` | ルート直下の run wrapper。中で `windows/run-windows.ps1` を呼びます |
| `windows/check-windows-env.ps1` | Rust / Cargo / MSVC 周辺の確認 |
| `windows/setup-rust-windows.ps1` | Rust インストール補助。`-UseWinget` で winget 利用 |
| `windows/run-windows.ps1` | GUI 起動。exe がなければ必要に応じてビルド |
| `windows/build-windows.ps1` | release/debug ビルド。`-Test` / `-Check` も可能 |
| `windows/test-windows.ps1` | `cargo test --all-targets` 実行。`-Check` / `-Fmt` も可能 |
| `windows/ci-windows.ps1` | env check → fmt/check/test → release build |
| `windows/package-windows.ps1` | `dist/diffgr_gui_windows.zip` を作成 |
| `windows/new-shortcut-windows.ps1` | デスクトップショートカット作成 |
| `windows/open-sample-windows.ps1` | サンプルJSONを開く |
| `windows/clear-cache-windows.ps1` | UI設定/キャッシュ候補を削除 |
| `Run DiffGR Review.cmd` | `run-windows.ps1` のダブルクリック用ラッパー |
| `Build Release.cmd` | `build-windows.ps1` のダブルクリック用ラッパー |
| `Test.cmd` | `test-windows.ps1` のダブルクリック用ラッパー |
| `Check Test Build.cmd` | `ci-windows.ps1` のダブルクリック用ラッパー |
| `Run Low Memory.cmd` | 低負荷モードで起動 |
| `Clear Cache.cmd` | UI設定/キャッシュ候補を削除 |

## shell スクリプト

| ファイル | 用途 |
|---|---|
| `build.sh` / `scripts/build.sh` | `cargo build` wrapper。`--debug`、`--test`、`--check`、`--run` 対応 |
| `test.sh` / `scripts/test.sh` | `cargo test --all-targets` wrapper。`--check`、`--fmt` 対応 |
| `run.sh` / `scripts/run.sh` | GUI起動 wrapper。`--release`、`--build`、`--low-memory` 対応 |

## 起動例

```powershell
# GUIだけ開く
.\windows\run-windows.ps1

# DiffGR JSONを指定
.\windows\run-windows.ps1 -Diffgr C:\work\review\input.diffgr.json

# 外部stateを指定
.\windows\run-windows.ps1 -Diffgr C:\work\review\input.diffgr.json -State C:\work\review\review.state.json

# releaseビルドして起動
.\windows\run-windows.ps1 -Release -Build -Diffgr .\examples\minimal.diffgr.json

# test → release build
.\windows\build-windows.ps1 -Test

# 配布zipを作成
.\windows\package-windows.ps1
```

## GUI の使い方

1. `開く` またはドラッグ&ドロップで DiffGR JSON を開きます。
2. `State保存先…` または `新規State` で `review.state.json` を作ると、元の DiffGR JSON を汚さずレビュー状態だけ保存できます。
3. 左の `Groups` で対象グループを絞り込み、中央の `Chunks` でレビュー対象を選びます。
4. 右の `Diff` タブで差分を見ます。行をクリックすると、`Review` タブで line comment を編集できます。
5. `Handoff` タブで groupBriefs / review handoff を編集できます。
6. `State` タブで保存予定の state JSON を確認・コピーできます。

## 改善した操作性

- 最近使った DiffGR の一覧
- ファイルドラッグ&ドロップ
- DiffGR と state の個別読み込み
- `review.state.json` の自動検出
- state 自動保存
- 未保存終了時の確認
- ウィンドウサイズ・UI設定の永続化
- グループ別進捗バー
- チャンクの状態・パス・本文・コメント検索
- コメント付きだけ表示
- チャンクの並び替え: 自然順 / ファイルパス / 状態 / 変更量
- 行番号表示、変更行のみ表示、折り返し切替
- 実ファイルを開く / 場所を表示
- 日本語フォントの自動フォールバック
- ダーク / ライト / システム風テーマ切替
- 表示中の行だけ描画する仮想スクロール
- ちらつき抑制 / コンパクト行 / UI状態記憶OFF
- 低負荷起動とキャッシュ削除スクリプト

## 軽量化・ちらつき対策

この版では「大きいキャッシュを増やして速くする」のではなく、描画と保存の無駄を減らす方針にしています。

- `Chunks` と `Diff` は `ScrollArea::show_rows` で表示中の行だけ描画します。
- Diff 行は全行 clone せず、チャンク内の行データを `Arc` で共有します。
- 変更量 `+/-` は読み込み時に計算し、毎フレーム全行を数え直しません。
- State JSON プレビューは 1件だけの揮発キャッシュです。編集が入ると破棄され、ファイルには保存されません。
- egui の細かな UI メモリ永続化は標準で OFF にしました。保存するのは設定と最近使ったファイル程度です。
- 選択移動やフィルタ操作だけでは未保存扱いにしません。レビュー状態・コメント・Handoff の編集だけを保存対象として扱います。
- `ちらつき抑制` ON ではアニメーション時間を 0 にし、スクロールの自動アニメーションも抑えます。
- ウィンドウタイトルは内容が変わった時だけ更新します。

重い環境では次で起動してください。

```powershell
.\windows\run-windows.ps1 -Release -LowMemory -Diffgr .\examples\minimal.diffgr.json
```

設定や古いUIメモリを消したい場合:

```powershell
.\windows\clear-cache-windows.ps1 -Force
# または
.\windows\run-windows.ps1 -ClearCache
```

## ショートカット

| キー | 操作 |
|---|---|
| `Ctrl+O` | DiffGRを開く |
| `Ctrl+S` | 保存 |
| `Ctrl+Shift+S` | state保存先を選ぶ |
| `Ctrl+F` | 検索欄へ |
| `Space` | 選択チャンクをレビュー済みへ切替 |
| `J` / `↓` | 次のチャンク |
| `K` / `↑` | 前のチャンク |
| `N` | 次の未完了チャンク |
| `R` | レビュー済み |
| `I` | 無視 |
| `F1` | ヘルプ |

## Windows の Rust 環境

Rust / Cargo が未インストールの場合は、次を実行してください。

```powershell
.\windows\setup-rust-windows.ps1 -UseWinget
```

`cargo build` で linker / MSVC 系のエラーが出る場合は、Visual Studio Build Tools の `Desktop development with C++` ワークロードを入れてください。

```powershell
.\windows\setup-rust-windows.ps1 -InstallBuildTools
```

## Linux / macOS / WSL

```bash
./run.sh examples/minimal.diffgr.json
./test.sh --check
./build.sh --release
```

Cargo を直接使う場合:

```bash
cargo run -- examples/minimal.diffgr.json
cargo run -- path/to/input.diffgr.json --state path/to/review.state.json
cargo build --release
```

Linux では環境によって X11 / Wayland / OpenGL / Vulkan 系の開発パッケージが必要になる場合があります。

## 保存形式

`--state` または GUI の `State保存先…` を使っている場合は、その state JSON に保存します。state 保存先がない場合は元の DiffGR JSON を更新し、バックアップとして `.bak` を作成します。

## 開発メモ

このプロジェクト本体は Rust edition 2021 です。GUI は `eframe = 0.34.1` / `egui = 0.34.1` 系の API に合わせています。`eframe 0.34.1` に合わせて `rust-version = 1.92` を指定しています。
