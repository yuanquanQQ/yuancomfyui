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

"%APP_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
"%APP_PYTHON%" -m PyInstaller admin.spec --noconfirm --clean
if errorlevel 1 exit /b 1
echo Build complete: dist\YunComfyUI-License-Admin.exe
pause
