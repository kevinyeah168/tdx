@echo off
setlocal
title Market Workbench - demo tunnel
cd /d "%~dp0"

echo.
echo [start] Public demo tunnel (Cloudflare)
echo        Make sure workbench is running first:
echo          start-workbench-all-background.cmd
echo        Press Ctrl+C in this window when the demo ends.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-demo-tunnel.ps1" %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo [ok] tunnel stopped.
) else (
  echo [warn] tunnel exited with code %EXITCODE%.
)
echo.
pause
exit /b %EXITCODE%
