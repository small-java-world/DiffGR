@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\run-windows.ps1" -Release -Smooth %*
