@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\run-windows.ps1" %*
