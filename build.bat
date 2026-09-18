@echo off
chcp 65001 >nul 2>&1
echo ================================
echo   Bili Downloader Build Script
echo ================================
echo.

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.

echo [2/3] Building executable...
pyinstaller --noconfirm --onefile --windowed ^
    --collect-data customtkinter ^
    --collect-data imageio_ffmpeg ^
    --collect-binaries imageio_ffmpeg ^
    --name "BiliDownloader" ^
    main.py
if %errorlevel% neq 0 (
    echo ERROR: Build failed.
    pause
    exit /b 1
)
echo.

echo [3/3] Done!
echo Executable: dist\BiliDownloader.exe
echo.
pause
