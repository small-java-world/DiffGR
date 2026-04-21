@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\gui-completion-verify-windows.ps1" -Json -CheckSubgates
pause
