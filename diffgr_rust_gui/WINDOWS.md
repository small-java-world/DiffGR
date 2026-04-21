# Windows 運用メモ

## 前提

これは Rust プロジェクトです。Windows でもビルドと UT の本体は Cargo です。

```powershell
cargo test --all-targets
cargo build --release
```

同梱の `.ps1` / `.cmd` は、上記を毎回打たずに済むようにしたラッパーです。PowerShell 実行ポリシー、パス解決、exe が無い場合の自動ビルド、低負荷モード、配布 zip 作成をまとめています。

## 最短ルート

```powershell
.\windows\check-windows-env.ps1
.\windows\run-windows.ps1 -Diffgr .\examples\minimal.diffgr.json
```

ルート wrapper でも同じです。

```powershell
.\run.ps1 -Diffgr .\examples\minimal.diffgr.json
```

ダブルクリック運用なら `Run DiffGR Review.cmd` を使ってください。引数なしで開いた場合は、GUI内の `開く` から DiffGR JSON を選べます。

## ビルド

```powershell
# release build
.\windows\build-windows.ps1

# debug build
.\windows\build-windows.ps1 -Debug

# cleanしてrelease build
.\windows\build-windows.ps1 -Clean

# cargo test --all-targets の後に release build
.\windows\build-windows.ps1 -Test

# cargo check --all-targets → cargo test --all-targets → release build
.\windows\build-windows.ps1 -Check -Test
```

ルート wrapper:

```powershell
.\build.ps1 -Test
```

## Doctor / 環境診断

```powershell
# 軽い診断: cargo/rustc/exe/パス長/必要ファイル
.\doctor.ps1

# 深い診断: fmt → check → test → release build
.\doctor.ps1 -Deep
```

cmd からは `Doctor.cmd` を使えます。

## UT / CI 相当

```powershell
# UTだけ
.\windows\test-windows.ps1

# checkしてからUT
.\windows\test-windows.ps1 -Check

# rustfmt check → cargo check → cargo test → release build
.\windows\ci-windows.ps1
```

ルート wrapper:

```powershell
.\test.ps1 -Check
```

cmd からは次を使えます。

```cmd
Test.cmd
Check Test Build.cmd
Doctor.cmd
```

## PowerShell 実行ポリシーで止まる場合

一時的に bypass して実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\test-windows.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\run-windows.ps1
```

## 配布zip

```powershell
.\windows\package-windows.ps1
# またはダブルクリック/ cmd
Package Windows.cmd
```

`dist/diffgr_gui_windows.zip` が作成されます。zip 内には `diffgr_gui.exe`、README、Windowsスクリプト、サンプルJSONが入ります。

## ショートカット作成

```powershell
.\windows\new-shortcut-windows.ps1 -Release
```

特定の DiffGR を常に開くショートカットにする場合:

```powershell
.\windows\new-shortcut-windows.ps1 -Release -Diffgr C:\work\input.diffgr.json -State C:\work\review.state.json
```

## 軽量・ちらつき対策モード

通常起動で問題がなければそのままで大丈夫です。大きい DiffGR で重い、スクロール時にちらつく、古いUI状態が残る場合は次を使います。

```powershell
# 低負荷モードで起動
.\windows\run-windows.ps1 -Release -LowMemory -Diffgr C:\work\input.diffgr.json

# UI設定/キャッシュ候補を削除してから起動
.\windows\run-windows.ps1 -ClearCache -Release -Diffgr C:\work\input.diffgr.json

# キャッシュ削除だけ
.\windows\clear-cache-windows.ps1 -Force
```

GUI 上部の `ちらつき抑制` は ON 推奨です。`UI状態を記憶` は標準 OFF です。ON にすると細かい egui メモリも保存できますが、通常は OFF の方が軽く保てます。`揮発キャッシュ破棄` は表示用キャッシュだけを捨て、設定やレビュー状態は消しません。

## よくあるトラブル

### cargo が見つからない

```powershell
.\windows\setup-rust-windows.ps1 -UseWinget
```

インストール後、新しい PowerShell を開き直してください。

### linker / MSVC エラー

Visual Studio Build Tools の `Desktop development with C++` ワークロードを入れてください。

```powershell
.\windows\setup-rust-windows.ps1 -InstallBuildTools
```

### GUI で実ファイルを開けない

Diff内のファイルパスが相対パスの場合、GUI上部の `作業ルート` にリポジトリのルートディレクトリを設定してください。

### スクロールが重い / ちらつく

1. `ちらつき抑制` を ON にします。
2. `UI状態を記憶` を OFF にします。
3. `Run Low Memory.cmd` または `.\windows\run-windows.ps1 -LowMemory` で起動します。
4. まだ重い場合は `.\windows\clear-cache-windows.ps1 -Force` で古いUI設定/キャッシュ候補を消します。


## 今回追加したGUI便利機能

- `概要` タブで、ステータス別件数とファイル別進捗を確認できます。
- 上部 `サマリコピー` / `サマリ保存…` で、レビュー結果を Markdown として出力できます。
- Chunks の `一括` ボタンで、表示中チャンクをレビュー済み・再レビュー・未レビュー・無視にまとめて変更できます。
- `Ctrl+Z` または `Undo Ctrl+Z` で、直近のステータス変更を戻せます。
- JSON / Markdown 保存は一時ファイル経由です。保存途中の失敗で対象ファイルが空になりにくいようにしています。

## Pythonレビュー運用相当の確認

GUIを起動したら、上部またはDetailタブから次を確認できます。

- `Layout`: group作成/rename/delete、chunk assign/unassign、layout patch適用、group split保存
- `Coverage`: virtual PR coverage、修正promptコピー/保存
- `State JSON`: state差分/merge preview
- `Impact`: old/current DiffGR impact preview
- `Approval`: approve/request changes/revoke、approval report JSON保存
- `HTML保存…`: static HTML report export

```powershell
.\run.ps1 -Diffgr .\examples\multi_file.diffgr.json
```

## diffgrctl: Python scripts相当のCLI

既存 Python アプリの生成・autoslice・state・bundle・rebase 系は、Rust 版では `diffgrctl` に集約しています。PowerShell からはルートの `diffgrctl.ps1`、cmd からは `DiffGR Tools.cmd` を使えます。

```powershell
# 生成 → autoslice → refine
.\diffgrctl.ps1 prepare --repo . --base main --feature HEAD --output out\work\review.diffgr.json

# GUIで開く
.\run.ps1 -Diffgr .\out\work\review.diffgr.json

# state抽出/適用/差分/merge
.\diffgrctl.ps1 extract-state --input .\out\work\review.diffgr.json --output .\out\work\review.state.json
.\diffgrctl.ps1 apply-state --input .\out\work\review.diffgr.json --state .\out\work\review.state.json --output .\out\work\applied.diffgr.json
.\diffgrctl.ps1 diff-state --base old.state.json --incoming new.state.json --tokens
.\diffgrctl.ps1 apply-state-diff --base old.state.json --incoming new.state.json --tokens reviews:c1 --output selected.state.json
.\diffgrctl.ps1 merge-state --base old.state.json --input new.state.json --output merged.state.json

# HTML / bundle / verify
.\diffgrctl.ps1 export-html --input .\out\work\review.diffgr.json --output .\out\work\review.html
.\diffgrctl.ps1 export-bundle --input .\out\work\review.diffgr.json --output-dir .\out\bundle
.\diffgrctl.ps1 verify-bundle --bundle .\out\bundle\bundle.diffgr.json --state .\out\bundle\review.state.json --manifest .\out\bundle\review.manifest.json

# approval / coverage
.\diffgrctl.ps1 coverage --input .\out\work\review.diffgr.json --json
.\diffgrctl.ps1 approve --input .\out\work\review.diffgr.json --output .\out\work\approved.diffgr.json --all --force --reviewer me
.\diffgrctl.ps1 check-approval --input .\out\work\approved.diffgr.json --json
```

`diffgrctl.ps1` は必要に応じて `cargo build --bin diffgrctl` を実行します。release版で使う場合は次です。

```powershell
.\windows\diffgrctl-windows.ps1 -Release prepare --repo . --base main --feature HEAD --output out\work\review.diffgr.json
```

配布zipには `diffgr_gui.exe` と `diffgrctl.exe` の両方が入り、`run-release.ps1` と `diffgrctl-release.ps1` から実行できます。

## Python parity smoke

サンプルJSONで `summarize`、`coverage`、`extract-state`、`export-html`、`export-bundle`、`verify-bundle` をまとめて確認できます。

```powershell
.\windows\parity-smoke-windows.ps1
# または cmd
Python Parity Smoke.cmd
```

## Strict Python compatibility verify

既存 Python アプリ相当を厳密に確認したい場合は、Rust 側の parity smoke に加えて、同梱 Python 互換レイヤーの source / wrapper 検査を実行します。

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
```

ダブルクリック用には `Python Compat Verify.cmd` もあります。

この検査は、元 Python アプリの non-cache file 163件が `compat/python` に byte-for-byte で入っていること、31本の旧 `scripts/*.py` に `.ps1` / `.sh` wrapper があること、Python source が compile できること、summary/state/coverage の smoke が通ることを確認します。

## Native parity verify on Windows

```powershell
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
```

ダブルクリック用には `Native Python Parity Verify.cmd` もあります。

## Python parity / functional parity verification

For the strictest Windows verification, run these after Rust is installed:

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\native-functional-parity-windows.ps1 -Json
```

`native-functional-parity` uses an existing `target\release\diffgrctl.exe` or `target\debug\diffgrctl.exe` when available; otherwise it falls back to `cargo run --quiet --bin diffgrctl -- ...`.

To check only that all 31 scenarios are present:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -List
```

Functional parity can also be run in Python-only mode to validate the scenario matrix before Rust is built:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -CompatOnly
```

Install the Python compatibility requirements first when using `-CompatOnly` because the legacy viewer imports `rich`.

## UT matrix gate

Cargo / Rust toolchain がまだ入っていない段階でも、追加した UT 資産の欠けを確認できます。

```powershell
.\windows\ut-matrix-windows.ps1 -Json
```

エクスプローラーからは `UT Matrix Verify.cmd` も使えます。最終的な確認は必ず Cargo で行います。

```powershell
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```


## UT matrix 0.3.5

この版の UT matrix は 16カテゴリ / 1,192 Rust tests です。`windows\ut-matrix-windows.ps1 -Json` で Cargo 実行前にテスト資産の欠け、重複名、カテゴリ不足を確認できます。

## Smooth rendering / no-freeze mode 0.3.6

For day-to-day review on Windows, the default GUI now uses background loading, background state auto-save, debounced search, on-demand chunk rows, and virtualized State JSON rendering.

Use this for the smoothest scroll behavior:

```powershell
.\windows\run-windows.ps1 -Release -Smooth -Diffgr .\examples\multi_file.diffgr.json
```

Use this when debugging or when you want strictly synchronous IO:

```powershell
.\windows\run-windows.ps1 -Release -NoBackgroundIO -Diffgr .\examples\multi_file.diffgr.json
```

Explorer/double-click entry:

```text
Run Smooth.cmd
```

Low-memory mode still disables extra smooth-scroll repainting:

```powershell
.\windows\run-windows.ps1 -Release -LowMemory -Diffgr .\examples\multi_file.diffgr.json
```

## Self-review / GUI completion checks

For Windows release validation, run:

```powershell
.\windows\self-review-windows.ps1 -Json -Strict
.\windows\quality-review-windows.ps1 -Json -Deep
.\windows\gui-completion-verify-windows.ps1 -Json -CheckSubgates
```

`Self Review.cmd`, `Quality Review.cmd`, and `Python GUI Completion Verify.cmd` are also provided for Explorer-based use. The GUI has a `診断` tab and `性能HUD` toggle for frame-time and cache inspection.



## Virtual PR review gate on Windows

After opening a DiffGR file, use the `仮想PR` tab to review readiness before approval. The same gate is available from PowerShell:

```powershell
.\diffgrctl.ps1 virtual-pr-review --input .\examples\multi_file.diffgr.json --markdown
.\diffgrctl.ps1 review-gate --input .\examples\multi_file.diffgr.json --json --fail-on-blockers
```

Virtual PR gate asset verifier:

```powershell
.\windows\virtual-pr-review-verify-windows.ps1 -Json
```


## UT depth gate

UT 拡充後の追加ゲートは次で確認できます。

```powershell
.\windows\ut-depth-windows.ps1 -Json
```

`ut-depth-windows.ps1` は `tools\verify_ut_depth.py` を呼び、追加UT4本、UT matrix、GUI/仮想PR/CLI wrapper 契約を検査します。
