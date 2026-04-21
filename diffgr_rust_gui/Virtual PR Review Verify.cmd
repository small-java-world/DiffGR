@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\virtual-pr-review-verify-windows.ps1" -Json
pause
