# Windows installers

The two Inno Setup projects create separate 64-bit Windows installers:

- `YunComfyUI-Client-Setup.exe`
- `YunComfyUI-Admin-Setup.exe`

Both installers allow the destination directory to be changed. The client
installer grants standard users write access only to its runtime data folders,
so it can run correctly when installed under Program Files or another drive.

## Build

Install the build-only image dependency once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r installer/requirements.txt
```

The SVG source marks in `installer/assets` are rendered automatically. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File installer/build_installers.ps1
```

Use `-SkipApplicationBuild` to compile only the installers from existing EXEs.

Generated installers are written to `installer/output`. Both installers use a
Chinese wizard, support a custom destination drive and directory, create an
uninstaller, and optionally create a desktop shortcut.
