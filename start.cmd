@echo off
cd /d "%~dp0"
set "SM_VIEWER_ROOT=data\extracted"
if not exist "%SM_VIEWER_ROOT%\manifest.json" if exist "..\test\sm\extracted\manifest.json" set "SM_VIEWER_ROOT=..\test\sm\extracted"
python browse.py --root "%SM_VIEWER_ROOT%" %*
pause
