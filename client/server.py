#!/usr/bin/env python3
"""Local RunningHub multi-account task console."""

import http.server
from email.parser import BytesParser
from email.policy import default as email_policy
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from license_client import LicenseError, LicenseManager
from runninghub_client.browser import BrowserRunner
from runninghub_client.workflow_specs import (
    ANIMATE_TRANSFER_SPEC,
    HD_RESTORE_SPEC,
    OOTD_7DAY_SPEC,
    PERSON_REPLACE_SPEC,
    QWEN_PROMPT_IMAGE_SPEC,
    QWEN_TRYON_SPEC,
    SCAIL_MULTI_REFERENCE_SPEC,
    SCAIL_SEVEN_OUTFIT_SPEC,
    SCAIL_4K_POSE_BACKGROUND_SPEC,
    KREA2_REALISTIC_4K_SPEC,
    QWEN_MULTI_VIEW_SPEC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("server")

# ---- Portable root resolution -------------------------------------------
# When frozen by PyInstaller, sys._MEIPASS is the temp extraction directory
# (read-only, holds bundled static files).  The EXE directory is used for
# mutable data (profiles, outputs, data/).  In dev mode both are the same.
if getattr(sys, "frozen", False):
    BUNDLE_ROOT = Path(sys._MEIPASS)
    APP_ROOT = Path(sys.executable).resolve().parent
else:
    BUNDLE_ROOT = Path(__file__).resolve().parent
    APP_ROOT = BUNDLE_ROOT

try:
    from dotenv import load_dotenv
    load_dotenv(APP_ROOT / ".env", override=False)
except ImportError:
    pass

ROOT = APP_ROOT  # legacy alias used throughout
DATA = APP_ROOT / "data"
UPLOADS = APP_ROOT / "uploads"
PROFILES = APP_ROOT / "profiles"
STATIC = BUNDLE_ROOT / "static"
PORT = 8080
MAX_WORKERS = 10
LOGIN_WORKERS = 2
PERSON_REPLACE_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_WORKFLOW_ID", "2087970301203279874"
).strip()
OOTD_7DAY_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_OOTD_WORKFLOW_ID", ""
).strip()
QWEN_TRYON_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_QWEN_TRYON_WORKFLOW_ID", ""
).strip()
HD_RESTORE_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_HD_RESTORE_WORKFLOW_ID", ""
).strip()
ANIMATE_TRANSFER_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_ANIMATE_TRANSFER_WORKFLOW_ID", ""
).strip()
QWEN_PROMPT_IMAGE_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_QWEN_PROMPT_IMAGE_WORKFLOW_ID", ""
).strip()
SCAIL_MULTI_REFERENCE_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_SCAIL_MULTI_REFERENCE_WORKFLOW_ID", ""
).strip()
SCAIL_SEVEN_OUTFIT_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_SCAIL_SEVEN_OUTFIT_WORKFLOW_ID", ""
).strip()
SCAIL_4K_POSE_BACKGROUND_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_SCAIL_4K_POSE_BACKGROUND_WORKFLOW_ID", ""
).strip()
KREA2_REALISTIC_4K_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_KREA2_REALISTIC_4K_WORKFLOW_ID", ""
).strip()
QWEN_MULTI_VIEW_WORKFLOW_ID = os.environ.get(
    "RUNNINGHUB_QWEN_MULTI_VIEW_WORKFLOW_ID", "2089193238610669570"
).strip()
WORKFLOW_TIMEOUT_SECONDS = int(os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "3000"))
OOTD_WORKFLOW_TIMEOUT_SECONDS = int(os.environ.get(
    "OOTD_WORKFLOW_TIMEOUT_SECONDS", "7200"
))
QUEUE_TIMEOUT_SECONDS = int(os.environ.get("QUEUE_TIMEOUT_SECONDS", "86400"))
MAX_TASK_REQUEUES = int(os.environ.get("MAX_TASK_REQUEUES", "2"))

DEFAULT_WORKFLOW_KEY = "person_replace"
WORKFLOWS = {
    "person_replace": {
        "key": "person_replace",
        "name": "人物替换",
        "description": "使用替换背景、参考人物与动作视频生成",
        "category": "video",
        "workflow_id": PERSON_REPLACE_WORKFLOW_ID,
        "spec": PERSON_REPLACE_SPEC,
        "timeout": WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "model",
        "inputs": (
            {"key": "background", "label": "替换背景图", "media_type": "image"},
            {"key": "video", "label": "动作视频", "media_type": "video"},
            {"key": "model", "label": "人物参考图", "media_type": "image"},
        ),
    },
    "ootd_7day": {
        "key": "ootd_7day",
        "name": "OOTD 7天变装",
        "description": "7 张穿搭图片生成并合成长视频",
        "category": "video",
        "workflow_id": OOTD_7DAY_WORKFLOW_ID,
        "spec": OOTD_7DAY_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "day1",
        "inputs": tuple(
            {"key": f"day{day}", "label": f"第 {day} 天图片", "media_type": "image"}
            for day in range(1, 8)
        ) + (
            {"key": "audio", "label": "背景音乐", "media_type": "audio"},
        ),
    },
    "qwen_tryon": {
        "key": "qwen_tryon",
        "name": "一键换衣 · 千问版",
        "description": "上传人物图和衣服图，只替换人物服装",
        "category": "image",
        "workflow_id": QWEN_TRYON_WORKFLOW_ID,
        "spec": QWEN_TRYON_SPEC,
        "timeout": WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "person",
        "inputs": (
            {"key": "person", "label": "人物图片", "media_type": "image"},
            {"key": "garment", "label": "衣服图片", "media_type": "image"},
        ),
    },
    "hd_restore": {
        "key": "hd_restore",
        "name": "高定版高清修复",
        "description": "去除 AI 感并增强图片细节",
        "category": "image",
        "workflow_id": HD_RESTORE_WORKFLOW_ID,
        "spec": HD_RESTORE_SPEC,
        "timeout": WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "image",
        "inputs": (
            {"key": "image", "label": "待修复图片", "media_type": "image"},
        ),
    },
    "animate_transfer": {
        "key": "animate_transfer",
        "name": "Animate 动作迁移 ProMax",
        "description": "根据动作视频驱动人物并自动匹配尺寸",
        "category": "video",
        "workflow_id": ANIMATE_TRANSFER_WORKFLOW_ID,
        "spec": ANIMATE_TRANSFER_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "reference_image",
        "inputs": (
            {"key": "motion_video", "label": "动作视频", "media_type": "video"},
            {"key": "reference_image", "label": "人物参考图", "media_type": "image"},
        ),
    },
    "qwen_prompt_image": {
        "key": "qwen_prompt_image",
        "name": "Qwen3 反推提示词 + Z-Image",
        "description": "从参考图反推提示词并重新生成高清图片",
        "category": "image",
        "workflow_id": QWEN_PROMPT_IMAGE_WORKFLOW_ID,
        "spec": QWEN_PROMPT_IMAGE_SPEC,
        "timeout": WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "reference",
        "inputs": (
            {"key": "reference", "label": "参考图片", "media_type": "image"},
        ),
    },
    "scail_multi_reference": {
        "key": "scail_multi_reference",
        "name": "极境 SCAIL2 动作迁移（多参考）",
        "description": "使用动作视频和 6 张人物参考图生成动作迁移视频",
        "category": "video",
        "workflow_id": SCAIL_MULTI_REFERENCE_WORKFLOW_ID,
        "spec": SCAIL_MULTI_REFERENCE_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "reference1",
        "inputs": (
            {"key": "motion_video", "label": "动作视频", "media_type": "video"},
            {"key": "reference1", "label": "参考图 1", "media_type": "image"},
            {"key": "reference2", "label": "参考图 2", "media_type": "image"},
            {"key": "reference3", "label": "参考图 3", "media_type": "image"},
            {"key": "reference4", "label": "参考图 4", "media_type": "image"},
            {"key": "reference5", "label": "参考图 5", "media_type": "image"},
            {"key": "reference6", "label": "参考图 6", "media_type": "image"},
        ),
    },
    "scail_seven_outfit": {
        "key": "scail_seven_outfit",
        "name": "SCAIL 2 七段贴图换装",
        "description": "使用动作视频和 7 张服装贴图生成七段换装视频",
        "category": "video",
        "workflow_id": SCAIL_SEVEN_OUTFIT_WORKFLOW_ID,
        "spec": SCAIL_SEVEN_OUTFIT_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "outfit1",
        "inputs": (
            {"key": "motion_video", "label": "动作视频", "media_type": "video"},
            {"key": "outfit1", "label": "第 1 段贴图", "media_type": "image"},
            {"key": "outfit2", "label": "第 2 段贴图", "media_type": "image"},
            {"key": "outfit3", "label": "第 3 段贴图", "media_type": "image"},
            {"key": "outfit4", "label": "第 4 段贴图", "media_type": "image"},
            {"key": "outfit5", "label": "第 5 段贴图", "media_type": "image"},
            {"key": "outfit6", "label": "第 6 段贴图", "media_type": "image"},
            {"key": "outfit7", "label": "第 7 段贴图", "media_type": "image"},
        ),
    },
    "scail_4k_pose_background": {
        "key": "scail_4k_pose_background",
        "name": "极境 4K 姿势迁移 · 背景替换",
        "description": "将人物迁移到背景场景并增强姿势与画面一致性",
        "category": "image",
        "workflow_id": SCAIL_4K_POSE_BACKGROUND_WORKFLOW_ID,
        "spec": SCAIL_4K_POSE_BACKGROUND_SPEC,
        "timeout": WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "person",
        "inputs": (
            {"key": "background", "label": "背景图", "media_type": "image"},
            {"key": "person", "label": "人物图", "media_type": "image"},
        ),
    },
    "krea2_realistic_4k": {
        "key": "krea2_realistic_4k",
        "name": "Krea2 超写实 4K 文生图",
        "description": "输入画面提示词，生成超写实 4K 图片",
        "category": "image",
        "workflow_id": KREA2_REALISTIC_4K_WORKFLOW_ID,
        "spec": KREA2_REALISTIC_4K_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "prompt",
        "inputs": (
            {
                "key": "prompt",
                "label": "画面提示词",
                "input_type": "text",
                "media_type": "text",
            },
        ),
    },
    "qwen_multi_view": {
        "key": "qwen_multi_view",
        "name": "Qwen 角色三视图 · 多视角",
        "description": "根据一张角色参考图生成多角度全身、半身和面部视图",
        "category": "image",
        "workflow_id": QWEN_MULTI_VIEW_WORKFLOW_ID,
        "spec": QWEN_MULTI_VIEW_SPEC,
        "timeout": OOTD_WORKFLOW_TIMEOUT_SECONDS,
        "primary_input": "character",
        "inputs": (
            {"key": "character", "label": "角色参考图", "media_type": "image"},
        ),
    },
}

DEFAULT_WORKFLOW_ID = PERSON_REPLACE_WORKFLOW_ID
DEFAULT_WORKFLOW_SPEC = PERSON_REPLACE_SPEC
DEFAULT_WORKFLOW_NAME = WORKFLOWS[DEFAULT_WORKFLOW_KEY]["name"]

# ---- Ensure required directories exist ----------------------------------
for _dir in (DATA / "pic", DATA / "ple", DATA / "video", UPLOADS, PROFILES, APP_ROOT / "outputs"):
    _dir.mkdir(parents=True, exist_ok=True)

LICENSE = LicenseManager(
    APP_ROOT / ".license",
    os.environ.get("LICENSE_SERVER_URL", "https://drxbpb65n5.coze.site"),
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


def _validate_workflow_id(value: str) -> str:
    workflow_id = str(value or "").strip()
    if not workflow_id or not re.fullmatch(r"\d{6,30}", workflow_id):
        raise ValueError("Workflow ID 应为 6–30 位数字")
    return workflow_id


def _workflow_config(key: str | None, require_configured=True) -> dict:
    workflow_key = str(key or DEFAULT_WORKFLOW_KEY).strip()
    workflow = WORKFLOWS.get(workflow_key)
    if not workflow:
        raise ValueError("未知的工作流")
    if require_configured and not workflow["workflow_id"]:
        raise ValueError(
            f"{workflow['name']} 尚未配置 RunningHub Workflow ID"
        )
    return workflow


def _public_workflows() -> list[dict]:
    return [
        {
            "key": workflow["key"],
            "name": workflow["name"],
            "description": workflow["description"],
            "category": workflow["category"],
            "configured": bool(workflow["workflow_id"]),
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
        workflow_id = DEFAULT_WORKFLOW_ID
        phone = str(cfg.get("phone") or (profile.name if profile.name != "default" else "未登记号码"))
        accounts.append({
            "id": profile.name,
            "name": profile.name,
            "phone": phone,
            "workflow_id": workflow_id,
            "session_valid": session["valid"],
            "session_status": session["status"],
            "session_expires_at": session["expires_at"],
            "login_in_progress": profile.name in logging_accounts,
            "busy": profile.name in busy_accounts,
            "ready": bool(
                session["valid"] and workflow_id
                and profile.name not in logging_accounts
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
        path.is_relative_to(base.resolve()) for base in (UPLOADS, DATA)
    ):
        raise ValueError("素材必须来自工作台上传或素材目录")
    return str(path)


def _resolve_workflow_inputs(workflow: dict, data: dict) -> dict[str, str]:
    resolved = {}
    for input_spec in workflow["inputs"]:
        key = input_spec["key"]
        if input_spec.get("input_type") == "text":
            value = str(data.get(key) or "").strip()
            if not value:
                raise ValueError(f"缺少{input_spec['label']}")
            resolved[key] = value
            continue
        try:
            resolved[key] = _resolve_uploaded_material(data.get(key))
        except ValueError as exc:
            raise ValueError(f"{input_spec['label']}：{exc}") from exc
    return resolved


def _resolve_batch_workflow_inputs(workflow: dict, data: dict) -> list[dict[str, str]]:
    raw_inputs = data.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise ValueError("批量任务缺少 inputs")

    repeat = int(data.get("repeat", 1))
    if not 1 <= repeat <= 20:
        raise ValueError("每组生成次数必须在 1–20 之间")

    resolved: dict[str, list[str]] = {}
    group_count = 1
    for input_spec in workflow["inputs"]:
        key = input_spec["key"]
        raw_values = raw_inputs.get(key)
        if not isinstance(raw_values, list):
            raise ValueError(f"{input_spec['label']}必须是批量列表")
        values = [str(value or "").strip() for value in raw_values]
        values = [value for value in values if value]
        if not values:
            raise ValueError(f"缺少{input_spec['label']}")

        if input_spec.get("input_type") == "text":
            resolved[key] = values
        else:
            try:
                resolved[key] = [
                    _resolve_uploaded_material(value) for value in values
                ]
            except ValueError as exc:
                raise ValueError(f"{input_spec['label']}：{exc}") from exc
        group_count = max(group_count, len(values))

    task_count = group_count * repeat
    if task_count > 500:
        raise ValueError("单个批次最多创建 500 个任务")

    combinations = []
    for group_index in range(group_count):
        group = {
            key: values[group_index % len(values)]
            for key, values in resolved.items()
        }
        for _ in range(repeat):
            combinations.append(dict(group))
    return combinations


def _new_task(
    workflow: dict,
    input_paths: dict[str, str],
    requested_account: str,
    now: float | None = None,
) -> dict:
    created_at = now if now is not None else time.time()
    task_id = f"task_{int(created_at * 1000)}_{uuid.uuid4().hex[:6]}"
    input_types = {
        item["key"]: item.get("input_type", "file")
        for item in workflow["inputs"]
    }
    input_files = {
        key: (value[:80] if input_types.get(key) == "text" else Path(value).name)
        for key, value in input_paths.items()
    }
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
            task["stage"] = stage
            task["stage_detail"] = detail
            task["heartbeat_at"] = time.time()


def _run_task(task_id: str, account: str) -> dict:
    with _tasks_lock:
        task = dict(_tasks[task_id])
    workflow = _workflow_config(task.get("workflow_key"))
    logger.info("[%s] Running on account=%s workflow=%s", task_id, account,
                task["workflow_id"])
    try:
        runner = BrowserRunner(
            headless=False,
            slow_mo=200,
            workflow_id=task["workflow_id"],
            workflow_spec=workflow["spec"],
            user_data_dir=str(PROFILES / account),
            progress_callback=lambda stage, detail: _update_task_progress(
                task_id, stage, detail),
        )
        # Store runner reference for screenshot IPC (accessible from HTTP handler)
        with _tasks_lock:
            if task_id in _tasks:
                _tasks[task_id]["runner"] = runner
        result = runner.run(
            inputs=task["input_paths"],
            mode="plus",
            output_dir=task["output_dir"],
            timeout=workflow["timeout"],
        )
        files = [str(Path(f).relative_to(ROOT)).replace("\\", "/") for f in (result or [])]
        if not files:
            raise RuntimeError("工作流结束，但没有保存到输出文件")
        return {"status": "done", "files": files}
    except Exception as exc:
        logger.exception("[%s] Failed on account=%s", task_id, account)
        return {"status": "failed", "error": str(exc)}


def _finish_task(task_id: str, account: str, future: Future):
    try:
        result = future.result()
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)}
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            task["status"] = result.get("status", "failed")
            task["stage"] = "completed" if task["status"] == "done" else "failed"
            task["stage_detail"] = "任务已完成" if task["status"] == "done" else "任务失败"
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
    logger.info("[%s] %s; account %s is free", task_id, result.get("status"), account)

    # Auto re-queue if the task timed out and still has retries left
    if task and result.get("status") == "failed":
        error_text = result.get("error", "")
        is_timeout = "超时" in error_text or "Timeout" in error_text or "timeout" in error_text
        is_browser_crash = any(phrase in error_text for phrase in (
            "Target page, context or browser has been closed",
            "Target closed",
            "Browser has been closed",
            "Target page has been closed",
            "browser has been closed",
        ))
        if is_timeout or is_browser_crash:
            requeue_count = task.get("retry_count", 0)
            if requeue_count < MAX_TASK_REQUEUES:
                now = time.time()
                new_task_id = f"task_{int(now * 1000)}_{uuid.uuid4().hex[:6]}"
                new_task = {
                    **{k: v for k, v in task.items()
                       if k in ("workflow_key", "workflow_name", "task_name",
                                "input_files", "input_paths", "video", "model",
                                "clothing", "video_path", "model_path",
                                "clothing_path", "requested_account")},
                    "task_id": new_task_id,
                    "status": "queued",
                    "stage": "queued",
                    "stage_detail": (
                        f"浏览器崩溃自动重新排队（{requeue_count + 1}/{MAX_TASK_REQUEUES}）"
                        if is_browser_crash
                        else f"超时自动重新排队（{requeue_count + 1}/{MAX_TASK_REQUEUES}）"
                    ),
                    "retry_count": requeue_count + 1,
                    "original_task_id": task.get("original_task_id") or task_id,
                    "account": None,
                    "phone": None,
                    "created_at": now,
                    "started_at": None,
                    "completed_at": None,
                    "heartbeat_at": now,
                    "files": [],
                    "error": None,
                }
                _tasks[new_task_id] = new_task
                _task_queue.append(new_task_id)
                logger.info(
                    "[%s] %s — re-queued as %s (attempt %d/%d)",
                    task_id,
                    "Browser crashed" if is_browser_crash else "Timed out",
                    new_task_id, requeue_count + 1, MAX_TASK_REQUEUES,
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
                "started_at": time.time(),
                "stage": "starting",
                "stage_detail": "等待执行线程启动",
                "heartbeat_at": time.time(),
                "output_dir": str(APP_ROOT / "outputs" / account),
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

    def _upload_file(self):
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
        }
        if suffix not in allowed:
            raise ValueError("仅支持常见图片、视频或音频文件")
        target = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
        target.write_bytes(content)
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
        if path == "/api/files":
            return self._json(_scan_files())
        if path == "/api/workflows":
            return self._json(_public_workflows())
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
            return self._json(LICENSE.reset())

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
            workflow_id = _validate_workflow_id(
                data.get("workflow_id") or DEFAULT_WORKFLOW_ID
            )
            profile = PROFILES / account
            cfg_path = profile / "config.json"
            old = _read_json(cfg_path, {})
            now = time.time()
            cfg = {
                **old,
                "phone": phone,
                "workflow_id": workflow_id,
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
                raise ValueError("请先保存电话号码和 Workflow ID")
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

                    if getattr(sys, "frozen", False):
                        import random
                        tag = session["session_id"]
                        _login_processes[account] = tag
                        try:
                            _login_executor.submit(
                                _login_thread, account, profile, tag)
                        except Exception:
                            _login_processes.pop(account, None)
                            raise
                    else:
                        phone = str(_read_json(profile / "config.json", {}).get("phone", ""))
                        proc = subprocess.Popen(
                            [sys.executable, str(BUNDLE_ROOT / "sms_login.py"),
                              "--profile", str(profile), "--phone", phone,
                              "--timeout", "600",
                              "--session-id", session["session_id"],
                              "--ipc-token", session["token"],
                              "--ipc-url",
                              f"http://127.0.0.1:{self.server.server_address[1]}"],
                            cwd=str(APP_ROOT),
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
            old_task_id = str(data.get("task_id") or "")
            if not old_task_id:
                raise ValueError("缺少 task_id")
            with _tasks_lock:
                old_task = _tasks.get(old_task_id)
                if not old_task:
                    raise ValueError("任务不存在")
                input_paths = dict(old_task.get("input_paths") or {})
                requested = old_task.get("requested_account", "auto")
                workflow = _workflow_config(old_task.get("workflow_key"))

            if not input_paths:
                raise ValueError("原任务缺少素材路径，无法重新提交")

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
            None, False, "Local\\YunComfyUI-Client-8080"
        )
        if not instance_mutex:
            raise OSError("无法创建工作台单实例锁")
        if ctypes.get_last_error() == 183:
            print("YunComfyUI 工作台已经在运行。")
            kernel32.CloseHandle(instance_mutex)
            return

    actual_port = PORT
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", actual_port), Handler)
    except OSError as exc:
        raise OSError(
            f"本机端口 {actual_port} 已被其他程序占用，请关闭占用程序后重试"
        ) from exc

    print("=" * 56)
    print("  RunningHub 多账号任务台")
    print(f"  数据目录:   {DATA}")
    print(f"  账号目录:   {PROFILES}")
    print(f"  输出目录:   {APP_ROOT / 'outputs'}")
    print(f"  服务地址:   http://localhost:{actual_port}")
    print("=" * 56)
    logger.info("Server listening on http://localhost:%d", actual_port)
    threading.Timer(
        0.8, lambda: webbrowser.open(f"http://127.0.0.1:{actual_port}")
    ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        _executor.shutdown(wait=False)
        _login_executor.shutdown(wait=False)
        server.server_close()


if __name__ == "__main__":
    main()
