@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0dist\yuncomfyui.exe" (
  echo [ERROR] dist\yuncomfyui.exe does not exist. Run build.bat first.
  pause
  exit /b 1
)

start "YunComfyUI" "%~dp0dist\yuncomfyui.exe"
