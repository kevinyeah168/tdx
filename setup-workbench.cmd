@echo off
setlocal
title Market Workbench - setup
cd /d "%~dp0"

echo.
echo [setup] Market Workbench first-time install
echo        Python venv + pip + npm + catalog sync
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup-workbench.ps1" %*
set EXITCODE=%ERRORLEVEL%

if not "%EXITCODE%"=="0" (
  echo.
  echo [failed] exit code %EXITCODE%
  echo.
  pause
  exit /b %EXITCODE%
)

echo.
pause
endlocal
