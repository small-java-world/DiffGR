@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\virtual-pr-review-windows.ps1" -Markdown
pause
