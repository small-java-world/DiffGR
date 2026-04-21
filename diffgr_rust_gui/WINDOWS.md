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

GUI 上部の `ちらつき抑制` は ON 推奨です。`UI状態を記憶` は標準 OFF です。ON にすると細かい egui メモリも保存できますが、通常は OFF の方が軽く保てます。

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
