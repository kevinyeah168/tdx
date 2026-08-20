@echo off
cd /d "%~dp0..\tdx-web-mobile"
if not exist node_modules (
  echo Installing npm dependencies...
  call npm install
)
echo Starting tdx-web-mobile on http://127.0.0.1:5179
call npm run dev
