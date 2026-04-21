@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0doctor.ps1" %*
pause
