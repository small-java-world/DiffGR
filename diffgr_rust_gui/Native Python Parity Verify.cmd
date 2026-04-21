@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\native-parity-verify-windows.ps1" -Json -CheckCompat
pause
