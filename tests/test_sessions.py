from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from agent_webview.cookies import SnapshotStore
from agent_webview.models import SessionCreateRequest
from agent_webview.proxy import ProxyConfigurationError
from agent_webview.sessions import Session, SessionManager, WorkerResponseError


class FakeProcess:
    def __init__(self, pid: int = 1234) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


def _manager(tmp_path: Path, *, proxy: str | None = None) -> SessionManager:
    return SessionManager(
        runtime_dir=tmp_path / "runtime",
        snapshot_store=SnapshotStore(tmp_path / "snapshots"),
        proxy=proxy,
    )


def test_create_and_destroy_session_uses_private_config(tmp_path, monkeypatch) -> None:
    manager = _manager(tmp_path)
    process = FakeProcess()
    monkeypatch.setattr("agent_webview.sessions.subprocess.Popen", lambda *_, **__: process)
    monkeypatch.setattr(
        manager,
        "_wait_ready",
        lambda *_: {"pid": process.pid, "port": 54321},
    )
    monkeypatch.setattr(
        manager,
        "request",
        lambda *_, **__: (_ for _ in ()).throw(httpx.ConnectError("不可用")),
    )

    created = manager.create(
        SessionCreateRequest(
            url="https://example.com/",
            cookies=[{"name": "session", "value": "测试值"}],
        )
    )
    session = manager.get(created["session_id"])
    config = json.loads(session.config_file.read_text(encoding="utf-8"))

    assert config["url"] == "https://example.com/"
    assert config["cookies"][0]["name"] == "session"
    assert config["proxy"] is None
    assert config["token"]
    if os.name != "nt":
        assert stat.S_IMODE(session.config_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(session.config_file.parent.stat().st_mode) == 0o700

    result = manager.destroy(session.session_id)
    assert result["exit_code"] == 0
    assert not session.config_file.parent.exists()
    manager.close()


@pytest.mark.parametrize(
    ("global_proxy", "window_proxy", "expected_url", "expected_scope"),
    [
        (None, "http://127.0.0.1:7001", "http://127.0.0.1:7001", "window"),
        (
            "https://proxy.example:7443",
            None,
            "https://proxy.example:7443",
            "global",
        ),
        (
            "http://127.0.0.1:7002",
            "http://127.0.0.1:7003",
            "http://127.0.0.1:7002",
            "global",
        ),
    ],
)
def test_session_proxy_scope_and_global_precedence(
    tmp_path,
    monkeypatch,
    global_proxy: str | None,
    window_proxy: str | None,
    expected_url: str,
    expected_scope: str,
) -> None:
    manager = _manager(tmp_path, proxy=global_proxy)
    process = FakeProcess()
    monkeypatch.setattr("agent_webview.sessions.subprocess.Popen", lambda *_, **__: process)
    monkeypatch.setattr(
        manager,
        "_wait_ready",
        lambda *_: {"pid": process.pid, "port": 54321},
    )
    monkeypatch.setattr(
        manager,
        "request",
        lambda *_, **__: (_ for _ in ()).throw(httpx.ConnectError("不可用")),
    )

    created = manager.create(SessionCreateRequest(proxy=window_proxy))
    session = manager.get(created["session_id"])
    config = json.loads(session.config_file.read_text(encoding="utf-8"))

    assert config["proxy"] == {"url": expected_url, "scope": expected_scope}
    manager.destroy(session.session_id)
    manager.close()


def test_request_maps_worker_errors_and_empty_responses(tmp_path) -> None:
    manager = _manager(tmp_path)
    process = FakeProcess()
    session = Session(
        session_id="session-1",
        window_id="window-1",
        token="worker-token",
        process=process,
        pid=process.pid,
        port=54321,
        created_at="2026-01-01T00:00:00+00:00",
        config_file=tmp_path / "worker.json",
        ready_file=tmp_path / "ready.json",
        requested_url="about:blank",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer worker-token"
        if request.url.path == "/error":
            return httpx.Response(422, json={"detail": "请求失败"})
        return httpx.Response(204)

    manager._client.close()
    manager._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert manager.request(session, "DELETE", "/empty") is None
    with pytest.raises(WorkerResponseError) as error:
        manager.request(session, "POST", "/error")
    assert error.value.status_code == 422
    assert error.value.detail == {"detail": "请求失败"}

    process.returncode = 1
    with pytest.raises(ProcessLookupError):
        manager.request(session, "GET", "/status")
    manager.close()


def test_cookie_overrides_replace_matching_identity() -> None:
    merged = SessionManager._merge_cookies(
        [{"name": "a", "value": "旧值", "domain": "example.com"}],
        [
            {"name": "a", "value": "新值", "domain": "example.com"},
            {"name": "b", "value": "2"},
        ],
    )

    assert [(item["name"], item["value"]) for item in merged] == [
        ("a", "新值"),
        ("b", "2"),
    ]


def test_worker_proxy_configuration_error_is_preserved(tmp_path) -> None:
    ready_file = tmp_path / "ready.json"
    ready_file.write_text(
        json.dumps({"error": "WKWebView 代理需要 macOS 14 或更高版本"}),
        encoding="utf-8",
    )

    with pytest.raises(ProxyConfigurationError, match="macOS 14"):
        SessionManager._wait_ready(FakeProcess(), ready_file)
