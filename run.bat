@echo off
setlocal
title TripartiteDataSTORE Launcher

echo =============================================
echo      Launching TripartiteDataSTORE STUDIO
echo =============================================

:: 1. Check if the virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo Please ensure .venv is located in this directory.
    pause
    exit /b
)

:: 2. Activate the environment
echo [1/2] Activating virtual environment...
call .venv\Scripts\activate.bat

:: 3. Run the application
echo [2/2] Starting the Studio...
python -m tripartite.studio

:: 4. Handle exit
if %ERRORLEVEL% neq 0 (
    echo.
    echo [alert] Application closed with an error (Code: %ERRORLEVEL%)
    pause
) else (
    echo.
    echo Application closed successfully.
)

deactivate
endlocal