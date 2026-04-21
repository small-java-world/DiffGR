@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\native-functional-parity-windows.ps1" -Json
pause
