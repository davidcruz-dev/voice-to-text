@echo off
pushd "%~dp0"
echo Installing Voice-to-Text dependencies...
pip install -r requirements.txt
echo.
echo Done! Run 'start.bat' to launch.
pause
