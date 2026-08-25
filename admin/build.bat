@echo off
setlocal
cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo [ERROR] Python environment is missing.
  pause
  exit /b 1
)

powershell -ExecutionPolicy Bypass -File "..\installer\build_installers.ps1" -AdminOnly
if errorlevel 1 exit /b 1
echo Build complete: ..\installer\output\YunComfyUI-Admin-Setup.exe
pause
