@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\..\..\yuntai\.venv-local\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  pause
  exit /b 1
)

"%APP_PYTHON%" full_test.py %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%APP_EXIT_CODE%"=="0" (echo [full_test] done.) else (echo [full_test] FAILED with code %APP_EXIT_CODE%)
pause
exit /b %APP_EXIT_CODE%
