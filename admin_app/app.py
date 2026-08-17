import csv
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pyperclip
import webview

from api_client import ApiError, LicenseApiClient


APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "YunComfyUI License Admin"
CONFIG_FILE = CONFIG_DIR / "config.json"


class AdminBridge:
    def __init__(self):
        self.client = LicenseApiClient()
        self.window = None
        self.config = self._load_config()
        if self.config.get("server_url"):
            self.client.configure(self.config["server_url"])

    @staticmethod
    def _load_config():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not config.get("server_url"):
                config["server_url"] = "http://127.0.0.1:8088"
            return config
        except (OSError, ValueError):
            return {"server_url": "http://127.0.0.1:8088"}

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _ok(data=None):
        return {"ok": True, "data": data}

    @staticmethod
    def _error(exc):
        return {"ok": False, "error": str(exc)}

    def get_config(self):
        return self._ok(self.config)

    def set_server(self, server_url):
        try:
            value = str(server_url).strip().rstrip("/")
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("服务器地址必须是完整的 http:// 或 https:// 地址")
            if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("远程服务器必须使用 HTTPS")
            self.client.configure(value)
            health = self.client.health()
            self.config["server_url"] = value
            self._save_config()
            return self._ok(health)
        except (ApiError, ValueError) as exc:
            return self._error(exc)

    def login(self, username, password):
        try:
            return self._ok(self.client.login(str(username), str(password)))
        except ApiError as exc:
            return self._error(exc)

    def logout(self):
        self.client.logout()
        return self._ok()

    def change_password(self, current_password, new_password):
        return self._call(self.client.post, "/api/admin/password", {
            "current_password": str(current_password), "new_password": str(new_password)
        })

    def stats(self):
        return self._call(self.client.get, "/api/admin/stats")

    def cards(self, status="", search=""):
        params = {"limit": 300}
        if status:
            params["status"] = status
        if search:
            params["search"] = search
        return self._call(self.client.get, "/api/admin/cards", params)

    def generate_cards(self, payload):
        return self._call(self.client.post, "/api/admin/cards/generate", payload)

    def update_card(self, card_id, action):
        return self._call(self.client.patch, f"/api/admin/cards/{card_id}", {"action": action})

    def licenses(self, status="", search=""):
        params = {"limit": 300}
        if status:
            params["status"] = status
        if search:
            params["search"] = search
        return self._call(self.client.get, "/api/admin/licenses", params)

    def license_action(self, license_id, action, days=None, note=""):
        payload = {"action": action, "note": note or None}
        if days:
            payload["days"] = int(days)
        return self._call(self.client.post, f"/api/admin/licenses/{license_id}/action", payload)

    def create_rebind_code(self, license_id, notes=""):
        return self._call(
            self.client.post, f"/api/admin/licenses/{license_id}/rebind-code", {"notes": notes or None}
        )

    def unbind_device(self, device_id):
        return self._call(self.client.post, f"/api/admin/devices/{device_id}/unbind", {})

    def audit_logs(self):
        return self._call(self.client.get, "/api/admin/audit-logs", {"limit": 300})

    def copy_text(self, value):
        try:
            pyperclip.copy(str(value))
            return self._ok()
        except pyperclip.PyperclipException as exc:
            return self._error(exc)

    def export_codes(self, codes):
        try:
            if not self.window:
                raise ValueError("窗口尚未初始化")
            selection = self.window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename="yuncomfyui-cards.csv",
                file_types=("CSV files (*.csv)",),
            )
            if not selection:
                return self._ok({"cancelled": True})
            if isinstance(selection, (list, tuple)):
                selection = selection[0]
            target = Path(selection)
            with target.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["card_code"])
                writer.writerows([[code] for code in codes])
            return self._ok({"path": str(target)})
        except (OSError, ValueError) as exc:
            return self._error(exc)

    def _call(self, method, *args):
        try:
            return self._ok(method(*args))
        except ApiError as exc:
            return self._error(exc)


def main():
    bridge = AdminBridge()
    window = webview.create_window(
        "YunComfyUI 授权管理",
        str(APP_DIR / "web" / "index.html"),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(1024, 680),
    )
    bridge.window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
