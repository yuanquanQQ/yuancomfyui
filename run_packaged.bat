@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local_license.ps1"
if errorlevel 1 (
  echo [ERROR] Local license service could not start.
  pause
  exit /b 1
)

if not exist "%~dp0dist\yuncomfyui.exe" (
  echo [ERROR] dist\yuncomfyui.exe does not exist. Run build.bat first.
  pause
  exit /b 1
)

start "YunComfyUI" "%~dp0dist\yuncomfyui.exe"
