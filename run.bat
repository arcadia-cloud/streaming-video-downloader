@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    echo [ERROR] Python 3.10+ not found.
    echo Install from https://www.python.org/downloads/ and tick "Add to PATH".
    pause
    exit /b 1
)

%PY% -c "import customtkinter, DrissionPage, requests, imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies, please wait...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check your network or proxy.
        pause
        exit /b 1
    )
)

echo Starting Video Downloader...
%PY% main.py

if errorlevel 1 (
    echo.
    echo Program exited with an error, see messages above.
    pause
)
