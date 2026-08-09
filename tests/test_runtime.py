from __future__ import annotations

from http.cookies import SimpleCookie
from threading import Event
from typing import Any

import pytest

from agent_webview.errors import BrowserNotReadyError
from agent_webview.events import EventBuffer
from agent_webview.models import (
    DomClickRequest,
    DomDispatchRequest,
    DomInputRequest,
    DomListenerRequest,
    DomQueryRequest,
    InstrumentationRequest,
)
from agent_webview.runtime import BrowserRuntime


class EventHook:
    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class WindowEvents:
    def __init__(self) -> None:
        self.before_load = EventHook()
        self.loaded = EventHook()
        self.shown = EventHook()
        self.closed = EventHook()


class FakeWindow:
    def __init__(self) -> None:
        self.events = WindowEvents()
        self.title = "示例"
        self.x = 10
        self.y = 20
        self.width = 1280
        self.height = 900
        self.native = type("Native", (), {"Handle": 42})()
        self.scripts: list[str] = []
        self.visible = False
        self.destroyed = False
        self.cleared = False
        self.url = "https://example.com/"

    def get_current_url(self) -> str:
        return self.url

    def run_js(self, script: str) -> None:
        self.scripts.append(script)

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def load_url(self, url: str) -> None:
        self.url = url

    def get_cookies(self):
        cookie = SimpleCookie()
        cookie["session"] = "测试值"
        return [cookie]

    def clear_cookies(self) -> None:
        self.cleared = True

    def destroy(self) -> None:
        self.destroyed = True


class FakeBridge:
    def __init__(self) -> None:
        self.ready = Event()
        self.ready.set()
        self.window = None
        self.calls: list[tuple[str, bool, float]] = []

    def attach_window(self, window) -> None:
        self.window = window

    def execute(self, code: str, *, expression: bool, timeout: float):
        self.calls.append((code, expression, timeout))
        return {"executed": True}


def test_runtime_window_and_dom_lifecycle() -> None:
    bridge = FakeBridge()
    events = EventBuffer()
    runtime = BrowserRuntime(
        session_id="session-1",
        window_id="window-1",
        bridge=bridge,
        events=events,
    )
    window = FakeWindow()
    runtime.attach_window(window, visible=False)
    runtime.operational_ready.set()

    assert len(window.events.loaded.handlers) == 1
    assert runtime.status()["native_window_id"] == 42
    assert runtime.show()["visible"] is True
    assert runtime.hide()["visible"] is False

    assert runtime.evaluate("1 + 1", 5) == {"executed": True}
    assert runtime.execute("document.title", 5) == {"executed": True}
    assert runtime.dom_query(DomQueryRequest(selector="a")) == {"executed": True}
    assert runtime.dom_click(DomClickRequest(selector="button")) == {
        "executed": True
    }
    assert runtime.dom_input(DomInputRequest(selector="input", value="值")) == {
        "executed": True
    }
    assert runtime.dom_dispatch(
        DomDispatchRequest(selector="form", event="submit")
    ) == {"executed": True}

    installed = runtime.add_dom_listener(
        DomListenerRequest(id="watch", selector="form", event="submit")
    )
    assert installed["installed"]["id"] == "watch"
    assert runtime.remove_dom_listener("watch") == {"removed": True, "id": "watch"}

    configured = runtime.set_instrumentation(InstrumentationRequest(mutations=True))
    assert configured["mutations"] is True
    assert window.scripts

    assert runtime.get_cookies()[0]["name"] == "session"
    assert runtime.clear_cookies() == {"cleared": True}
    assert window.cleared is True

    navigation = runtime.navigate("https://example.com/next")
    assert navigation["accepted"] is True
    with pytest.raises(BrowserNotReadyError):
        runtime.evaluate("1", 1)

    runtime.operational_ready.set()
    runtime.destroy()
    assert window.destroyed is True


def test_runtime_lifecycle_events_update_readiness() -> None:
    bridge = FakeBridge()
    runtime = BrowserRuntime(
        session_id="session-1",
        window_id="window-1",
        bridge=bridge,
        events=EventBuffer(),
    )
    runtime.attach_window(FakeWindow(), visible=False)
    runtime.operational_ready.set()

    runtime._on_before_load()
    assert runtime.operational_ready.is_set() is False
    runtime._on_shown()
    assert runtime.visible is True
    runtime._on_closed()
    assert runtime.closed is True
