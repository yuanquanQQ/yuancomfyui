"""
Open a Chromium browser for manual RunningHub login.
Usage: python open_browser.py [--profile PROFILE_DIR]
"""
import argparse, json, os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from runninghub_client.browser import _launch_browser

parser = argparse.ArgumentParser()
parser.add_argument("--profile", default="./profiles/default", help="Profile directory for login state")
parser.add_argument("--auto", action="store_true", help="Wait for login and save automatically")
parser.add_argument("--timeout", type=int, default=600, help="Automatic login timeout in seconds")
args = parser.parse_args()

PROFILE_DIR = Path(args.profile)
PROFILE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PROFILE_DIR / "state.json"

RUNNINGHUB_URL = "https://www.runninghub.cn"

# Help the Playwright driver find installed browsers.
# In frozen mode prefer the bundled extraction; otherwise use the system cache.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "ms-playwright"
        if (bundled / "chromium-1228").is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        local = os.environ.get("LOCALAPPDATA", "")
        ms_dir = Path(local) / "ms-playwright"
        if ms_dir.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ms_dir)

playwright = sync_playwright().start()
launch_options = {
    "headless": False,
    "slow_mo": 100,
    "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
}
try:
    browser = _launch_browser(playwright, launch_options)
except Exception as exc:
    playwright.stop()
    if "Executable doesn't exist" in str(exc):
        print("[ERROR] Playwright Chromium 未安装，请执行: python -m playwright install chromium", file=sys.stderr)
        sys.exit(3)
    raise
context = browser.new_context(
    viewport={"width": 1280, "height": 900},
    # Web-triggered login always starts clean.  Otherwise a still-valid old
    # cookie would be detected immediately and the re-login window would close
    # before the user could switch or refresh the account.
    storage_state=None if args.auto else (str(STATE_FILE) if STATE_FILE.exists() else None),
)
page = context.new_page()

print(f"[OPEN] {RUNNINGHUB_URL}")
print("请在浏览器中手动登录 RunningHub，登录完成后按 Enter 关闭窗口。")
page.goto(RUNNINGHUB_URL, wait_until="domcontentloaded", timeout=60000)

login_detected = False
if args.auto:
    import time
    print(f"请在 {args.timeout} 秒内完成登录，检测到登录后会自动保存并关闭。")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        for cookie in context.cookies():
            if cookie.get("name") == "Rh-Accesstoken":
                expires = cookie.get("expires", -1)
                if not expires or expires < 0 or expires > time.time():
                    login_detected = True
                    break
        if login_detected:
            time.sleep(2)
            break
        time.sleep(1)
    if not login_detected:
        print("[ERROR] 登录超时，未检测到有效登录状态。", file=sys.stderr)
        browser.close()
        playwright.stop()
        sys.exit(2)
else:
    print("\n按 Enter 关闭浏览器...")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass

new_state = context.storage_state()
with open(STATE_FILE, "w", encoding="utf-8") as f:
    json.dump(new_state, f, ensure_ascii=False, indent=2)
print(f"[OK] 登录态已保存到 {STATE_FILE}")

browser.close()
playwright.stop()
print("[OK] 浏览器已关闭")
