# Python Compatibility Mode

This project is primarily a Rust native GUI/CLI replacement for DiffGR.  To make
"existing Python app parity" practical and auditable, the original Python DiffGR
application is also vendored under `compat/python`.

There are two ways to run each historical Python script name:

1. Native Rust path: `scripts/<name>.ps1` / `scripts/<name>.sh` without any extra flag.
2. Exact Python compatibility path: add `-CompatPython` on PowerShell, add
   `--compat-python` on shell, or set `DIFFGR_COMPAT_PYTHON=1`.

Examples:

```powershell
.\scripts\summarize_diffgr.ps1 --input .\examples\multi_file.diffgr.json --json
.\scripts\summarize_diffgr.ps1 -CompatPython --input .\examples\multi_file.diffgr.json --json
$env:DIFFGR_COMPAT_PYTHON = '1'
.\scripts\view_diffgr.ps1 .\examples\multi_file.diffgr.json --json
```

```bash
./scripts/summarize_diffgr.sh --input ./examples/multi_file.diffgr.json --json
./scripts/summarize_diffgr.sh --compat-python --input ./examples/multi_file.diffgr.json --json
DIFFGR_COMPAT_PYTHON=1 ./scripts/view_diffgr.sh ./examples/multi_file.diffgr.json --json
```

`PYTHON_PARITY_MANIFEST.json` is generated from the vendored Python scripts and
records all 31 historical `scripts/*.py` entries and their argparse options.  The
Rust wrappers are present for every entry, and the compatibility wrappers call
the corresponding vendored Python script by the same stem.

## Smoke checks

Windows:

```powershell
.\windows\python-compat-smoke-windows.ps1
```

Shell:

```bash
./compat-python-smoke.sh
```

On the container used to prepare this archive, the shell smoke check passed with
`PYTHON='python3 -S'`.

## Why both native Rust and vendored Python?

The Rust GUI and `diffgrctl` cover the operational workflow directly: generation,
autoslice/refine, view, state operations, split/merge, rebase/impact, HTML/server,
review bundle, approval, coverage, reviewability, and summaries.

The vendored Python path exists for strict behavior parity: exact old text output,
exit-code conventions, prompt-mode edge cases, Textual-era state details, and any
future comparison against the Python unit tests.  This removes the ambiguity of
"feature name exists but edge behavior differs" while keeping the Rust app as the
main day-to-day GUI.

## Strict source parity verification

This archive also includes `COMPLETE_PYTHON_SOURCE_AUDIT.json` and
`tools/verify_python_parity.py`.  They verify that the vendored compatibility
layer contains every non-cache file from the uploaded Python app byte-for-byte,
that all 31 historical `scripts/*.py` entries have wrapper pairs, and that the
bundled Python source compiles.

Windows:

```powershell
.\windows\python-compat-verify-windows.ps1 -Json
```

Shell:

```bash
./compat-python-verify.sh --json
```

Use `-Pytest` / `--pytest` to run the vendored original Python pytest suite too
when Python test dependencies are installed.
