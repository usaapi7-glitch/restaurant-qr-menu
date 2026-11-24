@echo off
cd /d "%~dp0"
if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)
echo Starting Restaurant QR Menu Server on port 8085...
uvicorn app.main:app --host 0.0.0.0 --port 8085 --reload
pause
