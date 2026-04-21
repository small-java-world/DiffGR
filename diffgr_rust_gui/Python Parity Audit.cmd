@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\parity-audit-windows.ps1"
exit /b %ERRORLEVEL%
