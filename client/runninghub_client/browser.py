"""Generic browser automation for server-configured RunningHub workflows."""

import base64
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

from .workflow_specs import OutputSpec, WorkflowSpec

logger = logging.getLogger(__name__)

USER_DATA_DIR = Path("./profiles/default")

# Serialize upload + workflow-start across all BrowserRunner instances so
# only one task uploads files or clicks "Run" at a time, preventing
# RunningHub from being overwhelmed by concurrent uploads.
_upload_lock = threading.Lock()


def _ensure_playwright_driver():
    """Monkey-patch playwright's driver lookup to use bundled copy in frozen mode.

    ``playwright._impl._driver.compute_driver_executable()`` uses
    ``inspect.getfile(playwright)`` to locate node.exe and cli.js.  Under
    PyInstaller that may still resolve to the original system site-packages
    instead of ``sys._MEIPASS``.  We patch it early so both ``start()`` and
    ``setup_login()`` get the correct paths.
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = Path(sys._MEIPASS)
    driver_dir = meipass / "playwright" / "driver"
    node_exe = driver_dir / "node.exe"
    cli_js = driver_dir / "package" / "cli.js"
    if node_exe.is_file() and cli_js.is_file():
        os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(node_exe)
        try:
            import playwright._impl._driver as _pw_driver
            _pw_driver.compute_driver_executable = lambda: (str(node_exe), str(cli_js))
            logger.info("Patched playwright driver → %s", driver_dir)
        except Exception:
            logger.warning("Could not patch playwright driver")
    else:
        logger.warning("Bundled driver incomplete at %s (node=%s cli=%s)",
                       driver_dir,
                       "found" if node_exe.is_file() else "missing",
                       "found" if cli_js.is_file() else "missing")


def _ensure_playwright_browsers_path():
    """Set PLAYWRIGHT_BROWSERS_PATH so the driver finds installed browsers.

    In frozen (PyInstaller) mode the Chromium browser is bundled inside the
    EXE and extracted to ``sys._MEIPASS``.  In dev mode we fall back to the
    system-wide Playwright cache at ``%LOCALAPPDATA%\\ms-playwright``.
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return  # already explicitly configured — don't override

    # Frozen EXE: prefer the bundled browsers extracted from the EXE
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "ms-playwright"
        if (any(bundled.glob("chromium-*")) or
                any(bundled.glob("chromium_headless_shell-*"))):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
            logger.info("PLAYWRIGHT_BROWSERS_PATH → %s (bundled)", bundled)
            return
        logger.warning("Bundled browsers not found at %s", bundled)

    # Dev mode / fallback: use the system Playwright cache
    local = os.environ.get("LOCALAPPDATA", "")
    default_cache = Path(local) / "ms-playwright"
    if default_cache.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default_cache)
        logger.info("PLAYWRIGHT_BROWSERS_PATH → %s (system)", default_cache)
    else:
        logger.warning("ms-playwright not found at %s; chromium.launch() may fail", default_cache)


def _launch_browser(playwright, launch_options):
    """Launch bundled Chromium, falling back to the installed Microsoft Edge."""
    try:
        return playwright.chromium.launch(**launch_options)
    except Exception as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        logger.warning("Playwright Chromium is missing; trying Microsoft Edge")
        try:
            return playwright.chromium.launch(channel="msedge", **launch_options)
        except Exception as edge_exc:
            raise RuntimeError(
                "No supported browser was found. Install Microsoft Edge or run "
                "setup.bat to download Playwright Chromium."
            ) from edge_exc


class BrowserRunner:
    """Playwright-based browser automation for RunningHub workflow."""

    TASK_FAILURE_GRACE_SECONDS = 60

    def __init__(self, *, headless=True, slow_mo=300, user_data_dir=None,
                 workflow_url=None, workflow_id=None, post_id=None,
                 workflow_spec: Optional[WorkflowSpec] = None,
                 progress_callback: Optional[Callable[[str, str], None]] = None):
        self.headless = headless
        self.slow_mo = slow_mo
        self.user_data_dir = Path(user_data_dir or USER_DATA_DIR)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_url = workflow_url
        self.workflow_id = workflow_id
        self.post_id = post_id
        self.workflow_spec = workflow_spec
        self.progress_callback = progress_callback
        self._browser = None
        self._context = None
        self._page = None
        self._comfy = None
        self._playwright = None
        # Screenshot IPC: HTTP handler sets screenshot_requested, polling loop
        # takes the shot and sets screenshot_ready with data or error.
        self.screenshot_requested = threading.Event()
        self.screenshot_ready = threading.Event()
        self.screenshot_data: Optional[bytes] = None
        self.screenshot_error: Optional[str] = None
        self._screenshot_in_progress = False
        self.cancel_requested = threading.Event()
        self._cloud_cancel_attempted = False
        self._cloud_cancel_result = None

    def request_cancel(self):
        """Ask the owning worker thread to stop at its next safe checkpoint."""
        self.cancel_requested.set()
        if not self.screenshot_ready.is_set():
            self.screenshot_error = "Task was cancelled"
            self.screenshot_ready.set()

    def _raise_if_cancelled(self):
        if self.cancel_requested.is_set():
            # request_cancel() is called by the HTTP handler thread, while
            # Playwright's sync API may only be used by this worker thread.
            # Perform the RunningHub-side cancellation here, at the next safe
            # worker checkpoint, before unwinding and closing the browser.
            if self._page is not None and not self._cloud_cancel_attempted:
                self._cloud_cancel_attempted = True
                try:
                    self._report_progress(
                        "cancelling", "正在取消 RunningHub 云端任务"
                    )
                    self._cloud_cancel_result = (
                        self._cancel_runninghub_task_from_sidebar()
                    )
                except Exception as exc:
                    self._cloud_cancel_result = {
                        "clicked": False, "error": str(exc)[:300],
                    }
                    logger.warning(
                        "RunningHub cloud cancellation failed: %s", exc,
                    )
            raise RuntimeError("任务已取消")

    def _cancel_runninghub_task_from_sidebar(self):
        """Cancel the newest active task in RunningHub's right sidebar.

        The local API handler only sets ``cancel_requested`` because
        Playwright is thread-bound. This method runs in the browser worker and
        clicks the visible Cancel action belonging to the newest generating or
        queued task, then accepts a cancellation confirmation dialog if one is
        shown.
        """
        if not self._page:
            return {"clicked": False, "reason": "page_not_available"}

        result = self._page.evaluate(
            r"""() => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };
                const exactCancel = /^(取消|Cancel)$/i;
                const activeText = /(生成中|生产中|排队中|Generating|Running|Queued)/i;
                const candidates = [];
                for (const el of document.querySelectorAll(
                    'button, a, [role="button"], span, div'
                )) {
                    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!exactCancel.test(text) || !visible(el)) continue;
                    const clickable = el.closest('button, a, [role="button"]') || el;
                    if (!visible(clickable) || clickable.disabled) continue;
                    const rect = clickable.getBoundingClientRect();
                    let ancestor = clickable;
                    let card = null;
                    for (let depth = 0; ancestor && depth < 10; depth++) {
                        const ancestorText = (ancestor.textContent || '')
                            .replace(/\s+/g, ' ').trim();
                        if (activeText.test(ancestorText)
                                && ancestorText.length < 1500) {
                            card = ancestor;
                            break;
                        }
                        ancestor = ancestor.parentElement;
                    }
                    const cardText = card
                        ? (card.textContent || '').replace(/\s+/g, ' ').trim()
                        : '';
                    // Prefer a cancel action inside an active task card on the
                    // right side. The topmost such card is RunningHub's newest
                    // task; older failed history entries appear below it.
                    let score = rect.top;
                    if (rect.left > window.innerWidth * 0.60) score -= 10000;
                    if (card && activeText.test(cardText)) score -= 20000;
                    candidates.push({clickable, cardText, rect, score});
                }
                candidates.sort((a, b) => a.score - b.score);
                const target = candidates[0];
                if (!target) {
                    return {clicked: false, reason: 'active_cancel_not_found'};
                }
                target.clickable.click();
                return {
                    clicked: true,
                    text: (target.clickable.textContent || '').trim(),
                    cardText: target.cardText.slice(0, 500),
                    position: {
                        left: Math.round(target.rect.left),
                        top: Math.round(target.rect.top),
                    },
                };
            }"""
        )
        if not isinstance(result, dict) or not result.get("clicked"):
            logger.info("RunningHub active task cancel not found: %s", result)
            return result or {
                "clicked": False, "reason": "active_cancel_not_found",
            }

        logger.info("Clicked RunningHub task Cancel action: %s", result)
        self._page.wait_for_timeout(800)

        confirmation = self._page.evaluate(
            r"""() => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };
                for (const dialog of document.querySelectorAll(
                    '[role="dialog"], [role="alertdialog"], .ant-modal-content, '
                    + '.p-dialog, [class*="modal"], [class*="dialog"]'
                )) {
                    if (!visible(dialog)) continue;
                    const dialogText = (dialog.textContent || '')
                        .replace(/\s+/g, ' ').trim();
                    if (!/(取消|cancel|停止|终止)/i.test(dialogText)) continue;
                    for (const el of dialog.querySelectorAll(
                        'button, a, [role="button"]'
                    )) {
                        if (!visible(el) || el.disabled) continue;
                        const text = (el.textContent || '')
                            .replace(/\s+/g, ' ').trim();
                        if (/^(确认取消|确定|确认|是|Yes|Confirm)$/i.test(text)) {
                            el.click();
                            return {clicked: true, text};
                        }
                    }
                }
                return {clicked: false};
            }"""
        )
        if isinstance(confirmation, dict) and confirmation.get("clicked"):
            logger.info(
                "Confirmed RunningHub task cancellation: %s", confirmation,
            )
            self._page.wait_for_timeout(800)
        result["confirmation"] = confirmation
        return result

    def _report_progress(self, stage, detail):
        logger.info("Stage %s: %s", stage, detail)
        if self.progress_callback:
            try:
                self.progress_callback(stage, detail)
            except Exception as exc:
                logger.warning("Progress callback failed: %s", exc)

    def _require_workflow_spec(self) -> WorkflowSpec:
        if self.workflow_spec is None:
            raise ValueError("缺少服务器工作流执行配置")
        return self.workflow_spec

    def _write_download_diagnostic(self, payload):
        """Persist the last output-node inspection for post-run debugging."""
        try:
            path = self.user_data_dir / "download_diagnostic.json"
            data = {
                "written_at": time.time(),
                "workflow_id": self.workflow_id,
                "post_id": self.post_id,
                "workflow_name": getattr(self.workflow_spec, "name", None),
                **(payload if isinstance(payload, dict) else {"detail": payload}),
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Download diagnostic write failed: %s", exc)

    def _candidate_workflow_urls(self):
        if self.workflow_url:
            return [self.workflow_url]
        if not self.workflow_id:
            raise ValueError("workflow_url or workflow_id is required for browser mode")
        return [
            f"https://www.runninghub.cn/#/workflow/{self.workflow_id}?source=workspace",
            f"https://www.runninghub.cn/#/workflow/{self.workflow_id}",
            f"https://www.runninghub.cn/workflow/{self.workflow_id}?source=workspace",
            f"https://www.runninghub.cn/workflow/{self.workflow_id}",
        ]

    def _open_post_workflow(self):
        """Open a stable RunningHub post and enter its current workflow."""
        self._raise_if_cancelled()
        url = f"https://www.runninghub.cn/post/{self.post_id}"
        logger.info("Navigating to post %s", url)
        last_error = None
        for navigation_attempt in range(1, 4):
            self._raise_if_cancelled()
            try:
                self._page.goto(
                    url, wait_until="domcontentloaded", timeout=60000,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Post navigation failed (%d/3): %s",
                    navigation_attempt, str(exc)[:200],
                )
                if navigation_attempt < 3:
                    self._page.wait_for_timeout(1500 * navigation_attempt)
                continue

            run_button = self._page.get_by_text("运行工作流", exact=True).last
            try:
                run_button.wait_for(state="visible", timeout=30000)
            except Exception as exc:
                body = self._page.locator("body").inner_text(timeout=5000)
                if any(marker in body for marker in (
                        "验证码登录", "扫码登录", "密码登录")):
                    raise RuntimeError("账号登录状态已失效，请重新登录") from exc
                last_error = exc
                logger.info(
                    "Post page did not expose the run button (%d/3); "
                    "reloading the post", navigation_attempt,
                )
                continue

            original_page = self._page
            for click_attempt in range(1, 3):
                self._raise_if_cancelled()
                self._dismiss_rife_popup()
                self._dismiss_popups()
                pages_before = set(self._context.pages)
                try:
                    run_button.click(timeout=15000)
                    self._page.wait_for_timeout(2500)
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Post run action failed (%d/2 in navigation %d/3): %s",
                        click_attempt, navigation_attempt, str(exc)[:160],
                    )
                    continue

                new_pages = [
                    page for page in self._context.pages
                    if page not in pages_before
                ]
                # RunningHub can both navigate the current (left) page and
                # open a duplicate on its right. Only select a page after its
                # URL has actually entered /workflow/; an about:blank popup is
                # not proof that the action succeeded.
                candidates = [original_page, *new_pages]
                workflow_pages = [
                    page for page in candidates
                    if "/workflow/" in (page.url or "")
                    or "#/workflow/" in (page.url or "")
                ]
                if not workflow_pages:
                    for candidate in new_pages:
                        try:
                            candidate.wait_for_load_state(
                                "domcontentloaded", timeout=15000,
                            )
                        except Exception:
                            pass
                        if ("/workflow/" in (candidate.url or "")
                                or "#/workflow/" in (candidate.url or "")):
                            workflow_pages.append(candidate)
                            break
                if workflow_pages:
                    self._page = workflow_pages[0]
                    ordered_pages = list(self._context.pages)
                    logger.info(
                        "Selected left workflow page %d/%d: %s",
                        ordered_pages.index(self._page) + 1,
                        len(ordered_pages), self._page.url,
                    )
                    self._comfy = self._find_comfy_frame()
                    logger.info("Workflow loaded from post %s", self.post_id)
                    return

                last_error = RuntimeError(
                    "点击“运行工作流”后页面没有进入工作流"
                )
                logger.info(
                    "Post run action did not navigate (%d/2 in navigation "
                    "%d/3); dismissing overlays and retrying",
                    click_attempt, navigation_attempt,
                )

            # A click-only retry cannot recover a stale or half-loaded Vue
            # page. Restore the post page and repeat the complete navigation.
            self._page = original_page
            if navigation_attempt < 3:
                self._page.wait_for_timeout(1500 * navigation_attempt)

        if isinstance(last_error, RuntimeError):
            raise last_error
        if last_error is not None:
            raise RuntimeError("RunningHub Post 页面网络连接失败，请稍后重试") \
                from last_error
        raise RuntimeError("点击“运行工作流”后页面没有进入工作流")

    # =================================================================
    # Setup / Teardown
    # =================================================================

    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            # In frozen mode, hint about bundled dependencies
            if getattr(sys, "frozen", False):
                raise RuntimeError(
                    f"Playwright 导入失败: {exc}. "
                    f"当前运行目录: {getattr(sys, '_MEIPASS', 'N/A')}. "
                    f"请确认打包时包含了 playwright 及其依赖 (greenlet)."
                ) from exc
            raise RuntimeError(
                "Playwright 未安装。请先执行: pip install -r requirements.txt "
                "然后执行: python -m playwright install chromium"
            ) from exc

        # In frozen mode, patch playwright's driver lookup to use the
        # bundled node.exe + cli.js instead of trying the system path.
        _ensure_playwright_driver()
        _ensure_playwright_browsers_path()

        self._playwright = sync_playwright().start()
        self._raise_if_cancelled()
        launch_args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        if self.headless:
            launch_args.extend([
                "--headless=new",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--disable-features=IsolateOrigins,site-per-process",
            ])
        launch_options = {
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "args": launch_args,
        }
        try:
            self._browser = _launch_browser(self._playwright, launch_options)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Playwright Chromium 未安装。请执行: python -m playwright install chromium"
                ) from exc
            raise
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        )
        # Cloud desktops and cross-region links often have high latency. Keep
        # individual UI actions bounded, but give navigation and media
        # transfers enough time to survive temporary packet loss.
        self._context.set_default_timeout(45000)
        self._context.set_default_navigation_timeout(90000)
        # Inject saved session state via explicit add_cookies() instead of the
        # storage_state= kwarg.  The kwarg path silently drops cookies in some
        # PyInstaller-bundled runtimes (state.json looks correct on disk, but
        # the new context reports no cookies → "login expired" on first task).
        # localStorage entries are restored after first navigation.
        self._inject_saved_state()
        self._page = self._context.new_page()
        self._raise_if_cancelled()

        # Check login before navigating — if the session is expired,
        # RunningHub shows a login page without the ComfyUI iframe.
        if not self.ensure_logged_in():
            raise RuntimeError("账号登录已失效，请重新登录")

        if self.post_id:
            self._open_post_workflow()
            return

        last_error = None

        for url in self._candidate_workflow_urls():
            self._raise_if_cancelled()
            try:
                logger.info("Navigating to %s", url)
                self._page.goto(url, wait_until="networkidle", timeout=60000)
                self._page.wait_for_timeout(3000)
                self._comfy = self._find_comfy_frame()
                logger.info("Workflow loaded via %s", url)
                return
            except Exception as exc:
                last_error = exc
                logger.warning("Workflow open failed for %s: %s", url, str(exc)[:200])

        raise RuntimeError(f"Failed to open workflow page: {last_error}") from last_error

    def _find_comfy_frame(self):
        logger.info("Total frames: %d", len(self._page.frames))
        for i, f in enumerate(self._page.frames):
            logger.info("  Frame #%d: url=%s", i, (f.url or "(empty)")[:120])

        for attempt in range(30):
            self._raise_if_cancelled()
            elapsed = (attempt + 1) * 2
            for frame in self._page.frames:
                try:
                    has_app = frame.evaluate("() => !!(window.app && window.app.graph)")
                    if has_app:
                        n = frame.evaluate("() => (window.app.graph._nodes || []).length")
                        if n > 0:
                            ftype = "main" if frame == self._page.main_frame else "iframe"
                            logger.info("ComfyUI ready in %s with %d nodes (%ds)", ftype, n, elapsed)
                            return frame
                except Exception as exc:
                    logger.debug("Frame eval fail (%ds): %s", elapsed, str(exc)[:100])
            logger.debug("Waiting for ComfyUI... (%ds)", elapsed)
            self._page.wait_for_timeout(2000)

        # Diagnostic: dump page title, body text, cookies, and save a screenshot
        try:
            title = self._page.evaluate("() => document.title || ''")
            body = self._page.evaluate(
                "() => (document.body ? document.body.innerText : '').slice(0, 500)")
            logger.error(
                "ComfyUI not ready after 60s. "
                "Page title: %r, body preview: %r", title, body)
            # Log cookie names to verify login state
            cookies = self._context.cookies()
            cookie_names = [c.get("name", "") for c in cookies if c.get("name")]
            logger.error("Cookies available: %s", cookie_names)
            # Save screenshot for debugging
            diag_dir = self.user_data_dir
            diag_dir.mkdir(parents=True, exist_ok=True)
            ss_path = diag_dir / "iframe_failure.png"
            self._page.screenshot(path=str(ss_path), type="png", full_page=False)
            logger.error("Failure screenshot saved to %s", ss_path)
        except Exception as diag_exc:
            logger.error("Diagnostic save failed: %s", diag_exc)
        raise RuntimeError("ComfyUI iframe not ready after 60s")

    def stop(self):
        keep_open_seconds = 0
        if not self.headless:
            try:
                keep_open_seconds = max(
                    0, int(os.environ.get("YUNCOMFYUI_KEEP_BROWSER_SECONDS", "0"))
                )
            except (TypeError, ValueError):
                keep_open_seconds = 0
        if (keep_open_seconds and not self.cancel_requested.is_set()
                and (self._browser or self._page)):
            logger.info(
                "Keeping headed browser open for %d seconds for inspection.",
                keep_open_seconds,
            )
            try:
                time.sleep(keep_open_seconds)
            except Exception:
                pass
        # Release any HTTP handler thread waiting on a screenshot
        if not self.screenshot_ready.is_set():
            self.screenshot_error = "Browser has been stopped"
            self.screenshot_ready.set()
        playwright = self._playwright
        if self._context:
            self._save_state()
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        # Every BrowserRunner calls sync_playwright().start() in start(), so it
        # owns a separate driver/event loop.  It must stop that driver on the
        # same worker thread; otherwise ThreadPoolExecutor reuses the thread
        # with a live sync loop and the next task fails with:
        # "Playwright Sync API inside the asyncio loop".
        if playwright:
            try:
                playwright.stop()
            except Exception as exc:
                logger.warning("Playwright driver stop failed: %s", exc)
        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None
        self._comfy = None
        logger.info("Browser closed.")

    def close(self):
        """Backward-compatible alias used by older callers."""
        self.stop()

    def take_screenshot(self) -> bytes:
        """Take a PNG screenshot of the current page.

        MUST be called from the browser's own thread (inside the polling
        loop in ``run()``).  Playwright's sync API is not thread-safe.
        """
        if not self._page:
            raise RuntimeError("Browser page is not available (task may have ended)")
        return self._page.screenshot(type="png", full_page=False)

    def _load_state(self):
        f = self.user_data_dir / "state.json"
        if f.exists():
            try:
                return json.loads(f.read_text("utf-8"))
            except Exception:
                pass
        return None

    def _inject_saved_state(self):
        """Restore cookies + localStorage from state.json into a fresh context.

        ``BrowserContext.add_cookies()`` accepts the same list shape that
        ``storage_state()`` emits, so we hand the saved ``cookies`` array
        straight through.  localStorage is restored via JS once the first
        page has navigated (storage is origin-scoped, so we cannot
        populate it before any navigation has happened).  ``add_init_script``
        stores the pending items, and the first page navigation then runs
        the script which writes them into the matching origin.
        """
        state = self._load_state()
        if not state:
            return
        cookies = state.get("cookies") or []
        if cookies:
            try:
                # Playwright requires cookie.expires to be float seconds; for
                # session cookies (expires == -1) Chromium accepts -1 as
                # "session cookie".  Strip any non-standard keys defensively.
                cleaned = []
                for c in cookies:
                    if not isinstance(c, dict) or not c.get("name"):
                        continue
                    item = {
                        "name": c["name"],
                        "value": c.get("value", ""),
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                    }
                    try:
                        item["expires"] = float(c.get("expires", -1))
                    except (TypeError, ValueError):
                        item["expires"] = -1
                    if "url" in c and c["url"]:
                        item["url"] = c["url"]
                    cleaned.append(item)
                self._context.add_cookies(cleaned)
                logger.info("Restored %d cookies from state.json", len(cleaned))
            except Exception as exc:
                logger.warning("add_cookies() failed: %s", exc)

        # Defer localStorage restoration until first navigation.
        origins = state.get("origins") or []
        if origins:
            pending = []
            for entry in origins:
                origin = entry.get("origin")
                ls = entry.get("localStorage") or []
                if not origin or not ls:
                    continue
                pending.append({"origin": origin, "entries": ls})
            if pending:
                payload = json.dumps(pending, ensure_ascii=False)
                script = (
                    "(function(items){"
                    "  try{"
                    "    for(var i=0;i<items.length;i++){"
                    "      var o=items[i].origin,e=items[i].entries||[];"
                    "      if(location.origin!==o)continue;"
                    "      for(var j=0;j<e.length;j++){"
                    "        try{localStorage.setItem(e[j].name,e[j].value);}catch(_){}"
                    "      }"
                    "    }"
                    "  }catch(_){}"
                    "})(window.__rh_restore_payload||[]);"
                )
                # Stash the payload and run via add_init_script after the
                # first navigation.  Easiest approach: stringify into the
                # script itself (escaped) so it runs on the very first nav.
                safe = json.dumps(payload)  # double-encode to embed as string
                init = (
                    "window.__rh_restore_payload = JSON.parse(" + safe + ");"
                    + script
                )
                try:
                    self._context.add_init_script(init)
                except Exception as exc:
                    logger.warning("add_init_script failed: %s", exc)

    def save_state(self):
        """Public method: persist current browser storage state to disk."""
        self._save_state()

    def _save_state(self):
        try:
            if not self._context:
                logger.warning("Cannot save state: browser context not initialized")
                return
            s = self._context.storage_state()
            state_file = self.user_data_dir / "state.json"
            temp_file = state_file.with_name(
                f".{state_file.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            temp_file.write_text(
                json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
            os.replace(temp_file, state_file)
            logger.info("State saved to %s (%d bytes)", state_file, state_file.stat().st_size)
        except Exception as exc:
            logger.warning("Save state failed: %s", exc)

    # =================================================================
    # Login
    # =================================================================

    def ensure_logged_in(self, timeout=120):
        """Check if we're logged into RunningHub.
        Uses cookie-based detection (Rh-Accesstoken) — DOM selectors
        have false positives on RunningHub's UI."""
        logger.info("Checking login...")

        def valid_access_token(cookie):
            if cookie.get("name") != "Rh-Accesstoken":
                return False
            try:
                expires = float(cookie.get("expires", -1))
            except (TypeError, ValueError):
                expires = -1
            return expires <= 0 or expires > time.time()

        # Quick check: do we already have a non-expired auth cookie?
        try:
            for c in self._context.cookies():
                if valid_access_token(c):
                    logger.info("Already logged in (valid Rh-Accesstoken cookie found).")
                    return True
        except Exception:
            pass

        logger.info("Not logged in — waiting for manual login (timeout=%ds)...", timeout)
        start = time.time()
        while time.time() - start < timeout:
            self._raise_if_cancelled()
            try:
                for c in self._context.cookies():
                    if valid_access_token(c):
                        logger.info("Login detected (Rh-Accesstoken cookie appeared)!")
                        self._save_state()
                        return True
            except Exception:
                pass
            time.sleep(2)

        logger.warning("Login not detected within %ds — session may be expired. "
                       "Please re-login via the account management page.", timeout)
        return False

    # =================================================================
    # File Upload
    # =================================================================

    def upload_inputs(self, inputs):
        """Upload logical inputs according to the selected workflow spec."""
        uploads = self.workflow_spec.resolve_uploads(inputs)
        total = len(uploads)
        for index, (upload, path) in enumerate(uploads, 1):
            self._report_progress(
                "uploading", f"正在上传{upload.label}（{index}/{total}）"
            )
            logger.info("=== Upload %s -> node %s ===", upload.label, upload.node_id)
            self._upload_one(
                upload.node_id,
                upload.button_widget,
                str(Path(path).absolute()),
                file_widget=upload.file_widget,
            )

    def set_text_inputs(self, inputs):
        """Set configured text widgets before submitting the workflow."""
        for text_input, value in self.workflow_spec.resolve_texts(inputs):
            self._report_progress(
                "configuring", f"正在填写{text_input.label}"
            )
            result = self._comfy.evaluate(
                """({nodeId, widgetName, value}) => {
                    const node = app.graph.getNodeById(Number(nodeId));
                    if (!node) return {state: 'node_not_found'};
                    const widget = (node.widgets || []).find(
                        item => item.name === widgetName
                    );
                    if (!widget) {
                        return {
                            state: 'widget_not_found',
                            available: (node.widgets || []).map(item => item.name),
                        };
                    }
                    widget.value = value;
                    if (typeof widget.callback === 'function') {
                        widget.callback(value, app.canvas, node);
                    }
                    if (node.onWidgetChanged) {
                        node.onWidgetChanged(widgetName, value, null, widget);
                    }
                    app.graph.setDirtyCanvas(true, true);
                    return {state: 'updated', length: value.length};
                }""",
                {
                    "nodeId": text_input.node_id,
                    "widgetName": text_input.widget,
                    "value": value,
                },
            )
            if result.get("state") != "updated":
                raise RuntimeError(
                    f"Text input node {text_input.node_id} update failed: {result}"
                )
            logger.info(
                "Text input %s -> node %s widget %s (%d chars)",
                text_input.label, text_input.node_id, text_input.widget, len(value),
            )

    def set_widget_inputs(self, inputs):
        """Set configured boolean/value widgets before any file upload."""
        for widget_input, value in self.workflow_spec.resolve_widgets(inputs):
            self._report_progress(
                "configuring", f"正在设置{widget_input.label}"
            )
            if widget_input.interaction == "rgthree_toggle":
                result = self._comfy.evaluate(
                    """async ({nodeId, widgetName, desired}) => {
                        const node = app.graph.getNodeById(Number(nodeId));
                        if (!node) return {state: 'node_not_found'};
                        const widget = (node.widgets || []).find(
                            item => item.name === widgetName
                        );
                        if (!widget) {
                            return {state: 'widget_not_found', available:
                                (node.widgets || []).map(item => item.name)};
                        }
                        const current = Boolean(
                            widget.value && typeof widget.value === 'object'
                                ? widget.value.toggled : widget.toggled
                        );
                        if (current === Boolean(desired)) {
                            return {state: 'unchanged', current};
                        }
                        if (typeof widget.mouse !== 'function') {
                            return {state: 'widget_not_clickable'};
                        }
                        // Click the circle immediately to the right of yes/no.
                        // The custom widget owns this pointer handler; using it
                        // avoids brittle DOM selectors for a canvas-only node.
                        const height = Number(widget.computedHeight || 24);
                        const y = Number(widget.y ?? widget.last_y ?? 26)
                            + height / 2;
                        const x = Number(node.size[0]) - 59;
                        widget.mouse({type: 'pointerdown'}, [x, y], node);
                        await new Promise(resolve => setTimeout(resolve, 80));
                        const updated = Boolean(
                            widget.value && typeof widget.value === 'object'
                                ? widget.value.toggled : widget.toggled
                        );
                        app.graph.setDirtyCanvas(true, true);
                        return {state: updated === Boolean(desired)
                            ? 'updated' : 'toggle_not_applied',
                            previous: current, current: updated};
                    }""",
                    {
                        "nodeId": widget_input.node_id,
                        "widgetName": widget_input.widget,
                        "desired": bool(value),
                    },
                )
                if result.get("state") not in {"updated", "unchanged"}:
                    raise RuntimeError(
                        f"Widget input node {widget_input.node_id} click failed: "
                        f"{result}"
                    )
                logger.info(
                    "Widget input %s -> node %s %s (current=%s)",
                    widget_input.label, widget_input.node_id,
                    "clicked" if result.get("state") == "updated"
                    else "already matched",
                    result.get("current"),
                )
                continue

            result = self._comfy.evaluate(
                """({nodeId, widgetName, value}) => {
                    const node = app.graph.getNodeById(Number(nodeId));
                    if (!node) return {state: 'node_not_found'};
                    const widgets = node.widgets || [];
                    const normalize = name => String(name || '')
                        .trim().toLocaleLowerCase();
                    let widget = widgets.find(item => item.name === widgetName);
                    if (!widget) {
                        const wanted = normalize(widgetName);
                        widget = widgets.find(item => normalize(item.name) === wanted);
                    }
                    if (!widget) {
                        return {
                            state: 'widget_not_found',
                            available: widgets.map(item => item.name),
                        };
                    }
                    const previous = widget.value;
                    widget.value = value;
                    if (typeof widget.callback === 'function') {
                        widget.callback(value, app.canvas, node);
                    }
                    if (node.onWidgetChanged) {
                        node.onWidgetChanged(widget.name, value, previous, widget);
                    }
                    if (app.graph.afterChange) app.graph.afterChange();
                    app.graph.setDirtyCanvas(true, true);
                    return {
                        state: 'updated', widget: widget.name,
                        previous, value: widget.value,
                    };
                }""",
                {
                    "nodeId": widget_input.node_id,
                    "widgetName": widget_input.widget,
                    "value": value,
                },
            )
            if result.get("state") != "updated":
                raise RuntimeError(
                    f"Widget input node {widget_input.node_id} update failed: "
                    f"{result}"
                )
            logger.info(
                "Widget input %s -> node %s widget %s = %r",
                widget_input.label, widget_input.node_id,
                result.get("widget") or widget_input.widget, value,
            )

    def set_node_modes(self):
        """Apply fixed ComfyUI execution modes configured by the server."""
        for node_mode in self.workflow_spec.node_modes:
            self._report_progress(
                "configuring", f"正在屏蔽{node_mode.label}"
            )
            result = self._comfy.evaluate(
                """({nodeId, mode}) => {
                    const node = app.graph.getNodeById(Number(nodeId));
                    if (!node) return {state: 'node_not_found'};
                    const previous = Number(node.mode ?? 0);
                    if (typeof node.changeMode === 'function') {
                        node.changeMode(mode);
                    } else {
                        node.mode = mode;
                    }
                    if (Number(node.mode) !== Number(mode)) {
                        node.mode = mode;
                    }
                    if (app.graph.afterChange) app.graph.afterChange();
                    app.graph.setDirtyCanvas(true, true);
                    return {
                        state: Number(node.mode) === Number(mode)
                            ? 'updated' : 'mode_not_applied',
                        previous, mode: Number(node.mode),
                    };
                }""",
                {"nodeId": node_mode.node_id, "mode": node_mode.mode},
            )
            if result.get("state") != "updated":
                raise RuntimeError(
                    f"Node {node_mode.node_id} mode update failed: {result}"
                )
            logger.info(
                "Node mode %s -> node %s = %d (previous=%s)",
                node_mode.label, node_mode.node_id, node_mode.mode,
                result.get("previous"),
            )

    def upload_files(self, video_path, model_image_path, clothing_image_path=None):
        """Backward-compatible wrapper for the original workflow."""
        self.upload_inputs({
            "video": video_path,
            "model": model_image_path,
            "clothing": clothing_image_path,
        })

    def _upload_one(self, node_id, widget_name, file_path, file_widget=None):
        """Upload file to node.

        Approach: click widget (registers ComfyUI's onchange handler on file input)
        → dismiss "Unable to find workflow" popup → click file input (opens native
        file dialog) → file_chooser intercept → ComfyUI's handler uploads the file.

        Fallback: Playwright APIRequestContext upload → widget.callback(filename).
        """
        fp = Path(file_path)
        logger.info("  Upload: node=%s widget=%r file=%s (%d bytes)",
                    node_id, widget_name, fp.name, fp.stat().st_size)

        file_widget = file_widget or (
            "video" if widget_name == "choose video to upload" else "image"
        )

        # ---- Snapshot BEFORE ----
        before = self._read_upload_widget(node_id, file_widget)
        logger.info("  Before: %s", json.dumps(before, ensure_ascii=False))

        # Videos can take much longer than the old fixed three-second wait.
        # Upload them through the HTTP endpoint first so returning from this
        # method means the server really received the complete file. The UI
        # chooser remains a fallback for accounts where that endpoint changes.
        direct_upload = None
        if file_widget == "video":
            try:
                logger.info("  [C] Verified direct video upload...")
                direct_upload = self._upload_via_fetch_and_callback(
                    node_id, widget_name, file_widget, file_path,
                )
                logger.info("  [C] Video upload confirmed: %s", direct_upload)
            except Exception as direct_exc:
                logger.warning(
                    "  [C] Direct video upload failed (%s); using UI chooser",
                    str(direct_exc)[:120],
                )

        if direct_upload is None:
            try:
                self._upload_via_ui_chooser(node_id, widget_name, file_path)
            except Exception as ui_exc:
                logger.info(
                    "  UI upload failed (%s), trying verified direct upload...",
                    str(ui_exc)[:120],
                )
                self._dismiss_popups()
                try:
                    direct_upload = self._upload_via_fetch_and_callback(
                        node_id, widget_name, file_widget, file_path,
                    )
                except Exception as direct_exc:
                    logger.error("  Direct upload failed: %s", direct_exc)
                    raise RuntimeError(
                        f"All upload strategies failed for node {node_id}"
                    ) from direct_exc

        # ---- Verify ----
        after = self._read_upload_widget(node_id, file_widget)
        logger.info("  After: %s", json.dumps(after, ensure_ascii=False))
        old_v = before.get("fileValue", "")
        new_v = after.get("fileValue", "")
        invalid_values = ("", "N/A", "undefined", "null", "none")
        if new_v in invalid_values:
            raise RuntimeError(f"上传后节点 {node_id} 没有有效文件值")
        if old_v == new_v:
            if direct_upload is None:
                # Never silently accept an unchanged value. This was the cause
                # of node 214 continuing to use its old video.
                logger.warning(
                    "  Node %s value did not change after UI upload; forcing "
                    "a verified direct upload", node_id,
                )
                direct_upload = self._upload_via_fetch_and_callback(
                    node_id, widget_name, file_widget, file_path,
                )
                after = self._read_upload_widget(node_id, file_widget)
                new_v = after.get("fileValue", "")
            if direct_upload is None or new_v in invalid_values:
                raise RuntimeError(f"上传后节点 {node_id} 文件值未更新")
            logger.info(
                "  OK: node value repeated but server upload was confirmed: %s",
                new_v[:80],
            )
        else:
            logger.info("  OK: %s -> %s", old_v[:40], new_v[:40])

        self._dismiss_popups()

    def _read_upload_widget(self, node_id, file_widget):
        """Read a node file widget without guessing that a missing value is OK."""
        return self._comfy.evaluate(
            """({nodeId, widgetName}) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return {state: 'node_not_found', fileValue: 'N/A'};
                const normalize = value => String(value || '').trim().toLowerCase();
                const widgets = node.widgets || [];
                const widget = widgets.find(item => item.name === widgetName)
                    || widgets.find(item => normalize(item.name) === normalize(widgetName));
                if (!widget) return {
                    state: 'widget_not_found', fileValue: 'N/A',
                    available: widgets.map(item => item.name),
                };
                return {
                    state: 'found', widget: widget.name,
                    fileValue: String(widget.value || '').slice(0, 500),
                };
            }""",
            {"nodeId": str(node_id), "widgetName": file_widget},
        )

    def _upload_via_ui_chooser(self, node_id, widget_name, file_path):
        """Use ComfyUI's native upload chooser, with a DOM-input fallback."""
        fp = Path(file_path)
        try:
            logger.info("  [A] Widget callback + file chooser...")
            with self._page.expect_file_chooser(timeout=8000) as fc_info:
                trigger_result = self._trigger_widget_upload(node_id, widget_name)
            logger.info(
                "  [A] Trigger: %s", json.dumps(trigger_result, ensure_ascii=False)
            )
            fc_info.value.set_files(file_path)
            logger.info("  [A] File via chooser: %s", fp.name)
            self._comfy.wait_for_timeout(3000)
            self._dismiss_popups()
            return
        except Exception as exc:
            logger.info("  [A] Failed (%s), trying B...", str(exc)[:80])
            self._dismiss_popups()

        logger.info("  [B] Widget callback + set_input_files...")
        trigger_result = self._trigger_widget_upload(node_id, widget_name)
        logger.info(
            "  [B] Trigger: %s", json.dumps(trigger_result, ensure_ascii=False)
        )
        self._page.wait_for_timeout(1000)
        for _ in range(12):
            self._dismiss_popups()
            self._page.wait_for_timeout(250)
        used_selector = self._set_comfy_file_input(file_path)
        logger.info("  [B] File set: %s via %s", fp.name, used_selector)
        self._comfy.wait_for_timeout(3000)
        self._dismiss_popups()
        logger.info("  [B] OK")

    def _upload_via_fetch_and_callback(self, node_id, widget_name, file_widget,
                                       file_path):
        """Upload file via Playwright APIRequestContext (shares browser cookies),
        then call widget.callback(filename) to update node state."""
        fp = Path(file_path)
        suffix = fp.suffix.lower()
        is_video = suffix in (".mp4", ".mov", ".webm", ".avi", ".mkv")
        is_audio = suffix in (".mp3", ".wav", ".m4a", ".aac", ".flac")
        mime = (
            "video/mp4" if is_video
            else "audio/mpeg" if suffix == ".mp3"
            else "audio/wav" if suffix == ".wav"
            else "audio/mp4" if suffix == ".m4a"
            else "audio/aac" if suffix == ".aac"
            else "audio/flac" if suffix == ".flac"
            else "image/png"
        )
        if is_video:
            upload_targets = (("video", "/upload/video"), ("image", "/upload/image"))
        elif is_audio:
            upload_targets = (("audio", "/upload/audio"), ("image", "/upload/image"))
        else:
            upload_targets = (("image", "/upload/image"),)

        # Determine full URL (ComfyUI is in iframe on runninghub.cn)
        base = "https://www.runninghub.cn"

        raw = fp.read_bytes()
        data = None
        last_error = None

        # Use Playwright's APIRequestContext — shares cookies with browser
        for field_name, endpoint_path in upload_targets:
            endpoint = f"{base}{endpoint_path}"
            logger.info(
                "  Upload via APIRequest: %d bytes -> %s field=%s",
                len(raw), endpoint, field_name,
            )
            for request_attempt in range(1, 4):
                try:
                    response = self._page.request.post(
                        endpoint,
                        multipart={field_name: (fp.name, raw, mime)},
                        timeout=180000,
                    )
                    logger.info(
                        "  HTTP %d: %s", response.status,
                        response.text()[:200],
                    )
                    if response.status != 200:
                        raise RuntimeError(
                            f"Upload HTTP {response.status}: "
                            f"{response.text()[:200]}"
                        )
                    data = response.json()
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "  Upload request failed (%d/3): %s",
                        request_attempt, str(exc)[:120],
                    )
                    if request_attempt < 3:
                        self._page.wait_for_timeout(1000 * request_attempt)
            if data is not None:
                break
        if data is None:
            raise RuntimeError("All direct upload endpoints failed") from last_error

        if isinstance(data, str):
            fname = data
            subfolder = ""
        elif isinstance(data, dict):
            fname = data.get("name") or data.get("filename") or data.get("file") or ""
            subfolder = str(data.get("subfolder") or "").strip("/\\")
        else:
            fname = ""
            subfolder = ""
        if not fname:
            raise RuntimeError(f"No filename in response: {data}")

        widget_value = f"{subfolder}/{fname}" if subfolder else fname

        logger.info("  Uploaded filename: %s", widget_value)

        # Update the file widget itself. Calling the upload-button callback here
        # can reopen a chooser without selecting anything, which is how node 214
        # could retain the previous video despite a successful HTTP upload.
        cb_result = self._comfy.evaluate(
            """({nodeId, widgetName, value}) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return {state: 'node_not_found'};
                const normalize = item => String(item || '').trim().toLowerCase();
                const widgets = node.widgets || [];
                const widget = widgets.find(item => item.name === widgetName)
                    || widgets.find(item => normalize(item.name) === normalize(widgetName));
                if (!widget) return {
                    state: 'widget_not_found',
                    available: widgets.map(item => item.name),
                };
                const previous = widget.value;
                widget.value = value;
                if (typeof widget.callback === 'function') {
                    widget.callback(value, app.canvas, node);
                }
                if (node.onWidgetChanged) {
                    node.onWidgetChanged(widget.name, value, previous, widget);
                }
                if (app.graph.afterChange) app.graph.afterChange();
                app.graph.setDirtyCanvas(true, true);
                return {
                    state: String(widget.value || '') === String(value)
                        ? 'updated' : 'value_not_applied',
                    widget: widget.name, previous,
                    value: String(widget.value || ''),
                };
            }""",
            {
                "nodeId": str(node_id), "widgetName": file_widget,
                "value": widget_value,
            },
        )
        logger.info("  Callback: %s", json.dumps(cb_result, ensure_ascii=False))
        if cb_result.get("state") != "updated":
            raise RuntimeError(
                f"Uploaded file could not be applied to node {node_id}: {cb_result}"
            )
        return {
            "filename": widget_value,
            "endpoint": endpoint,
            "node_update": cb_result,
        }

    # =================================================================
    # Precise Positioning
    # =================================================================

    def _workflow_target_node_ids(self, inputs):
        """Return the configured nodes that must be visible for this run."""
        node_ids = []
        node_ids.extend(
            upload.node_id
            for upload, _path in self.workflow_spec.resolve_uploads(inputs)
        )
        node_ids.extend(
            text_input.node_id
            for text_input, _value in self.workflow_spec.resolve_texts(inputs)
        )
        node_ids.extend(
            widget_input.node_id
            for widget_input, _value in self.workflow_spec.resolve_widgets(inputs)
        )
        node_ids.extend(output.node_id for output in self.workflow_spec.outputs)
        return list(dict.fromkeys(str(node_id) for node_id in node_ids))

    def _fit_nodes_on_canvas(self, node_ids, *, stabilize_ms=1000,
                             max_attempts=10):
        """Repeatedly fit nodes until every target is actually clickable."""
        node_ids = list(dict.fromkeys(str(node_id) for node_id in node_ids))
        if not node_ids:
            return {"ok": True, "nodeIds": []}

        last_verification = None
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            self._raise_if_cancelled()
            result = self._comfy.evaluate(
                """({nodeIds, attempt}) => {
                if (!app.canvas || !app.canvas.ds || !app.canvas.canvas
                        || typeof app.canvas.centerOnNode !== 'function') {
                    return {error: 'canvas_not_ready'};
                }
                try {
                    if (typeof app.canvas.resize === 'function') {
                        app.canvas.resize();
                    }
                } catch (_) {}
                const nodes = [];
                const missing = [];
                for (const nodeId of nodeIds) {
                    const node = app.graph.getNodeById(Number(nodeId));
                    if (node) nodes.push(node);
                    else missing.push(String(nodeId));
                }
                if (!nodes.length) {
                    return {error: 'nodes_not_found', missing};
                }

                const left = Math.min(...nodes.map(node => Number(node.pos[0])));
                const top = Math.min(...nodes.map(node => Number(node.pos[1])));
                const right = Math.max(...nodes.map(
                    node => Number(node.pos[0]) + Number(node.size[0])
                ));
                const bottom = Math.max(...nodes.map(
                    node => Number(node.pos[1]) + Number(node.size[1])
                ));
                const graphWidth = Math.max(1, right - left);
                const graphHeight = Math.max(1, bottom - top);
                const canvasWidth = app.canvas.canvas.width;
                const canvasHeight = app.canvas.canvas.height;
                // RunningHub's task list opens over the right side of the
                // iframe. Reserve that area even though iframe hit-testing
                // cannot see the parent-page overlay.
                const rightReserve = Math.min(
                    460,
                    Math.max(220, canvasWidth * 0.34),
                    canvasWidth * 0.45
                );
                // Increase the safe inset on retries. This pulls targets away
                // from toolbars and iframe edges that can intercept clicks.
                const padding = Math.min(240, 64 + (attempt - 1) * 20);
                const scale = Math.max(0.02, Math.min(
                    1,
                    Math.max(
                        1, canvasWidth - rightReserve - padding * 2
                    ) / graphWidth,
                    Math.max(1, canvasHeight - padding * 2) / graphHeight
                ));
                app.canvas.ds.scale = scale;
                // Extend the virtual bounds on the right. LiteGraph therefore
                // centers the real target nodes inside the unobstructed left
                // region without relying on version-specific offset math.
                const reservedGraphWidth = rightReserve / scale;
                app.canvas.centerOnNode({
                    pos: [left, top],
                    size: [graphWidth + reservedGraphWidth, graphHeight],
                });
                app.canvas.setDirty(true, true);
                return {
                    ok: true,
                    nodeIds: nodes.map(node => String(node.id)),
                    missing,
                    scale,
                    rightReserve,
                    bounds: {left, top, right, bottom},
                    offset: [...app.canvas.ds.offset],
                };
            }""",
                {"nodeIds": node_ids, "attempt": attempt},
            )
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(f"Canvas auto-fit failed: {result}")
            if isinstance(result, dict) and result.get("missing"):
                raise RuntimeError(
                    f"Canvas auto-fit could not find nodes: {result['missing']}"
                )

            self._comfy.wait_for_timeout(stabilize_ms)
            verification = self._comfy.evaluate(
                """(nodeIds) => {
                const canvas = app.canvas && app.canvas.canvas;
                const ds = app.canvas && app.canvas.ds;
                if (!canvas || !ds) {
                    return {error: 'canvas_not_ready', nonClickableNodeIds: nodeIds};
                }
                const rect = canvas.getBoundingClientRect();
                if (!rect.width || !rect.height || !canvas.width || !canvas.height) {
                    return {error: 'canvas_has_no_size', nonClickableNodeIds: nodeIds};
                }
                const visible = new Set(
                    (app.canvas.visible_nodes || []).map(node => String(node.id))
                );
                const cssScaleX = rect.width / canvas.width;
                const cssScaleY = rect.height / canvas.height;
                const safeInset = 36;
                const rightReserve = Math.min(
                    460,
                    Math.max(220, rect.width * 0.34),
                    rect.width * 0.45
                );
                const rightSafeBoundary = rect.width - rightReserve - safeInset;
                const toCanvas = (x, y) => {
                    if (typeof ds.convertOffsetToCanvas === 'function') {
                        const input = [x, y];
                        const output = [0, 0];
                        const converted = ds.convertOffsetToCanvas(input, output);
                        const point = converted || output;
                        if (Number.isFinite(point[0]) && Number.isFinite(point[1])) {
                            return point;
                        }
                    }
                    return [
                        (x + ds.offset[0]) * ds.scale,
                        (y + ds.offset[1]) * ds.scale,
                    ];
                };
                const details = nodeIds.map(nodeId => {
                    const node = app.graph.getNodeById(Number(nodeId));
                    if (!node) {
                        return {nodeId: String(nodeId), clickable: false,
                            reasons: ['node_not_found']};
                    }
                    const center = toCanvas(
                        Number(node.pos[0]) + Number(node.size[0]) / 2,
                        Number(node.pos[1]) + Number(node.size[1]) / 2
                    );
                    const x = center[0] * cssScaleX;
                    const y = center[1] * cssScaleY;
                    const screenWidth = Number(node.size[0]) * ds.scale * cssScaleX;
                    const screenHeight = Number(node.size[1]) * ds.scale * cssScaleY;
                    const nodeInside = x - screenWidth / 2 >= safeInset
                        && y - screenHeight / 2 >= safeInset
                        && x + screenWidth / 2 <= rightSafeBoundary
                        && y + screenHeight / 2 <= rect.height - safeInset;
                    const hit = nodeInside
                        ? document.elementFromPoint(rect.left + x, rect.top + y)
                        : null;
                    const hitCanvas = hit === canvas || (hit && canvas.contains(hit));
                    const reasons = [];
                    const diagnostics = [];
                    if (!visible.has(String(node.id))) reasons.push('not_rendered');
                    if (!nodeInside) reasons.push('node_outside_left_safe_area');
                    if (screenWidth < 10 || screenHeight < 10) {
                        diagnostics.push('small_on_screen');
                    }
                    // Upload and save operations invoke the configured widget
                    // or node callback directly. A DOM element covering the
                    // node centre (for example a Comfy toolbar/widget overlay)
                    // does not make that callback unusable. Keep this as a
                    // diagnostic only; parent-page task-list protection is
                    // enforced by nodeInside/rightSafeBoundary above.
                    if (!hitCanvas) diagnostics.push('center_dom_hit_is_not_canvas');
                    return {
                        nodeId: String(node.id),
                        clickable: reasons.length === 0,
                        reasons,
                        diagnostics,
                        center: {x: Math.round(x), y: Math.round(y)},
                        screenSize: {
                            width: Math.round(screenWidth),
                            height: Math.round(screenHeight),
                        },
                    };
                });
                return {
                    visibleNodeIds: [...visible],
                    nodes: details,
                    nonClickableNodeIds: details.filter(item => !item.clickable)
                        .map(item => item.nodeId),
                    canvas: {
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        rightReserve: Math.round(rightReserve),
                        rightSafeBoundary: Math.round(rightSafeBoundary),
                    },
                    scale: ds.scale,
                };
            }""",
                node_ids,
            )
            last_verification = verification
            non_clickable = (
                verification.get("nonClickableNodeIds", node_ids)
                if isinstance(verification, dict) else node_ids
            )
            if not non_clickable:
                result["attempts"] = attempt
                result["verification"] = verification
                logger.info(
                    "Canvas targets clickable after %d attempt(s): %s",
                    attempt, verification,
                )
                return result

            logger.warning(
                "Canvas targets not clickable after attempt %d/%d: %s",
                attempt, max_attempts, verification,
            )
            if attempt < max_attempts:
                self._comfy.wait_for_timeout(500)

        details = (
            last_verification.get("nodes", [])
            if isinstance(last_verification, dict) else last_verification
        )
        raise RuntimeError(
            "Canvas auto-fit could not make configured nodes clickable: "
            f"{details}"
        )

    def _widget_screen_pos(self, node_id, widget_name):
        js = (
            "(function(){"
            "var n=app.graph.getNodeById(" + node_id + ");"
            "if(!n)return{error:'node_not_found'};"
            "var wi=-1;"
            "for(var i=0;i<(n.widgets||[]).length;i++){"
            "if(n.widgets[i].name=='" + widget_name + "'){wi=i;break;}"
            "}"
            "if(wi===-1)return{error:'widget_not_found'};"
            "var gx=n.pos[0]+n.size[0]*0.55;"
            "var gy=n.pos[1]+24+wi*26+13;"
            "var ds=app.canvas.ds;"
            "var scale=ds.scale||1;var off=ds.offset||[0,0];"
            "var cx=gx*scale+off[0];var cy=gy*scale+off[1];"
            "var cv=document.querySelector('canvas');"
            "if(!cv)return{error:'no_canvas'};"
            "var r=cv.getBoundingClientRect();"
            "return{x:r.x+cx,y:r.y+cy,scale:scale};"
            "})()"
        )
        result = self._comfy.evaluate(js)
        if isinstance(result, dict) and result.get("error"):
            logger.warning("Widget position failed: %s", result)
            return None
        return result

    def _center_node_on_canvas(self, node_id, *, stabilize_ms=500,
                               verify=False):
        """Use LiteGraph's native node-centering operation."""
        script = """(nodeId) => {
            const node = app.graph.getNodeById(Number(nodeId));
            if (!node) return {error: 'node_not_found'};
            if (!app.canvas || typeof app.canvas.centerOnNode !== 'function') {
                return {error: 'center_on_node_unavailable'};
            }
            app.canvas.centerOnNode(node);
            app.canvas.setDirty(true, true);
            return {
                ok: true,
                nodeId: String(node.id),
                scale: app.canvas.ds.scale,
                offset: [...app.canvas.ds.offset],
            };
        }"""
        result = self._comfy.evaluate(script, node_id)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"Node positioning failed: {result['error']}")
        self._comfy.wait_for_timeout(stabilize_ms)

        if not verify:
            return result

        verification = self._comfy.evaluate(
            """(nodeId) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return {error: 'node_not_found'};
                return {
                    nodeId: String(node.id),
                    visibleNodes: (app.canvas.visible_nodes || [])
                        .map(item => String(item.id)),
                };
            }""",
            node_id,
        )
        if (isinstance(verification, dict)
                and str(node_id) not in verification.get("visibleNodes", [])):
            logger.warning(
                "Node %s is not visible after centering: %s; retrying",
                node_id, verification,
            )
            result = self._comfy.evaluate(script, node_id)
            self._comfy.wait_for_timeout(2000)
        logger.info(
            "Node %s center result=%s verification=%s",
            node_id, result, verification,
        )
        return result

    def _set_canvas_zoom(self, percent=15):
        """Set canvas zoom without changing its pan/offset position."""
        scale = max(0.05, min(2.0, float(percent) / 100.0))
        result = self._comfy.evaluate(
            """(scale) => {
                if (!app.canvas || !app.canvas.ds) {
                    return {error: 'canvas_not_ready'};
                }
                const previousOffset = [...app.canvas.ds.offset];
                app.canvas.ds.scale = scale;
                app.canvas.setDirty(true, true);
                return {
                    ok: true,
                    scale: app.canvas.ds.scale,
                    offset: [...app.canvas.ds.offset],
                    offsetUnchanged: previousOffset[0] === app.canvas.ds.offset[0]
                        && previousOffset[1] === app.canvas.ds.offset[1],
                };
            }""",
            scale,
        )
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"Canvas zoom failed: {result['error']}")
        logger.info("Canvas zoom set to %.0f%% without moving: %s", percent, result)
        return result

    def _pan_canvas_right_once(self):
        """Pan the visible ComfyUI canvas in the corrected direction once."""
        rect = self._comfy.locator("canvas").first.bounding_box()
        if not rect or rect["width"] <= 0 or rect["height"] <= 0:
            raise RuntimeError("Canvas is not visible for left pan")
        start_x = rect["x"] + rect["width"] * 0.10
        start_y = rect["y"] + rect["height"] * 0.50
        end_x = rect["x"] + rect["width"] * 0.90
        logger.info(
            "Panning canvas right once: (%.1f, %.1f) -> (%.1f, %.1f)",
            start_x, start_y, end_x, start_y,
        )
        self._page.mouse.move(start_x, start_y)
        self._page.mouse.down(button="middle")
        self._page.mouse.move(end_x, start_y, steps=12)
        self._page.mouse.up(button="middle")
        self._comfy.wait_for_timeout(2000)
        return {"ok": True, "distance": round(end_x - start_x, 1)}

    # =================================================================
    # Run
    # =================================================================

    def select_plus_mode(self):
        logger.info("Selecting Plus mode...")
        self._dismiss_popups()

        # --- Step 1: diagnostic — dump the ENTIRE mode selector area ---
        diag = self._page.evaluate(
            "() => {"
            "  var result = [];"
            ""
            "  /* Approach 1: Find the mode selector container and dump its full HTML tree */"
            "  var containers = document.querySelectorAll("
            "    '.ant-segmented, [class*=\"segmented\"], .plus-tags,'"
            "    + ' [class*=\"mode\"], [class*=\"plan\"], [class*=\"tier\"],'"
            "    + ' [class*=\"subscription\"], [class*=\"pricing\"]'"
            "  );"
            "  for (var i = 0; i < containers.length; i++) {"
            "    var c = containers[i];"
            "    result.push({"
            "      type: 'CONTAINER',"
            "      tag: c.tagName.toLowerCase(),"
            "      cls: (c.className || '').toString(),"
            "      fullText: (c.textContent || '').trim().substring(0, 200),"
            "      html: c.outerHTML.substring(0, 1200)"
            "    });"
            "  }"
            ""
            "  /* Approach 2: Dump EVERY element inside mode containers, recursively */"
            "  var seen = {};"
            "  for (var i = 0; i < containers.length; i++) {"
            "    var allDescendants = containers[i].querySelectorAll('*');"
            "    for (var j = 0; j < allDescendants.length; j++) {"
            "      var el = allDescendants[j];"
            "      var tag = el.tagName.toLowerCase();"
            "      var cls = (el.className || '').toString();"
            "      var ownText = '';"
            "      el.childNodes.forEach(function(cn) {"
            "        if (cn.nodeType === 3) ownText += cn.textContent;"
            "      });"
            "      ownText = ownText.trim();"
            "      var key = tag + '|' + cls + '|' + ownText;"
            "      if (seen[key]) continue; seen[key] = 1;"
            "      /* Skip empty/invisible utility elements */"
            "      if (!ownText && tag !== 'input' && tag !== 'img') continue;"
            "      var parent = el.parentElement;"
            "      var parentInfo = parent ? (parent.tagName + '.' + (parent.className || '').toString().substring(0, 50)) : 'none';"
            "      result.push({"
            "        type: 'CHILD',"
            "        tag: tag,"
            "        cls: cls,"
            "        text: ownText.substring(0, 80),"
            "        parent: parentInfo,"
            "        html: el.outerHTML.substring(0, 350)"
            "      });"
            "    }"
            "  }"
            ""
            "  /* Approach 3: ALWAYS scan all nearby buttons/labels (unconditional) */"
            "  /* Search in parent area around the mode containers, or globally if none */"
            "  var searchRoot = containers.length > 0 ? containers[0].parentElement : document.body;"
            "  if (searchRoot) {"
            "    var btns = searchRoot.querySelectorAll('button, [role=\"tab\"], [role=\"radio\"], [role=\"option\"], [role=\"menuitem\"], [role=\"listitem\"], label, .ant-btn, [class*=\"tag\"], span[class*=\"item\"], div[class*=\"item\"]');"
            "    for (var k = 0; k < btns.length; k++) {"
            "      var b = btns[k];"
            "      var bText = (b.textContent || '').trim().substring(0, 80);"
            "      if (!bText) continue;"
            "      var bCls = (b.className || '').toString();"
            "      result.push({"
            "        type: 'BUTTON',"
            "        tag: b.tagName.toLowerCase(),"
            "        cls: bCls,"
            "        text: bText,"
            "        parent: b.parentElement ? (b.parentElement.tagName + '.' + (b.parentElement.className || '').toString().substring(0, 40)) : '',"
            "        html: b.outerHTML.substring(0, 500)"
            "      });"
            "    }"
            "  }"
            ""
            "  return result;"
            "}"
        )
        logger.info("  === MODE SELECTOR DIAGNOSTIC (%d elements) ===", len(diag))
        for item in diag:
            logger.info("  [%s] <%s class=%r> text=%r",
                       item["type"], item["tag"], item["cls"], item.get("text", ""))
            if item.get("parent"):
                logger.info("        parent=%s", item["parent"])
            logger.info("        html=%s", item["html"])

        # --- Step 2: click the Lite/Plus run button (Plus mode) ---
        # HTML structure:
        #   Standard: <button class="beveled-btn-right run-btn"><div class="plus-tags"><span>Lite/Standard</span></div></button>
        #   Plus:     <div><button class="beveled-btn-left run-btn">运行</button><div class="plus-tags"><span>Lite/Plus</span></div></div>
        #
        # The beveled-btn-left button IS the Run button in Plus mode layout.
        # Click it once — it both selects Plus mode AND triggers the workflow.
        # click_run() is NOT called separately to avoid double-firing.
        plus_clicked = self._page.evaluate(
            "() => {\n"
            "  /* Click the beveled-btn-left button (Plus mode run button) */\n"
            "  var btn = document.querySelector('.beveled-btn-left.run-btn');\n"
            "  if (btn) { btn.click(); return 'clicked_beveled_btn_left'; }\n"
            "  /* Fallback: find button inside the parent of Lite/Plus .plus-tags */\n"
            "  var tags = document.querySelectorAll('.plus-tags');\n"
            "  for (var i = 0; i < tags.length; i++) {\n"
            "    var span = tags[i].querySelector('span');\n"
            "    if (span && (span.textContent || '').trim() === 'Lite/Plus') {\n"
            "      var parent = tags[i].parentElement;\n"
            "      if (parent) {\n"
            "        var innerBtn = parent.querySelector('button');\n"
            "        if (innerBtn) { innerBtn.click(); return 'clicked_inner_button'; }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "  return 'not_found';\n"
            "}"
        )
        logger.info("  Plus click result: %s", plus_clicked)
        self._page.wait_for_timeout(1500)

        # --- Step 3: dump full parent hierarchy to find the active state indicator ---
        hierarchy = self._page.evaluate(
            "() => {\n"
            "  var result = [];\n"
            "  /* Dump the full ancestor chain of BOTH Standard and Plus .plus-tags */\n"
            "  var tags = document.querySelectorAll('.plus-tags');\n"
            "  for (var i = 0; i < tags.length; i++) {\n"
            "    var tag = tags[i];\n"
            "    var label = (tag.textContent || '').trim();\n"
            "    /* Walk up 5 levels */\n"
            "    var el = tag;\n"
            "    for (var level = 0; level < 5 && el; level++) {\n"
            "      var info = {\n"
            "        element: label,\n"
            "        level: level,\n"
            "        tag: el.tagName.toLowerCase(),\n"
            "        cls: (el.className || '').toString(),\n"
            "        id: el.id || '',\n"
            "      };\n"
            "      /* Collect all data-* attributes */\n"
            "      var dataAttrs = {};\n"
            "      if (el.attributes) {\n"
            "        for (var a = 0; a < el.attributes.length; a++) {\n"
            "          var attr = el.attributes[a];\n"
            "          if (attr.name.startsWith('data-')) dataAttrs[attr.name] = attr.value;\n"
            "          if (attr.name === 'aria-selected' || attr.name === 'aria-checked' || attr.name === 'aria-pressed' || attr.name === 'aria-current') {\n"
            "            dataAttrs[attr.name] = attr.value;\n"
            "          }\n"
            "        }\n"
            "      }\n"
            "      if (Object.keys(dataAttrs).length > 0) info.dataAttrs = dataAttrs;\n"
            "      /* Check inline style */\n"
            "      var style = el.getAttribute('style') || '';\n"
            "      if (style) info.style = style.substring(0, 200);\n"
            "      result.push(info);\n"
            "      el = el.parentElement;\n"
            "    }\n"
            "  }\n"
            "  return result;\n"
            "}"
        )
        logger.info("  === HIERARCHY DUMP === (walking up from each .plus-tags)")
        for item in hierarchy:
            extra = ""
            if item.get("dataAttrs"):
                extra += " data=" + json.dumps(item["dataAttrs"])
            if item.get("style"):
                extra += " style=" + item["style"]
            logger.info("  [%s] L%d <%s class=%r id=%r>%s",
                       item["element"], item["level"], item["tag"], item["cls"], item["id"], extra)

        return plus_clicked != "not_found"

    def click_run(self, timeout=30):
        """Click the Run button, waiting for it to settle into a stable clickable state.

        Why a retry loop: ``select_plus_mode()`` triggers an async mode switch
        during which the Run button may be temporarily disabled, re-rendered,
        or briefly hidden behind a confirmation popup.  A single-shot check
        would fail with "not_found" on unlucky timing.  We poll (with re-dismiss)
        until the button is ready or we hit the timeout.

        Match rule: button text contains "运行", but is not "运行中" / "运行记录" /
        "重新运行" / "运行历史" (in-progress / history / re-run, etc.).  Looser
        than the previous exact-match rule so icon overlays, badges, and
        whitespace don't break the search.
        """
        logger.info("Clicking Run (wait up to %ds)...", timeout)

        # Safety: if run was already submitted, don't click again.
        if getattr(self, '_run_submitted', False):
            logger.info("Run already submitted, skipping click_run()")
            return True

        # Inline JS — note the REJECT list intentionally includes the
        # substring '运行' itself; .test() returns true if any reject token
        # appears anywhere in the trimmed text.
        js_find_and_click = r"""
        () => {
            const REJECT = /(运行中|运行记录|重新运行|运行历史|Running|run.?history|is.?running)/i;
            const btns = document.querySelectorAll('button, [role="button"]');
            const candidates = [];
            for (let i = 0; i < btns.length; i++) {
                const b = btns[i];
                const txt = (b.textContent || '').replace(/\s+/g, ' ').trim();
                if (!txt || !txt.includes('运行') || REJECT.test(txt)) continue;
                const style = window.getComputedStyle(b);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const rect = b.getBoundingClientRect();
                if (rect.width < 4 || rect.height < 4) continue;
                candidates.push({i: i, txt: txt, disabled: !!b.disabled});
            }
            if (!candidates.length) return {state: 'not_found'};
            const enabled = candidates.find(function(c){ return !c.disabled; });
            if (!enabled) return {state: 'all_disabled', candidates: candidates};
            const target = btns[enabled.i];
            target.click();
            return {state: 'clicked', txt: enabled.txt};
        }
        """

        deadline = time.time() + timeout
        attempt = 0
        last_state = None
        poll_ms = 1500

        while time.time() < deadline:
            attempt += 1
            # Re-dismiss popups every iteration — they may appear mid-transition
            self._dismiss_popups()
            try:
                result = self._page.evaluate(js_find_and_click)
            except Exception as exc:
                logger.debug("  [attempt %d] JS eval failed: %s",
                             attempt, str(exc)[:100])
                self._page.wait_for_timeout(poll_ms)
                continue

            if isinstance(result, dict):
                state = result.get("state")
                if state == "clicked":
                    logger.info("  [attempt %d] Clicked Run: %r",
                                attempt, result.get("txt"))
                    # Wait for the button to become disabled or change text;
                    # this guards against a 2nd click being fired by framework
                    # event listeners that re-fire on synthetic click().
                    self._page.wait_for_timeout(5000)
                    # Mark this page as having been submitted so a follow-up
                    # accidental click in wait_for_completion loop is a no-op.
                    self._run_submitted = True
                    return True
                # Remember the most informative state for the post-mortem dump
                if state == "all_disabled":
                    last_state = (state, result.get("candidates") or [])
                elif state == "not_found" and last_state is None:
                    last_state = state

            self._page.wait_for_timeout(poll_ms)

        # All attempts failed — emit diagnostic so the next failure is debuggable
        logger.warning("  Run button NOT FOUND after %d attempts in %ds",
                       attempt, timeout)
        self._diagnose_run_button(last_state)
        return False

    def _diagnose_run_button(self, last_state=None):
        """Snapshot the main-page button area for post-mortem debugging.

        Called only when ``click_run()`` exhausts its retry budget.  Prints the
        most recent poll's "all disabled" candidate list (if any) plus a full
        dump of every visible button on the main page, so the next failure has
        enough context to identify the actual cause (still-transitioning,
        hidden behind a popup, page structure changed, etc.).
        """
        if isinstance(last_state, tuple) and last_state[0] == "all_disabled":
            candidates = last_state[1]
            logger.warning("  Last poll: found %d '运行' candidate(s) but ALL disabled:",
                           len(candidates))
            for c in candidates[:5]:
                logger.warning("    %r (disabled=%s)",
                               c.get("txt"), c.get("disabled"))
        try:
            diag = self._page.evaluate(
                "() => {"
                "  var out = [];"
                "  document.querySelectorAll('button, [role=\"button\"]').forEach(function(b){"
                "    var t = (b.textContent || '').replace(/\\s+/g,' ').trim();"
                "    if (!t) return;"
                "    out.push({txt: t.slice(0, 60), disabled: !!b.disabled,"
                "              cls: (b.className || '').toString().slice(0, 80)});"
                "  });"
                "  return out;"
                "}"
            )
            if diag:
                logger.warning("  Current main-page buttons (%d):", len(diag))
                for d in diag[:25]:
                    logger.warning("    %r disabled=%s cls=%r",
                                   d.get("txt"), d.get("disabled"), d.get("cls"))
        except Exception as exc:
            logger.warning("  Run-button diagnostic failed: %s", exc)

    # =================================================================
    # Wait
    # =================================================================

    def _detect_error_popup(self):
        """Detect visible error/warning popups that need to be dismissed.

        Returns a dict with ``type`` and ``text`` if found, or None.

        Known types and their handling:
          - ``oom`` (显存不足) — close popup, then re-click Run
        """
        # Error markers: (type, text_fragment)
        error_patterns = [
            ("oom", "显存不足"),
            ("oom", "显存耗尽"),
            ("oom", "WanVideo Sampler"),
            ("vhs_error", "ZeroDivisionError"),
            ("vhs_error", "VHS_LoadVideo"),
            ("balance", "balance is insufficient"),
            ("balance", "余额不足"),
            ("workflow_error", "list index out of range"),
            ("workflow_error", "too many indices for tensor"),
            ("workflow_error", "tuple indices must be integers"),
        ]

        script = r"""
            ([patterns]) => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };

                for (const el of document.querySelectorAll(
                    '[role="dialog"], [role="alertdialog"], .ant-modal-content, '
                    + '.ant-modal-confirm, .ant-modal-wrap, '
                    + '[class*="dialog"], [class*="modal"], [class*="popup"], '
                    + '[class*="notification"], [class*="alert"]'
                )) {
                    if (!visible(el)) continue;
                    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    for (let i = 0; i < patterns.length; i++) {
                        if (text.includes(patterns[i])) {
                            return {
                                matched: patterns[i],
                                fullText: text.slice(0, 500)
                            };
                        }
                    }
                }
                return null;
            }
        """
        patterns = [p[1] for p in error_patterns]
        for scope_name, scope in (("ComfyUI iframe", self._comfy),
                                  ("main page", self._page)):
            if not scope:
                continue
            try:
                result = scope.evaluate(script, [patterns])
                if result:
                    # Determine type from matched pattern
                    matched = result.get("matched", "")
                    for etype, epat in error_patterns:
                        if epat == matched:
                            logger.warning("Error popup [%s] detected in %s: %s",
                                           etype, scope_name,
                                           result.get("fullText", "")[:200])
                            return {"type": etype, "text": result.get("fullText", "")}
            except Exception as exc:
                logger.debug("Error popup check failed in %s: %s",
                             scope_name, str(exc)[:120])
        return None

    def _dismiss_error_popup(self):
        """Close any visible error/warning popup by clicking its X button.

        Returns True if a popup was found and dismissed.
        """
        logger.info("Attempting to dismiss error popup...")
        # Use the existing _dismiss_rife_popup which handles X buttons well
        if self._dismiss_rife_popup():
            return True
        # Also try dismiss_popups as fallback
        self._dismiss_popups()
        self._page.wait_for_timeout(500)
        # Check if it's gone
        return self._detect_error_popup() is None

    def _visible_completion_popup(self):
        """Return details for the visible final report popup, if present.

        RunningHub may leave the words used by the popup in hidden DOM nodes, so
        searching the whole page text is not a reliable completion signal.  The
        final popup is identified by its *visible* "显示报告" / "Show Report"
        action instead.
        """
        script = r"""
            (configuredMarkers) => {
                const markers = new Set(configuredMarkers);
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };

                // The report action can be a button or a styled span/div.
                // Exact text matching avoids matching the entire document or a
                // hidden template that merely contains the same words.
                for (const el of document.querySelectorAll(
                    'button, a, [role="button"], span, div'
                )) {
                    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!markers.has(text) || !visible(el)) continue;

                    const popup = el.closest(
                        '[role="dialog"], [role="alertdialog"], .ant-modal-content, '
                        + '.ant-modal-confirm, [class*="dialog"], [class*="modal"]'
                    );
                    if (popup && visible(popup)) {
                        const popupText = (popup.textContent || '')
                            .replace(/\s+/g, ' ').trim();
                        return {
                            marker: text,
                            text: popupText.slice(0, 500),
                        };
                    }

                    // Some ComfyUI popups do not expose dialog semantics.  A
                    // visible exact-match report action is still authoritative.
                    return {marker: text, text: text};
                }
                return null;
            }
        """
        for scope_name, scope in (("main page", self._page),
                                  ("ComfyUI iframe", self._comfy)):
            if not scope:
                continue
            try:
                result = scope.evaluate(
                    script, list(self.workflow_spec.completion.markers)
                )
                if result:
                    result["scope"] = scope_name
                    return result
            except Exception as exc:
                logger.debug("Completion popup check failed in %s: %s",
                             scope_name, str(exc)[:120])
        return None

    def _visible_error_dialog_text(self):
        """Return the most specific visible error dialog text available."""
        script = r"""
            () => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };
                const candidates = [];
                for (const el of document.querySelectorAll(
                    '[role="alertdialog"], [role="alert"], [role="dialog"], '
                    + '.ant-modal-content, .ant-modal-confirm, .p-dialog, '
                    + '[class*="error"], [class*="Error"], '
                    + '[class*="notification"], [class*="toast-message"]'
                )) {
                    if (!visible(el)) continue;
                    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    if (!text || text === '显示报告' || text === 'Show Report') continue;
                    if (!/(error|failed|failure|exception|insufficient|错误|失败|异常|不足)/i.test(text)) {
                        continue;
                    }
                    candidates.push(text.slice(0, 800));
                }
                candidates.sort((a, b) => a.length - b.length);
                return candidates[0] || null;
            }
        """
        for scope_name, scope in (("ComfyUI iframe", self._comfy),
                                  ("main page", self._page)):
            if not scope:
                continue
            try:
                text = scope.evaluate(script)
                if text:
                    logger.warning(
                        "Visible error dialog in %s: %s",
                        scope_name, str(text)[:300],
                    )
                    return str(text)
            except Exception as exc:
                logger.debug(
                    "Visible error dialog check failed in %s: %s",
                    scope_name, str(exc)[:120],
                )
        return None

    def _output_media_fingerprints(self):
        """Snapshot media owned by configured output nodes."""
        if not self._comfy:
            return {}
        try:
            result = self._comfy.evaluate(
                """(nodeIds) => {
                    const snapshot = {};
                    const add = (items, values) => {
                        if (!Array.isArray(items)) return;
                        for (const item of items) {
                            if (!item) continue;
                            if (typeof item === 'string') {
                                values.push(item);
                                continue;
                            }
                            const src = item.currentSrc || item.src || '';
                            if (src) values.push(String(src));
                            if (item.filename) {
                                values.push(JSON.stringify({
                                    filename: item.filename,
                                    subfolder: item.subfolder || '',
                                    type: item.type || 'output',
                                }));
                            }
                        }
                    };
                    for (const nodeId of nodeIds) {
                        const node = app.graph.getNodeById(Number(nodeId));
                        const outputData = node && app.nodeOutputs
                            ? (app.nodeOutputs[node.id]
                                || app.nodeOutputs[String(node.id)] || {}) : {};
                        const values = [];
                        add(node && node.imgs, values);
                        add(node && node.images, values);
                        add(outputData.imgs, values);
                        add(outputData.images, values);
                        add(outputData.videos, values);
                        add(outputData.audio, values);
                        snapshot[String(nodeId)] = [...new Set(values)].sort();
                    }
                    return snapshot;
                }""",
                [output.node_id for output in self.workflow_spec.outputs],
            )
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.debug("Output media snapshot failed: %s", str(exc)[:160])
            return {}

    @staticmethod
    def _has_new_output_media(baseline, current):
        """Return True when an output node acquired a new media signature."""
        baseline = baseline or {}
        current = current or {}
        for node_id, values in current.items():
            old_values = set(baseline.get(str(node_id)) or [])
            if set(values or []) - old_values:
                return True
        return False

    def _current_task_list_state(self):
        """Return the status of the newest visible RunningHub task-list item.

        The sidebar keeps older failed tasks visible while a new task is
        running.  Looking for any ``任务失败`` text therefore produces false
        failures.  Status labels are sorted by their screen position and only
        the topmost (newest) visible item is considered.
        """
        if not self._page:
            return None

        script = r"""
            () => {
                const visible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && Number(style.opacity || 1) > 0
                        && rect.width > 0 && rect.height > 0;
                };
                const matches = [];
                for (const el of document.querySelectorAll('div, span, p')) {
                    if (!visible(el)) continue;
                    const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                    let state = null;
                    if (/^生成中(?:\s|\d|:)*$/.test(text)
                            || /^生产中(?:\s|\d|:)*$/.test(text)) {
                        state = 'running';
                    } else if (/^排队中(?:\s|（|\(|第|\d|位|）|\))*$/.test(text)) {
                        state = 'queued';
                    } else if (text === '任务失败') {
                        state = 'failed';
                    }
                    if (!state) continue;
                    const rect = el.getBoundingClientRect();
                    matches.push({state, text, top: rect.top, left: rect.left});
                }
                if (!matches.length) return null;
                matches.sort((a, b) => a.top - b.top || a.left - b.left);
                return matches[0];
            }
        """
        try:
            result = self._page.evaluate(script)
            if result:
                logger.debug(
                    "Newest task-list state: %s (%s)",
                    result.get("state"), result.get("text", ""),
                )
            return result
        except Exception as exc:
            logger.debug("Task-list state check failed: %s", str(exc)[:120])
            return None

    @staticmethod
    def _observe_task_failure(task_list_state, first_seen_at, now,
                              grace_seconds=TASK_FAILURE_GRACE_SECONDS):
        """Track a failed sidebar state without racing the completion popup.

        RunningHub can render ``任务失败`` before its authoritative completion
        popup appears.  A visible running state cancels the observation; a
        missing state keeps it alive because the sidebar may be refreshing.
        """
        state = (task_list_state or {}).get("state")
        if state in ("running", "queued"):
            return None, False
        if state != "failed":
            return first_seen_at, False
        if first_seen_at is None:
            return now, False
        return first_seen_at, now - first_seen_at >= grace_seconds

    def wait_for_completion(self, timeout=600, poll_interval=2):
        timeout_text = f"{timeout}s" if timeout and timeout > 0 else "unlimited"
        logger.info("Waiting for visible final report popup (timeout=%s)...",
                    timeout_text)
        start = time.time()

        while not timeout or timeout <= 0 or time.time() - start < timeout:
            elapsed = time.time() - start
            if int(elapsed) % 30 < poll_interval:
                logger.info("Waiting... (%.0fs elapsed)", elapsed)

            popup = self._visible_completion_popup()
            if popup:
                logger.info(
                    "Visible final report popup detected in %s after %.0fs: %s",
                    popup.get("scope"), elapsed, popup.get("text", "")[:200],
                )
                return "done"

            time.sleep(poll_interval)

        logger.error("Final report popup not detected within %ds", timeout)
        return "timeout"

    def _dismiss_rife_popup(self):
        """Force-close any visible modal/dialog on the main page AND inside the ComfyUI iframe."""
        close_selectors = [
            '.ant-modal-close',
            'span.ant-modal-close-x',
            'button[aria-label="Close"]',
            'button[aria-label="关闭"]',
            '.ant-modal-wrap .ant-modal-close',
            '.ant-modal-content .ant-modal-close',
            '.lucide-x',
            'svg.lucide-x',
            '[class*="modal"] [class*="close"]',
            '[class*="popup"] [class*="close"]',
            '[class*="dialog"] [class*="close"]',
            '[class*="modal"] button:has(svg)',
        ]
        # Main page
        for sel in close_selectors:
            try:
                btn = self._page.locator(sel).first
                if btn.is_visible(timeout=300):
                    btn.click(force=True)
                    logger.info("Closed X via: %s (main)", sel)
                    self._page.wait_for_timeout(500)
                    return True
            except Exception:
                pass
        # ComfyUI iframe
        if self._comfy:
            for sel in close_selectors:
                try:
                    btn = self._comfy.locator(sel).first
                    if btn.is_visible(timeout=300):
                        btn.click(force=True)
                        logger.info("Closed X via: %s (comfy)", sel)
                        self._page.wait_for_timeout(500)
                        return True
                except Exception:
                    pass
            try:
                self._comfy.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',keyCode:27,bubbles:true}))")
                self._page.wait_for_timeout(300)
            except Exception:
                pass
        # Fallback: Escape on main page
        try:
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
        except Exception:
            pass
        return False

    def _dismiss_cancel_popups(self):
        """Click Cancel in every visible popup and keep watching for new ones.

        The exact-text and popup-container checks are intentional: RunningHub's
        task sidebar also contains a ``取消`` action, but it must only be used
        by the explicit task-cancellation path.  This watcher is installed in
        both the outer page and ComfyUI iframe, and its timer handles dialogs
        that appear asynchronously between Python-side polling checkpoints.
        """
        script = r"""() => {
            const visible = (el) => {
                if (!el || !el.isConnected) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number(style.opacity || 1) > 0
                    && rect.width > 0 && rect.height > 0;
            };
            const popupSelector = [
                '[role="dialog"]', '[role="alertdialog"]',
                '.ant-modal-content', '.ant-modal-wrap', '.ant-modal-confirm',
                '.p-dialog', '.comfy-dialog', '.comfy-modal', '.lite-dialog',
                '[class*="modal"]', '[class*="Modal"]',
                '[class*="dialog"]', '[class*="Dialog"]',
                '[class*="popup"]', '[class*="Popup"]',
                '[class*="overlay"]', '[class*="Overlay"]'
            ].join(',');
            const popupFor = (button) => {
                const semantic = button.closest(popupSelector);
                if (semantic && visible(semantic)) return semantic;
                // Some custom dialogs have no useful class. Accept a fixed
                // full-screen/large overlay ancestor, but never a normal task
                // card in the document flow.
                let ancestor = button.parentElement;
                for (let depth = 0; ancestor && depth < 10; depth++) {
                    const style = window.getComputedStyle(ancestor);
                    const rect = ancestor.getBoundingClientRect();
                    if (visible(ancestor) && style.position === 'fixed'
                            && rect.width >= Math.min(240, innerWidth * 0.25)
                            && rect.height >= Math.min(100, innerHeight * 0.12)) {
                        return ancestor;
                    }
                    ancestor = ancestor.parentElement;
                }
                return null;
            };
            const scan = () => {
                let clicked = 0;
                for (const candidate of document.querySelectorAll(
                    'button, a, [role="button"], input[type="button"], input[type="submit"]'
                )) {
                    if (!visible(candidate) || candidate.disabled
                            || candidate.dataset.yunCancelClicked === '1') continue;
                    const text = ((candidate.innerText || candidate.textContent
                        || candidate.value || '') + '').replace(/\s+/g, ' ').trim();
                    if (!/^(取消|Cancel)$/i.test(text)) continue;
                    const popup = popupFor(candidate);
                    if (!popup) continue;
                    candidate.dataset.yunCancelClicked = '1';
                    candidate.click();
                    clicked++;
                }
                return clicked;
            };
            const clicked = scan();
            if (!window.__yunCancelPopupWatcher) {
                const observer = new MutationObserver(scan);
                observer.observe(document.documentElement || document.body, {
                    childList: true, subtree: true, attributes: true,
                    attributeFilter: ['class', 'style', 'hidden', 'open']
                });
                const timer = window.setInterval(scan, 250);
                window.__yunCancelPopupWatcher = {observer, timer};
            }
            return {clicked, watching: true};
        }"""
        clicked = 0
        scopes = (("main", self._page), ("comfy", self._comfy))
        for scope, frame in scopes:
            if not frame:
                continue
            try:
                result = frame.evaluate(script)
                count = int((result or {}).get("clicked") or 0)
                clicked += count
                if count:
                    logger.info(
                        "Dismissed %d popup(s) via Cancel (%s)", count, scope,
                    )
            except Exception as exc:
                logger.debug(
                    "Unable to install Cancel popup watcher in %s: %s",
                    scope, str(exc)[:160],
                )
        if clicked:
            self._page.wait_for_timeout(300)
        return clicked

    def _dismiss_popups(self):
        self._dismiss_cancel_popups()
        button_selectors = [
            'button:has-text("OK")', 'button:has-text("确定")',
            'button:has-text("Close")', 'button:has-text("关闭")',
            'button:has-text("Got it")', 'button:has-text("知道了")',
            'button:has-text("Confirm")', 'button:has-text("确认")',
            'button:has-text("Yes")', 'button:has-text("是")',
            '.ant-modal-close', '[aria-label="Close"]',
            '[aria-label="关闭"]',
        ]
        # Main page
        for sel in button_selectors:
            try:
                for el in self._page.locator(sel).all():
                    if el.is_visible():
                        el.click(force=True)
                        logger.info("Dismissed: %s (main)", sel)
                        self._page.wait_for_timeout(500)
            except Exception:
                pass

        # noticeModal — RunningHub announcement dialog blocking all clicks
        # Try JS removal unconditionally (visibility check may fail for modals)
        try:
            removed = self._page.evaluate(
                "() => {"
                "  var count = 0;"
                "  var sel = '.noticeModal, .ant-modal-root:has(.noticeModal), .ant-modal-wrap:has(.noticeModal)';"
                "  document.querySelectorAll(sel).forEach(function(el) { el.remove(); count++; });"
                "  return count;"
                "}"
            )
            if removed:
                logger.info("JS removed %d noticeModal element(s)", removed)
                self._page.wait_for_timeout(300)
        except Exception:
            pass
        # Also try Escape key to dismiss ant-modal
        try:
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
        except Exception:
            pass

        # ComfyUI iframe
        if self._comfy:
            for sel in button_selectors:
                try:
                    for el in self._comfy.locator(sel).all():
                        if el.is_visible():
                            el.click(force=True)
                            logger.info("Dismissed: %s (comfy)", sel)
                            self._page.wait_for_timeout(500)
                except Exception:
                    pass

    def _dismiss_stale_completion_popup(self):
        """Clear a leftover final-report dialog before configuring a run.

        Some accounts reopen the workflow with the previous run's
        ``显示报告``/``Show Report`` dialog still visible.  That dialog lives
        in either the page or the ComfyUI iframe and can block canvas actions
        and uploads, so handle it before any workflow setup.  This method is
        intentionally separate from the completion polling path: a report
        popup detected after the run is still the authoritative success
        signal.
        """
        self._dismiss_comfy_popups()
        self._dismiss_rife_popup()
        self._dismiss_popups()
        self._page.wait_for_timeout(500)

        popup = self._visible_completion_popup()
        if not popup:
            return

        logger.info(
            "Dismissing stale Show Report popup before workflow setup: %s",
            popup.get("text", "")[:200] if isinstance(popup, dict) else popup,
        )
        self._dismiss_comfy_popups()
        self._dismiss_rife_popup()
        self._dismiss_popups()
        self._page.wait_for_timeout(1000)

    def _diagnose_comfy_popups(self):
        """Inject JS to snapshot all visible dialog/modal/popup elements
        inside the ComfyUI iframe. Saves detailed DOM info to a file for
        debugging what popup is blocking the UI."""
        if not self._comfy:
            return
        try:
            report = self._comfy.evaluate("""
                () => {
                    const result = {
                        visibleDialogs: [],
                        allVisibleDivs: [],
                        litegraphNodes: [],
                        bodyChildren: []
                    };

                    // 1. Find all visible dialog/modal/popup elements
                    const patterns = [
                        '[class*="dialog"]', '[class*="Dialog"]',
                        '[class*="modal"]', '[class*="Modal"]',
                        '[class*="popup"]', '[class*="Popup"]',
                        '[class*="overlay"]', '[class*="Overlay"]',
                        '[class*="notification"]', '[class*="Notification"]',
                        '[class*="alert"]', '[class*="Alert"]',
                        '[class*="panel"]', '[class*="toast"]',
                        '.ant-modal-wrap', '.ant-modal-mask',
                        '.ant-modal-content', '.ant-notification',
                        '.lite-dialog', '.graphdialog',
                        '.comfy-dialog', '.comfy-modal',
                    ];
                    patterns.forEach(function(pat) {
                        try {
                            document.querySelectorAll(pat).forEach(function(el) {
                                const s = window.getComputedStyle(el);
                                if (s.display !== 'none' && s.visibility !== 'hidden'
                                    && parseFloat(s.opacity) > 0.1) {
                                    const rect = el.getBoundingClientRect();
                                    result.visibleDialogs.push({
                                        tag: el.tagName,
                                        id: el.id || '',
                                        className: (el.className || '').toString().slice(0, 120),
                                        text: (el.textContent || '').trim().slice(0, 200),
                                        rect: {x:Math.round(rect.x), y:Math.round(rect.y),
                                               w:Math.round(rect.width), h:Math.round(rect.height)},
                                        zIndex: s.zIndex,
                                        position: s.position,
                                        innerHTML: el.innerHTML.slice(0, 500)
                                    });
                                }
                            });
                        } catch(e) {}
                    });

                    // 2. Top-level visible divs (catch anything we missed)
                    document.querySelectorAll('body > div').forEach(function(el) {
                        const s = window.getComputedStyle(el);
                        if (s.display !== 'none' && s.visibility !== 'hidden'
                            && parseFloat(s.opacity) > 0.1) {
                            const rect = el.getBoundingClientRect();
                            result.bodyChildren.push({
                                tag: el.tagName,
                                id: el.id || '',
                                className: (el.className || '').toString().slice(0, 120),
                                text: (el.textContent || '').trim().slice(0, 150),
                                rect: {x:Math.round(rect.x), y:Math.round(rect.y),
                                       w:Math.round(rect.width), h:Math.round(rect.height)},
                                zIndex: s.zIndex
                            });
                        }
                    });

                    // 3. Check for LiteGraph dialogs (ComfyUI uses LiteGraph)
                    if (window.app && window.app.ui) {
                        result.litegraphNodes = ['app.ui available'];
                    }
                    if (typeof LiteGraph !== 'undefined') {
                        result.litegraphNodes.push('LiteGraph available');
                    }
                    if (window.graph && window.graph._nodes) {
                        result.litegraphNodes.push('graph._nodes: ' + window.graph._nodes.length);
                    }

                    return JSON.stringify(result);
                }
            """)
            if report:
                data = json.loads(report)
                visible_count = len(data.get("visibleDialogs", []))
                body_count = len(data.get("bodyChildren", []))
                if visible_count > 0 or body_count > 0:
                    logger.info("DIAGNOSTIC: %d visible dialogs, %d body children",
                                visible_count, body_count)
                    # Write full report to disk for inspection
                    diag_path = self.user_data_dir / "comfy_diag.json"
                    diag_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
                    logger.info("Diagnostic saved to %s", diag_path)
                    # Print details of each visible dialog
                    for d in data.get("visibleDialogs", []):
                        logger.info("  DIALOG: <%s> id=%r class=%r text=%r rect=%s z=%s",
                                    d.get("tag"), d.get("id"), d.get("className"),
                                    d.get("text"), d.get("rect"), d.get("zIndex"))
                        if d.get("innerHTML"):
                            logger.info("    innerHTML: %s", d["innerHTML"][:300])
                    for d in data.get("bodyChildren", []):
                        logger.info("  BODY: <%s> id=%r class=%r text=%r rect=%s z=%s",
                                    d.get("tag"), d.get("id"), d.get("className"),
                                    d.get("text"), d.get("rect"), d.get("zIndex"))
        except Exception as e:
            logger.warning("Diagnostic failed: %s", e)

    def _dismiss_comfy_popups(self):
        """Aggressively dismiss any dialog/popup inside the ComfyUI iframe.
        Called after wait_for_completion() to ensure the iframe is clear
        before attempting downloads."""
        if not self._comfy:
            return
        logger.info("Dismissing ComfyUI iframe popups...")
        self._dismiss_cancel_popups()

        # ── Step 0: DIAGNOSTIC — snapshot visible elements in iframe ──
        self._diagnose_comfy_popups()

        # Step 1: Try selectors for common close/dismiss buttons
        close_selectors = [
            '.ant-modal-close', 'span.ant-modal-close-x',
            'button[aria-label="Close"]', 'button[aria-label="关闭"]',
            '.ant-modal-wrap .ant-modal-close', '.lucide-x', 'svg.lucide-x',
            'button:has-text("OK")', 'button:has-text("确定")',
            'button:has-text("Close")', 'button:has-text("关闭")',
            'button:has-text("Got it")', 'button:has-text("知道了")',
            'button:has-text("Confirm")', 'button:has-text("确认")',
            'button:has-text("Yes")', 'button:has-text("是")',
            '.dialog-close', '.modal-close', '[data-dismiss="modal"]',
            '.btn-close', 'button.close', '.comfy-close',
            '[class*="close"]', '[class*="Close"]',
        ]
        for sel in close_selectors:
            try:
                for el in self._comfy.locator(sel).all():
                    if el.is_visible():
                        el.click(force=True)
                        logger.info("Comfy popup dismissed: %s", sel)
                        self._page.wait_for_timeout(400)
            except Exception:
                pass
        # Step 2: Try pressing Escape
        try:
            self._comfy.evaluate(
                "() => {"
                "  var e = new KeyboardEvent('keydown', {key:'Escape',code:'Escape',keyCode:27,bubbles:true});"
                "  document.dispatchEvent(e);"
                "  if (document.activeElement) document.activeElement.dispatchEvent(e);"
                "}"
            )
            self._page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self._page.keyboard.press("Escape")
            self._page.wait_for_timeout(300)
        except Exception:
            pass
        # Step 3: JS brute-force — find and remove/clone any visible modal/dialog overlay
        try:
            removed = self._comfy.evaluate("""
                () => {
                    let count = 0;
                    // Common modal/dialog classes and attributes
                    const patterns = [
                        '[class*="modal"]', '[class*="Modal"]',
                        '[class*="dialog"]', '[class*="Dialog"]',
                        '[class*="overlay"]', '[class*="Overlay"]',
                        '[class*="popup"]', '[class*="Popup"]',
                        '[role="dialog"]', '[role="alertdialog"]',
                        '.ant-modal-wrap', '.ant-modal-mask',
                        '.ant-notification', '.ant-message',
                    ];
                    for (const pat of patterns) {
                        try {
                            document.querySelectorAll(pat).forEach(el => {
                                const style = window.getComputedStyle(el);
                                if (style.display !== 'none' && style.visibility !== 'hidden'
                                    && parseFloat(style.opacity) > 0) {
                                    el.remove();
                                    count++;
                                }
                            });
                        } catch(e) {}
                    }
                    return count;
                }
            """)
            if removed:
                logger.info("JS brute-force removed %d modal/dialog elements", removed)
                self._page.wait_for_timeout(500)
        except Exception:
            pass

    def _set_comfy_file_input(self, file_path):
        """Set files on ComfyUI's hidden file input after widget click registered
        the current target node."""
        selectors = [
            "#comfy-file-input",
            "#component-file-input",
            "input[type=file]",
        ]
        last_error = None

        for sel in selectors:
            try:
                locator = self._comfy.locator(sel).first
                locator.set_input_files(file_path, timeout=10000)
                logger.info("  File injected via %s", sel)
                return sel
            except Exception as exc:
                last_error = exc
                logger.debug("set_input_files failed for %s: %s", sel, str(exc)[:120])

        raise RuntimeError(f"Unable to set any ComfyUI file input: {last_error}")

    def _trigger_widget_upload(self, node_id, widget_name):
        """Trigger a node upload widget from inside the ComfyUI frame."""
        return self._comfy.evaluate(
            "(function(){"
            "var n=app.graph.getNodeById(" + node_id + ");"
            "var w=(n.widgets||[]).find(function(x){return x.name=='" + widget_name + "';});"
            "if(!w)return{error:'widget_not_found'};"
            "if(typeof w.callback==='function'){w.callback();return{ok:true,method:'callback'};}"
            "if(w.element){w.element.click();return{ok:true,method:'element.click'};}"
            "if(typeof w.click==='function'){w.click();return{ok:true,method:'click'};}"
            "return{error:'no_widget_trigger'};"
            "})()"
        )

    # =================================================================
    # Download
    # =================================================================

    def download_outputs(self, output_dir="./outputs"):
        logger.info("=== Download phase ===")
        base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        self._write_download_diagnostic({
            "stage": "download_started",
            "output_dir": str(output_dir),
            "configured_outputs": [
                {"node_id": o.node_id, "media_type": o.media_type,
                 "menu_actions": list(o.menu_actions)}
                for o in self.workflow_spec.outputs
            ],
        })

        self._dismiss_comfy_popups()
        self._page.wait_for_timeout(1000)

        # Wait for output files to finalize
        logger.info("Waiting 10s for output files to finalize...")
        self._page.wait_for_timeout(10000)

        # Strategy 1 (PRIMARY): invoke each configured output-node save action.
        for output in self.workflow_spec.outputs:
            try:
                # SaveImage batches expose every result in node metadata. Use
                # those URLs before the context menu, which may download only
                # the currently selected preview image.
                if output.media_type == "image":
                    media_saved = self._download_output_node_media(base_dir, output)
                    if media_saved:
                        logger.info(
                            "Configured output node %s succeeded: %s",
                            output.node_id, media_saved,
                        )
                        return media_saved
                result = self._download_via_context_menu(base_dir, output)
                if result:
                    logger.info(
                        "Configured output node %s succeeded: %s",
                        output.node_id, result,
                    )
                    return result
            except Exception as exc:
                logger.warning(
                    "Context menu download failed for node %s: %s",
                    output.node_id, exc,
                )
        if saved:
            logger.info("Configured output downloads OK: %s", saved)
            return saved
        # Save directly from the configured node's own media metadata. This
        # remains scoped to the declared output and cannot capture input media.
        for output in self.workflow_spec.outputs:
            try:
                media_saved = self._download_output_node_media(base_dir, output)
                if media_saved:
                    saved.extend(media_saved)
            except Exception as exc:
                logger.warning(
                    "Output node media fallback failed for node %s: %s",
                    output.node_id, str(exc)[:200],
                )
        if saved:
            logger.info("Configured output node media downloads OK: %s", saved)
            return saved
        if self.workflow_spec.strict_outputs:
            raise RuntimeError(
                "Configured output node download failed; refusing to save other nodes"
            )

        # Strategy 2: Scan page HTML for video URLs
        all_urls = set()
        try:
            for url in self._extract_urls_from_html(self._page.content() or ""):
                all_urls.add(url)
        except Exception:
            pass
        try:
            html = self._comfy.evaluate("() => document.documentElement.outerHTML || ''")
            for url in self._extract_urls_from_html(html):
                all_urls.add(url)
        except Exception:
            pass

        import requests as req
        best = None
        for url in all_urls:
            if not url or not url.startswith("http") or "/vhs/viewvideo" in url:
                continue
            try:
                resp = req.head(url, timeout=30, allow_redirects=True)
                size = int(resp.headers.get("content-length", 0))
                if size > 50000 and (best is None or size > best[0]):
                    best = (size, url)
            except Exception:
                pass

        if best:
            size, url = best
            try:
                resp = req.get(url, timeout=180)
                resp.raise_for_status()
                fname = url.split("/")[-1].split("?")[0] or f"output_{int(time.time())}.mp4"
                sp = base_dir / fname
                sp.write_bytes(resp.content)
                saved.append(str(sp))
                logger.info("Downloaded %d bytes -> %s", len(resp.content), sp)
                return saved
            except Exception as exc:
                logger.warning("Download failed: %s", exc)

        # Fallback to DOM video
        try:
            result = self._download_via_dom_video(base_dir)
            if result:
                saved.extend(result)
                return saved
        except Exception:
            pass

        raise RuntimeError(
            "工作流已完成，但自动下载输出失败；任务已结束以释放账号，请查看浏览器或日志中的下载错误"
        )

    @staticmethod
    def _extract_urls_from_html(html):
        """Extract all video and output URLs from HTML string."""
        import re
        urls = set()
        end = '[^"\'\\s<>]*?'
        for pat in [
            'https?://' + end + 'rh-images' + end,
            'https?://' + end + 'xiaoyaoyou' + end,
            'https?://' + end + r'\.mp4' + end,
            'https?://' + end + '/output/' + end,
        ]:
            for m in re.finditer(pat, html, re.IGNORECASE):
                url = m.group(0).rstrip('.,;:)!}')
                if len(url) > 30:
                    urls.add(url)
        return urls

    def _download_via_dom_video(self, base_dir):
        """Find <video> elements in the ComfyUI iframe, extract the output
        video URL (NOT the input/source video), and download via page.request.
        Only used as a fallback when right-click context menu fails."""
        saved = []
        try:
            videos = self._comfy.evaluate(
                """(function(){
                return Array.from(document.querySelectorAll('video[src]'))
                    .map(function(v){ return v.src || ''; })
                    .filter(function(s){ return s.length > 20; });
            })()"""
            )
            if not videos:
                logger.info("No <video> elements found in iframe")
                return saved

            logger.info("DOM videos found: %d", len(videos))
            for src in videos:
                # Skip input/source videos — these are from VHS_LoadVideo previews,
                # not the final rendered output.
                if "/vhs/viewvideo" in src or "type=input" in src:
                    logger.info("Skipping input video: %s", src[:120])
                    continue

                # Extract cos_url (the actual CDN URL) if present
                cos_url = None
                if "cos_url=" in src:
                    try:
                        parsed = urllib.parse.urlparse(src)
                        qs = urllib.parse.parse_qs(parsed.query)
                        cos_url = qs.get("cos_url", [None])[0]
                    except Exception:
                        pass

                target = cos_url or src
                logger.info("Trying: %s", target[:200])

                try:
                    resp = self._page.request.get(target, timeout=120000)
                    body = resp.body()
                    content_type = resp.headers.get("content-type", "")
                    if resp.ok and len(body) > 50000:  # Output video should be >50KB
                        fname = f"output_{int(time.time())}.mp4"
                        sp = base_dir / fname
                        sp.write_bytes(body)
                        logger.info("Downloaded %s bytes (type=%s) -> %s", len(body), content_type, sp)
                        saved.append(str(sp))
                        if cos_url:
                            break  # Got the CDN output video, done
                    elif resp.ok:
                        logger.info("Skipping small file: %d bytes (type=%s)", len(body), content_type)
                except Exception as exc:
                    logger.warning("Download failed for %s: %s", target[:120], exc)

            return saved
        except Exception as exc:
            logger.warning("DOM video extraction failed: %s", exc)
            return saved

    def _download_output_node_media(self, base_dir, output):
        """Download media URLs owned by one configured output node."""
        try:
            inspection = self._comfy.evaluate(
                """(nodeId) => {
                    const node = app.graph.getNodeById(Number(nodeId));
                    const outputData = node && app.nodeOutputs
                        ? (app.nodeOutputs[node.id] || app.nodeOutputs[String(node.id)] || {}) : {};
                    const summarize = (items) => (Array.isArray(items) ? items : []).map((item) => {
                        const src = item && (item.currentSrc || item.src || '');
                        let safeSrc = String(src || '');
                        try { safeSrc = safeSrc.split('?')[0]; } catch (_) {}
                        return {tag: item && item.tagName || null,
                            complete: !!(item && item.complete),
                            naturalWidth: item && item.naturalWidth || 0,
                            naturalHeight: item && item.naturalHeight || 0,
                            src: safeSrc.slice(0, 300)};
                    });
                    return {nodeExists: !!node, nodeType: node && node.type || null,
                        nodeKeys: node ? Object.keys(node).filter((key) => /img|image|output|preview/i.test(key)).slice(0, 80) : [],
                        nodeImgs: summarize(node && node.imgs),
                        nodeImages: Array.isArray(node && node.images) ? node.images : [],
                        nodeImageRects: Array.isArray(node && node.imageRects) ? node.imageRects.length : 0,
                        outputKeys: Object.keys(outputData || {}).filter((key) => /img|image|output|preview/i.test(key)).slice(0, 80),
                        outputImgs: summarize(outputData && outputData.imgs),
                        outputImages: Array.isArray(outputData && outputData.images) ? outputData.images : []};
                }""",
                output.node_id,
            )
            self._write_download_diagnostic({
                "stage": "node_inspection",
                "node_id": output.node_id,
                "media_type": output.media_type,
                "inspection": inspection,
            })
        except Exception as exc:
            self._write_download_diagnostic({
                "stage": "node_inspection_failed",
                "node_id": output.node_id,
                "error": str(exc)[:500],
            })
        # Prefer pixels already rendered inside the configured output node.
        # Some RunningHub image URLs are short-lived/private: Chromium can
        # display them, while a second HTTP request returns 401. Exporting the
        # loaded image through a canvas avoids that second network request and
        # remains strictly scoped to this node.
        embedded = self._comfy.evaluate(
            """async (nodeId) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return [];
                const outputData = (app.nodeOutputs && app.nodeOutputs[node.id])
                    || (app.nodeOutputs && app.nodeOutputs[String(node.id)]) || {};
                const images = [
                    ...(Array.isArray(node.imgs) ? node.imgs : []),
                    ...(Array.isArray(outputData.imgs) ? outputData.imgs : []),
                ];
                const results = [];
                const seen = new Set();
                for (const image of images) {
                    if (!image) continue;
                    if (!image.complete || !image.naturalWidth || !image.naturalHeight) {
                        try { await image.decode(); } catch (_) {}
                    }
                    if (!image.naturalWidth || !image.naturalHeight) continue;
                    const source = image.currentSrc || image.src || '';
                    if (source && seen.has(source)) continue;
                    if (source) seen.add(source);
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = image.naturalWidth;
                        canvas.height = image.naturalHeight;
                        const context = canvas.getContext('2d');
                        context.drawImage(image, 0, 0);
                        results.push(canvas.toDataURL('image/png'));
                    } catch (_) {
                        try {
                            if (!source) continue;
                            const response = await fetch(source, {credentials: 'include'});
                            if (!response.ok) continue;
                            const blob = await response.blob();
                            results.push(await new Promise((resolve, reject) => {
                                const reader = new FileReader();
                                reader.onload = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            }));
                        } catch (_) {}
                    }
                }
                return results;
            }""",
            output.node_id,
        ) or []
        saved = []
        if output.media_type == "image":
            for index, data_url in enumerate(embedded, 1):
                if not isinstance(data_url, str) or not data_url.startswith(
                        "data:image/"):
                    continue
                try:
                    header, encoded = data_url.split(",", 1)
                    if ";base64" not in header:
                        continue
                    body = base64.b64decode(encoded, validate=True)
                    image_signature = (
                        body.startswith(b"\x89PNG\r\n\x1a\n")
                        or body.startswith(b"\xff\xd8\xff")
                        or (body.startswith(b"RIFF")
                            and body[8:12] == b"WEBP")
                    )
                    if not image_signature or len(body) < 10000:
                        continue
                    destination = base_dir / (
                        f"output_{output.node_id}_{index:02d}.png"
                    )
                    collision = 1
                    while destination.exists():
                        destination = base_dir / (
                            f"output_{output.node_id}_{index:02d}_"
                            f"{collision}.png"
                        )
                        collision += 1
                    destination.write_bytes(body)
                    saved.append(str(destination))
                    logger.info(
                        "Saved rendered image from node %s: %s (%d bytes)",
                        output.node_id, destination, len(body),
                    )
                except Exception as exc:
                    logger.warning(
                        "Rendered image export failed for node %s: %s",
                        output.node_id, str(exc)[:160],
                    )
            if saved:
                return saved

        sources = self._comfy.evaluate(
            """(nodeId) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return [];
                const urls = [];
                const outputData = (app.nodeOutputs && app.nodeOutputs[node.id])
                    || (app.nodeOutputs && app.nodeOutputs[String(node.id)]) || {};
                const loadedImages = [
                    ...(Array.isArray(node.imgs) ? node.imgs : []),
                    ...(Array.isArray(outputData.imgs) ? outputData.imgs : []),
                ];
                for (const image of loadedImages) {
                    const src = image && (image.currentSrc || image.src);
                    if (src) urls.push(src);
                }
                const imageMetadata = [
                    ...(Array.isArray(node.images) ? node.images : []),
                    ...(Array.isArray(outputData.images) ? outputData.images : []),
                ];
                for (const item of imageMetadata) {
                    if (!item || !item.filename) continue;
                    const url = new URL('/view', location.origin);
                    url.searchParams.set('filename', item.filename);
                    url.searchParams.set('subfolder', item.subfolder || '');
                    url.searchParams.set('type', item.type || 'output');
                    urls.push(url.href);
                }
                return [...new Set(urls)];
            }""",
            output.node_id,
        ) or []
        for source in dict.fromkeys(sources):
            if not isinstance(source, str) or not source.startswith("http"):
                continue
            for request_attempt in range(1, 4):
                try:
                    response = self._page.request.get(source, timeout=180000)
                    body = response.body()
                    content_type = (
                        response.headers.get("content-type") or ""
                    ).lower()
                    expected = (
                        "image" if output.media_type == "image" else "video"
                    )
                    image_signature = (
                        body.startswith(b"\x89PNG\r\n\x1a\n")
                        or body.startswith(b"\xff\xd8\xff")
                        or (body.startswith(b"RIFF")
                            and body[8:12] == b"WEBP")
                    )
                    valid_type = expected in content_type
                    if output.media_type == "image":
                        valid_type = valid_type or image_signature
                    if not response.ok or not valid_type or len(body) < 10000:
                        raise RuntimeError(
                            f"invalid media response: status={response.status}, "
                            f"type={content_type!r}, bytes={len(body)}"
                        )
                    suffix = (
                        ".png" if output.media_type == "image" else ".mp4"
                    )
                    parsed = urllib.parse.urlparse(source)
                    query_name = urllib.parse.parse_qs(parsed.query).get(
                        "filename", [""]
                    )[0]
                    name = (
                        Path(query_name or parsed.path).name
                        or f"output_{int(time.time())}{suffix}"
                    )
                    if not Path(name).suffix:
                        name += suffix
                    destination = base_dir / Path(name).name
                    collision = 1
                    while destination.exists():
                        destination = base_dir / (
                            f"{Path(name).stem}_{collision}"
                            f"{Path(name).suffix}"
                        )
                        collision += 1
                    destination.write_bytes(body)
                    saved.append(str(destination))
                    break
                except Exception as exc:
                    logger.warning(
                        "Output media request failed for node %s (%d/3): %s",
                        output.node_id, request_attempt, str(exc)[:160],
                    )
                    if request_attempt < 3:
                        self._page.wait_for_timeout(1000 * request_attempt)
        return saved

    def _download_preview_batch(self, base_dir, output, actions):
        """Download every image displayed by one image output node.

        RunningHub's SaveImage node sometimes renders a thumbnail grid without
        exposing the corresponding URLs through ``node.imgs``/``node.images``.
        Its image-specific save action is supplied by ``getExtraMenuOptions``
        (the menu users see after right-clicking a thumbnail), rather than by
        the ordinary node context menu.  Select each image in turn, invoke that
        image menu action, then clear the selection just like closing the
        expanded preview with its ``x`` button.
        """
        node_id = output.node_id
        raw_count = self._comfy.evaluate(
            """(nodeId) => {
                const node = app.graph.getNodeById(Number(nodeId));
                if (!node) return 0;
                const outputData = (app.nodeOutputs && app.nodeOutputs[node.id])
                    || (app.nodeOutputs && app.nodeOutputs[String(node.id)]) || {};
                const counts = [
                    Array.isArray(node.imgs) ? node.imgs.length : 0,
                    Array.isArray(node.images) ? node.images.length : 0,
                    Array.isArray(node.imageRects) ? node.imageRects.length : 0,
                    Array.isArray(outputData.imgs) ? outputData.imgs.length : 0,
                    Array.isArray(outputData.images) ? outputData.images.length : 0,
                ];
                return Math.max(...counts, 0);
            }""",
            node_id,
        )
        try:
            image_count = int(raw_count)
        except (TypeError, ValueError):
            logger.debug(
                "Preview image count unavailable for node %s: %r",
                node_id, raw_count,
            )
            return None
        if image_count <= 0:
            logger.info("Output node %s has no preview images", node_id)
            return None

        logger.info(
            "Output node %s contains %d preview images; saving all",
            node_id, image_count,
        )
        saved = []
        for image_index in range(image_count):
            last_error = None
            for attempt in range(3):
                try:
                    with self._page.expect_download(timeout=60000) as dl:
                        result = self._comfy.evaluate(
                            """({nodeId, actions, imageIndex}) => {
                                const node = app.graph.getNodeById(Number(nodeId));
                                if (!node) return {state: 'node_not_found'};
                                node.imageIndex = imageIndex;
                                node.overIndex = imageIndex;
                                if (node.setDirtyCanvas) {
                                    node.setDirtyCanvas(true, true);
                                }
                                // SaveImage/PreviewImage adds "Save Image" only
                                // to its image-sensitive (right-click) menu.
                                const imageOptions = [];
                                if (typeof node.getExtraMenuOptions === 'function') {
                                    try {
                                        node.getExtraMenuOptions(app.canvas, imageOptions);
                                    } catch (error) {
                                        try {
                                            node.getExtraMenuOptions(null, imageOptions);
                                        } catch (_) {}
                                    }
                                }
                                const nodeOptions = app.canvas.getNodeMenuOptions
                                    ? (app.canvas.getNodeMenuOptions(node) || []) : [];
                                const options = [...imageOptions, ...nodeOptions];
                                if (!options.length) return {state: 'no_options'};
                                for (const option of options) {
                                    if (!option) continue;
                                    const label = option.content || option.label || '';
                                    const normalized = String(label).trim().toLowerCase()
                                        .replace(/[^a-z0-9]+/g, '');
                                    if (!actions.includes(normalized)) continue;
                                    if (!option.callback) {
                                        return {state: 'no_callback', label};
                                    }
                                    option.callback();
                                    return {state: 'invoked', label};
                                }
                                return {
                                    state: 'not_found',
                                    available: options.filter(Boolean).map(
                                        option => option.content || option.label || ''
                                    ),
                                };
                            }""",
                            {
                                "nodeId": node_id,
                                "actions": actions,
                                "imageIndex": image_index,
                            },
                        )
                    if (not isinstance(result, dict)
                            or result.get("state") != "invoked"):
                        raise RuntimeError(result or "unknown_error")

                    download = dl.value
                    suggested = Path(
                        download.suggested_filename
                        or f"output_{int(time.time())}.png"
                    ).name
                    suffix = Path(suggested).suffix or ".png"
                    filename = (
                        f"{Path(suggested).stem}_{image_index + 1:02d}{suffix}"
                    )
                    destination = base_dir / filename
                    collision = 1
                    while destination.exists():
                        destination = base_dir / (
                            f"{Path(filename).stem}_{collision}{suffix}"
                        )
                        collision += 1
                    download.save_as(str(destination))
                    saved.append(str(destination))
                    # Clear the enlarged/selected image before selecting the
                    # next thumbnail. This is equivalent to clicking its x.
                    self._comfy.evaluate(
                        """(nodeId) => {
                            const node = app.graph.getNodeById(Number(nodeId));
                            if (!node) return;
                            node.imageIndex = null;
                            node.overIndex = null;
                            if (node.setDirtyCanvas) node.setDirtyCanvas(true, true);
                        }""",
                        node_id,
                    )
                    logger.info(
                        "Saved preview image %d/%d: %s (%d bytes)",
                        image_index + 1, image_count, destination,
                        destination.stat().st_size,
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Preview image %d/%d save attempt %d failed: %s",
                        image_index + 1, image_count, attempt + 1,
                        str(exc)[:200],
                    )
                    self._page.wait_for_timeout(1000 * (attempt + 1))
            if last_error is not None:
                raise RuntimeError(
                    f"Output node {node_id} saved only {len(saved)}/{image_count} images"
                ) from last_error
        return saved

    def _download_via_context_menu(self, base_dir, output: Optional[OutputSpec] = None):
        """Invoke a configured save action and intercept its download."""
        self._dismiss_popups()
        self._dismiss_rife_popup()

        output = output or self.workflow_spec.outputs[0]
        node_id = output.node_id
        actions = [
            re.sub(r"[^a-z0-9]+", "", action.casefold())
            for action in output.menu_actions
        ]

        if output.media_type == "image":
            batch_saved = self._download_preview_batch(base_dir, output, actions)
            if batch_saved is not None:
                return batch_saved

        # Use ComfyUI's getNodeMenuOptions to find and invoke the
        # "Save preview" callback directly — no right-click needed.
        saved = []
        try:
            with self._page.expect_download(timeout=30000) as dl:
                result = self._comfy.evaluate(
                    "({actions,nodeId,mediaType}) => {"
                    "var n=app.graph.getNodeById(Number(nodeId));"
                    "if(!n)return {state:'node_not_found',configuredNodeId:String(nodeId)};"
                    "var opts=app.canvas.getNodeMenuOptions ? app.canvas.getNodeMenuOptions(n) : null;"
                    "if(!opts)return 'no_options';"
                    "for(var i=0;i<opts.length;i++) {"
                    "  var o=opts[i];"
                    "  if(!o) continue;"
                    "  var label=(o.content||o.label||'');"
                    "  var normalized=String(label).trim().toLowerCase().replace(/[^a-z0-9]+/g,'');"
                    "  if(actions.indexOf(normalized)!==-1) {"
                    "    if(o.callback) { o.callback(); return {state:'invoked',label:label}; }"
                    "    return {state:'no_callback',label:label};"
                    "  }"
                    "}"
                    "return {state:'not_found',nodeId:String(n.id),available:opts.filter(Boolean).map(function(o){return o.content||o.label||'';})};"
                    "}",
                    {"actions": actions, "nodeId": node_id, "mediaType": output.media_type},
                )
                logger.info("Output save result for node %s: %s", node_id, result)
                self._write_download_diagnostic({
                    "stage": "context_menu_result",
                    "node_id": node_id,
                    "result": result,
                })

            if not isinstance(result, dict) or result.get("state") != "invoked":
                raise RuntimeError(result or "unknown_error")

            download = dl.value
            extension = ".png" if output.media_type == "image" else ".mp4"
            fname = download.suggested_filename or f"output_{int(time.time())}{extension}"
            sp = base_dir / fname
            download.save_as(str(sp))
            saved.append(str(sp))
            logger.info(
                "Downloaded via %s: %s (%d bytes)",
                result.get("label"), sp, sp.stat().st_size,
            )
        except Exception as exc:
            self._write_download_diagnostic({
                "stage": "context_menu_failed",
                "node_id": node_id,
                "error": str(exc)[:500],
            })
            logger.warning("Configured output save failed: %s", str(exc)[:200])

        return saved

    def _download_via_page_links(self, base_dir):
        """Search the main RunningHub page for result download links.
        After a workflow completes, RunningHub may show a result panel
        with links to the generated output files."""
        import requests as req
        saved = []

        # Search the main page for any link pointing to an output file
        # RunningHub result links typically point to rh-images.xiaoyaoyou.com
        for sel in [
            'a[href*="output"]', 'a[href*=".mp4"]',
            'a[href*="rh-images"]', 'a[href*="xiaoyaoyou"]',
            'a[href*="download"]', 'a[href*="result"]',
            '[class*="result"] a', '[class*="output"] a',
        ]:
            try:
                for el in self._page.locator(sel).all():
                    href = el.get_attribute("href")
                    text = (el.text_content() or "").strip()
                    if href and len(href) > 20:
                        logger.info("Page link: text=%r href=%s", text[:80], href[:150])
                        # Download if it looks like a video output
                        if any(x in href.lower() for x in ['.mp4', 'output', 'xiaoyaoyou', 'rh-images']):
                            try:
                                fname = href.split("/")[-1].split("?")[0] or f"output_{int(time.time())}.mp4"
                                if not fname.endswith('.mp4'):
                                    fname += '.mp4'
                                sp = base_dir / fname
                                r = req.get(href, timeout=120)
                                r.raise_for_status()
                                if len(r.content) > 100000:  # >100KB
                                    sp.write_bytes(r.content)
                                    logger.info("Downloaded %d bytes -> %s", len(r.content), sp)
                                    saved.append(str(sp))
                                else:
                                    logger.info("Skipping small file: %d bytes", len(r.content))
                            except Exception as exc:
                                logger.warning("Download failed for %s: %s", href[:120], exc)
            except Exception:
                pass

        return saved

    def _download_via_links(self, base_dir):
        import requests as req
        saved = []
        for scope_name, scope in [("main", self._page), ("iframe", self._comfy)]:
            for sel in ['a[href*=".mp4"]', 'a[href*="output"]', 'a[href*="download"]']:
                try:
                    for el in scope.locator(sel).all():
                        href = el.get_attribute("href")
                        if href and href not in saved:
                            logger.info("Found link: %s", href[:120])
                            fname = href.split("/")[-1].split("?")[0] or f"output_{int(time.time())}.mp4"
                            sp = base_dir / fname
                            r = req.get(href, timeout=120)
                            r.raise_for_status()
                            sp.write_bytes(r.content)
                            saved.append(str(sp))
                except Exception:
                    pass
        return saved

    # =================================================================
    # Pipeline
    # =================================================================

    def run(self, *, video_path=None, model_image_path=None, image_path=None,
            clothing_image_path=None, seed=42, mode="plus",
            output_dir="./outputs", timeout=600, inputs=None):
        """Run the selected workflow with logical input names.

        ``inputs`` is the generic multi-workflow API. The named path arguments
        remain supported for callers of the original action-transfer workflow.
        """
        self._require_workflow_spec()
        if inputs is None:
            if model_image_path and image_path and model_image_path != image_path:
                raise ValueError(
                    "model_image_path and image_path refer to different files"
                )
            model_image_path = model_image_path or image_path
            inputs = {
                "video": video_path,
                "model": model_image_path,
                "clothing": clothing_image_path,
            }
        else:
            inputs = dict(inputs)

        # Validate all required logical inputs before opening a browser.
        self.workflow_spec.resolve_uploads(inputs)
        self.workflow_spec.resolve_texts(inputs)
        self.workflow_spec.resolve_widgets(inputs)
        target_node_ids = self._workflow_target_node_ids(inputs)
        self._raise_if_cancelled()

        try:
            self.start()
            self._raise_if_cancelled()
            self._report_progress("starting", "正在打开工作流")

            # Dismiss any notice/announcement modals that block the UI
            self._page.wait_for_timeout(1000)
            self._dismiss_stale_completion_popup()

            with _upload_lock:
                self._raise_if_cancelled()
                self._report_progress(
                    "positioning", "正在自动适配工作流操作节点"
                )
                self._fit_nodes_on_canvas(target_node_ids)
                self.set_node_modes()
                self.set_widget_inputs(inputs)
                self.upload_inputs(inputs)
                self.set_text_inputs(inputs)
            self._raise_if_cancelled()

            # ── Dismiss any stale completion popup from a previous run ──
            # If the browser session was reused or the page shows a leftover
            # "显示报告" popup from the last workflow, the detection loop
            # below would fire immediately and download old output files.
            self._dismiss_comfy_popups()
            self._dismiss_popups()
            # Verify no completion popup is already visible before we start
            if self._visible_completion_popup():
                logger.warning(
                    "Stale completion popup detected before run — dismissing"
                )
                self._dismiss_comfy_popups()
                self._dismiss_popups()
                self._page.wait_for_timeout(2000)

            output_media_baseline = self._output_media_fingerprints()

            # ── Run with retry on OOM errors ──
            max_retries = 3
            attempt = 0
            status = None
            # Exclude page loading, uploads and account queue time.
            execution_started_at = None
            execution_limit = min(max(1, int(timeout or 600)), 60 * 60)

            while attempt <= max_retries:
                self._raise_if_cancelled()
                if attempt > 0:
                    logger.info("Retry attempt %d/%d after OOM error",
                                attempt, max_retries)
                attempt += 1
                self._report_progress(
                    "running_workflow",
                    f"工作流运行中（尝试 {attempt}/{max_retries + 1}）",
                )

                # Click the Lite/Plus run button (serialized via lock so
                # only one task starts a workflow at a time)
                with _upload_lock:
                    if not self.select_plus_mode():
                        raise RuntimeError("未找到 Plus 模式运行按钮")

                if execution_started_at is None:
                    execution_started_at = time.monotonic()
                    logger.info("Workflow execution timer started (limit=%ds)", execution_limit)

                # Click a blank area to defocus / close any open popups
                self._page.mouse.click(10, 450)
                self._page.wait_for_timeout(1000)

                # Poll for completion or error popups.
                # Guard: refuse to accept completion before a minimum elapsed
                # time so a stale popup from a previous run is not mistaken for
                # a freshly completed workflow.
                min_run_seconds = self.workflow_spec.completion.minimum_run_seconds
                poll_interval = 2
                deadline = execution_started_at + execution_limit
                failure_first_seen_at = None
                queue_last_seen_at = None
                last_task_state = None
                while time.monotonic() < deadline or last_task_state == "queued":
                    self._raise_if_cancelled()
                    self._dismiss_cancel_popups()
                    elapsed = time.monotonic() - execution_started_at
                    if int(elapsed) % 30 < poll_interval:
                        detail = (
                            f"工作流运行中（已等待 {int(elapsed)} 秒，"
                            f"尝试 {attempt}/{max_retries + 1}）"
                        )
                        self._report_progress("running_workflow", detail)

                    # Check for success (completion popup)
                    if self._visible_completion_popup():
                        if elapsed < min_run_seconds:
                            logger.warning(
                                "Completion popup appeared after only %.0fs "
                                "(minimum %ds) — dismissing as stale and "
                                "continuing to wait",
                                elapsed, min_run_seconds,
                            )
                            self._dismiss_comfy_popups()
                            self._dismiss_popups()
                            self._page.wait_for_timeout(2000)
                            continue
                        status = "done"
                        break

                    # Completion is authoritative and must always be checked
                    # before the task list: RunningHub can show "任务失败" in
                    # the sidebar even after a workflow has completed.
                    task_list_state = self._current_task_list_state()
                    task_state = (task_list_state or {}).get("state")
                    last_task_state = task_state
                    now_monotonic = time.monotonic()
                    if task_state == "queued":
                        # RunningHub's own capacity queue is not workflow
                        # execution time. Extend the deadline for every period
                        # continuously observed in this state.
                        if queue_last_seen_at is not None:
                            deadline += max(0, now_monotonic - queue_last_seen_at)
                        queue_last_seen_at = now_monotonic
                        queue_text = task_list_state.get("text") or "排队中"
                        self._report_progress(
                            "running_workflow",
                            f"RunningHub {queue_text}，正在正常等待可用资源",
                        )
                    else:
                        queue_last_seen_at = None
                    previous_failure_seen_at = failure_first_seen_at
                    if (self.workflow_spec.completion.ignore_task_failure
                            and task_state == "failed"):
                        # Some workflows show "failed" in the task sidebar
                        # while their requested image node is still usable.
                        # For those workflows Show Report + output presence is
                        # the only authoritative result.
                        failure_first_seen_at = now_monotonic
                        failure_confirmed = False
                    else:
                        failure_first_seen_at, failure_confirmed = (
                            self._observe_task_failure(
                                task_list_state,
                                failure_first_seen_at,
                                time.monotonic(),
                            )
                        )
                    if (failure_first_seen_at is not None
                            and previous_failure_seen_at is None):
                        logger.warning(
                            "Task list shows failure; waiting for an "
                            "authoritative Show Report popup",
                        )
                        self._report_progress(
                            "running_workflow",
                            "检测到任务状态异常，正在确认工作流是否已经完成",
                        )
                    if failure_confirmed:
                        current_output_media = self._output_media_fingerprints()
                        if self._has_new_output_media(
                                output_media_baseline, current_output_media):
                            logger.warning(
                                "Task list shows failure, but configured output "
                                "node contains newly generated media; treating "
                                "the requested output as complete",
                            )
                            status = "done"
                            break
                        dialog_text = self._visible_error_dialog_text()
                        if dialog_text:
                            raise RuntimeError(
                                f"RunningHub 工作流执行失败：{dialog_text}"
                            )
                        raise RuntimeError(
                            "RunningHub 任务列表持续显示任务失败，且目标输出节点没有新结果"
                        )

                    # Check for error popups
                    err = self._detect_error_popup()
                    if err:
                        etype = err["type"]
                        logger.warning("Error popup [%s] detected, dismissing...",
                                       etype)
                        self._dismiss_error_popup()
                        self._page.wait_for_timeout(1000)

                        if etype == "oom":
                            # OOM: need to re-click Run after closing
                            logger.info("OOM error — will retry after dismiss")
                            # Click blank area to defocus
                            self._page.mouse.click(10, 450)
                            self._page.wait_for_timeout(1000)
                            break  # exit inner loop, retry from select_plus_mode
                        if etype == "vhs_error":
                            # Video processing error: retrying won't help
                            raise RuntimeError(
                                "VHS_LoadVideo 视频处理失败 (ZeroDivisionError)，"
                                "请检查视频文件是否损坏或格式不兼容"
                            )
                        if etype == "balance":
                            raise RuntimeError(
                                f"RunningHub/API 余额不足：{err.get('text', '')}"
                            )
                        if etype == "workflow_error":
                            raise RuntimeError(
                                f"RunningHub 工作流节点执行失败：{err.get('text', '')}"
                            )
                        # For other errors: just close, keep waiting
                        logger.info("Non-OOM error [%s] dismissed, continuing to wait",
                                    etype)
                        continue

                    # ---- Screenshot request (thread-safe IPC via threading.Event) ----
                    if self.screenshot_requested.is_set():
                        try:
                            self.screenshot_data = self.take_screenshot()
                            self.screenshot_error = None
                        except Exception as exc:
                            logger.warning("Screenshot failed: %s", exc)
                            self.screenshot_data = None
                            self.screenshot_error = str(exc)
                        finally:
                            self.screenshot_requested.clear()
                            self.screenshot_ready.set()

                    if self.cancel_requested.wait(poll_interval):
                        self._raise_if_cancelled()

                if status == "done":
                    break  # exit retry loop

                if time.monotonic() >= deadline:
                    logger.warning("Timeout on attempt %d/%d",
                                   attempt, max_retries + 1)
                    status = "timeout"
                    break

            logger.info("Final status: %s (retries used: %d)", status, attempt - 1)
            if status != "done":
                raise TimeoutError(
                    f"任务运行超时（{execution_limit} 秒），"
                    '未检测到带"显示报告/Show Report"的完成弹窗'
                )

            # Dismiss any ComfyUI iframe popups before downloading
            self._report_progress("downloading", "工作流完成，正在下载结果")
            self._dismiss_comfy_popups()
            self._page.wait_for_timeout(3000)

            self._raise_if_cancelled()
            files = self.download_outputs(output_dir)
            self._report_progress("completed", "结果已保存")
            return files
        finally:
            self.stop()

    # =================================================================
    # Setup login
    # =================================================================

    def setup_login(self):
        """Open the RunningHub login page and wait for manual login.

        Unlike ``start()`` this does *not* require a workflow URL/ID — it
        simply opens the site root so the user can sign in, then polls for
        the ``Rh-Accesstoken`` cookie and persists the session state.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Playwright 未安装。请先执行: pip install -r requirements.txt "
                "然后执行: python -m playwright install chromium"
            ) from exc

        _ensure_playwright_driver()
        _ensure_playwright_browsers_path()
        self._playwright = sync_playwright().start()
        launch_options = {
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        try:
            self._browser = self._playwright.chromium.launch(**launch_options)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Playwright Chromium 未安装。请执行: python -m playwright install chromium"
                ) from exc
            raise

        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            # Always start clean for login — stale cookies would prevent
            # the user from switching or refreshing their account.
        )
        self._page = self._context.new_page()
        self._page.goto("https://www.runninghub.cn", wait_until="domcontentloaded", timeout=60000)
        logger.info("Please log in manually on the RunningHub page.")
        try:
            self.ensure_logged_in(timeout=600)
            self._save_state()
            logger.info("Login saved!")
        except KeyboardInterrupt:
            self._save_state()
            logger.info("Login saved.")
        finally:
            self.stop()
