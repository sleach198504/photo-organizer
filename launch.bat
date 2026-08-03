@echo off
setlocal
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo Virtual environment not found.
    echo Right-click setup.ps1 and "Run with PowerShell" first, then try again.
    pause
    exit /b 1
)

if "%~1"=="" (
    start "" venv\Scripts\pythonw.exe -m app.gui_launcher
) else (
    venv\Scripts\python.exe -m app.cli %*
    pause
)
