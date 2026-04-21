@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diffgrctl.ps1" %*
