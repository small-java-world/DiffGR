@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\parity-smoke-windows.ps1" %*
