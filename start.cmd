@echo off
cd /d "%~dp0"
if "%~1"=="" (
    python launcher.py
) else (
    python browse.py %*
)
if errorlevel 1 pause
