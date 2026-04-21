@echo off
echo Usage examples:
echo   scripts\summarize_diffgr.ps1 -CompatPython --input examples\multi_file.diffgr.json --json
echo   set DIFFGR_COMPAT_PYTHON=1 ^& scripts\view_diffgr.ps1 examples\multi_file.diffgr.json --json
powershell -NoProfile -ExecutionPolicy Bypass -Command "Write-Host 'Python compatibility mode is available via -CompatPython or DIFFGR_COMPAT_PYTHON=1.'"
