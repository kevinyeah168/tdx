@echo off
setlocal
title Market Workbench - background start
cd /d "%~dp0"

echo.
echo [start] Market Workbench (background, no extra windows)
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-workbench-all.ps1" -Background
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
  echo.
  echo [failed] exit code %EXITCODE%
  echo          check logs in data\run\workbench\
  echo.
  pause
  exit /b %EXITCODE%
)

echo.
echo [ok] open http://127.0.0.1:5180/workbench.html
echo [stop] run stop-workbench-all.cmd
echo.
pause
endlocal
