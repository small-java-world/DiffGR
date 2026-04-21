# DiffGR Review GUI

DiffGR JSON をレビューするための Rust / egui ネイティブ GUI です。Windows では PowerShell / cmd から、Git Bash / WSL / Linux / macOS では shell から、そのまま `cargo build` / `cargo test` を呼べるラッパーを同梱しています。

## 重要: ビルドの本体は Rust/Cargo

`.ps1`、`.cmd`、`.sh` は「便利な入口」です。実際に行っていることは次の Cargo コマンドです。

```powershell
cargo test --all-targets
cargo build --release
cargo run -- .\examples\minimal.diffgr.json
cargo run -- .\examples\minimal.diffgr.json --low-memory
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

UT は 1,192 tests まで増やし、モデル層だけでなく、DiffGR生成、chunk分割、slice/layout patch、state diff/merge/selection token、HTML/report、bundle検証、split/merge group reviews、approval、impact/rebase、Python parity manifest、Windows/shell wrapper までカバーしています。

Cargo 実行前の静的UT matrix確認も追加しています。
### UT depth gate

今回の版では UT depth gate も追加しています。`tools/verify_ut_depth.py` は拡充した4本の追加UT、UT matrix、GUI/仮想PR/CLI wrapper の重要マーカーをまとめて確認します。静的ゲートの下限は **1,180 Rust tests** です。

```powershell
.\windows\ut-depth-windows.ps1 -Json
```

```bash
./ut-depth.sh --json
```


```powershell
.\windows\ut-matrix-windows.ps1 -Json
```

```bash
./ut-matrix.sh --json
```

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

詳細は `TESTING.md` を見てください。変更点は `CHANGELOG.md` にまとめています。


## 既存Pythonアプリ相当の機能網羅

この版では GUI だけでなく、Rust CLI `diffgrctl` を追加し、Python の `scripts/*.py` で提供していた主要運用を Rust/Cargo から実行できるようにしました。

| 領域 | Rust側の入口 |
|---|---|
| Git diff から DiffGR 生成 | `diffgrctl generate` / GUI `Tools` |
| autoslice / refine / AI prompt | `diffgrctl autoslice` / `refine` / `prepare` / `run-agent` |
| slice patch / layout patch | `diffgrctl apply-slice-patch` / `apply-layout` / GUI `Layout` / `Tools` |
| state extract / apply / diff / merge / token apply | `diffgrctl extract-state` / `apply-state` / `diff-state` / `merge-state` / `state-apply` / `apply-state-diff` |
| split / merge group reviews | `diffgrctl split-group-reviews` / `merge-group-reviews` / GUI `Tools` |
| impact / preview rebased merge / rebase state/reviews | `diffgrctl impact-report` / `preview-rebased-merge` / `rebase-state` / `rebase-reviews` |
| HTML export / local HTML server | `diffgrctl export-html` / `serve-html` / GUI `HTML保存` |
| review bundle export / verify | `diffgrctl export-bundle` / `verify-bundle` / GUI `Bundle出力` |
| approval / request changes / verify | `diffgrctl approve` / `request-changes` / `check-approval` / GUI `Approval` |
| coverage / reviewability / summary | `diffgrctl coverage` / `reviewability` / `summarize` / GUI `Coverage` / `概要` |
| Python Textual viewer相当 | `diffgr_gui` のレビュー画面 / `diffgrctl view` |

基本例:

```powershell
.\diffgrctl.ps1 prepare --repo . --base main --feature HEAD --output out\work\review.diffgr.json
.\run.ps1 -Diffgr .\out\work\review.diffgr.json
.\diffgrctl.ps1 export-bundle --input .\out\work\review.diffgr.json --output-dir .\out\bundle
.\diffgrctl.ps1 verify-bundle --bundle .\out\bundle\bundle.diffgr.json --state .\out\bundle\review.state.json --manifest .\out\bundle\review.manifest.json
```

Cargo直打ちでも同じです。

```bash
cargo run --bin diffgrctl -- prepare --repo . --base main --feature HEAD --output out/work/review.diffgr.json
cargo run --bin diffgrctl -- apply-state-diff --base old.state.json --incoming new.state.json --tokens reviews:c1 --output selected.state.json
cargo run --bin diffgrctl -- view --input out/work/review.diffgr.json
cargo run --bin diffgrctl -- verify-bundle --bundle out/bundle/bundle.diffgr.json --state out/bundle/review.state.json --manifest out/bundle/review.manifest.json
```

対応表と注意点は `PYTHON_PARITY.md` を見てください。見た目やHTMLの細部はRust版に寄せていますが、既存Pythonアプリで必要だった運用機能はGUIまたはCLIで網羅しています。

互換性の確認は次でできます。

```powershell
.\diffgrctl.ps1 parity-audit
.\windows\parity-smoke-windows.ps1
```

旧Python script名に近い入口も `scripts/*.ps1` / `scripts/*.sh` に追加しています。例: `scripts\generate_diffgr.ps1`、`scripts\view_diffgr_app.ps1`、`scripts/export_review_bundle.sh`。

AI refine / `run-agent` 用に `agent_cli.toml` と `schemas/slice_patch.schema.json` も同梱しています。

例:

```powershell
.\diffgrctl.ps1 run-agent --prompt refine-prompt.md --schema schemas\slice_patch.schema.json --output slice_patch.json --timeout 180
```

## Windows スクリプト

| ファイル | 用途 |
|---|---|
| `build.ps1` | ルート直下の build wrapper。中で `windows/build-windows.ps1` を呼びます |
| `test.ps1` | ルート直下の test wrapper。中で `windows/test-windows.ps1` を呼びます |
| `run.ps1` | ルート直下の run wrapper。中で `windows/run-windows.ps1` を呼びます |
| `windows/check-windows-env.ps1` | Rust / Cargo / MSVC 周辺の確認 |
| `windows/doctor-windows.ps1` | 環境・exe・パス長・必要ファイルの診断。`-Deep` で fmt/check/test/build |
| `windows/setup-rust-windows.ps1` | Rust インストール補助。`-UseWinget` で winget 利用 |
| `windows/run-windows.ps1` | GUI 起動。exe がなければ必要に応じてビルド |
| `windows/build-windows.ps1` | release/debug ビルド。`-Test` / `-Check` も可能 |
| `windows/test-windows.ps1` | `cargo test --all-targets` 実行。`-Check` / `-Fmt` も可能 |
| `windows/ci-windows.ps1` | env check → fmt/check/test → release build |
| `windows/package-windows.ps1` | `dist/diffgr_gui_windows.zip` を作成 |
| `windows/new-shortcut-windows.ps1` | デスクトップショートカット作成 |
| `windows/open-sample-windows.ps1` | サンプルJSONを開く |
| `windows/clear-cache-windows.ps1` | UI設定/キャッシュ候補を削除 |
| `windows/diffgrctl-windows.ps1` | `diffgrctl.exe` 起動/ビルド wrapper。Python scripts相当のCLI入口 |
| `windows/parity-smoke-windows.ps1` | サンプルでPython parity CLI経路をsmoke確認 |
| `windows/parity-audit-windows.ps1` | Python scripts対応表をCLIで確認 |
| `Run DiffGR Review.cmd` | `run-windows.ps1` のダブルクリック用ラッパー |
| `Build Release.cmd` | `build-windows.ps1` のダブルクリック用ラッパー |
| `Test.cmd` | `test-windows.ps1` のダブルクリック用ラッパー |
| `Check Test Build.cmd` | `ci-windows.ps1` のダブルクリック用ラッパー |
| `Doctor.cmd` | `doctor-windows.ps1` のダブルクリック用ラッパー |
| `Package Windows.cmd` | 配布zip作成のダブルクリック用ラッパー |
| `Run Low Memory.cmd` | 低負荷モードで起動 |
| `Clear Cache.cmd` | UI設定/キャッシュ候補を削除 |
| `DiffGR Tools.cmd` | `diffgrctl.ps1` のcmdラッパー |
| `Python Parity Smoke.cmd` | parity smokeのcmdラッパー |
| `Python Parity Audit.cmd` | parity auditのcmdラッパー |
| `Python Compat Verify.cmd` | strict Python source/wrapper parity verifyのcmdラッパー |

## shell スクリプト

| ファイル | 用途 |
|---|---|
| `build.sh` / `scripts/build.sh` | `cargo build` wrapper。`--debug`、`--test`、`--check`、`--run` 対応 |
| `test.sh` / `scripts/test.sh` | `cargo test --all-targets` wrapper。`--check`、`--fmt` 対応 |
| `run.sh` / `scripts/run.sh` | GUI起動 wrapper。`--release`、`--build`、`--low-memory` 対応 |
| `diffgrctl.sh` / `scripts/diffgrctl.sh` | `cargo run --bin diffgrctl -- ...` wrapper |
| `scripts/<python_script_name>.sh` | 旧Python script名に対応するshell互換wrapper |
| `scripts/<python_script_name>.ps1` | 旧Python script名に対応するPowerShell互換wrapper |

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
6. `概要` タブでファイル別進捗を確認し、レビューサマリを Markdown でコピー/保存できます。
7. `State` タブで保存予定の state JSON を確認・コピーできます。

## 改善した操作性

- 最近使った DiffGR の一覧
- ファイルドラッグ&ドロップ
- DiffGR と state の個別読み込み
- `review.state.json` の自動検出
- state 自動保存
- 未保存終了時の確認
- ウィンドウサイズ・UI設定の永続化
- グループ別進捗バー
- 概要タブ: ステータス別件数、ファイル別進捗、Markdownレビューサマリ出力
- 表示中チャンクの一括ステータス変更と Ctrl+Z によるステータスUndo
- チャンクの状態・パス・本文・コメント検索
- コメント付きだけ表示
- チャンクの並び替え: 自然順 / ファイルパス / 状態 / 変更量
- 行番号表示、変更行のみ表示、折り返し切替
- 実ファイルを開く / 場所を表示
- 日本語フォントの自動フォールバック
- ダーク / ライト / システム風テーマ切替
- 表示中の行だけ描画する仮想スクロール
- ちらつき抑制 / コンパクト行 / UI状態記憶OFF
- `--low-memory` CLIオプション、低負荷起動とキャッシュ削除スクリプト
- JSON/Markdown保存は一時ファイル経由で行い、途中失敗で本体が壊れにくい書き込みに変更
- `doctor-windows.ps1` で環境・ビルド状態をまとめて診断

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
| `Ctrl+Z` | 直近のステータス変更を戻す |
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
./run.sh examples/multi_file.diffgr.json
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

## Complete Python parity / compatibility mode

All 31 historical Python `scripts/*.py` entry points are represented by Rust
`diffgrctl` aliases and by Windows/shell wrappers under `scripts/`.  For strict
old-Python behavior parity, the original Python implementation is vendored under
`compat/python` and can be invoked per command:

```powershell
.\scripts\summarize_diffgr.ps1 -CompatPython --input .\examples\multi_file.diffgr.json --json
```

```bash
./scripts/summarize_diffgr.sh --compat-python --input ./examples/multi_file.diffgr.json --json
```

See `PYTHON_COMPATIBILITY.md`, `COMPLETE_PARITY_AUDIT.md`, and
`PYTHON_PARITY_MANIFEST.json`.

## Strict Python parity verification

For strict compatibility, the original Python DiffGR app source is bundled under
`compat/python`.  `COMPLETE_PYTHON_SOURCE_AUDIT.json` verifies that every
non-cache file from the uploaded Python app is present byte-for-byte.  The only
excluded files are `__pycache__/*.pyc`, because they are rebuildable interpreter
caches.

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
```

```bash
./compat-python-verify.sh --json
```

This validates 163 Python source/support files, 31 historical script wrappers,
Python compilation, and a small compatibility smoke run.  Use `-Pytest` or
`--pytest` to run the vendored original Python tests when the Python test
dependencies are installed.

## Native Python parity verification

既存 Python アプリ相当の機能網羅を確認する入口を追加しています。

```powershell
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\python-compat-verify-windows.ps1 -Json
```

shell では:

```bash
./native-parity-verify.sh --json --check-compat
./compat-python-verify.sh --json
```

詳細は `NATIVE_PYTHON_PARITY.md` と `NATIVE_PYTHON_PARITY_AUDIT.json` を見てください。

## Python app parity gates

The package includes three separate gates for the claim that the existing Python app functionality is covered:

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\native-functional-parity-windows.ps1 -Json
```

- Python strict compatibility verifies the bundled original Python source.
- Native command parity verifies 31 script entries, CLI aliases, wrappers, and discovered options.
- Native functional parity runs all 31 script-equivalent operations against temporary fixtures through both Python compat and native Rust.

See `NATIVE_FUNCTIONAL_PARITY.md` for details.

## Smooth scrolling and no-freeze behavior

The GUI now avoids common stalls by loading large DiffGR JSON in a worker thread, auto-saving state in a worker thread, applying search filters after a short debounce, creating chunk rows only for the visible virtual-scroll range, virtualizing large State JSON text, and clipping extremely long diff lines for display.

Windows smooth launch:

```powershell
.\windows\run-windows.ps1 -Release -Smooth -Diffgr .\examples\multi_file.diffgr.json
```

Cargo launch:

```powershell
cargo run --bin diffgr_gui -- .\examples\multi_file.diffgr.json --smooth-scroll
```

For very low-memory environments, keep using `-LowMemory`; it keeps the extra smooth-scroll repaint loop off while preserving the non-blocking/debounced safeguards.

## Self-review and completion gates

This revision adds a consolidated self-review flow for Python parity, GUI completion, and UT coverage.

Windows:

```powershell
.\windows\self-review-windows.ps1 -Json -Strict
.\windows\quality-review-windows.ps1 -Json -Deep
.\windows\gui-completion-verify-windows.ps1 -Json -CheckSubgates
```

The GUI also exposes these from `Tools` -> `自己レビュー / 品質ゲート`. The `診断` tab and `性能HUD` help verify that rendering, scrolling, volatile caches, and background I/O remain responsive on large DiffGR files.


### Diff表示の読みやすさ改善

Diffタブでは、`統合表示` と `左右比較` を切り替えられます。表示範囲は `全行`、`変更行のみ`、`変更周辺` から選べます。`変更周辺` では文脈行数を増減できるため、大きなchunkでも変更箇所を見失いにくくなります。

Diff内検索、前/次の変更ジャンプ、前/次の検索ジャンプ、表示中diffコピー、選択行コピーにも対応しています。行をクリックすると同じDiffタブ内で line comment を編集できます。

### Word-level diff viewer

Diff タブは `統合表示` / `左右比較` に加えて、`行内差分` を標準で有効にしています。変更行同士を `賢く対応付け` したうえで、単語・記号単位の変更だけを背景ハイライトするため、GitHub / VS Code の diff viewer に近い粒度でレビューできます。低メモリ起動では行内差分を自動で無効化し、巨大行は安全に行単位表示へフォールバックします。


## Virtual PR review gate

The GUI now has a `仮想PR` tab for final virtual-PR review decisions. It combines coverage, pending review status, approval validity, group handoff gaps, file hotspots, and high-risk chunk heuristics into a readiness score. Use `最重要chunkへ` or `未完了高リスクへ` to jump directly to the next review target.

CLI equivalent:

```powershell
.\diffgrctl.ps1 virtual-pr-review --input .\examples\multi_file.diffgr.json --markdown
.\diffgrctl.ps1 review-gate --input .\examples\multi_file.diffgr.json --json --fail-on-blockers
.\diffgrctl.ps1 vpr-review --input .\examples\multi_file.diffgr.json --prompt --max-items 12
```

Static asset verifier for this gate:

```powershell
.\virtual-pr-review-verify.ps1 -Json
```
