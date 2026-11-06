@echo off
rem Builds dist\RMDeck-Setup-<version>.exe
rem Needs: Python 3.10+ and Inno Setup 6 (https://jrsoftware.org/isdl.php)
setlocal
cd /d "%~dp0"

echo [1/4] Installing build requirements...
python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo [2/4] Generating icon and version info...
for /f %%v in ('python packaging\prepare.py') do set VERSION=%%v
if not defined VERSION goto :fail

echo [3/4] Building the app (version %VERSION%)...
python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work packaging\RMDeck.spec
if errorlevel 1 goto :fail

echo [4/4] Building the installer...
set "ISCC="
for %%p in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
  if exist %%p set "ISCC=%%~p"
)
if not defined ISCC (
  echo Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php
  goto :fail
)
"%ISCC%" /Q /DAppVersion=%VERSION% packaging\installer.iss
if errorlevel 1 goto :fail

echo.
echo Done: dist\RMDeck-Setup-%VERSION%.exe
if not "%1"=="nopause" pause
exit /b 0

:fail
echo.
echo Build failed.
if not "%1"=="nopause" pause
exit /b 1
