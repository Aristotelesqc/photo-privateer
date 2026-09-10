@echo off
title Photo Privateer Launcher
cd /d "%~dp0"

echo ===================================================
echo   Photo Privateer - Starting Local Application
echo ===================================================

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo   [INFO] Using virtual environment: .venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo   [INFO] Using virtual environment: venv
)

if "%PYTHON_EXE%"=="python" (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python is not found on your PATH.
        echo Please install Python 3.14 (or Python 3.11+ fallback) or run setup.ps1.
        pause
        exit /b 1
    )
) else (
    if not exist "%PYTHON_EXE%" (
        echo [ERROR] Virtual environment python executable not found: %PYTHON_EXE%
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" start.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with an error.
    pause
)
