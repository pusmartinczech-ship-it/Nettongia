@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Preparing Nettongia PDF Editor for the first run...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -c "import pymupdf, PySide6, PIL" >nul 2>&1
if errorlevel 1 (
    echo Updating Nettongia PDF Editor dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

start "Nettongia PDF Editor" ".venv\Scripts\pythonw.exe" run_editor.py
exit /b 0

:error
echo.
echo Installation failed. Check your internet connection and Python installation.
pause
exit /b 1
