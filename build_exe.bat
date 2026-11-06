@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name RMDex --collect-all pyaudiowpatch --hidden-import pystray._win32 rmdex.py
echo.
echo Done: dist\RMDex.exe
pause
