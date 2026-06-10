@echo off
echo ============================================
echo   VideoDownloader - PyInstaller Build Tool
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ first.
    pause & exit /b 1
)

:: Install / upgrade dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

:: Run PyInstaller
echo [2/3] Building executable...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "VideoDownloader" ^
    --icon NONE ^
    --add-data "%LOCALAPPDATA%\Programs\Python\Python311\Lib\site-packages\customtkinter;customtkinter" ^
    --hidden-import customtkinter ^
    --hidden-import yt_dlp ^
    --hidden-import PIL ^
    --clean ^
    video_downloader.py

echo.
echo [3/3] Done!
if exist "dist\VideoDownloader.exe" (
    echo SUCCESS: dist\VideoDownloader.exe created.
    echo You can now share this single file with anyone.
) else (
    echo Something went wrong. Check the output above for errors.
)
echo.
pause
