@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\package-windows.ps1" %*
pause
