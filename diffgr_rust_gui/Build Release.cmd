@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\build-windows.ps1" %*
