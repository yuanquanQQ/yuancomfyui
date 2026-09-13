import time

import pytest

import server
from runninghub_client.browser import LoginExpiredError


def test_auth_rejection_text_is_not_retried():
    for message in (
        'Upload HTTP 401: {"error":"No auth data provided/upload/image"}',
        '{"code":403,"msg":"TOKEN_MISSION"}',
        "RunningHub 登录态已失效（上传接口返回未授权），请重新登录该账号后再试",
    ):
        assert server._is_auth_rejection_text(message) is True
        assert server._automatic_retry_reason(message) is None


def test_plain_upload_failure_still_retries():
    message = "All direct upload endpoints failed"
    assert server._is_auth_rejection_text(message) is False
    assert server._automatic_retry_reason(message) == "任务失败"


def test_mark_account_session_expired_shortens_cookie_expiry(tmp_path, monkeypatch):
    account = "13600000000"
    profile = tmp_path / account
    profile.mkdir(parents=True)
    state = profile / "state.json"
    future = time.time() + 3600
    state.write_text(
        __import__("json").dumps({"cookies": [
            {"name": "Rh-Accesstoken", "value": "x", "expires": future},
            {"name": "other", "value": "y", "expires": -1},
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "PROFILES", tmp_path)

    server._mark_account_session_expired(account)

    import json
    written = json.loads(state.read_text(encoding="utf-8"))
    token = next(c for c in written["cookies"]
                 if c["name"] == "Rh-Accesstoken")
    assert token["expires"] < time.time()
    info = server._session_info(state)
    assert info["valid"] is False
    assert info["status"] == "expired"


def test_login_expired_error_recognised_as_runtime_error():
    assert issubclass(LoginExpiredError, RuntimeError)
