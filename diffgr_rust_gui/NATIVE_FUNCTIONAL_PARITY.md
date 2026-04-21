# Native Functional Python Parity Gate

This gate verifies more than command-name coverage. It creates temporary fixtures and exercises every historical Python `scripts/*.py` entry through both paths:

1. bundled Python compatibility script, for example `compat/python/scripts/view_diffgr.py`
2. native Rust CLI, for example `diffgrctl view-diffgr`

The result is a shape-level functional comparison. It intentionally does not require byte-for-byte output equality because timestamps, console wording, HTML formatting, and Rust/Python ordering can legitimately differ. It does require both paths to complete and produce the same semantic output shape for the operation.

## Gates now available

| Gate | Command | What it proves |
|---|---|---|
| Python source strict parity | `python tools/verify_python_parity.py --json` | The bundled Python compatibility layer contains the original non-cache Python app files. |
| Native command/option parity | `python tools/verify_native_parity.py --json` | All 31 Python script entries and 80 discovered long options have native Rust commands/wrappers. |
| Native functional parity | `python tools/verify_functional_parity.py --json` | All 31 script-equivalent operations run against sample fixtures in both Python compat and native Rust. |

## Windows

```powershell
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
.\windows\native-functional-parity-windows.ps1 -Json
.\windows\python-compat-verify-windows.ps1 -Json
```

The functional gate needs a built `diffgrctl` or a working Cargo toolchain. If `target\release\diffgrctl.exe` or `target\debug\diffgrctl.exe` exists, it is used. Otherwise the gate falls back to:

```powershell
cargo run --quiet --bin diffgrctl -- <command> ...
```

You can point it to a specific binary:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -NativeCmd .\target\release\diffgrctl.exe
```

## Shell

```bash
./native-parity-verify.sh --json --check-compat
./native-functional-parity.sh --json
./compat-python-verify.sh --json
```

## Static scenario audit only

This checks that the scenario matrix still covers all 31 Python scripts without running Rust/Python commands:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -List
```

```bash
./native-functional-parity.sh --json --list
```

## Scenario matrix

`NATIVE_FUNCTIONAL_PARITY_SCENARIOS.json` lists the 31 script-equivalent functional scenarios. The verifier compares it with `PYTHON_PARITY_MANIFEST.json` and fails if any Python script is missing from the functional matrix.

## Scope

This gate is intended to prove operational coverage, not visual pixel equality. For exact historical behavior, use `-CompatPython` or `DIFFGR_COMPAT_PYTHON=1`, which runs the bundled original Python implementation.

## Compat-only dry run

To validate the scenario definitions and bundled Python behavior without Rust, run:

```powershell
.\windows\native-functional-parity-windows.ps1 -Json -CompatOnly
```

```bash
./native-functional-parity.sh --json --compat-only
```

The compat-only run requires the Python compatibility requirements, especially `rich` for `view_diffgr.py` and `view_diffgr_app.py`. Install from `compat/python/requirements.txt` when using this mode.

## Strict shape comparison

By default, the functional gate requires both native and compat paths to complete and each output to pass the operation-specific checks. Add `--strict-shape` / `-StrictShape` to require exact equality of the compact semantic summaries too.
