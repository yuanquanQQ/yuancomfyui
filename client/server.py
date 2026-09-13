#!/usr/bin/env python3
"""Local RunningHub multi-account task console."""

import http.server
import hashlib
from email.parser import BytesParser
from email.policy import default as email_policy
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from license_client import LicenseError, LicenseManager
from runninghub_client.browser import BrowserRunner, LoginExpiredError
from runninghub_client.workflow_specs import workflow_spec_from_dict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("server")

# ---- Application root resolution ----------------------------------------
# Bundled assets live in PyInstaller's extraction directory. Installed builds
# keep mutable state beside the executable so a portable/install-directory
# deployment keeps license, profiles and user files on the selected drive.
configured_data_root = os.environ.get("YUNCOMFYUI_DATA_DIR", "").strip()
if getattr(sys, "frozen", False):
    BUNDLE_ROOT = Path(sys._MEIPASS)
    INSTALL_ROOT = Path(sys.executable).resolve().parent
    if configured_data_root:
        APP_ROOT = Path(configured_data_root).expanduser().resolve()
    else:
        # Keep mutable files separate from the executable. Inno Setup removes
        # only the program on uninstall, so this directory survives a normal
        # uninstall/reinstall on the selected drive.
        APP_ROOT = INSTALL_ROOT / "UserData"
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent
    INSTALL_ROOT = BUNDLE_ROOT
    APP_ROOT = (
        Path(configured_data_root).expanduser().resolve()
        if configured_data_root else BUNDLE_ROOT
    )


def _migrate_legacy_install_data(legacy_root: Path, target_root: Path) -> None:
    """Copy one previous data root once, without overwriting newer data."""
    try:
        if legacy_root.resolve() == target_root.resolve():
            return
        if not legacy_root.is_dir():
            # Do not mark an unavailable old drive as migrated. Its registry
            # entry is retained and migration can resume if the drive returns.
            return
        # A source-mode installer briefly used UserData without running the
        # frozen-build migration. It may therefore have created a fresh,
        # unactivated state before the older valid state was discovered. A
        # valid signed receipt is more valuable than that empty state and must
        # be recovered even when this source already has a migration marker.
        source_license = legacy_root / ".license" / "license_state.json"
        target_license = target_root / ".license" / "license_state.json"
        try:
            source_state = json.loads(source_license.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            source_state = {}
        try:
            target_state = json.loads(target_license.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            target_state = {}
        source_has_license = bool(
            source_state.get("receipt") and source_state.get("public_key_pem")
        )
        target_has_license = bool(
            target_state.get("receipt") and target_state.get("public_key_pem")
        )
        if source_has_license and not target_has_license:
            target_license.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_license, target_license)
            logger.info("Recovered existing license state from %s", legacy_root)
        source_key = hashlib.sha256(
            str(legacy_root.resolve()).casefold().encode("utf-8")
        ).hexdigest()[:16]
        marker = target_root / f".migrated-{source_key}"
        if marker.exists():
            return
        target_root.mkdir(parents=True, exist_ok=True)
        for directory_name in (".license", "profiles", "data", "uploads", "outputs", "library", "works"):
            source = legacy_root / directory_name
            if not source.is_dir():
                continue
            for source_path in source.rglob("*"):
                destination = target_root / directory_name / source_path.relative_to(source)
                if source_path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, destination)
        marker.write_text("migrated\n", encoding="ascii")
    except OSError as exc:
        logger.warning("Legacy client data migration failed: %s", exc)


def _known_data_roots() -> list[Path]:
    """Read prior data locations; these registry values survive uninstall."""
    if os.name != "nt":
        return []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\YunComfyUI\Client") as key:
            values = []
            try:
                value, _ = winreg.QueryValueEx(key, "DataRoot")
                if value:
                    values.append(value)
            except OSError:
                pass
            try:
                history, _ = winreg.QueryValueEx(key, "DataRoots")
                values.extend(history if isinstance(history, list) else [])
            except OSError:
                pass
        roots = []
        for value in values:
            root = Path(str(value)).expanduser().resolve()
            if root not in roots:
                roots.append(root)
        return roots
    except (OSError, ValueError):
        return []


def _remember_data_root(data_root: Path) -> None:
    """Remember data independently of the installer's uninstall registry."""
    if os.name != "nt":
        return
    try:
        import winreg
        current = str(data_root.resolve())
        history = [current] + [str(root) for root in _known_data_roots()]
        history = list(dict.fromkeys(history))[:10]
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\YunComfyUI\Client") as key:
            winreg.SetValueEx(key, "DataRoot", 0, winreg.REG_SZ, current)
            winreg.SetValueEx(key, "DataRoots", 0, winreg.REG_MULTI_SZ, history)
    except OSError as exc:
        logger.warning("Unable to remember client data location: %s", exc)


def _legacy_default_data_roots() -> list[Path]:
    """Return known install roots used before the persistent UserData layout."""
    if os.name != "nt":
        return []
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    candidates = [
        local_app_data / "Programs" / "YunComfyUI" / "Client",
        local_app_data / "YunComfyUI" / "Client",
    ]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "YunComfyUI" / "Client")
    # A user may have chosen another drive while retaining Inno Setup's
    # default directory shape. Checking these exact paths is fast and bounded.
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        if not drive.is_dir():
            continue
        candidates.extend([
            drive / "Program Files" / "YunComfyUI" / "Client",
            drive / "Program Files (x86)" / "YunComfyUI" / "Client",
            drive / "YunComfyUI" / "Client",
        ])
    return list(dict.fromkeys(path.resolve() for path in candidates))


if getattr(sys, "frozen", False):
    _legacy_local = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "YunComfyUI" / "Client"
    )
    # Sources cover: the immediately previous build (data beside the EXE), a
    # reinstall on another drive/path, and the oldest LocalAppData builds.
    _migration_sources = [
        INSTALL_ROOT,
        *_known_data_roots(),
        *_legacy_default_data_roots(),
        _legacy_local,
    ]
    for _previous_root in dict.fromkeys(_migration_sources):
        if _previous_root:
            _migrate_legacy_install_data(_previous_root, APP_ROOT)
    _remember_data_root(APP_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(INSTALL_ROOT / ".env", override=False)
    if APP_ROOT != INSTALL_ROOT:
        load_dotenv(APP_ROOT / ".env", override=False)
except ImportError:
    pass

ROOT = APP_ROOT  # legacy alias used throughout
DATA = APP_ROOT / "data"
UPLOADS = APP_ROOT / "uploads"
PROFILES = APP_ROOT / "profiles"
STATIC = BUNDLE_ROOT / "static"
DEFAULT_PORT = 8081
PORT_SCAN_ATTEMPTS = 100
MAX_WORKERS = 10
LOGIN_WORKERS = 2
QUEUE_TIMEOUT_SECONDS = int(os.environ.get("QUEUE_TIMEOUT_SECONDS", "86400"))
MAX_TASK_REQUEUES = int(os.environ.get("MAX_TASK_REQUEUES", "3"))


def _browser_headless() -> bool:
    """Choose browser visibility; packaged clients default to headless."""
    default = "1" if getattr(sys, "frozen", False) else "0"
    value = os.environ.get("YUNCOMFYUI_HEADLESS", default).strip().lower()
    return value not in {"0", "false", "no", "off", "headed"}


def _configured_port() -> int:
    """Return the preferred local port, allowing an environment override."""
    raw = os.environ.get("YUNCOMFYUI_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"YUNCOMFYUI_PORT 不是有效端口: {raw!r}") from exc
    if not 0 <= port <= 65535:
        raise ValueError(f"YUNCOMFYUI_PORT 超出有效范围: {port}")
    return port


class LocalThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """A local server that cannot share its listening port on Windows."""

    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
            )
        super().server_bind()


def _create_http_server(preferred_port: int, *, server_class=None):
    """Bind the preferred port or the first available following port.

    Port 0 is preserved as an explicit request for an operating-system chosen
    ephemeral port.  Otherwise a bounded consecutive range is scanned by
    binding directly, which avoids a check-then-bind race.
    """
    server_class = server_class or LocalThreadingHTTPServer
    if preferred_port == 0:
        server = server_class(("127.0.0.1", 0), Handler)
        return server, int(server.server_address[1])

    last_error = None
    final_port = min(65535, preferred_port + PORT_SCAN_ATTEMPTS - 1)
    for candidate in range(preferred_port, final_port + 1):
        try:
            server = server_class(("127.0.0.1", candidate), Handler)
            if candidate != preferred_port:
                logger.warning(
                    "Preferred port %d is unavailable; using %d instead",
                    preferred_port, candidate,
                )
            return server, int(server.server_address[1])
        except OSError as exc:
            last_error = exc

    raise OSError(
        f"本机端口 {preferred_port}-{final_port} 均不可用"
    ) from last_error


def _write_server_state(actual_port: int) -> Path:
    """Publish the selected port for local launch/restart helpers."""
    runtime_dir = APP_ROOT / ".runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / "server.json"
    temp_path = runtime_dir / f".server.{os.getpid()}.{time.time_ns()}.tmp"
    temp_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": actual_port,
                "url": f"http://127.0.0.1:{actual_port}",
                "started_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temp_path, state_path)
    return state_path

DEFAULT_WORKFLOW_KEY = ""
DEFAULT_WORKFLOW_NAME = "工作流"
WORKFLOWS: dict[str, dict] = {}
_workflow_catalog_lock = threading.RLock()
_library_lock = threading.RLock()
_workflow_catalog_loaded_at = 0.0

# ---- Ensure required directories exist ----------------------------------
LIBRARY = APP_ROOT / "library"
WORKS = APP_ROOT / "works"
LIBRARY_META = LIBRARY / ".metadata.json"


def _quarantine_damaged_path(path: Path) -> Path:
    """Move an unusable runtime path aside so a clean one can be rebuilt."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.damaged-{timestamp}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(
            f"{path.name}.damaged-{timestamp}-{counter}"
        )
        counter += 1
    path.replace(candidate)
    logger.warning("Quarantined damaged runtime path: %s -> %s", path, candidate)
    return candidate


def _ensure_runtime_layout(app_root: Path | None = None) -> dict[str, Path]:
    """Recreate disposable runtime structure deleted/damaged by the user."""
    root = Path(app_root or APP_ROOT)
    library = root / "library"
    required_dirs = (
        root,
        root / "data",
        library,
        root / ".license",
        root / ".runtime",
        root / "data" / "pic",
        root / "data" / "ple",
        root / "data" / "video",
        root / "uploads",
        root / "profiles",
        root / "outputs",
        library / "images",
        library / "videos",
        library / "audio",
        library / "texts",
        root / "works",
    )
    for directory in required_dirs:
        if directory.exists() and not directory.is_dir():
            _quarantine_damaged_path(directory)
        directory.mkdir(parents=True, exist_ok=True)

    metadata = library / ".metadata.json"
    valid_metadata = False
    if metadata.is_file():
        try:
            valid_metadata = isinstance(
                json.loads(metadata.read_text(encoding="utf-8")), dict
            )
        except (OSError, ValueError, TypeError):
            pass
    if metadata.exists() and not valid_metadata:
        _quarantine_damaged_path(metadata)
    if not valid_metadata:
        metadata.write_text("{}\n", encoding="utf-8")
        logger.info("Rebuilt missing/damaged library metadata: %s", metadata)
    return {"root": root, "library_metadata": metadata}


_ensure_runtime_layout()

LICENSE = LicenseManager(
    APP_ROOT / ".license",
    os.environ.get("LICENSE_SERVER_URL", "http://124.223.224.38"),
)

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="runner")
_login_executor = ThreadPoolExecutor(max_workers=LOGIN_WORKERS, thread_name_prefix="login")
_tasks: dict[str, dict] = {}
_task_queue: deque[str] = deque()
_account_busy: set[str] = set()
_tasks_lock = threading.RLock()
_login_processes: dict[str, object] = {}
_login_sessions: dict[str, dict] = {}
_login_lock = threading.RLock()
_shutdown_lock = threading.Lock()
_shutdown_started = False

LOGIN_STAGES = {
    "starting", "slider", "code_required", "verifying",
    "completed", "failed", "stopped",
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for attempt in range(8):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 7:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(0.015 * (attempt + 1))


def _new_login_session(account: str) -> dict:
    now = time.time()
    return {
        "account": account,
        "session_id": uuid.uuid4().hex,
        "token": secrets.token_urlsafe(32),
        "stage": "starting",
        "detail": "Opening RunningHub SMS login",
        "error": None,
        "cancel_requested": False,
        "created_at": now,
        "updated_at": now,
        "frame": None,
        "frame_updated_at": None,
        "events": deque(),
    }


def _public_login_session(session: dict | None) -> dict | None:
    if not session:
        return None
    return {
        "session_id": session["session_id"],
        "stage": session["stage"],
        "detail": session.get("detail"),
        "error": session.get("error"),
        "updated_at": session.get("updated_at"),
    }


def _find_login_session_locked(session_id: str) -> dict | None:
    if not session_id:
        return None
    for session in _login_sessions.values():
        if secrets.compare_digest(session["session_id"], session_id):
            return session
    return None


def _current_login_session_locked(account: str, session_id: str) -> dict | None:
    session = _login_sessions.get(account)
    if not session or not session_id:
        return None
    if not secrets.compare_digest(session["session_id"], session_id):
        return None
    return session


def _set_login_status_locked(
        session: dict, stage: str, detail: str | None, error=None) -> None:
    session["stage"] = stage
    session["detail"] = detail
    session["error"] = error
    session["updated_at"] = time.time()
    # A captcha frame is meaningful only while the official slider is active.
    # Clearing under the same lock prevents an in-flight stale frame response.
    if stage != "slider":
        session["frame"] = None
        session["frame_updated_at"] = None


def _queue_login_event_locked(session: dict, event: dict) -> None:
    events = session["events"]
    if event.get("type") == "move" and events and events[-1].get("type") == "move":
        events[-1] = event
    else:
        events.append(event)
    # Do not let an abandoned browser session grow without bound. Prefer
    # dropping old move samples while preserving mouse boundaries and commands.
    while len(events) > 512:
        move_index = next(
            (index for index, item in enumerate(events)
             if item.get("type") == "move"),
            None,
        )
        if move_index is None:
            events.popleft()
        else:
            del events[move_index]


def _normalize_phone(value: str) -> tuple[str, str]:
    phone = str(value or "").strip()
    account_id = re.sub(r"\D", "", phone)
    if not 6 <= len(account_id) <= 20:
        raise ValueError("请输入 6–20 位有效电话号码")
    return phone, account_id


def _refresh_workflow_catalog(force=False) -> None:
    global DEFAULT_WORKFLOW_KEY, DEFAULT_WORKFLOW_NAME, WORKFLOWS
    global _workflow_catalog_loaded_at
    with _workflow_catalog_lock:
        if (not force and WORKFLOWS
                and time.time() - _workflow_catalog_loaded_at < 60):
            return
        try:
            catalog = LICENSE.fetch_workflows()
        except ConnectionError:
            if WORKFLOWS:
                return
            raise
        parsed = {}
        for item in catalog["workflows"]:
            if not isinstance(item, dict):
                raise LicenseError("工作流服务返回的数据无效")
            key = str(item.get("key") or "").strip()
            post_id = str(item.get("post_id") or "").strip()
            workflow_id = str(item.get("workflow_id") or "").strip()
            if not re.fullmatch(r"[a-z0-9_]{1,64}", key):
                raise LicenseError("工作流标识无效")
            if not re.fullmatch(r"\d{6,30}", post_id or workflow_id):
                raise LicenseError(f"工作流 {key} 的 RunningHub ID 无效")
            workflow = dict(item)
            workflow["post_id"] = post_id
            workflow["workflow_id"] = workflow_id
            workflow["inputs"] = tuple(workflow.get("inputs") or ())
            workflow["timeout"] = int(workflow.get("timeout") or 3000)
            workflow["spec"] = workflow_spec_from_dict(workflow.get("spec") or {})
            parsed[key] = workflow
        default_key = str(catalog.get("default_workflow_key") or "").strip()
        if not parsed or default_key not in parsed:
            raise LicenseError("服务器没有提供可用工作流")
        WORKFLOWS = parsed
        DEFAULT_WORKFLOW_KEY = default_key
        DEFAULT_WORKFLOW_NAME = parsed[default_key]["name"]
        _workflow_catalog_loaded_at = time.time()


def _clear_workflow_catalog() -> None:
    global DEFAULT_WORKFLOW_KEY, DEFAULT_WORKFLOW_NAME, WORKFLOWS
    global _workflow_catalog_loaded_at
    with _workflow_catalog_lock:
        WORKFLOWS = {}
        DEFAULT_WORKFLOW_KEY = ""
        DEFAULT_WORKFLOW_NAME = "工作流"
        _workflow_catalog_loaded_at = 0.0


def _workflow_config(key: str | None, require_configured=True) -> dict:
    _refresh_workflow_catalog()
    workflow_key = str(key or DEFAULT_WORKFLOW_KEY).strip()
    workflow = WORKFLOWS.get(workflow_key)
    if not workflow:
        raise ValueError("未知的工作流")
    if require_configured and not (workflow.get("post_id") or workflow.get("workflow_id")):
        raise ValueError(
            f"{workflow['name']} 尚未配置 RunningHub Post/Workflow ID"
        )
    return workflow


def _public_workflows() -> list[dict]:
    _refresh_workflow_catalog()
    return [
        {
            "key": workflow["key"],
            "name": workflow["name"],
            "description": workflow["description"],
            "category": workflow["category"],
            "configured": bool(workflow.get("post_id") or workflow.get("workflow_id")),
            "inputs": list(workflow["inputs"]),
        }
        for workflow in WORKFLOWS.values()
    ]


def _session_info(state_path: Path) -> dict:
    if not state_path.exists():
        return {"valid": False, "status": "missing", "expires_at": None}
    data = _read_json(state_path, {})
    token = next((c for c in data.get("cookies", [])
                  if c.get("name") == "Rh-Accesstoken"), None)
    if not token:
        return {"valid": False, "status": "missing", "expires_at": None}
    try:
        expires = float(token.get("expires", -1))
    except (TypeError, ValueError):
        expires = -1
    # RunningHub re-stamps the auth cookie's ``expires`` attribute to the next
    # silent-refresh time, so a freshly saved state.json can show a *past*
    # attribute while the JWT itself remains valid for days.  Trust the JWT
    # ``exp`` claim when present; fall back to the cookie attribute.
    jwt_exp = 0.0
    try:
        import base64
        seg = str(token.get("value", "")).split(".")[1]
        seg += "=" * (-len(seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg))
        candidate = float(payload.get("exp", 0))
        if 0 < candidate <= 1e12:
            jwt_exp = candidate
    except (IndexError, ValueError, TypeError, KeyError):
        jwt_exp = 0.0
    if jwt_exp:
        expires = jwt_exp
    expired = expires > 0 and expires <= time.time()
    return {
        "valid": not expired,
        "status": "expired" if expired else "valid",
        "expires_at": expires if expires > 0 else None,
    }


def _login_thread(account, profile, session_id):
    """Run browser login in a background thread (EXE mode)."""
    try:
        from runninghub_client.browser import BrowserRunner
        runner = BrowserRunner(user_data_dir=str(profile), headless=False)
        runner.setup_login()
        cfg_path = profile / "config.json"
        cfg = _read_json(cfg_path, {})
        cfg["last_login_at"] = time.time()
        cfg.pop("last_login_error", None)
        _write_json(cfg_path, cfg)
        with _login_lock:
            session = _current_login_session_locked(account, session_id)
            if session:
                _set_login_status_locked(
                    session, "completed", "RunningHub login succeeded")
        logger.info("Login thread %s completed successfully", account)
    except Exception as exc:
        cfg_path = profile / "config.json"
        cfg = _read_json(cfg_path, {})
        cfg["last_login_error"] = str(exc)
        _write_json(cfg_path, cfg)
        with _login_lock:
            session = _current_login_session_locked(account, session_id)
            if session:
                _set_login_status_locked(
                    session, "failed", "RunningHub login failed", str(exc))
        logger.error("Login thread %s failed: %s", account, exc)
    finally:
        with _login_lock:
            if _login_processes.get(account) == session_id:
                _login_processes.pop(account, None)
        _dispatch_tasks()


def _reap_login_processes():
    with _login_lock:
        # Subprocess-based login (dev mode)
        for account, proc in list(_login_processes.items()):
            if hasattr(proc, "poll") and proc.poll() is not None:
                _login_processes.pop(account, None)
                cfg_path = PROFILES / account / "config.json"
                cfg = _read_json(cfg_path, {})
                valid_session = _session_info(
                    PROFILES / account / "state.json"
                )["valid"]
                process_session_id = getattr(proc, "_login_session_id", "")
                session = _current_login_session_locked(
                    account, process_session_id
                )
                if proc.returncode == 0 and valid_session:
                    cfg["last_login_at"] = time.time()
                    cfg.pop("last_login_error", None)
                    if session and session["stage"] not in ("completed", "failed"):
                        _set_login_status_locked(
                            session, "completed", "RunningHub login succeeded")
                elif proc.returncode != 0:
                    cfg["last_login_error"] = f"登录进程退出，代码 {proc.returncode}"
                    if session and session["stage"] not in ("failed", "stopped"):
                        _set_login_status_locked(
                            session,
                            "failed",
                            "RunningHub login process exited unexpectedly",
                            f"exit code {proc.returncode}",
                        )
                if cfg:
                    _write_json(cfg_path, cfg)
        # Thread-based login (EXE mode) — threads clean themselves up via finally

    # Check if any accounts finished logging in
    finished = any(
        not (hasattr(p, "poll") and p.poll() is None)
        and not isinstance(p, str)
        for p in list(_login_processes.values())
    )
    if finished:
        _dispatch_tasks()


def _shutdown_application():
    """Cancel active work and terminate child processes before pywebview exits."""
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    now = time.time()
    with _tasks_lock:
        queued = list(_task_queue)
        _task_queue.clear()
        for task_id in queued:
            task = _tasks.get(task_id)
            if task and task.get("status") == "queued":
                task.update({
                    "status": "cancelled", "stage": "cancelled",
                    "stage_detail": "应用已关闭，任务已取消",
                    "completed_at": now, "error": "应用已关闭，任务已取消",
                })
        runners = [
            task.get("runner") for task in _tasks.values()
            if task.get("status") == "running" and task.get("runner")
        ]
        for task in _tasks.values():
            if task.get("status") == "running":
                task["cancel_requested"] = True
                task.update({
                    "status": "cancelled", "stage": "cancelled",
                    "stage_detail": "应用已关闭，正在取消任务",
                    "completed_at": now, "error": "应用已关闭，任务已取消",
                })
        _account_busy.clear()
    for runner in runners:
        try:
            runner.request_cancel()
        except Exception:
            logger.exception("Failed to request browser task cancellation")

    with _login_lock:
        login_items = list(_login_processes.items())
        _login_processes.clear()
        for _account, session in _login_sessions.items():
            if session.get("stage") not in {"completed", "failed", "stopped"}:
                _set_login_status_locked(session, "stopped", "应用已关闭")
    for _account, proc in login_items:
        if proc and hasattr(proc, "poll") and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    logger.info("Application shutdown requested; active tasks and logins cancelled")


def _account_list() -> list[dict]:
    PROFILES.mkdir(parents=True, exist_ok=True)
    _reap_login_processes()
    with _login_lock:
        logging_accounts = set(_login_processes)
        login_sessions = {
            account: _public_login_session(session)
            for account, session in _login_sessions.items()
        }
    with _tasks_lock:
        busy_accounts = set(_account_busy)

    accounts = []
    for profile in sorted((p for p in PROFILES.iterdir() if p.is_dir()),
                          key=lambda p: p.name):
        cfg = _read_json(profile / "config.json", {})
        session = _session_info(profile / "state.json")
        login_session = login_sessions.get(profile.name)
        phone = str(cfg.get("phone") or (profile.name if profile.name != "default" else "未登记号码"))
        accounts.append({
            "id": profile.name,
            "name": profile.name,
            "phone": phone,
            "session_valid": session["valid"],
            "session_status": session["status"],
            "session_expires_at": session["expires_at"],
            "login_in_progress": profile.name in logging_accounts,
            "busy": profile.name in busy_accounts,
            "ready": bool(
                session["valid"] and profile.name not in logging_accounts
            ),
            "last_login_at": cfg.get("last_login_at"),
            "last_login_error": cfg.get("last_login_error"),
            "login_session_id": (
                login_session.get("session_id") if login_session else None
            ),
            "login_stage": (
                login_session.get("stage") if login_session else None
            ),
            "login_detail": (
                login_session.get("detail") if login_session else None
            ),
            "login_error": (
                login_session.get("error") if login_session else None
            ),
            "login_updated_at": (
                login_session.get("updated_at") if login_session else None
            ),
        })
    return accounts


def _ready_account_ids() -> list[str]:
    return [
        a["id"] for a in _account_list()
        if a["ready"] and not a["login_in_progress"]
    ]


def _scan_files():
    result = {}
    for cat in ("video", "pic", "ple"):
        directory = DATA / cat
        result[cat] = [
            {"name": f.name, "path": str(f.relative_to(ROOT)).replace("\\", "/")}
            for f in sorted(directory.iterdir()) if f.is_file()
        ] if directory.is_dir() else []
    return result

def _library_items():
    types = {"images": "image", "videos": "video", "audio": "audio", "texts": "text"}
    items = []
    metadata = _read_json(LIBRARY_META, {})
    for folder, kind in types.items():
        root = LIBRARY / folder
        for f in root.rglob("*") if root.exists() else ():
            if f.is_file() and f != LIBRARY_META:
                preview = ""
                if kind == "text":
                    try:
                        preview = f.read_text(encoding="utf-8", errors="replace")[:800]
                    except OSError:
                        pass
                item_id = str(f.relative_to(LIBRARY)).replace("\\", "/")
                item_meta = metadata.get(item_id, {})
                items.append({"id": item_id, "name": f.name,
                              "type": kind, "path": str(f.relative_to(ROOT)).replace("\\", "/"),
                              "folder": str(f.parent.relative_to(root)).replace("\\", "/") if f.parent != root else "默认",
                              "size": f.stat().st_size, "updated_at": f.stat().st_mtime,
                              "preview": preview, "tags": item_meta.get("tags", []),
                              "imported_at": item_meta.get("imported_at", f.stat().st_mtime)})
    return sorted(items, key=lambda x: x["updated_at"], reverse=True)

def _works_items():
    out = []
    for f in WORKS.rglob("*") if WORKS.exists() else ():
        if f.is_file():
            parts = f.relative_to(WORKS).parts
            out.append({"name": f.name, "path": str(f.relative_to(ROOT)).replace("\\", "/"),
                        "date": parts[0] if parts else "", "phone": parts[1] if len(parts)>1 else "",
                        "workflow": parts[2] if len(parts)>2 else "", "size": f.stat().st_size,
                        "updated_at": f.stat().st_mtime})
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


def _resolve_material(value: str | None, category: str, required=True) -> str | None:
    if not value:
        if required:
            raise ValueError(f"缺少 {category} 素材")
        return None
    path = (ROOT / unquote(str(value))).resolve()
    base = (DATA / category).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError(f"无效的 {category} 素材路径")
    return str(path)


def _resolve_uploaded_material(value: str | None, required=True) -> str | None:
    if not value:
        if required:
            raise ValueError("缺少上传素材")
        return None
    raw = unquote(str(value))
    candidate = Path(raw)
    path = (candidate if candidate.is_absolute() else ROOT / raw).resolve()
    if not path.is_file() or not any(
        path.is_relative_to(base.resolve()) for base in (UPLOADS, DATA, LIBRARY)
    ):
        raise ValueError("素材必须来自工作台上传或素材目录")
    return str(path)


def _parse_boolean(value, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on", "是"}:
            return True
        if normalized in {"false", "no", "0", "off", "否"}:
            return False
    raise ValueError(f"{label}必须是开关值")


def _input_is_required(input_spec: dict, values: dict) -> bool:
    condition = input_spec.get("required_when")
    if isinstance(condition, dict) and condition.get("key"):
        return _input_condition_met(input_spec, values)
    return bool(input_spec.get("required", True))


def _input_condition_met(input_spec: dict, values: dict) -> bool:
    condition = input_spec.get("required_when")
    if not isinstance(condition, dict) or not condition.get("key"):
        return True
    return values.get(condition["key"]) == condition.get("equals", True)


def _parse_numeric_input(raw_value, input_spec: dict):
    label = input_spec.get("label", input_spec["key"])
    input_type = input_spec.get("input_type")
    if isinstance(raw_value, bool):
        raise ValueError(f"{label}必须是数字")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label}必须是有限数字")
    if input_type == "integer":
        if not value.is_integer():
            raise ValueError(f"{label}必须是整数")
        value = int(value)
    minimum = input_spec.get("min")
    maximum = input_spec.get("max")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label}不能小于{minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label}不能大于{maximum}")
    return value


def _resolve_workflow_inputs(workflow: dict, data: dict) -> dict[str, object]:
    resolved: dict[str, object] = {}
    input_specs = workflow["inputs"]

    # Resolve switches first so conditional file requirements do not depend
    # on the order in which fields happen to appear in the catalog.
    for input_spec in input_specs:
        if input_spec.get("input_type") != "boolean":
            continue
        key = input_spec["key"]
        label = input_spec.get("label", key)
        raw_value = data.get(key, input_spec.get("default"))
        if raw_value is None:
            if _input_is_required(input_spec, resolved):
                raise ValueError(f"缺少{label}")
            continue
        resolved[key] = _parse_boolean(raw_value, label)

    for input_spec in input_specs:
        key = input_spec["key"]
        if input_spec.get("input_type") == "boolean":
            continue
        label = input_spec.get("label", key)
        if not _input_condition_met(input_spec, resolved):
            continue
        required = _input_is_required(input_spec, resolved)
        input_type = input_spec.get("input_type")
        if input_type == "text":
            value = str(
                data.get(key) or input_spec.get("default") or ""
            ).strip()
            if not value:
                if required:
                    raise ValueError(f"缺少{label}")
                continue
            resolved[key] = value
            continue
        if input_type in {"number", "integer"}:
            raw_value = data.get(key, input_spec.get("default"))
            if raw_value in (None, ""):
                if required:
                    raise ValueError(f"缺少{label}")
                continue
            resolved[key] = _parse_numeric_input(raw_value, input_spec)
            continue
        try:
            value = _resolve_uploaded_material(data.get(key), required=required)
        except ValueError as exc:
            raise ValueError(f"{label}：{exc}") from exc
        if value is not None:
            resolved[key] = value
    return resolved


def _resolve_batch_workflow_inputs(workflow: dict, data: dict) -> list[dict[str, object]]:
    raw_inputs = data.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise ValueError("批量任务缺少 inputs")

    repeat = int(data.get("repeat", 1))
    if not 1 <= repeat <= 20:
        raise ValueError("每组生成次数必须在 1–20 之间")

    resolved: dict[str, list[object | None]] = {}
    group_count = 1
    input_specs = workflow["inputs"]

    for input_spec in input_specs:
        if input_spec.get("input_type") != "boolean":
            continue
        key = input_spec["key"]
        label = input_spec.get("label", key)
        raw_values = raw_inputs.get(key)
        if raw_values is None and "default" in input_spec:
            raw_values = [input_spec["default"]]
        if not isinstance(raw_values, list):
            raise ValueError(f"{label}必须是批量列表")
        if not raw_values:
            raise ValueError(f"缺少{label}")
        values = [_parse_boolean(value, label) for value in raw_values]
        resolved[key] = values
        group_count = max(group_count, len(values))

    for input_spec in input_specs:
        key = input_spec["key"]
        if input_spec.get("input_type") == "boolean":
            continue
        label = input_spec.get("label", key)
        raw_values = raw_inputs.get(key)
        input_type = input_spec.get("input_type")
        if (input_type in {"text", "number", "integer"}
                and not raw_values and "default" in input_spec):
            raw_values = [input_spec["default"]]
        may_be_optional = (
            not input_spec.get("required", True)
            or bool(input_spec.get("required_when"))
        )
        if raw_values is None and may_be_optional:
            raw_values = []
        if not isinstance(raw_values, list):
            raise ValueError(f"{label}必须是批量列表")
        if input_type in {"number", "integer"}:
            values = [
                _parse_numeric_input(value, input_spec)
                for value in raw_values if value not in (None, "")
            ]
            resolved[key] = values or [None]
        else:
            values = [str(value or "").strip() for value in raw_values]
            values = [value for value in values if value]

        if input_type == "text":
            resolved[key] = values or [None]
        elif input_type not in {"number", "integer"}:
            try:
                resolved[key] = ([
                    _resolve_uploaded_material(value) for value in values
                ] or [None])
            except ValueError as exc:
                raise ValueError(f"{label}：{exc}") from exc
        group_count = max(group_count, len(resolved[key]))

    task_count = group_count * repeat
    if task_count > 500:
        raise ValueError("单个批次最多创建 500 个任务")

    combinations = []
    for group_index in range(group_count):
        candidate = {
            key: values[group_index % len(values)]
            for key, values in resolved.items()
        }
        for input_spec in input_specs:
            key = input_spec["key"]
            if _input_is_required(input_spec, candidate) and candidate.get(key) is None:
                raise ValueError(f"缺少{input_spec.get('label', key)}")
        group = {
            key: value for key, value in candidate.items()
            if value is not None and _input_condition_met(
                next(spec for spec in input_specs if spec["key"] == key),
                candidate,
            )
        }
        for _ in range(repeat):
            combinations.append(dict(group))
    return combinations


def _new_task(
    workflow: dict,
    input_paths: dict[str, object],
    requested_account: str,
    now: float | None = None,
) -> dict:
    created_at = now if now is not None else time.time()
    task_id = f"task_{int(created_at * 1000)}_{uuid.uuid4().hex[:6]}"
    input_types = {
        item["key"]: item.get("input_type", "file")
        for item in workflow["inputs"]
    }
    input_files = {}
    for key, value in input_paths.items():
        input_type = input_types.get(key)
        if input_type in {"text", "number", "integer"}:
            input_files[key] = str(value)[:80]
        elif input_type == "boolean":
            input_files[key] = "开启" if value else "关闭"
        else:
            input_files[key] = Path(str(value)).name
    primary_key = workflow["primary_input"]
    task = {
        "task_id": task_id,
        "workflow_key": workflow["key"],
        "workflow_name": workflow["name"],
        "task_name": input_files.get(primary_key) or workflow["name"],
        "status": "queued",
        "requested_account": requested_account,
        "account": None,
        "phone": None,
        "workflow_id": None,
        "post_id": None,
        "input_files": input_files,
        "input_paths": dict(input_paths),
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "stage": "queued",
        "stage_detail": "等待可用账号",
        "heartbeat_at": created_at,
        "files": [],
        "error": None,
    }
    for legacy_key in ("video", "model", "clothing"):
        task[legacy_key] = input_files.get(legacy_key)
        task[f"{legacy_key}_path"] = input_paths.get(legacy_key)
    return task


def _parse_multipart_file(headers, body: bytes):
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("请使用 multipart/form-data 上传文件")
    message = BytesParser(policy=email_policy).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: "
        + content_type.encode("utf-8") + b"\r\n\r\n" + body
    )
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        filename = part.get_filename()
        if filename:
            return Path(filename).name, part.get_payload(decode=True) or b""
    raise ValueError("上传请求中没有文件")


def _update_task_progress(task_id: str, stage: str, detail: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task and task.get("status") == "running":
            retry_count = int(task.get("retry_count") or 0)
            if retry_count:
                detail = (
                    f"自动重试 {retry_count}/{MAX_TASK_REQUEUES} · {detail}"
                )
            task["stage"] = stage
            task["stage_detail"] = detail
            task["heartbeat_at"] = time.time()


def _run_task(task_id: str, account: str) -> dict:
    with _tasks_lock:
        task = dict(_tasks[task_id])
    workflow = _workflow_config(task.get("workflow_key"))
    logger.info("[%s] Running on account=%s post=%s workflow=%s", task_id, account,
                task.get("post_id"), task.get("workflow_id"))
    try:
        runner = BrowserRunner(
            headless=_browser_headless(),
            slow_mo=0,
            workflow_id=task["workflow_id"],
            post_id=task.get("post_id"),
            workflow_spec=workflow["spec"],
            user_data_dir=str(PROFILES / account),
            progress_callback=lambda stage, detail: _update_task_progress(
                task_id, stage, detail),
        )
        # Store runner reference for screenshot IPC (accessible from HTTP handler)
        with _tasks_lock:
            if task_id in _tasks:
                _tasks[task_id]["runner"] = runner
                if _tasks[task_id].get("cancel_requested"):
                    runner.request_cancel()
        result = runner.run(
            inputs=task["input_paths"],
            mode="plus",
            output_dir=task["output_dir"],
            timeout=workflow["timeout"],
        )
        with _tasks_lock:
            if _tasks.get(task_id, {}).get("cancel_requested"):
                return {"status": "cancelled", "error": "任务已取消"}
        files = [str(Path(f).relative_to(ROOT)).replace("\\", "/") for f in (result or [])]
        if not files:
            raise RuntimeError("工作流结束，但没有保存到输出文件")
        return {"status": "done", "files": files}
    except Exception as exc:
        with _tasks_lock:
            if _tasks.get(task_id, {}).get("cancel_requested"):
                return {"status": "cancelled", "error": "任务已取消"}
        logger.exception("[%s] Failed on account=%s", task_id, account)
        result = {"status": "failed", "error": str(exc)}
        if isinstance(exc, LoginExpiredError) or _is_auth_rejection_text(str(exc)):
            result["login_expired"] = True
        return result


def _is_auth_rejection_text(error_text: str) -> bool:
    folded = str(error_text or "").casefold()
    return any(pattern in folded for pattern in (
        "no auth data provided",
        "token_mission",
        "token_missing",
        "登录态已失效",
    ))


def _mark_account_session_expired(account: str) -> None:
    """Shorten the saved session so a revoked account stops being dispatched.

    RunningHub can revoke a session server-side while state.json still
    claims a far-future expiry.  After an authoritative 401/403 we force the
    stored cookie expiry into the past so ``/api/accounts`` reports the
    account as expired and the user is prompted to log in again.
    """
    if not account:
        return
    state_path = PROFILES / account / "state.json"
    data = _read_json(state_path, None)
    if not isinstance(data, dict):
        return
    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return
    past = time.time() - 1.0
    changed = False
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        if cookie.get("name") == "Rh-Accesstoken":
            # _session_info trusts the JWT exp when decodable; destroy the
            # value so the revocation cannot be undone by that fallback.
            cookie["value"] = "revoked"
        try:
            expires = float(cookie.get("expires", -1))
        except (TypeError, ValueError):
            expires = -1
        if expires > 0 and expires > past:
            cookie["expires"] = past
            changed = True
    if changed:
        _write_json(state_path, data)
        logger.warning(
            "Account %s marked as expired after a server-side auth rejection",
            account,
        )


def _automatic_retry_reason(error_text: str) -> str | None:
    """Return a user-facing retry reason for every failure except cancel."""
    text = str(error_text or "")
    folded = text.casefold()
    if ("任务已取消" in text or "用户取消" in text
            or "task was cancelled" in folded
            or "task was canceled" in folded):
        return None
    if _is_auth_rejection_text(text):
        # A revoked login is only fixed by logging in again; requeuing just
        # burns the account slot and confuses the user.
        return None
    if ("超时" in text or "timeout" in folded):
        return "任务超时"
    if any(phrase in folded for phrase in (
            "target page, context or browser has been closed",
            "target closed",
            "browser has been closed",
            "target page has been closed")):
        return "浏览器异常关闭"
    return "任务失败"


def _finish_task(task_id: str, account: str, future: Future):
    try:
        result = future.result()
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)}
    retry_scheduled = False
    retry_reason = None
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            result_status = result.get("status", "failed")
            error_text = str(result.get("error") or "")
            retry_reason = (
                _automatic_retry_reason(error_text)
                if result_status == "failed" else None
            )
            if (result_status == "failed"
                    and (result.get("login_expired")
                         or _is_auth_rejection_text(error_text))):
                retry_reason = None
                _mark_account_session_expired(account)
            retry_count = int(task.get("retry_count") or 0)
            if retry_reason and retry_count < MAX_TASK_REQUEUES:
                attempt_errors = list(task.get("attempt_errors") or ())
                attempt_errors.append(error_text)
                retry_count += 1
                now = time.time()
                task.update({
                    "status": "queued",
                    "stage": "queued",
                    "stage_detail": (
                        f"{retry_reason}，自动重试 "
                        f"{retry_count}/{MAX_TASK_REQUEUES}，等待执行"
                    ),
                    "retry_count": retry_count,
                    "original_task_id": (
                        task.get("original_task_id") or task_id
                    ),
                    "attempt_errors": attempt_errors,
                    "account": None,
                    "phone": None,
                    "started_at": None,
                    "completed_at": None,
                    "heartbeat_at": now,
                    "files": [],
                    "error": None,
                })
                if task_id not in _task_queue:
                    _task_queue.append(task_id)
                retry_scheduled = True
            else:
                task["status"] = result_status
                if result_status == "done":
                    task["stage"], task["stage_detail"] = (
                        "completed", "任务已完成"
                    )
                elif result_status == "cancelled":
                    task["stage"], task["stage_detail"] = (
                        "cancelled", "任务已取消"
                    )
                else:
                    task["stage"], task["stage_detail"] = (
                        "failed", "重试 3 次后仍然失败"
                    )
                task["heartbeat_at"] = time.time()
                task["completed_at"] = time.time()
                task["files"] = result.get("files", [])
                task["error"] = result.get("error")
            # Release any pending screenshot waiters before removing runner reference
            runner = task.pop("runner", None)
            if runner and runner.screenshot_requested.is_set():
                runner.screenshot_error = "Task has completed"
                runner.screenshot_ready.set()
        _account_busy.discard(account)
    if retry_scheduled:
        logger.info(
            "[%s] %s — retrying in the same task row (%d/%d)",
            task_id, retry_reason, task.get("retry_count"), MAX_TASK_REQUEUES,
        )
    else:
        logger.info(
            "[%s] %s; account %s is free",
            task_id, result.get("status"), account,
        )

    _dispatch_tasks()


def _expire_queued_tasks(now=None):
    """Remove invalid queue entries and fail tasks that waited too long."""
    now = now or time.time()
    for task_id in list(_task_queue):
        task = _tasks.get(task_id)
        if not task or task.get("status") != "queued":
            _task_queue.remove(task_id)
            continue
        if now - task.get("created_at", now) < QUEUE_TIMEOUT_SECONDS:
            continue
        task.update({
            "status": "failed",
            "stage": "failed",
            "stage_detail": "排队超时",
            "heartbeat_at": now,
            "completed_at": now,
            "error": f"任务排队超过 {QUEUE_TIMEOUT_SECONDS} 秒",
        })
        _task_queue.remove(task_id)


def _dispatch_tasks():
    """Feed queued tasks to free accounts; one active task per account."""
    with _tasks_lock:
        _expire_queued_tasks()
        ready = _ready_account_ids()
        free = [account for account in ready if account not in _account_busy]
        if not free or not _task_queue:
            return

        for task_id in list(_task_queue):
            if not free:
                break
            task = _tasks.get(task_id)
            if not task or task["status"] != "queued":
                _task_queue.remove(task_id)
                continue
            requested = task.get("requested_account")
            if requested and requested != "auto":
                if requested not in free:
                    continue
                account = requested
            else:
                account = free[0]

            free.remove(account)
            _task_queue.remove(task_id)
            _account_busy.add(account)
            cfg = _read_json(PROFILES / account / "config.json", {})
            workflow = _workflow_config(task.get("workflow_key"))
            task.update({
                "status": "running",
                "account": account,
                "phone": cfg.get("phone") or account,
                "workflow_id": workflow["workflow_id"],
                "post_id": workflow.get("post_id"),
                "started_at": time.time(),
                "stage": "starting",
                "stage_detail": "等待执行线程启动",
                "heartbeat_at": time.time(),
                "output_dir": str(WORKS / time.strftime("%Y-%m-%d") / (cfg.get("phone") or account) / task.get("workflow_key", "workflow")),
            })
            try:
                future = _executor.submit(_run_task, task_id, account)
            except Exception:
                _account_busy.discard(account)
                task.update({
                    "status": "failed",
                    "stage": "failed",
                    "stage_detail": "无法启动执行线程",
                    "completed_at": time.time(),
                    "heartbeat_at": time.time(),
                    "error": "无法启动任务执行线程",
                })
                logger.exception("[%s] Executor submission failed", task_id)
                continue
            future.add_done_callback(
                lambda fut, tid=task_id, acc=account: _finish_task(tid, acc, fut)
            )
            logger.info("[%s] Dispatched to account=%s", task_id, account)


def _public_task(task: dict) -> dict:
    now = time.time()
    created = task["created_at"]
    started = task.get("started_at")
    completed = task.get("completed_at")
    result = {
        key: value for key, value in task.items()
        if not key.endswith("_path")
        and key not in ("input_paths", "output_dir", "runner")
    }
    result.setdefault("workflow_name", DEFAULT_WORKFLOW_NAME)
    result["queue_seconds"] = round((started or now) - created)
    result["run_seconds"] = round(((completed or now) - started)) if started else 0
    result["total_seconds"] = round((completed or now) - created)
    return result


def _task_list():
    _dispatch_tasks()
    with _tasks_lock:
        return [_public_task(t) for t in sorted(
            _tasks.values(), key=lambda item: item["created_at"], reverse=True)]


def _restart_task_in_place(task_id: str) -> dict:
    """Manually restart a terminal task without creating another table row."""
    with _tasks_lock:
        old_task = _tasks.get(task_id)
        if not old_task:
            raise ValueError("任务不存在")
        if old_task.get("status") in ("queued", "running"):
            raise ValueError("任务仍在排队或运行中")
        input_paths = dict(old_task.get("input_paths") or {})
        requested = old_task.get("requested_account", "auto")
        workflow_key = old_task.get("workflow_key")
        manual_restart_count = int(old_task.get("manual_restart_count") or 0)

    if not input_paths:
        raise ValueError("原任务缺少素材路径，无法重新提交")
    workflow = _workflow_config(workflow_key)
    now = time.time()
    restarted = _new_task(workflow, input_paths, requested, now)
    restarted.update({
        "task_id": task_id,
        "manual_restart_count": manual_restart_count + 1,
        "stage_detail": "手动重新运行，等待可用账号",
    })

    with _tasks_lock:
        current = _tasks.get(task_id)
        if not current:
            raise ValueError("任务不存在")
        if current.get("status") in ("queued", "running"):
            raise ValueError("任务仍在排队或运行中")
        current.clear()
        current.update(restarted)
        if task_id not in _task_queue:
            _task_queue.append(task_id)

    _dispatch_tasks()
    with _tasks_lock:
        return _public_task(_tasks[task_id])


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args[1] not in ("200", "204"):
            sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]} - {args[1]}\n")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _empty(self, status=204):
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _require_active_license(self) -> bool:
        status = LICENSE.status(check_online=True)
        if status["active"]:
            return True
        self._json({
            "error": status.get("message") or "授权不可用",
            "license_required": True,
        }, 403)
        return False

    def _login_internal_session(self, parsed):
        session_id = parse_qs(parsed.query).get("session_id", [""])[0]
        token = self.headers.get("X-Login-Token", "")
        with _login_lock:
            session = _find_login_session_locked(session_id)
            if not session or not token or not secrets.compare_digest(
                    session["token"], token):
                return None
            return session

    def _upload_file(self, library=False):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            raise ValueError("上传文件为空")
        if length > 2 * 1024 * 1024 * 1024:
            raise ValueError("文件超过 2GB 限制")
        filename, content = _parse_multipart_file(
            self.headers, self.rfile.read(length)
        )
        if not content:
            raise ValueError("上传文件为空")
        suffix = Path(filename).suffix.lower()
        allowed = {
            ".png", ".jpg", ".jpeg", ".webp", ".bmp",
            ".mp4", ".mov", ".webm", ".avi", ".mkv",
            ".mp3", ".wav", ".m4a", ".aac", ".flac",
            ".txt", ".md",
        }
        if suffix not in allowed:
            raise ValueError("仅支持常见图片、视频或音频文件")
        if library:
            category = parse_qs(urlparse(self.path).query).get("category", [""])[0]
            folder = {"image": "images", "video": "videos", "audio": "audio", "text": "texts"}.get(category)
            if not folder:
                folder = "texts" if suffix in {".txt", ".md"} else ("videos" if suffix in {".mp4", ".mov", ".webm", ".avi", ".mkv"} else ("audio" if suffix in {".mp3", ".wav", ".m4a", ".aac", ".flac"} else "images"))
            safe_stem = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "_", Path(filename).stem).strip("._") or "material"
            target = LIBRARY / folder / f"{safe_stem}{suffix}"
            counter = 2
            while target.exists():
                target = LIBRARY / folder / f"{safe_stem}_{counter}{suffix}"
                counter += 1
        else:
            target = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        target.write_bytes(content)
        if library:
            with _library_lock:
                metadata = _read_json(LIBRARY_META, {})
                item_id = str(target.relative_to(LIBRARY)).replace("\\", "/")
                metadata[item_id] = {"tags": [], "imported_at": time.time()}
                _write_json(LIBRARY_META, metadata)
        return self._json({
            "name": filename,
            "path": str(target.relative_to(ROOT)).replace("\\", "/"),
            "size": len(content),
        })

    def _internal_login_frame(self):
        parsed = urlparse(self.path)
        session = self._login_internal_session(parsed)
        if not session:
            return self._json({"error": "Forbidden"}, 403)
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 8 * 1024 * 1024:
            raise ValueError("Invalid login frame")
        frame = self.rfile.read(length)
        if not frame.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid login frame")
        with _login_lock:
            current = _find_login_session_locked(session["session_id"])
            if current is not session:
                return self._json({"error": "Login session expired"}, 410)
            if session["stage"] not in ("starting", "slider"):
                return self._json({"status": "ignored"})
            session["frame"] = frame
            session["frame_updated_at"] = time.time()
        return self._json({"status": "accepted"})

    def _send_file(self, path: Path):
        if not path.is_file():
            self._json({"error": "Not found"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            return self._send_file(STATIC / "index.html")
        if path.startswith("/static/"):
            target = (BUNDLE_ROOT / path.lstrip("/")).resolve()
            if target.is_relative_to(STATIC.resolve()):
                return self._send_file(target)
            return self._json({"error": "Forbidden"}, 403)
        if path.startswith("/outputs/"):
            target = (APP_ROOT / path.lstrip("/")).resolve()
            if target.is_relative_to((APP_ROOT / "outputs").resolve()):
                return self._send_file(target)
            return self._json({"error": "Forbidden"}, 403)
        if path.startswith("/works/") or path.startswith("/library/"):
            target = (APP_ROOT / path.lstrip("/")).resolve()
            base = WORKS.resolve() if path.startswith("/works/") else LIBRARY.resolve()
            if target.is_relative_to(base):
                return self._send_file(target)
            return self._json({"error": "Forbidden"}, 403)
        if path == "/api/files":
            return self._json(_scan_files())
        if path == "/api/library":
            return self._json({"items": _library_items()})
        if path == "/api/works":
            return self._json({"items": _works_items()})
        if path == "/api/workflows":
            try:
                return self._json(_public_workflows())
            except (LicenseError, ConnectionError) as exc:
                logger.error("Workflow catalog unavailable: %s", exc)
                return self._json({"error": str(exc)}, 503)
        if path == "/api/license/status":
            return self._json(LICENSE.status(check_online=True))
        if path == "/api/accounts":
            return self._json(_account_list())
        if path == "/api/tasks":
            return self._json(_task_list())
        if path == "/api/screenshot":
            self._handle_screenshot(parsed)
            return
        if path == "/api/status":
            task_id = parse_qs(parsed.query).get("task_id", [""])[0]
            with _tasks_lock:
                task = _tasks.get(task_id)
                return self._json(_public_task(task), 200) if task else self._json({"error": "Task not found"}, 404)
        if path == "/api/accounts/login/view":
            query = parse_qs(parsed.query)
            account = query.get("account", [""])[0]
            session_id = query.get("session_id", [""])[0]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", account):
                return self._json({"error": "无效的账号标识"}, 400)
            with _login_lock:
                session = _current_login_session_locked(account, session_id)
                if not session:
                    return self._json({"error": "登录会话已失效"}, 410)
                # This check is the final privacy boundary: no image can leave
                # the process after the official slider has disappeared.
                if session["stage"] != "slider" or not session.get("frame"):
                    return self._empty()
                frame = session["frame"]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)
            return
        if path == "/api/internal/login/events":
            session = self._login_internal_session(parsed)
            if not session:
                return self._json({"error": "Forbidden"}, 403)
            with _login_lock:
                current = _find_login_session_locked(session["session_id"])
                if current is not session:
                    return self._json({"error": "Login session expired"}, 410)
                events = list(session["events"])
                session["events"].clear()
            return self._json({"events": events})
        return self._json({"error": "Not found"}, 404)

    def _handle_screenshot(self, parsed):
        """GET /api/screenshot?task_id=X — request a browser screenshot."""
        task_id = parse_qs(parsed.query).get("task_id", [""])[0]
        if not task_id:
            return self._json({"error": "Missing task_id"}, 400)

        with _tasks_lock:
            task = _tasks.get(task_id)
            if not task:
                return self._json({"error": "Task not found"}, 404)
            if task.get("status") != "running":
                return self._json({"error": "Task is not running"}, 400)
            runner = task.get("runner")
            if not runner:
                return self._json({"error": "Runner not available (task may be starting)"}, 503)

            # Guard against concurrent screenshot requests for the same task
            if runner._screenshot_in_progress:
                return self._json(
                    {"error": "Screenshot already in progress, please wait"},
                    429,
                )
            runner._screenshot_in_progress = True

        try:
            # Reset ready event from any previous request, then signal
            runner.screenshot_ready.clear()
            runner.screenshot_requested.set()

            # Wait for the browser thread to take the screenshot
            if not runner.screenshot_ready.wait(timeout=5.0):
                return self._json(
                    {"error": "Screenshot timed out (browser may be busy)"},
                    408,
                )

            # Check for errors from the browser thread
            if runner.screenshot_error:
                return self._json({"error": runner.screenshot_error}, 500)

            data = runner.screenshot_data
            if not data:
                return self._json({"error": "No screenshot data received"}, 500)

            # Return raw PNG bytes (not JSON)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        finally:
            if runner:
                runner._screenshot_in_progress = False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            path = unquote(urlparse(self.path).path)
            if path in {"/api/uploads", "/api/run", "/api/restart", "/api/batch-run"}:
                if not self._require_active_license():
                    return
            if path == "/api/uploads":
                return self._upload_file()
            if path == "/api/library/upload":
                return self._upload_file(library=True)
            if path == "/api/internal/login/frame":
                return self._internal_login_frame()
            return self._do_post()
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except ConnectionError as exc:
            return self._json({"error": str(exc)}, 503)
        except Exception as exc:
            logger.exception("POST %s failed", self.path)
            return self._json({"error": str(exc)}, 500)

    def do_DELETE(self):
        try:
            path = unquote(urlparse(self.path).path)
            if path.startswith("/api/library/"):
                rel = unquote(path[len("/api/library/"):])
                target = (LIBRARY / rel).resolve()
                if not target.is_relative_to(LIBRARY.resolve()) or not target.is_file():
                    return self._json({"error": "素材不存在"}, 404)
                target.unlink()
                return self._json({"status": "deleted"})
            prefix = "/api/accounts/"
            if not path.startswith(prefix):
                return self._json({"error": "Not found"}, 404)
            account = path[len(prefix):].strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", account):
                raise ValueError("无效的账号标识")

            profile = (PROFILES / account).resolve()
            profiles_root = PROFILES.resolve()
            if not profile.is_relative_to(profiles_root) or profile == profiles_root:
                raise ValueError("无效的账号目录")
            if not profile.is_dir():
                return self._json({"error": "账号不存在"}, 404)

            with _tasks_lock:
                if account in _account_busy:
                    raise ValueError("该账号正在运行任务，不能删除")
                if any(
                    task.get("status") == "queued"
                    and task.get("requested_account") == account
                    for task in _tasks.values()
                ):
                    raise ValueError("该账号还有指定排队任务，不能删除")
            with _login_lock:
                proc = _login_processes.pop(account, None)
                session = _login_sessions.pop(account, None)
                if session:
                    _queue_login_event_locked(session, {"type": "stop"})
            if proc and hasattr(proc, "poll") and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)

            # Remove only local account configuration and session. Generated
            # outputs are outside profiles/ and remain untouched.
            shutil.rmtree(profile)
            logger.info("Account %s deleted; output files retained", account)
            _dispatch_tasks()
            return self._json({"status": "deleted", "account": account})
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:
            logger.exception("DELETE %s failed", self.path)
            return self._json({"error": str(exc)}, 500)

    def _do_post(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        data = self._body()

        if path == "/api/library/manage":
            ids = data.get("ids") or []
            if not isinstance(ids, list) or not ids:
                raise ValueError("请选择素材")
            action = str(data.get("action") or "")
            changed = []
            with _library_lock:
                metadata = _read_json(LIBRARY_META, {})
                for item_id in ids:
                    source = (LIBRARY / unquote(str(item_id))).resolve()
                    if not source.is_relative_to(LIBRARY.resolve()) or not source.is_file() or source == LIBRARY_META:
                        continue
                    current_id = str(source.relative_to(LIBRARY)).replace("\\", "/")
                    if action == "delete":
                        source.unlink()
                        metadata.pop(current_id, None)
                        changed.append(current_id)
                    elif action == "tags":
                        tags = [str(tag).strip()[:30] for tag in (data.get("tags") or []) if str(tag).strip()][:10]
                        metadata.setdefault(current_id, {"imported_at": source.stat().st_mtime})["tags"] = tags
                        changed.append(current_id)
                    elif action == "rename":
                        if len(ids) != 1:
                            raise ValueError("改名时只能选择一个素材")
                        name = Path(str(data.get("name") or "")).name.strip()
                        if not name:
                            raise ValueError("请输入新名称")
                        if Path(name).suffix.lower() != source.suffix.lower():
                            name += source.suffix
                        target = source.with_name(name).resolve()
                        if not target.is_relative_to(source.parent.resolve()) or target.exists():
                            raise ValueError("名称无效或已存在")
                        source.rename(target)
                        new_id = str(target.relative_to(LIBRARY)).replace("\\", "/")
                        metadata[new_id] = metadata.pop(current_id, {"tags": [], "imported_at": time.time()})
                        changed.append(new_id)
                    else:
                        raise ValueError("不支持的素材操作")
                _write_json(LIBRARY_META, metadata)
            return self._json({"status": "ok", "changed": changed})

        if path == "/api/tasks/cancel":
            task_id = str(data.get("task_id") or "")
            with _tasks_lock:
                task = _tasks.get(task_id)
                if not task:
                    raise ValueError("任务不存在")
                if task.get("status") == "queued":
                    try: _task_queue.remove(task_id)
                    except ValueError: pass
                    task.update({"status": "cancelled", "stage": "cancelled", "stage_detail": "任务已取消", "completed_at": time.time(), "error": "任务已取消"})
                    return self._json(_public_task(task))
                if task.get("status") != "running":
                    return self._json(_public_task(task))
                task["cancel_requested"] = True
                task.update({
                    "status": "cancelled", "stage": "cancelled",
                    "stage_detail": "正在取消任务", "completed_at": time.time(),
                    "error": "任务已取消",
                })
                runner = task.get("runner")
            if runner:
                runner.request_cancel()
            return self._json({"status": "cancelled", "task_id": task_id})

        if path == "/api/license/activate":
            code = str(data.get("code") or "").strip()
            if not code:
                raise ValueError("请输入激活码")
            return self._json(LICENSE.activate(code))

        if path == "/api/license/renew":
            code = str(data.get("code") or "").strip()
            if not code:
                raise ValueError("请输入续费卡密")
            return self._json(LICENSE.renew(code))

        if path == "/api/license/check":
            return self._json(LICENSE.check_now())

        if path == "/api/license/reset":
            result = LICENSE.reset()
            _clear_workflow_catalog()
            return self._json(result)

        if path == "/api/internal/login/status":
            session = self._login_internal_session(parsed)
            if not session:
                return self._json({"error": "Forbidden"}, 403)
            stage = str(data.get("stage", ""))
            if stage not in LOGIN_STAGES:
                raise ValueError("Invalid login stage")
            with _login_lock:
                current = _find_login_session_locked(session["session_id"])
                if current is not session:
                    return self._json({"error": "Login session expired"}, 410)
                _set_login_status_locked(
                    session, stage, str(data.get("detail") or ""),
                    data.get("error"),
                )
            return self._json({"status": "accepted"})

        if path == "/api/accounts":
            phone, account = _normalize_phone(data.get("phone"))
            profile = PROFILES / account
            cfg_path = profile / "config.json"
            old = _read_json(cfg_path, {})
            now = time.time()
            cfg = {
                **old,
                "phone": phone,
                "created_at": old.get("created_at", now),
                "updated_at": now,
            }
            _write_json(cfg_path, cfg)
            _dispatch_tasks()
            return self._json({"status": "saved", "account": account})

        if path == "/api/accounts/login":
            account = str(data.get("account", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", account):
                raise ValueError("无效的账号标识")
            profile = PROFILES / account
            if not account or not (profile / "config.json").exists():
                raise ValueError("请先保存电话号码")
            # Keep the busy check and login marker registration atomic with the
            # dispatcher, which uses the same tasks -> login lock order.
            with _tasks_lock:
                with _login_lock:
                    if account in _account_busy:
                        raise ValueError("该账号正在运行任务，暂时不能重新登录")
                    existing = _login_processes.get(account)
                    if existing and (
                            not hasattr(existing, "poll") or existing.poll() is None):
                        session = _login_sessions.get(account)
                        return self._json({
                            "status": "login_in_progress", "account": account,
                            **(_public_login_session(session) or {}),
                        })

                    session = _new_login_session(account)
                    _login_sessions[account] = session
                    (profile / "login_status.json").unlink(missing_ok=True)

                    phone = str(_read_json(
                        profile / "config.json", {}).get("phone", ""))
                    worker_args = [
                        "--profile", str(profile), "--phone", phone,
                        "--timeout", "600",
                        "--session-id", session["session_id"],
                        "--ipc-token", session["token"],
                        "--ipc-url",
                        f"http://127.0.0.1:{self.server.server_address[1]}",
                    ]
                    if getattr(sys, "frozen", False):
                        command = [
                            sys.executable, "--sms-login-worker", *worker_args]
                    else:
                        command = [
                            sys.executable, str(BUNDLE_ROOT / "sms_login.py"),
                            *worker_args,
                        ]
                    proc = subprocess.Popen(
                        command,
                        cwd=str(APP_ROOT),
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        ),
                    )
                    proc._login_session_id = session["session_id"]
                    _login_processes[account] = proc
            return self._json({
                "status": "login_started", "account": account,
                **_public_login_session(session),
            })

        if path == "/api/accounts/login/verify":
            account = str(data.get("account", "")).strip()
            session_id = str(data.get("session_id", "")).strip()
            code = str(data.get("code", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", account):
                raise ValueError("无效的账号标识")
            if not re.fullmatch(r"\d{4,8}", code):
                raise ValueError("请输入有效的短信验证码")
            profile = (PROFILES / account).resolve()
            if not profile.is_relative_to(PROFILES.resolve()) or not profile.is_dir():
                raise ValueError("账号不存在")
            with _login_lock:
                proc = _login_processes.get(account)
                if not proc or (hasattr(proc, "poll") and proc.poll() is not None):
                    raise ValueError("登录会话已结束，请重新点击登录")
                session = _current_login_session_locked(account, session_id)
                if not session:
                    raise ValueError("登录会话已失效，请重新点击登录")
                _queue_login_event_locked(session, {
                    "type": "verify", "code": code,
                })
                _set_login_status_locked(
                    session, "verifying", "正在验证短信验证码")
            return self._json({"status": "verifying", "account": account})

        if path == "/api/accounts/login/pointer":
            account = str(data.get("account", "")).strip()
            session_id = str(data.get("session_id", "")).strip()
            event_type = str(data.get("type", ""))
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", account):
                raise ValueError("无效的账号标识")
            if event_type not in ("down", "move", "up"):
                raise ValueError("无效的指针事件")
            try:
                x = min(1.0, max(0.0, float(data.get("x"))))
                y = min(1.0, max(0.0, float(data.get("y"))))
            except (TypeError, ValueError):
                raise ValueError("无效的指针坐标")
            with _login_lock:
                session = _current_login_session_locked(account, session_id)
                if not session:
                    raise ValueError("登录会话已失效，请重新点击登录")
                if session["stage"] != "slider":
                    return self._json({"status": "ignored"})
                _queue_login_event_locked(session, {
                    "type": event_type, "x": x, "y": y,
                })
            return self._json({"status": "accepted"})

        if path == "/api/run":
            workflow = _workflow_config(data.get("workflow"))
            input_paths = _resolve_workflow_inputs(workflow, data)
            requested = str(data.get("account") or "auto")
            if requested != "auto":
                accounts = {a["id"]: a for a in _account_list()}
                if requested not in accounts or not accounts[requested]["ready"]:
                    raise ValueError("指定账号未登录、登录已过期或尚未设置 Workflow")

            now = time.time()
            task = _new_task(workflow, input_paths, requested, now)
            task_id = task["task_id"]
            with _tasks_lock:
                _tasks[task_id] = task
                _task_queue.append(task_id)
            _dispatch_tasks()
            with _tasks_lock:
                response = _public_task(_tasks[task_id])
            return self._json(response)

        if path == "/api/restart":
            task_id = str(data.get("task_id") or "")
            if not task_id:
                raise ValueError("缺少 task_id")
            return self._json(_restart_task_in_place(task_id))

        if path == "/api/batch-run":
            workflow = _workflow_config(data.get("workflow"))
            requested = str(data.get("account") or "auto")
            input_groups = _resolve_batch_workflow_inputs(workflow, data)
            if requested != "auto":
                accounts = {a["id"]: a for a in _account_list()}
                if requested not in accounts or not accounts[requested]["ready"]:
                    raise ValueError("指定账号未登录、登录已过期或尚未设置 Workflow")

            batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            now = time.time()

            with _tasks_lock:
                for index, inputs in enumerate(input_groups):
                    task = _new_task(workflow, inputs, requested, now)
                    task_id = task["task_id"]
                    task["batch_id"] = batch_id
                    task["batch_index"] = index + 1
                    task["batch_size"] = len(input_groups)
                    _tasks[task_id] = task
                    _task_queue.append(task_id)
                    now += 0.001  # ensure unique task_id timestamps

            _dispatch_tasks()
            return self._json({
                "batch_id": batch_id,
                "workflow": workflow["key"],
                "tasks_created": len(input_groups),
                "repeat": int(data.get("repeat", 1)),
            })

        return self._json({"error": "Not found"}, 404)


def main():
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        instance_mutex = kernel32.CreateMutexW(
            None, False, "Local\\YunComfyUI-Client"
        )
        if not instance_mutex:
            raise OSError("无法创建工作台单实例锁")
        if ctypes.get_last_error() == 183:
            print("YunComfyUI 工作台已经在运行。")
            kernel32.CloseHandle(instance_mutex)
            return

    preferred_port = _configured_port()
    server, actual_port = _create_http_server(preferred_port)
    server_state_path = _write_server_state(actual_port)

    logger.info("Server listening on http://localhost:%d", actual_port)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="yuncomfyui-http",
        daemon=True,
    )
    server_thread.start()
    try:
        import webview
        window = webview.create_window(
            "云创工作台",
            f"http://127.0.0.1:{actual_port}",
            width=1480,
            height=920,
            min_size=(1080, 700),
        )
        window.events.closing += lambda *_args: _shutdown_application()
        webview.start(debug=False)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        _shutdown_application()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        try:
            current_state = json.loads(
                server_state_path.read_text(encoding="utf-8")
            )
            if current_state.get("pid") == os.getpid():
                server_state_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        _executor.shutdown(wait=False, cancel_futures=True)
        _login_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    if "--sms-login-worker" in sys.argv:
        sys.argv.remove("--sms-login-worker")
        from sms_login import main as sms_login_main
        sms_login_main()
    else:
        main()
