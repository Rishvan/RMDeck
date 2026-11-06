@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name RMDeck --collect-all pyaudiowpatch --hidden-import pystray._win32 rmdeck.py
echo.
echo Done: dist\RMDeck.exe
pause
