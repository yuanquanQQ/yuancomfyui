@echo off
setlocal
cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo [ERROR] Python environment is missing: .venv-local or .venv
  echo Run setup.bat once, then run this file again.
  pause
  exit /b 1
)

"%APP_PYTHON%" server.py
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" pause
exit /b %APP_EXIT_CODE%
