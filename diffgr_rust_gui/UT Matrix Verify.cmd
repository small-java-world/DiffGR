@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\windows\ut-matrix-windows.ps1" %*
pause
