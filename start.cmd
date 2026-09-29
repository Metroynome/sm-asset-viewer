@echo off
cd /d "%~dp0"
python browse.py --root "data\extracted" %*
pause
