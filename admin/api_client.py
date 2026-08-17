from urllib.parse import urljoin

import requests


class ApiError(Exception):
    pass


class LicenseApiClient:
    def __init__(self):
        self.base_url = ""
        self.session = requests.Session()

    def configure(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"
        self.session.headers.pop("Authorization", None)

    def _request(self, method: str, path: str, **kwargs):
        if not self.base_url:
            raise ApiError("请先设置服务器地址")
        try:
            response = self.session.request(
                method, urljoin(self.base_url, path.lstrip("/")), timeout=(5, 30), **kwargs
            )
        except requests.RequestException as exc:
            raise ApiError(f"无法连接授权服务器：{exc}") from exc
        if response.status_code == 401:
            self.session.headers.pop("Authorization", None)
        if not response.ok:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(str(detail or f"服务器返回 {response.status_code}"))
        if response.status_code == 204:
            return None
        return response.json()

    def health(self):
        return self._request("GET", "/api/health")

    def login(self, username: str, password: str):
        result = self._request("POST", "/api/admin/login", json={"username": username, "password": password})
        self.session.headers["Authorization"] = f"Bearer {result['access_token']}"
        return {"expires_in": result["expires_in"]}

    def logout(self):
        self.session.headers.pop("Authorization", None)

    def get(self, path: str, params=None):
        return self._request("GET", path, params=params)

    def post(self, path: str, payload=None):
        return self._request("POST", path, json=payload or {})

    def patch(self, path: str, payload=None):
        return self._request("PATCH", path, json=payload or {})
