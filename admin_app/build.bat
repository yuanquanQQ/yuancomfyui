@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m PyInstaller admin_app.spec --noconfirm --clean
echo Build complete: dist\YunComfyUI-License-Admin.exe
pause
