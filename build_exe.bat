@echo off
setlocal
cd /d "%~dp0"
title Building CoyoteVRChat.exe

rem Builds dist\CoyoteVRChat.exe (one file, no Python needed to run it).
rem It uses its own virtual environment (.venv-build), so the one that runs the program is left alone.

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv-build\Scripts\python.exe" (
  echo Creating the build environment ^(first run only^)...
  %PY% -m venv .venv-build
  if errorlevel 1 goto failed
)

echo Installing the build tools...
".venv-build\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 goto failed

echo Building...
".venv-build\Scripts\python.exe" -m PyInstaller coyote_vrchat.spec --noconfirm --clean
if errorlevel 1 goto failed

rem PyInstaller writes into dist\; also put the file next to main.py, where it is easy to find and double-click.
copy /Y "dist\CoyoteVRChat.exe" "CoyoteVRChat.exe" >nul
if errorlevel 1 goto failed

echo.
echo Done: CoyoteVRChat.exe ^(a copy is in dist\^)
exit /b 0

:failed
echo.
echo The build failed ^(see the message above^).
echo - If CoyoteVRChat.exe is open, close it ^(all its windows^) and run this again: Windows will not let it be replaced.
echo - You need Python 3.10 or newer: https://www.python.org/downloads/
pause
exit /b 1
