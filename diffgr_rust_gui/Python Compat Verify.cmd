@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\python-compat-verify-windows.ps1"
pause
