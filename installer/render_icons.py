"""Render the project SVG marks into UI PNGs and Windows ICO files."""

from pathlib import Path
import shutil

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
ASSETS = ROOT / "assets"
TARGETS = {
    "client": REPO_ROOT / "client" / "static" / "client-logo.png",
    "admin": REPO_ROOT / "admin" / "web" / "admin-logo.png",
}
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def validate_png(path: Path) -> None:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if rgba.size != (1024, 1024):
            raise RuntimeError(f"Unexpected logo dimensions: {path} -> {rgba.size}")
        if any(rgba.getpixel(point)[3] != 0 for point in ((0, 0), (1023, 0), (0, 1023), (1023, 1023))):
            raise RuntimeError(f"Logo corners are not transparent: {path}")
        alpha = rgba.getchannel("A")
        if alpha.getbbox() is None:
            raise RuntimeError(f"Logo is blank: {path}")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 1024})
            for name, ui_target in TARGETS.items():
                source = ASSETS / f"{name}-logo.svg"
                png_target = ASSETS / f"{name}-logo.png"
                page.goto(source.as_uri(), wait_until="load")
                page.screenshot(path=str(png_target), omit_background=True)
                validate_png(png_target)

                with Image.open(png_target) as image:
                    image.convert("RGBA").save(
                        ASSETS / f"{name}-icon.ico",
                        format="ICO",
                        sizes=ICO_SIZES,
                    )
                shutil.copy2(png_target, ui_target)
        finally:
            browser.close()

    print(f"Rendered logos and icons in {ASSETS}")


if __name__ == "__main__":
    main()
