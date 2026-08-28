@echo off
setlocal
title Market Workbench - stop
cd /d "%~dp0"

echo.
echo [stop] shutting down Market Workbench...
echo        (frontend node + api + collectors)
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-workbench-all.ps1"
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo [ok] services stopped. Refresh browser - page should fail to load.
) else (
  echo [warn] some ports may still be in use. Run stop again or check Task Manager.
)
echo.
pause
exit /b %EXITCODE%
