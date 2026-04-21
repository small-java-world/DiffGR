@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\ci-windows.ps1" %*
