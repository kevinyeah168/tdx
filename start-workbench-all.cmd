@echo off
setlocal
title Market Workbench - debug windows
cd /d "%~dp0"

echo.
echo [start] Market Workbench (foreground PowerShell windows)
echo        for daily use, prefer start-workbench-all-background.cmd
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-workbench-all.ps1" %*
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%
