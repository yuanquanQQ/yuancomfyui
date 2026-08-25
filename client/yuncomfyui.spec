# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RunningHub multi-account task console."""

import os
import site
from pathlib import Path

_root = Path(SPECPATH)

_playwright_driver = None
for _sp in site.getsitepackages():
    _candidate = Path(_sp) / "playwright" / "driver"
    if _candidate.is_dir():
        _playwright_driver = _candidate
        break

_ms_pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
_bundled_browsers = []
if _ms_pw.is_dir():
    for _prefix in ["chromium", "chromium_headless_shell", "ffmpeg", "winldd"]:
        _candidates = sorted(
            (path for path in _ms_pw.glob(f"{_prefix}-*") if path.is_dir()),
            key=lambda path: int(path.name.rsplit("-", 1)[-1]),
        )
        _browser_dir = _candidates[-1] if _candidates else None
        if _browser_dir:
            for _file in _browser_dir.rglob("*"):
                if _file.is_file():
                    _relative = _file.relative_to(_ms_pw)
                    _bundled_browsers.append(
                        (str(_file), f"ms-playwright/{_relative.parent}")
                    )

_datas = [
    (str(_root / "static" / "index.html"), "static"),
    (str(_root / "static" / "client-logo.png"), "static"),
]
if _playwright_driver:
    _datas.append((str(_playwright_driver), "playwright/driver"))
_datas.extend(_bundled_browsers)

a = Analysis(
    [str(_root / "server.py")],
    pathex=[str(_root)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "greenlet",
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",
        "playwright._impl",
        "playwright._impl._browser",
        "playwright._impl._browser_type",
        "playwright._impl._connection",
        "playwright._impl._driver",
        "playwright._impl._frame",
        "playwright._impl._helper",
        "playwright._impl._js_handle",
        "playwright._impl._network",
        "playwright._impl._object_factory",
        "playwright._impl._page",
        "playwright._impl._transport",
        "playwright._impl._local_utils",
        "playwright._impl._set_input_files_helpers",
        "requests",
        "cryptography",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "tqdm",
        "dotenv",
        "webview",
        "webview.platforms.edgechromium",
        "sms_login",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "cv2",
        "scipy",
        "notebook",
        "jupyter",
        "IPython",
        "pytest",
        "setuptools",
        "pip",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="yuncomfyui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(_root.parent / "installer" / "assets" / "client-icon.ico"),
)
