@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\ut-depth-windows.ps1" -Json
pause
