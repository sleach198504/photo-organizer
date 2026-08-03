@echo off
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo PowerShell was not found on this computer, which is needed to run
    echo setup. This ships with every supported version of Windows, so
    echo something unusual is going on - please contact whoever gave you
    echo this software.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Setup.ps1"
