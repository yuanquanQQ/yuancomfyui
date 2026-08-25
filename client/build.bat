@echo off
rem ============================================================
rem   RunningHub Multi-Account Task Console - Build Script
rem   Pure-ASCII to avoid GBK/UTF-8 codepage issues on old cmd
rem ============================================================

cd /d "%~dp0"

set "APP_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo   ERROR: Python environment is missing. Run setup.bat first.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   [1/4] Checking icon...
echo ============================================
if exist "..\installer\assets\client-icon.ico" (
  echo   installer\assets\client-icon.ico ready
) else (
  echo   ERROR: installer\assets\client-icon.ico missing
  exit /b 1
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
echo   [3/4] PyInstaller 6.14.2 + Inno Setup packaging...
echo ============================================
set PYTHONIOENCODING=utf-8
powershell -ExecutionPolicy Bypass -File "..\installer\build_installers.ps1" -ClientOnly
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo   *** PACKAGE FAILED ***
  pause
  exit /b %ERRORLEVEL%
)

echo.
echo ============================================
echo   [4/4] Installer ready...
echo ============================================
echo   done.

echo.
echo ============================================
echo   BUILD COMPLETE
echo   Output: installer\output\YunComfyUI-Client-Setup.exe
echo ============================================
pause
