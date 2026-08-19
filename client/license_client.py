"""Machine-bound client for the YunComfyUI license service."""

import base64
import ctypes
import hashlib
import json
import os
import platform
import threading
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization


CHECK_INTERVAL_SECONDS = 12 * 60 * 60
RETRY_INTERVAL_SECONDS = 60


class LicenseError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _windows_machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
        flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            flags,
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError:
        return ""


def _system_drive_serial() -> str:
    if os.name != "nt":
        return ""
    root = os.environ.get("SystemDrive", "C:") + "\\"
    serial = wintypes.DWORD()
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial),
            None, None, None, 0,
        )
        return f"{serial.value:08X}" if ok else ""
    except (AttributeError, OSError):
        return ""


def machine_hash() -> str:
    components = [
        _windows_machine_guid(),
        _system_drive_serial(),
        platform.node(),
        str(uuid.getnode()),
    ]
    stable = "|".join(value.strip().lower() for value in components if value)
    if not stable:
        raise LicenseError("无法读取本机机器码")
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi_libraries():
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _dpapi_protect(value: str) -> str:
    raw = value.encode("utf-8")
    if os.name != "nt":
        return "local:" + base64.b64encode(raw).decode("ascii")
    crypt32, kernel32 = _dpapi_libraries()
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "YunComfyUI License", None, None, None, 5,
        ctypes.byref(target),
    ):
        raise LicenseError(f"无法加密本机授权令牌（Windows 错误 {ctypes.get_last_error()}）")
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, wintypes.HLOCAL))


def _dpapi_unprotect(value: str) -> str:
    prefix, _, encoded = value.partition(":")
    raw = base64.b64decode(encoded)
    if prefix == "local" and os.name != "nt":
        return raw.decode("utf-8")
    if prefix != "dpapi" or os.name != "nt":
        raise LicenseError("本机授权令牌格式无效")
    crypt32, kernel32 = _dpapi_libraries()
    buffer = ctypes.create_string_buffer(raw)
    source = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)
    ):
        raise LicenseError(
            f"本机授权令牌无法解密，授权可能来自另一台电脑（Windows 错误 {ctypes.get_last_error()}）"
        )
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, wintypes.HLOCAL))


class LicenseManager:
    def __init__(self, state_dir: Path, server_url: str):
        self.state_dir = state_dir
        self.state_path = state_dir / "license_state.json"
        self.server_url = server_url.rstrip("/")
        self.session = requests.Session()
        self.lock = threading.RLock()
        self.last_attempt_at = 0.0
        self.state = self._read_state()
        if not self.state.get("install_id"):
            self.state["install_id"] = uuid.uuid4().hex
            self._save_state()

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = self.session.request(
                method, f"{self.server_url}{path}", json=payload, timeout=(3, 12)
            )
        except requests.RequestException as exc:
            raise ConnectionError(f"授权服务器无法连接：{exc}") from exc
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise LicenseError(str(detail or f"授权服务器返回 {response.status_code}"))
        return response.json()

    def _public_key(self) -> str:
        existing = self.state.get("public_key_pem")
        if existing:
            return existing
        result = self._request("GET", "/api/v1/license/public-key")
        if result.get("algorithm") != "Ed25519" or not result.get("public_key_pem"):
            raise LicenseError("授权服务器公钥无效")
        return result["public_key_pem"]

    def _verify_receipt(self, receipt: str, public_key_pem: str) -> dict:
        try:
            encoded_body, encoded_signature = receipt.split(".", 1)
            body = _b64decode(encoded_body)
            signature = _b64decode(encoded_signature)
            public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
            public_key.verify(signature, body)
            payload = json.loads(body)
        except Exception as exc:
            raise LicenseError("授权签名验证失败") from exc
        if payload.get("machine_hash") != machine_hash():
            raise LicenseError("授权与当前机器不匹配")
        if self.state.get("license_id") and payload.get("license_id") != self.state["license_id"]:
            raise LicenseError("授权编号不匹配")
        if payload.get("status") != "active":
            raise LicenseError("授权当前不可用")
        expires_at = _parse_time(payload.get("expires_at"))
        if expires_at and expires_at <= _utcnow():
            raise LicenseError("授权已到期")
        offline_until = _parse_time(payload.get("offline_until"))
        if not offline_until or offline_until <= _utcnow():
            raise LicenseError("离线授权已超时，请连接授权服务器")
        return payload

    def _store_response(self, result: dict, public_key_pem: str | None = None):
        key = public_key_pem or self.state.get("public_key_pem")
        if not key:
            raise LicenseError("缺少授权签名公钥")
        previous_license_id = self.state.get("license_id")
        self.state["license_id"] = result["license_id"]
        try:
            payload = self._verify_receipt(result["signed_receipt"], key)
        except Exception:
            if previous_license_id is None:
                self.state.pop("license_id", None)
            else:
                self.state["license_id"] = previous_license_id
            raise
        self.state.update({
            "license_id": result["license_id"],
            "receipt": result["signed_receipt"],
            "public_key_pem": key,
            "last_check_at": time.time(),
            "last_error": None,
            "server_denied": False,
            "plan_type": payload.get("plan_type"),
            "expires_at": payload.get("expires_at"),
        })
        if result.get("refresh_token"):
            self.state["refresh_token_protected"] = _dpapi_protect(result["refresh_token"])
        self._save_state()

    def activate(self, code: str) -> dict:
        with self.lock:
            key = self._public_key()
            result = self._request("POST", "/api/v1/license/activate", {
                "code": code,
                "machine_hash": machine_hash(),
                "install_id": self.state["install_id"],
                "device_label": platform.node() or "Windows PC",
                "app_version": "1.0.0",
            })
            self._store_response(result, key)
            return self.status(check_online=False)

    def _check_online(self):
        result = self._request("POST", "/api/v1/license/check", self._auth_payload())
        self._store_response(result)

    def _auth_payload(self) -> dict:
        protected = self.state.get("refresh_token_protected")
        if not self.state.get("license_id") or not protected:
            raise LicenseError("尚未激活")
        return {
            "license_id": self.state["license_id"],
            "refresh_token": _dpapi_unprotect(protected),
            "machine_hash": machine_hash(),
            "install_id": self.state["install_id"],
            "app_version": "1.0.0",
        }

    def fetch_workflows(self) -> dict:
        """Fetch the server-owned catalog without persisting it on disk."""
        with self.lock:
            result = self._request(
                "POST", "/api/v1/license/workflows", self._auth_payload()
            )
            if not isinstance(result.get("workflows"), list):
                raise LicenseError("工作流服务返回的数据无效")
            return result

    def renew(self, code: str) -> dict:
        with self.lock:
            protected = self.state.get("refresh_token_protected")
            if not self.state.get("license_id") or not protected:
                raise LicenseError("请先完成首次激活")
            result = self._request("POST", "/api/v1/license/renew", {
                "license_id": self.state["license_id"],
                "refresh_token": _dpapi_unprotect(protected),
                "machine_hash": machine_hash(),
                "install_id": self.state["install_id"],
                "app_version": "1.0.0",
                "code": code,
            })
            self._store_response(result)
            return self.status(check_online=False)

    def check_now(self) -> dict:
        with self.lock:
            if not self.state.get("license_id"):
                return self._public_status(False, "尚未激活")
            self.last_attempt_at = time.time()
            try:
                self._check_online()
            except ConnectionError as exc:
                self.state["last_error"] = str(exc)
            except LicenseError as exc:
                self.state["server_denied"] = True
                self.state["last_error"] = str(exc)
                self._save_state()
                return self._public_status(False, str(exc))
            return self.status(check_online=False)

    def reset(self) -> dict:
        """Clear server-issued credentials while preserving this installation."""
        with self.lock:
            install_id = self.state.get("install_id") or uuid.uuid4().hex
            self.state = {"install_id": install_id}
            self.last_attempt_at = 0.0
            self._save_state()
            return self._public_status(False, "旧授权已清除，请输入新卡密激活")

    def status(self, check_online: bool = True) -> dict:
        with self.lock:
            receipt = self.state.get("receipt")
            key = self.state.get("public_key_pem")
            if not receipt or not key:
                return self._public_status(False, "未激活")
            if self.state.get("server_denied"):
                return self._public_status(False, self.state.get("last_error") or "授权不可用")
            now = time.time()
            last_check = float(self.state.get("last_check_at") or 0)
            # Startup is local-first: a valid signed receipt is sufficient to
            # open the client. Explicit "重新校验" still uses check_now().
            if False and check_online and now - last_check >= CHECK_INTERVAL_SECONDS and now - self.last_attempt_at >= RETRY_INTERVAL_SECONDS:
                self.last_attempt_at = now
                try:
                    self._check_online()
                except ConnectionError as exc:
                    self.state["last_error"] = str(exc)
                except LicenseError as exc:
                    self.state["server_denied"] = True
                    self.state["last_error"] = str(exc)
                    self._save_state()
                    return self._public_status(False, str(exc))
            receipt = self.state.get("receipt")
            key = self.state.get("public_key_pem")
            try:
                payload = self._verify_receipt(receipt, key)
            except LicenseError as exc:
                return self._public_status(False, str(exc))
            if self.state.get("last_error"):
                mode = "offline"
            elif now - float(self.state.get("last_check_at") or 0) < 90:
                mode = "online"
            else:
                mode = "cached"
            return self._public_status(True, "授权有效", payload, mode)

    def _public_status(self, active: bool, message: str, payload: dict | None = None,
                       mode: str = "inactive") -> dict:
        payload = payload or {}
        return {
            "active": active,
            "message": message,
            "mode": mode,
            "license_id": self.state.get("license_id"),
            "machine_hash": machine_hash(),
            "plan_type": payload.get("plan_type") or self.state.get("plan_type"),
            "expires_at": payload.get("expires_at") or self.state.get("expires_at"),
            "offline_until": payload.get("offline_until"),
            "server_url": self.server_url,
        }
