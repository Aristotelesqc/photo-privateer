@echo off
title Photo Privateer Launcher
cd /d "%~dp0"

echo ===================================================
echo   Photo Privateer - Starting Local Application
echo ===================================================

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found on your PATH.
    echo Please install Python 3.9+ or run setup.ps1.
    pause
    exit /b 1
)

python start.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with an error.
    pause
)
