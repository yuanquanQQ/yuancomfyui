"""Interactive RunningHub SMS login bridged through local HTTP IPC."""

import argparse
import re
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from runninghub_client.browser import _launch_browser


class LoginIpc:
    def __init__(self, base_url: str, session_id: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.http = requests.Session()
        self.headers = {"X-Login-Token": token}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}?session_id={self.session_id}"

    def status(self, stage: str, detail: str, error=None):
        response = self.http.post(
            self._url("/api/internal/login/status"),
            headers=self.headers,
            json={"stage": stage, "detail": detail, "error": error},
            timeout=2,
        )
        response.raise_for_status()

    def frame(self, png: bytes):
        response = self.http.post(
            self._url("/api/internal/login/frame"),
            headers={**self.headers, "Content-Type": "image/png"},
            data=png,
            timeout=2,
        )
        response.raise_for_status()

    def events(self) -> list[dict]:
        response = self.http.get(
            self._url("/api/internal/login/events"),
            headers=self.headers,
            timeout=1,
        )
        response.raise_for_status()
        return response.json().get("events", [])


def has_access_token(context):
    now = time.time()
    for cookie in context.cookies():
        if cookie.get("name") != "Rh-Accesstoken":
            continue
        expires = float(cookie.get("expires", -1) or -1)
        if expires <= 0 or expires > now:
            return True
    return False


def first_visible(locators, timeout=1200):
    """Return the first visible locator without assuming the current tab."""
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout):
                return locator.first
        except Exception:
            continue
    return None


def open_sms_login(page, phone):
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        page.wait_for_timeout(2500)

    login_button = first_visible([
        page.get_by_role("button", name="登 录", exact=True),
        page.get_by_role("button", name="登录", exact=True),
        page.locator("button").filter(has_text=re.compile(r"^\s*登\s*录\s*$")),
    ], timeout=3000)
    if login_button is None:
        raise RuntimeError("RunningHub 页面上未找到登录按钮")

    phone_input = page.get_by_placeholder(re.compile("请输入.*手机(号|号码)"))
    sms_entry_pattern = re.compile("(验证码|短信)" + r"\s*" + "登录")
    dialog_ready = False
    for _ in range(2):
        login_button.click(timeout=30000)
        try:
            page.wait_for_function(
                """() => document.body.innerText.includes('验证码登录')
                    || document.body.innerText.includes('短信登录')
                    || [...document.querySelectorAll('input')].some(el =>
                        (el.placeholder || '').includes('手机'))""",
                timeout=5000,
            )
            dialog_ready = True
            break
        except Exception:
            page.wait_for_timeout(1500)
    if not dialog_ready:
        raise RuntimeError("点击登录后弹窗未打开，请稍后重试")

    send_pattern = re.compile("获取" + r"\s*" + "验证码")
    send_button = first_visible([
        page.get_by_role("button", name=send_pattern),
        page.locator("button").filter(has_text=send_pattern),
        page.get_by_text("获取验证码", exact=True),
    ], timeout=800)
    if send_button is None:
        sms_switch = first_visible([
            page.get_by_text("验证码登录", exact=True),
            page.get_by_text("短信登录", exact=True),
            page.get_by_text(sms_entry_pattern),
            page.locator("button, a, span, div").filter(
                has_text=sms_entry_pattern
            ),
        ])
        if sms_switch is None:
            raise RuntimeError("登录弹窗已打开，但未找到短信登录入口")
        sms_switch.click(timeout=10000)
        send_button = first_visible([
            page.get_by_role("button", name=send_pattern),
            page.locator("button").filter(has_text=send_pattern),
            page.get_by_text("获取验证码", exact=True),
        ], timeout=5000)

    phone_input.wait_for(state="visible", timeout=10000)
    phone_input.fill(phone)
    if send_button is None:
        raise RuntimeError("未找到“获取验证码”按钮")
    send_button.click(timeout=15000)


def find_slider_region(page):
    """Return only a region that visibly contains the official slider text."""
    return page.evaluate("""() => {
        const visible = el => {
            const s = getComputedStyle(el), r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden'
                && Number(s.opacity || 1) > 0 && r.width >= 280 && r.height >= 180;
        };
        const candidates = [...document.querySelectorAll('div, section')]
            .filter(el => visible(el) && (el.innerText || '').includes('拖动滑块'));
        if (!candidates.length) return null;
        const target = candidates.sort((a, b) => {
            const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
            return ar.width * ar.height - br.width * br.height;
        })[0].getBoundingClientRect();
        const x = Math.max(0, target.left - 8);
        const y = Math.max(0, target.top - 8);
        const right = Math.min(innerWidth, target.right + 8);
        const bottom = Math.min(innerHeight, target.bottom + 8);
        return {x, y, width: right - x, height: bottom - y};
    }""")


def capture_slider(page):
    region = find_slider_region(page)
    if not region or region["width"] < 30 or region["height"] < 30:
        return None, None
    return page.screenshot(clip=region, type="png"), region


def save_failure_diagnostics(page, profile):
    try:
        page.screenshot(path=str(profile / "login_failure.png"), full_page=True)
        body = page.locator("body").inner_text(timeout=3000)
        (profile / "login_failure.txt").write_text(
            body[:12000], encoding="utf-8")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--ipc-token", required=True)
    parser.add_argument("--ipc-url", required=True)
    args = parser.parse_args()

    profile = Path(args.profile).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    state_path = profile / "state.json"
    ipc = LoginIpc(args.ipc_url, args.session_id, args.ipc_token)

    playwright = browser = context = page = None
    try:
        ipc.status("starting", "正在打开 RunningHub 短信登录")
        playwright = sync_playwright().start()
        browser = _launch_browser(playwright, {
            "headless": True,
            "slow_mo": 0,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=900,820",
            ],
        })
        context = browser.new_context(viewport={"width": 900, "height": 820})
        page = context.new_page()
        page.goto(
            "https://www.runninghub.cn", wait_until="domcontentloaded",
            timeout=60000,
        )
        open_sms_login(page, args.phone)

        # Do not advertise slider state until a strict slider-only frame exists.
        clip = first_png = None
        first_frame_deadline = min(
            time.time() + 20, time.time() + args.timeout)
        while time.time() < first_frame_deadline:
            first_png, clip = capture_slider(page)
            if first_png:
                break
            time.sleep(0.08)
        if not first_png:
            raise RuntimeError("官方滑块验证区域未出现，请重新发起登录")
        ipc.frame(first_png)
        ipc.status(
            "slider",
            "请在工作台内完成官方滑块验证，然后输入短信验证码",
        )

        deadline = time.time() + args.timeout
        submitted_code = None
        captcha_done = False
        missing_ticks = 0
        pointer_down = False
        last_capture = time.monotonic()
        last_captcha_check = 0.0

        while time.time() < deadline:
            if submitted_code and has_access_token(context):
                break

            try:
                events = ipc.events()
            except requests.RequestException as exc:
                raise RuntimeError("本机登录服务连接已中断") from exc

            for event in events:
                kind = event.get("type")
                if kind == "stop":
                    ipc.status("stopped", "登录已取消")
                    return
                if kind == "verify":
                    submitted_code = str(event.get("code", "")).strip()
                    try:
                        page.get_by_placeholder("请输入验证码").fill(
                            submitted_code)
                        page.get_by_role(
                            "button", name=re.compile("立即" + r"\s*" + "登录")
                        ).click()
                        captcha_done = True
                        ipc.status("verifying", "正在验证短信验证码")
                    except Exception as exc:
                        submitted_code = None
                        ipc.status(
                            "code_required", "验证码提交失败，请重试", str(exc))
                    continue
                if captcha_done or not clip or kind not in ("down", "move", "up"):
                    continue
                x = clip["x"] + float(event.get("x", 0)) * clip["width"]
                y = clip["y"] + float(event.get("y", 0)) * clip["height"]
                if kind == "down":
                    page.mouse.move(x, y)
                    page.mouse.down()
                    pointer_down = True
                elif kind == "move":
                    page.mouse.move(x, y)
                else:
                    page.mouse.move(x, y)
                    page.mouse.up()
                    pointer_down = False

            now = time.monotonic()
            if not captcha_done and not pointer_down and now - last_captcha_check >= 0.08:
                last_captcha_check = now
                region = find_slider_region(page)
                if region is None:
                    missing_ticks += 1
                    if missing_ticks >= 2:
                        captcha_done = True
                        ipc.status(
                            "code_required", "滑块验证已完成，请输入短信验证码")
                else:
                    missing_ticks = 0
                    clip = region

            # Screenshot only a freshly verified slider region. Once the text
            # disappears, captcha_done is permanent and no later page is sent.
            interval = 0.14 if pointer_down else 0.18
            if not captcha_done and now - last_capture >= interval:
                png, fresh_clip = capture_slider(page)
                if png and fresh_clip:
                    clip = fresh_clip
                    ipc.frame(png)
                last_capture = now

            if submitted_code:
                page.wait_for_timeout(350)
                if has_access_token(context):
                    break
                body = page.locator("body").inner_text(timeout=3000)
                if "验证码无效" in body or "验证码错误" in body:
                    submitted_code = None
                    ipc.status(
                        "code_required", "验证码无效，请重新输入")
            time.sleep(0.01)
        else:
            raise TimeoutError("登录等待超时，请重新发起登录")

        context.storage_state(path=str(state_path))
        ipc.status("completed", "RunningHub 登录成功")
    except Exception as exc:
        if page is not None:
            save_failure_diagnostics(page, profile)
        try:
            ipc.status("failed", "RunningHub 登录失败", str(exc))
        except Exception:
            pass
        raise
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
        ipc.http.close()


if __name__ == "__main__":
    main()
