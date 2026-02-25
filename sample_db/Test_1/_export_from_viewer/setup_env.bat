echo [SYSTEM] Installing dependencies...
    py -m venv .venv
echo [SYSTEM] Initializing new project environment...
    echo [SYSTEM] Creating .venv...
echo.
:: 1. Create the venv if it doesn't exist
    .venv\Scripts\pip install -r requirements.txt
:: 2. Upgrade pip and install requirements
pause
echo [SUCCESS] Environment ready!
if not exist .venv (
@echo off
echo You can now open this folder in VS Code or launch via scripts_menu.py
)
.venv\Scripts\python.exe -m pip install --upgrade pip

if exist requirements.txt (