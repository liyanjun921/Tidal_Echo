@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\lune.ps1" -Action Access
if errorlevel 1 pause
