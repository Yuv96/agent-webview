from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from agent_webview.events import EventBuffer
from agent_webview.worker_api import create_worker_app


class FakeRuntime:
    def __init__(self) -> None:
        self.events = EventBuffer()

    def status(self) -> dict[str, Any]:
        return {
            "session_id": "session-1",
            "window_id": "window-1",
            "native_window_id": None,
            "pid": 1234,
            "ready": True,
            "closed": False,
            "visible": False,
            "url": "about:blank",
            "title": "Agent Webview",
            "bounds": {"x": 0, "y": 0, "width": 1280, "height": 900},
            "latest_event_sequence": self.events.latest_sequence,
        }

    def show(self) -> dict[str, Any]:
        return self.status()

    def hide(self) -> dict[str, Any]:
        return self.status()

    def navigate(self, url: str) -> dict[str, Any]:
        return {"accepted": True, "url": url}

    def evaluate(self, code: str, timeout: float) -> Any:
        return {"code": code, "timeout": timeout}

    def execute(self, code: str, timeout: float) -> None:
        return None

    def get_cookies(self) -> list[dict[str, Any]]:
        return [{"name": "session", "value": "测试值"}]


def test_worker_core_endpoints_require_auth() -> None:
    runtime = FakeRuntime()
    app = create_worker_app(runtime, "worker-token")
    headers = {"Authorization": "Bearer worker-token"}

    with TestClient(app) as client:
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/v1/status").status_code == 401

        status = client.get("/v1/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["session_id"] == "session-1"

        navigation = client.post(
            "/v1/navigate",
            headers=headers,
            json={"url": "https://example.com/"},
        )
        assert navigation.json() == {
            "accepted": True,
            "url": "https://example.com/",
        }

        evaluated = client.post(
            "/v1/javascript/evaluate",
            headers=headers,
            json={"code": "1 + 1", "timeout": 5},
        )
        assert evaluated.json()["value"]["code"] == "1 + 1"


def test_worker_events_have_stable_schema() -> None:
    runtime = FakeRuntime()
    runtime.events.append("lifecycle", {"event": "ready"})
    app = create_worker_app(runtime, "worker-token")

    with TestClient(app) as client:
        response = client.get(
            "/v1/events",
            headers={"Authorization": "Bearer worker-token"},
        )

    assert response.status_code == 200
    assert response.json()["events"][0]["kind"] == "lifecycle"
    assert response.json()["latest_sequence"] == 1
