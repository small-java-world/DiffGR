@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\test-windows.ps1" %*
