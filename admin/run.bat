@echo off
setlocal
cd /d "%~dp0"

set "ADMIN_EXE=%~dp0dist\YunComfyUI-License-Admin.exe"
if exist "%ADMIN_EXE%" (
  start "YunComfyUI License Admin" "%ADMIN_EXE%"
  exit /b 0
)

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  pause
  exit /b 1
)
"%APP_PYTHON%" app.py
