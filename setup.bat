@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv-local\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python 3.10 or newer is required.
    pause
    exit /b 1
  )
  py -3 -m venv .venv-local
  if errorlevel 1 exit /b 1
)

".venv-local\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv-local\Scripts\python.exe" -m pip install -r license_server\requirements.txt
if errorlevel 1 exit /b 1

echo [OK] Python dependencies installed.
echo The application will use Microsoft Edge when Playwright Chromium is absent.
echo Run run.bat to start the application.
pause
