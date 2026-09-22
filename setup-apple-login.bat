@echo off
REM One-time Apple login for the fetching account. Run this once before starting.
cd /d %~dp0
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate
pip install -r requirements.txt >nul
python -m app.setup_apple_login
pause
