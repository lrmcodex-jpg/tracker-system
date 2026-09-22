@echo off
REM Start the Tracker CRM web app + background fetcher.
REM Runs on http://localhost:8000
cd /d %~dp0
if not exist .venv (
    echo Creating virtual environment...
    py -3 -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
