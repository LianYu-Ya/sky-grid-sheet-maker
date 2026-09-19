@echo off
title Sky Grid Sheet Maker
cd /d "%~dp0"

rem ===== find python: prefer "python", fallback "py -3" =====
set "PYTHON="
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=python"
) else (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON=py -3"
    )
)
if "%PYTHON%"=="" (
    echo [ERROR] Python 3 not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

rem ===== ensure PySide6 is installed =====
%PYTHON% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo [INFO] PySide6 not found, installing...
    %PYTHON% -m pip install PySide6
    if errorlevel 1 (
        echo [ERROR] PySide6 install failed. Retry or run: pip install PySide6
        pause
        exit /b 1
    )
)

rem ===== launch app =====
%PYTHON% main.py
if errorlevel 1 (
    echo [ERROR] App exited with an error. See messages above.
    pause
)
