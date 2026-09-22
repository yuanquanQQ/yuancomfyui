import time
import base64
import json
from unittest import mock

import pytest

import server
from runninghub_client.browser import BrowserRunner, LoginExpiredError


def test_auth_rejection_text_retries_on_another_account():
    for message in (
        'Upload HTTP 401: {"error":"No auth data provided/upload/image"}',
        '{"code":403,"msg":"TOKEN_MISSION"}',
        "RunningHub 登录态已失效（上传接口返回未授权），请重新登录该账号后再试",
    ):
        assert server._is_auth_rejection_text(message) is True
    assert server._automatic_retry_reason(message) == "登录已过期，切换其他账号重试"


def test_plain_upload_failure_still_retries():
    message = "All direct upload endpoints failed"
    assert server._is_auth_rejection_text(message) is False
    assert server._automatic_retry_reason(message) == "任务失败"


def test_mark_account_session_expired_records_revocation_without_poisoning_refresh_state(tmp_path, monkeypatch):
    account = "13600000000"
    profile = tmp_path / account
    profile.mkdir(parents=True)
    state = profile / "state.json"
    future = time.time() + 3600
    state.write_text(
        __import__("json").dumps({
            "cookies": [
                {"name": "Rh-Accesstoken", "value": "x", "expires": future},
                {"name": "other", "value": "y", "expires": -1},
            ],
            "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
                {"name": "Rh-Expire-In", "value": str(future * 1000)},
            ]}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "PROFILES", tmp_path)

    server._mark_account_session_expired(account)

    import json
    written = json.loads(state.read_text(encoding="utf-8"))
    token = next(c for c in written["cookies"]
                 if c["name"] == "Rh-Accesstoken")
    assert token["expires"] < time.time()
    stored_expiry = written["origins"][0]["localStorage"][0]["value"]
    assert float(stored_expiry) / 1000 > time.time()
    assert written["session_revoked"] is True
    info = server._session_info(state)
    assert info["valid"] is False
    assert info["status"] == "expired"


def test_opaque_access_token_uses_local_storage_session_expiry(tmp_path):
    state = tmp_path / "state.json"
    future_cookie = time.time() - 60
    future_session = (time.time() + 86400) * 1000
    state.write_text(
        __import__("json").dumps({
            "cookies": [{
                "name": "Rh-Accesstoken",
                "value": "opaque-token-without-jwt-parts",
                "expires": future_cookie,
            }],
            "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
                {"name": "Rh-Expire-In", "value": str(future_session)},
            ]}],
        }),
        encoding="utf-8",
    )

    info = server._session_info(state)

    assert info["valid"] is True
    assert info["status"] == "valid"
    assert info["expires_at"] > time.time()


def test_expired_access_jwt_with_live_refresh_session_is_restorable(tmp_path):
    state = tmp_path / "state.json"
    expired_payload = base64.urlsafe_b64encode(json.dumps({
        "exp": time.time() - 3600,
    }).encode("utf-8")).decode("ascii").rstrip("=")
    future_session = (time.time() + 86400) * 1000
    state.write_text(json.dumps({
        "cookies": [{
            "name": "Rh-Accesstoken",
            "value": f"header.{expired_payload}.signature",
            "expires": time.time() - 3600,
        }],
        "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
            {"name": "Rh-Refreshtoken", "value": "saved-refresh-token"},
            {"name": "Rh-Expire-In", "value": str(future_session)},
        ]}],
    }), encoding="utf-8")

    info = server._session_info(state)

    assert info["valid"] is True
    assert info["status"] == "refreshable"
    assert info["expires_at"] > time.time()


def test_legacy_revoked_cookie_can_use_still_live_refresh_state(tmp_path):
    state = tmp_path / "state.json"
    future_session = (time.time() + 86400) * 1000
    state.write_text(
        __import__("json").dumps({
            "cookies": [{
                "name": "Rh-Accesstoken", "value": "revoked",
                "expires": time.time() - 1,
            }],
            "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
                {"name": "Rh-Refreshtoken", "value": "stale-refresh-token"},
                {"name": "Rh-Expire-In", "value": str(future_session)},
            ]}],
        }),
        encoding="utf-8",
    )

    info = server._session_info(state)

    assert info["valid"] is True
    assert info["status"] == "valid"


def test_auth_probe_sends_frontend_authorization_header(tmp_path):
    runner = BrowserRunner(user_data_dir=tmp_path)
    response = mock.MagicMock(status=200)
    response.text.return_value = '{"code":404,"msg":"NOT_FOUND"}'
    runner._page = mock.MagicMock()
    runner._page.evaluate.return_value = "saved-access-token"
    runner._page.request.get.return_value = response

    assert runner._live_auth_revoked() is False
    runner._page.request.get.assert_called_once_with(
        "https://www.runninghub.cn/api/comfyui/tasks",
        headers={"Authorization": "Bearer saved-access-token"},
        timeout=15000,
    )


def test_browser_skips_expired_access_cookie_when_refresh_state_exists(tmp_path):
    past_cookie = time.time() - 60
    future_session = time.time() + 86400
    (tmp_path / "state.json").write_text(
        __import__("json").dumps({
            "cookies": [{
                "name": "Rh-Accesstoken",
                "value": "opaque-token-without-jwt-parts",
                "domain": ".runninghub.cn",
                "path": "/",
                "expires": past_cookie,
            }],
            "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
                {"name": "Rh-Refreshtoken", "value": "saved-refresh-token"},
                {"name": "Rh-Expire-In", "value": str(future_session * 1000)},
            ]}],
        }),
        encoding="utf-8",
    )
    runner = BrowserRunner(user_data_dir=tmp_path)

    class Context:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, cookies):
            self.cookies = cookies

        def add_init_script(self, script):
            pass

    runner._context = Context()

    runner._inject_saved_state()

    assert runner._context.cookies == []


def test_browser_does_not_restore_poisoned_expiry_with_refresh_token(tmp_path):
    poisoned_expiry = str((time.time() - 3600) * 1000)
    (tmp_path / "state.json").write_text(json.dumps({
        "cookies": [],
        "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
            {"name": "Rh-Refreshtoken", "value": "saved-refresh-token"},
            {"name": "Rh-Expire-In", "value": poisoned_expiry},
        ]}],
    }), encoding="utf-8")
    runner = BrowserRunner(user_data_dir=tmp_path)

    class Context:
        def __init__(self):
            self.scripts = []

        def add_init_script(self, script):
            self.scripts.append(script)

    runner._context = Context()

    runner._inject_saved_state()

    assert len(runner._context.scripts) == 1
    assert "Rh-Refreshtoken" in runner._context.scripts[0]
    assert poisoned_expiry not in runner._context.scripts[0]


def test_missing_cookie_uses_refreshable_local_storage_session(tmp_path):
    state = tmp_path / "state.json"
    future_session = (time.time() + 86400) * 1000
    state.write_text(
        __import__("json").dumps({
            "cookies": [],
            "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
                {"name": "Rh-Accesstoken", "value": "saved-access-token"},
                {"name": "Rh-Refreshtoken", "value": "saved-refresh-token"},
                {"name": "Rh-Expire-In", "value": str(future_session)},
            ]}],
        }),
        encoding="utf-8",
    )

    info = server._session_info(state)

    assert info["valid"] is True
    assert info["status"] == "refreshable"


def test_browser_navigates_once_to_refresh_local_storage_login(tmp_path):
    runner = BrowserRunner(user_data_dir=tmp_path)
    runner._page = mock.MagicMock()
    runner._load_state = mock.MagicMock(return_value={
        "origins": [{"origin": "https://www.runninghub.cn", "localStorage": [
            {"name": "Rh-Refreshtoken", "value": "saved-refresh-token"},
        ]}],
    })
    runner.ensure_logged_in = mock.MagicMock(side_effect=[False, True])

    assert runner._restore_saved_login() is True
    runner._page.goto.assert_called_once_with(
        "https://www.runninghub.cn/",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    assert runner.ensure_logged_in.call_args_list == [
        mock.call(timeout=0), mock.call(timeout=60),
    ]


def test_login_expired_error_recognised_as_runtime_error():
    assert issubclass(LoginExpiredError, RuntimeError)
