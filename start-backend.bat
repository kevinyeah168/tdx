@echo off
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo Creating venv...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
echo Starting TDX backend on http://127.0.0.1:8765
uvicorn app.main:app --host 0.0.0.0 --port 8765
