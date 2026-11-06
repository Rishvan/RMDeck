@echo off
cd /d "%~dp0"
echo Installing requirements (first run only takes a minute)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python not found or install failed. Install Python 3.10+ from python.org and tick "Add to PATH".
  pause
  exit /b
)
start "" pythonw rmdex.py
