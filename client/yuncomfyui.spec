# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RunningHub 多账号任务台."""

import os, sys, site
from pathlib import Path

_root = Path(SPECPATH)  # directory containing this .spec file

# ---------------------------------------------------------------------------
# Playwright driver (node.exe + JS bundles) — required for any browser launch
# ---------------------------------------------------------------------------
_playwright_driver = None
for _sp in site.getsitepackages():
    _candidate = Path(_sp) / "playwright" / "driver"
    if _candidate.is_dir():
        _playwright_driver = _candidate
        break

# ---------------------------------------------------------------------------
# Playwright Chromium browser — bundle so the EXE is fully self-contained.
# Use recursive glob to ensure every file is collected.
# ---------------------------------------------------------------------------
_ms_pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
_BUNDLED_BROWSERS = []
if _ms_pw.is_dir():
    for _prefix in ["chromium", "chromium_headless_shell", "ffmpeg", "winldd"]:
        _candidates = sorted(
            (path for path in _ms_pw.glob(f"{_prefix}-*") if path.is_dir()),
            key=lambda path: int(path.name.rsplit("-", 1)[-1]),
        )
        _p = _candidates[-1] if _candidates else None
        if _p:
            for _file in _p.rglob("*"):
                if _file.is_file():
                    _rel = _file.relative_to(_ms_pw)
                    _BUNDLED_BROWSERS.append(
                        (str(_file), f"ms-playwright/{_rel.parent}"))

# ---------------------------------------------------------------------------
# Assemble the datas list
# ---------------------------------------------------------------------------
_datas = [
    (str(_root / "static" / "index.html"), "static"),
    (str(_root / "static" / "client-logo.png"), "static"),
]
if _playwright_driver:
    _datas.append((str(_playwright_driver), "playwright/driver"))
_datas.extend(_BUNDLED_BROWSERS)

a = Analysis(
    [str(_root / 'server.py')],
    pathex=[str(_root)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        'greenlet',
        'playwright',
        'playwright.sync_api',
        'playwright.async_api',
        'playwright._impl',
        'playwright._impl._browser',
        'playwright._impl._browser_type',
        'playwright._impl._connection',
        'playwright._impl._driver',
        'playwright._impl._frame',
        'playwright._impl._helper',
        'playwright._impl._js_handle',
        'playwright._impl._network',
        'playwright._impl._object_factory',
        'playwright._impl._page',
        'playwright._impl._transport',
        'playwright._impl._local_utils',
        'playwright._impl._set_input_files_helpers',
        'requests',
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'tqdm',
        'dotenv',
        'json',
        'logging',
        'pathlib',
        'urllib',
        'asyncio',
        'webview',
        'webview.platforms.edgechromium',
        'sms_login',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavyweight packages not needed at runtime
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'cv2',
        'scipy',
        'notebook',
        'jupyter',
        'IPython',
        'pytest',
        'setuptools',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='yuncomfyui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_root.parent / 'installer' / 'assets' / 'client-icon.ico'),
)
