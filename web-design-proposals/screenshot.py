import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

# 配置
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

PAGES = [
    {"file": "方案1-轻量快用版.html", "name": "方案1-轻量快用版"},
    {"file": "方案2-专业工作台版.html", "name": "方案2-专业工作台版"},
    {"file": "方案3-沉浸式创作版.html", "name": "方案3-沉浸式创作版"},
]

VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080, "device_scale_factor": 1},
    "mobile": {"width": 390, "height": 844, "device_scale_factor": 2, "is_mobile": True, "has_touch": True},
}

async def take_screenshots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for page_info in PAGES:
            file_path = Path(__file__).parent / page_info["file"]
            url = file_path.as_uri()
            name = page_info["name"]

            print(f"正在截图: {name}")

            for device, vp in VIEWPORTS.items():
                page = await browser.new_page(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    device_scale_factor=vp["device_scale_factor"],
                    is_mobile=vp.get("is_mobile", False),
                    has_touch=vp.get("has_touch", False),
                )
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_timeout(1000)  # 等待页面完全渲染

                screenshot_path = SCREENSHOT_DIR / f"{name}-{device}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"  已保存: {screenshot_path.name}")

                await page.close()

        await browser.close()
    print("所有截图完成!")

if __name__ == "__main__":
    asyncio.run(take_screenshots())
