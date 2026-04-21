# Testing

## このプロジェクトのテスト方針

GUIそのものは目視確認が必要な部分がありますが、重くなりやすい・壊れやすいロジックは `model` と小さな helper に寄せて UT で確認できるようにしています。

追加済みテストの主な対象:

- DiffGR JSON の必須キー / format / version 検証
- groups / chunks / assignments の読み取り
- add/delete 件数の事前計算
- review status の切替
- chunk comment / line comment の追加・削除・prune
- selected line anchor の state 保存・復元
- state JSON の正規化と overlay
- groupBriefs の pipe-list 入出力
- metrics の reviewed / pending / ignored / unassigned 集計
- full document / state JSON 書き込みと backup 作成
- CLI 引数解析: `diffgr.json --state review.state.json`
- GUI helper: 検索、近傍 `review.state.json` 検出、status sort key
- public API integration workflow

## Windows

```powershell
# UT
.\test.ps1

# check + UT
.\test.ps1 -Check

# fmt check + check + UT
.\test.ps1 -Fmt -Check

# UT後にrelease build
.\build.ps1 -Test

# env check + fmt/check/test + release build
.\windows\ci-windows.ps1
```

PowerShell 実行ポリシーで止まる場合:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test.ps1 -Check
```

## cmd

```cmd
Test.cmd
Check Test Build.cmd
```

## Git Bash / WSL / Linux / macOS

```bash
./test.sh
./test.sh --check
./test.sh --fmt --check
./build.sh --test
./build.sh --release
```

## Cargo 直打ち

```bash
cargo test --all-targets
cargo check --all-targets
cargo fmt --all -- --check
cargo build --release
```

## 特定テストだけ実行

```powershell
.\test.ps1 -TestName review_state_roundtrips
```

```bash
./test.sh -- review_state_roundtrips
```

Cargo 直打ち:

```bash
cargo test review_state_roundtrips
```

## 注意

この実行環境では Rust toolchain が無い場合があります。その場合、ローカル Windows で `cargo test --all-targets` を実行してください。スクリプトはすべて最終的に Cargo を呼んでいるため、エラーは Cargo のログを見れば追えます。
