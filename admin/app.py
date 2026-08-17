import csv
from pathlib import Path

import pyperclip
import webview

from api_client import ApiError, LicenseApiClient


APP_DIR = Path(__file__).resolve().parent
SERVER_URL = "http://124.223.224.38"


class AdminBridge:
    def __init__(self):
        # PyWebView recursively exposes public object attributes. Keep internal
        # objects private so bridge registration only scans the intended methods.
        self._client = LicenseApiClient()
        self._client.configure(SERVER_URL)
        self._window = None

    @staticmethod
    def _ok(data=None):
        return {"ok": True, "data": data}

    @staticmethod
    def _error(exc):
        return {"ok": False, "error": str(exc)}

    def get_config(self):
        return self._ok({"server_url": SERVER_URL})

    def set_server(self, server_url):
        try:
            self._client.configure(SERVER_URL)
            health = self._client.health()
            return self._ok(health)
        except ApiError as exc:
            return self._error(exc)

    def login(self, username, password):
        try:
            return self._ok(self._client.login(str(username), str(password)))
        except ApiError as exc:
            return self._error(exc)

    def logout(self):
        self._client.logout()
        return self._ok()

    def change_password(self, current_password, new_password):
        return self._call(self._client.post, "/api/admin/password", {
            "current_password": str(current_password), "new_password": str(new_password)
        })

    def stats(self):
        return self._call(self._client.get, "/api/admin/stats")

    def cards(self, status="", search=""):
        params = {"limit": 300}
        if status:
            params["status"] = status
        if search:
            params["search"] = search
        return self._call(self._client.get, "/api/admin/cards", params)

    def generate_cards(self, payload):
        return self._call(self._client.post, "/api/admin/cards/generate", payload)

    def update_card(self, card_id, action):
        return self._call(self._client.patch, f"/api/admin/cards/{card_id}", {"action": action})

    def licenses(self, status="", search=""):
        params = {"limit": 300}
        if status:
            params["status"] = status
        if search:
            params["search"] = search
        return self._call(self._client.get, "/api/admin/licenses", params)

    def license_action(self, license_id, action, days=None, note=""):
        payload = {"action": action, "note": note or None}
        if days:
            payload["days"] = int(days)
        return self._call(self._client.post, f"/api/admin/licenses/{license_id}/action", payload)

    def create_rebind_code(self, license_id, notes=""):
        return self._call(
            self._client.post, f"/api/admin/licenses/{license_id}/rebind-code", {"notes": notes or None}
        )

    def unbind_device(self, device_id):
        return self._call(self._client.post, f"/api/admin/devices/{device_id}/unbind", {})

    def audit_logs(self):
        return self._call(self._client.get, "/api/admin/audit-logs", {"limit": 300})

    def copy_text(self, value):
        try:
            pyperclip.copy(str(value))
            return self._ok()
        except pyperclip.PyperclipException as exc:
            return self._error(exc)

    def export_codes(self, codes):
        try:
            if not self._window:
                raise ValueError("窗口尚未初始化")
            selection = self._window.create_file_dialog(
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
    bridge._window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
