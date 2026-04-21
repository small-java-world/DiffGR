# Strict Python Parity Gate

This package treats "existing Python app parity" as two separate guarantees.

1. **Operational parity**: the Rust GUI and `diffgrctl` expose the DiffGR workflow for normal use.
2. **Strict compatibility parity**: the uploaded Python app is vendored under `compat/python` and can be invoked by the same historical script names.

The strict gate verifies that every non-cache file from the original Python app is bundled byte-for-byte under `compat/python`, and that every historical `scripts/*.py` entry has matching PowerShell and shell wrappers.

## What is included

`COMPLETE_PYTHON_SOURCE_AUDIT.json` records 163 source/support files from the original Python app:

- `diffgr/*.py`
- `scripts/*.py`
- `tests/*.py`
- docs, samples, schemas, requirements, and supporting files

It intentionally excludes 99 `__pycache__/*.pyc` files because those are interpreter-specific rebuildable caches and not application functionality.

## Verify on Windows

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
```

For the original Python pytest suite as well:

```powershell
.\windows\python-compat-verify-windows.ps1 -Pytest
```

`-Pytest` requires pytest and the original Python optional dependencies such as Textual when viewer tests are run.

## Verify on shell

```bash
./compat-python-verify.sh --json
```

For the original Python pytest suite as well:

```bash
./compat-python-verify.sh --pytest
```

## Run a historical Python script exactly

PowerShell:

```powershell
.\scripts\view_diffgr.ps1 -CompatPython .\examples\multi_file.diffgr.json --json
```

Shell:

```bash
./scripts/view_diffgr.sh --compat-python ./examples/multi_file.diffgr.json --json
```

Environment-wide strict mode:

```powershell
$env:DIFFGR_COMPAT_PYTHON = '1'
.\scripts\view_diffgr.ps1 .\examples\multi_file.diffgr.json --json
```

```bash
DIFFGR_COMPAT_PYTHON=1 ./scripts/view_diffgr.sh ./examples/multi_file.diffgr.json --json
```

## Native Rust coverage gate

Strict Python compatibility に加え、native Rust 側の入口・option 綴りも検査する:

```powershell
.\windows\native-parity-verify-windows.ps1 -Json -CheckCompat
```

この gate は `NATIVE_PYTHON_PARITY_AUDIT.json` と同じ観点で、31 scripts / 80 option spellings / wrappers / rebase parity guards を確認する。
