from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from agent_webview import __version__
from agent_webview.controller_api import create_controller_app
from agent_webview.cookies import SnapshotStore


def _window() -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "window_id": "window-1",
        "native_window_id": 42,
        "pid": 1234,
        "ready": True,
        "closed": False,
        "visible": False,
        "url": "https://example.com/",
        "title": "示例",
        "proxy": {
            "enabled": False,
            "scope": None,
            "server": None,
            "state": "disabled",
            "ip": None,
            "location": None,
        },
        "bounds": {"x": 0, "y": 0, "width": 1280, "height": 900},
        "latest_event_sequence": 0,
    }


def _session() -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "window_id": "window-1",
        "pid": 1234,
        "launcher_pid": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "requested_url": "https://example.com/",
        "state": "running",
        "exit_code": None,
        "process": {
            "pid": 1234,
            "status": "running",
            "create_time": 1.0,
            "num_threads": 2,
            "memory_rss": 1024,
        },
        "window": _window(),
    }


class FakeManager:
    def __init__(self, tmp_path) -> None:
        self.snapshot_store = SnapshotStore(tmp_path / "snapshots")
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def list(self) -> list[dict[str, Any]]:
        return [_session()]

    def create(self, _) -> dict[str, Any]:
        return _session()

    def get(self, session_id: str) -> str:
        if session_id != "session-1":
            raise KeyError(session_id)
        return session_id

    def describe(self, _) -> dict[str, Any]:
        return _session()

    def destroy(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "pid": 1234, "exit_code": 0}

    def request(
        self,
        _,
        method: str,
        path: str,
        **__,
    ) -> dict[str, Any]:
        if method == "GET" and path == "/v1/cookies":
            return {
                "url": "https://example.com/",
                "cookies": [{"name": "session", "value": "测试值"}],
            }
        if method == "GET" and path == "/v1/proxy":
            return _window()["proxy"]
        if path in {"/v1/window/show", "/v1/window/hide"}:
            return _window()
        return {"ok": True}


def test_controller_auth_schema_and_lifespan(tmp_path) -> None:
    manager = FakeManager(tmp_path)
    app = create_controller_app(manager, "test-token")

    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/v1/sessions").status_code == 401
        response = client.get(
            "/v1/sessions",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        assert response.json()["sessions"][0]["session_id"] == "session-1"

        openapi = client.get("/openapi.json").json()
        assert openapi["info"]["version"] == __version__
        schema = openapi["paths"]["/v1/sessions"]["get"]["responses"]["200"]
        assert schema["content"]["application/json"]["schema"]["$ref"].endswith(
            "/SessionListResponse"
        )
        proxy_schema = openapi["paths"]["/v1/sessions/{session_id}/proxy"]["get"]
        assert proxy_schema["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/ProxyStatus")

    assert manager.closed is True


def test_snapshot_endpoints_do_not_expose_authless_data(tmp_path) -> None:
    manager = FakeManager(tmp_path)
    app = create_controller_app(manager, "test-token")
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        assert client.get("/v1/cookie-snapshots").status_code == 401
        created = client.post(
            "/v1/sessions/session-1/cookie-snapshots",
            headers=headers,
            json={"name": "登录状态"},
        )
        assert created.status_code == 201
        snapshot_id = created.json()["snapshot_id"]

        loaded = client.get(
            f"/v1/cookie-snapshots/{snapshot_id}",
            headers=headers,
        )
        assert loaded.status_code == 200
        assert loaded.json()["cookies"][0]["name"] == "session"

        deleted = client.delete(
            f"/v1/cookie-snapshots/{snapshot_id}",
            headers=headers,
        )
        assert deleted.json() == {"deleted": True, "snapshot_id": snapshot_id}


def test_proxy_status_endpoint_supports_hidden_sessions(tmp_path) -> None:
    manager = FakeManager(tmp_path)
    app = create_controller_app(manager, "test-token")

    with TestClient(app) as client:
        response = client.get(
            "/v1/sessions/session-1/proxy?timeout=1",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == _window()["proxy"]
