@echo off
setlocal enabledelayedexpansion

:: Force UTF-8 encoding for better character rendering
chcp 65001 >nul

REM ============================================================
REM _TripartiteDataSTORE - Environment Setup
REM ============================================================

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║         _TripartiteDataSTORE - Environment Setup              ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM ── Step 1: Check for Python ────────────────────────────────────
echo [1/4] Checking Python installation...
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Please install Python 3.10 or higher.
    echo        Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

py --version
echo [OK] Python found
echo.

REM ── Step 2: Create Virtual Environment ─────────────────────────
echo [2/4] Setting up virtual environment...

if exist .venv (
    echo [INFO] Virtual environment already exists ^(.venv^)
) else (
    echo [SETUP] Creating .venv...
    py -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)
echo.

REM ── Step 3: Upgrade pip ─────────────────────────────────────────
echo [3/4] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    echo [WARNING] Failed to upgrade pip, continuing anyway...
) else (
    echo [OK] Pip upgraded
)
echo.

REM ── Step 4: Install Dependencies ───────────────────────────────
echo [4/4] Installing dependencies...

if not exist requirements.txt (
    echo [WARNING] requirements.txt not found!
    echo           Skipping dependency installation
    goto :Finish
)

echo [INSTALL] Installing core dependencies...
echo  • llama-cpp-python (embeddings)
echo  • tree-sitter (multi-language parsing)
echo.

.venv\Scripts\pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install some dependencies!
    echo.
    echo Common issues:
    echo  - llama-cpp-python requires C++ build tools
    echo    Install from: https://visualstudio.microsoft.com/downloads/
    echo.
    echo [INFO] You can continue - some features may be limited
    pause
) else (
    echo [OK] All dependencies installed successfully!
)

:Finish
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║                     SETUP COMPLETE!                        ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.
echo Next steps:
echo  1. Activate the environment:
echo     .venv\Scripts\activate
echo.
echo  2. Run the CLI:
echo     python -m src.cli ingest /path/to/source --db mydata.db
echo.
echo  3. Or launch the viewer:
echo     python -m src.viewer mydata.db
echo.
echo Documentation:
echo  • README.md - Project overview
echo.
pause