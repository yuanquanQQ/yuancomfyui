@echo off
rem ============================================================
rem   RunningHub Multi-Account Task Console - Build Script
rem   Pure-ASCII to avoid GBK/UTF-8 codepage issues on old cmd
rem ============================================================

cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo   ERROR: Python environment is missing. Run setup.bat first.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   [1/4] Checking icon...
echo ============================================
if exist "app_icon.ico" (
  echo   app_icon.ico ready
) else (
  echo   WARNING: app_icon.ico missing, default icon will be used
)

echo.
echo ============================================
echo   [2/4] Cleaning old build...
echo ============================================
if exist "dist\yuncomfyui.exe" del /q "dist\yuncomfyui.exe"
if exist "build" rmdir /s /q "build"
echo   done.

echo.
echo ============================================
echo   [3/4] PyInstaller packaging (1-2 min)...
echo ============================================
set PYTHONIOENCODING=utf-8
"%APP_PYTHON%" -m PyInstaller yuncomfyui.spec --clean --noconfirm
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo   *** PACKAGE FAILED ***
  pause
  exit /b %ERRORLEVEL%
)

echo.
echo ============================================
echo   [4/4] Creating runtime directories...
echo ============================================
set "OUTDIR=dist"
if not exist "%OUTDIR%\data\pic"     mkdir "%OUTDIR%\data\pic"
if not exist "%OUTDIR%\data\ple"     mkdir "%OUTDIR%\data\ple"
if not exist "%OUTDIR%\data\video"   mkdir "%OUTDIR%\data\video"
if not exist "%OUTDIR%\profiles"     mkdir "%OUTDIR%\profiles"
if not exist "%OUTDIR%\outputs"      mkdir "%OUTDIR%\outputs"
echo   done.

echo.
echo ============================================
echo   BUILD COMPLETE
echo   Output: dist\yuncomfyui.exe
echo.
echo   Folder layout:
echo     dist\
echo     +-- yuncomfyui.exe     (main program, double-click to run)
echo     +-- data\              (asset folders)
echo     |   +-- pic\           (model images  *.png *.jpg)
echo     |   +-- ple\           (clothing     *.png *.jpg)
echo     |   +-- video\         (video clips  *.mp4)
echo     +-- profiles\          (account config & session)
echo     +-- outputs\           (generated results)
echo.
echo   Usage:
echo     1. Drop assets into the matching data\* subfolder
echo     2. Double-click dist\yuncomfyui.exe
echo     3. Browser opens at http://localhost:8080
echo     4. Add account -> Login -> Submit task
echo ============================================
pause
