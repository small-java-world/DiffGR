@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\quality-review-windows.ps1" -Json -Strict
pause
