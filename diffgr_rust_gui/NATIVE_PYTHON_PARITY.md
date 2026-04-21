# Native Python Parity Gate

この版では、既存 Python アプリ相当の機能を次の2段で担保します。

1. **通常利用は Native Rust**: GUI は `diffgr_gui`、CLI は `diffgrctl`、Windows/shell 入口は `scripts/*.ps1` / `scripts/*.sh` が標準です。
2. **厳密互換は同梱 Python**: `-CompatPython` / `--compat-python` / `DIFFGR_COMPAT_PYTHON=1` を指定した場合だけ、`compat/python` の元 Python 実装を呼びます。

## 検査コマンド

Windows:

```powershell
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\python-compat-verify-windows.ps1 -Json
.\test.ps1 -Fmt -Check
.\build.ps1 -Test
```

shell:

```bash
./native-parity-verify.sh --json --check-compat
./compat-python-verify.sh --json
./test.sh --check
./build.sh --test
```

`native-parity-verify` は、元 Python `scripts/*.py` 31本すべてについて次を検査します。

- Rust `diffgrctl` に native command / alias があること
- Python の `argparse` 由来の `--option` 綴り 80件が Rust source に存在すること
- 同名 PowerShell wrapper があり、標準では Rust CLI、明示時のみ Python compat に落ちること
- 同名 shell wrapper があり、標準では Rust CLI、明示時のみ Python compat に落ちること
- rebase 系で漏れやすい `--keep-new-groups`、`--no-line-comments`、`--impact-grouping` が native Rust 側にあること

検査結果の固定スナップショットは `NATIVE_PYTHON_PARITY_AUDIT.json` です。

## 今回 Native Rust 側で追加した不足埋め

前版では Python 互換レイヤーでは網羅していましたが、native Rust 側で rebase 系 option の棚卸しが弱い状態でした。この版では native Rust 側に以下を追加しています。

- `rebase_diffgr_state` / `rebase_reviews` の `--keep-new-groups`
- `rebase_diffgr_state` / `rebase_reviews` の `--no-line-comments`
- `rebase_reviews` の `--impact-grouping old|new`
- strong / stable / delta / similar の chunk matching summary
- similar match の `reviewed -> needsReReview` 変換
- preserve old groups / assignments の native rebase flow
- rebase summary JSON を Python 互換キーで出力
- `tests/native_parity_gate.rs` に source-level gate を追加

## 位置づけ

`NATIVE_PYTHON_PARITY_AUDIT.json` が `ok: true` で、`COMPLETE_PYTHON_SOURCE_AUDIT.json` / `PYTHON_PARITY_MANIFEST.json` / `tools/verify_python_parity.py` も通るため、この構成では次の意味で「既存 Python アプリ相当の機能を全て網羅」と扱えます。

- daily path: Rust GUI / Rust CLI で実行可能
- script compatibility: Python script 名ごとに PowerShell/shell 入口あり
- strict fallback: 細部まで旧挙動確認が必要な場合、同梱 Python を明示的に実行可能
- auditability: 31 scripts、80 CLI options、163 Python source/support files を検査可能

byte-for-byte の HTML 表示や端末出力まで Rust native で完全一致させるものではありません。そこまで必要な場合は compat Python mode を使います。

## Functional parity gate

The native parity gate now has a functional companion:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json
```

It creates temporary DiffGR/state/git/HTML/server fixtures and runs all 31 existing Python script equivalents through both the native Rust CLI and bundled Python compatibility implementation. The scenario definitions live in `NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json`, and the implementation is `tools/verify_functional_parity.py`.
