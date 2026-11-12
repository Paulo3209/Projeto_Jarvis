@echo off
REM JARVIS Auto-Start Script
REM This script starts JARVIS in voice mode on Windows login

cd /d "C:\Users\paulo\jarvis"

REM Activate virtual environment if exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Start JARVIS in voice mode
python main.py --voice

pause