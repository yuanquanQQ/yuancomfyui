import json
from pathlib import Path

import pytest

import server


class FakeHttpServer:
    attempts = []
    blocked_ports = set()

    def __init__(self, address, handler):
        del handler
        host, port = address
        self.__class__.attempts.append(port)
        if port in self.__class__.blocked_ports:
            raise OSError("address in use")
        self.server_address = (host, 49152 if port == 0 else port)


def test_configured_port_defaults_and_supports_override(monkeypatch):
    monkeypatch.delenv("YUNCOMFYUI_PORT", raising=False)
    assert server._configured_port() == 8080

    monkeypatch.setenv("YUNCOMFYUI_PORT", "9000")
    assert server._configured_port() == 9000


def test_configured_port_rejects_invalid_override(monkeypatch):
    monkeypatch.setenv("YUNCOMFYUI_PORT", "not-a-port")
    with pytest.raises(ValueError, match="YUNCOMFYUI_PORT"):
        server._configured_port()


def test_http_server_scans_forward_when_preferred_port_is_occupied():
    FakeHttpServer.attempts = []
    FakeHttpServer.blocked_ports = {8080, 8081}

    httpd, actual_port = server._create_http_server(
        8080, server_class=FakeHttpServer
    )

    assert actual_port == 8082
    assert httpd.server_address == ("127.0.0.1", 8082)
    assert FakeHttpServer.attempts == [8080, 8081, 8082]


def test_http_server_allows_os_selected_port():
    FakeHttpServer.attempts = []
    FakeHttpServer.blocked_ports = set()

    _httpd, actual_port = server._create_http_server(
        0, server_class=FakeHttpServer
    )

    assert actual_port == 49152
    assert FakeHttpServer.attempts == [0]


def test_server_state_publishes_actual_port(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(server, "APP_ROOT", tmp_path)

    state_path = server._write_server_state(8084)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert state_path == tmp_path / ".runtime" / "server.json"
    assert state["port"] == 8084
    assert state["url"] == "http://127.0.0.1:8084"
    assert isinstance(state["pid"], int)
