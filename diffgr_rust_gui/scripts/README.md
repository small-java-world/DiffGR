# Python script compatible Rust wrappers

This directory contains PowerShell and shell wrappers named after the original Python scripts.
They call `diffgrctl` subcommands with Python-compatible option names, so existing runbooks can switch from:

```powershell
python scripts\generate_diffgr.py --base main --feature HEAD --output out\review.diffgr.json
```

to:

```powershell
.\scripts\generate_diffgr.ps1 --base main --feature HEAD --output out\review.diffgr.json
```

Cargo remains the build/test engine; these files are only ergonomic launchers.
