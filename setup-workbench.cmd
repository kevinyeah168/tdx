@echo off
setlocal
title Market Workbench - setup
cd /d "%~dp0"

if exist "%ProgramFiles%\nodejs\npm.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%ProgramFiles(x86)%\nodejs\npm.cmd" set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
  set "PATH=%%~dpP;%%~dpPScripts;%PATH%"
)

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
