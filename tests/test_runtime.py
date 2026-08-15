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
from agent_webview.proxy import ProxyIdentity
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

    def set_title(self, title: str) -> None:
        self.title = title

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
        self.result: Any = {"executed": True}

    def attach_window(self, window) -> None:
        self.window = window

    def execute(self, code: str, *, expression: bool, timeout: float):
        self.calls.append((code, expression, timeout))
        return self.result


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
    assert runtime.status()["proxy"]["state"] == "disabled"
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


def test_runtime_loads_page_while_proxy_lookup_runs_and_updates_title() -> None:
    bridge = FakeBridge()
    events = EventBuffer()
    lookup_started = Event()
    release_lookup = Event()

    def lookup(proxy_url: str) -> ProxyIdentity:
        assert proxy_url == "http://127.0.0.1:7890"
        lookup_started.set()
        assert release_lookup.wait(2)
        return ProxyIdentity(ip="198.51.100.4", location="中国 / 香港")

    runtime = BrowserRuntime(
        session_id="session-1",
        window_id="window-1",
        bridge=bridge,
        events=events,
        title="代理调试",
        requested_url="https://example.com/",
        proxy_url="http://127.0.0.1:7890",
        proxy_scope="window",
        proxy_lookup=lookup,
    )
    window = FakeWindow()
    runtime.attach_window(window, visible=False)

    assert runtime.startup_url == "https://example.com/"
    assert runtime.initial_title == "[代理模式] 代理调试"

    runtime.start_proxy_lookup()
    assert lookup_started.wait(1)
    runtime._on_loaded()
    assert runtime.operational_ready.wait(1)
    assert runtime.proxy_status()["state"] == "checking"
    assert runtime.navigate("https://example.org/")["accepted"] is True

    release_lookup.set()
    status = runtime.proxy_status(timeout=2)

    assert status == {
        "enabled": True,
        "scope": "window",
        "server": "http://127.0.0.1:7890",
        "state": "active",
        "ip": "198.51.100.4",
        "location": "中国 / 香港",
    }
    assert window.url == "https://example.org/"
    assert window.title == (
        "[已进入代理模式 · 198.51.100.4 · 中国 / 香港] 代理调试"
    )
    proxy_events = events.get(after=0, limit=10, kinds=["proxy"]).events
    assert proxy_events[0]["payload"]["event"] == "active"


def test_runtime_keeps_proxy_mode_visible_when_ip_lookup_fails() -> None:
    bridge = FakeBridge()
    events = EventBuffer()

    def failed_lookup(_: str) -> ProxyIdentity:
        raise RuntimeError("查询不可用")

    runtime = BrowserRuntime(
        session_id="session-1",
        window_id="window-1",
        bridge=bridge,
        events=events,
        title="代理调试",
        requested_url="about:blank",
        proxy_url="https://127.0.0.1:8443",
        proxy_scope="global",
        proxy_lookup=failed_lookup,
    )
    window = FakeWindow()
    runtime.attach_window(window, visible=False)

    runtime.start_proxy_lookup()

    status = runtime.proxy_status(timeout=2)
    assert status["state"] == "unavailable"
    assert status["ip"] is None
    assert status["scope"] == "global"
    assert window.title == "[代理模式] 代理调试"
    assert window.url == "https://example.com/"
    proxy_events = events.get(after=0, limit=10, kinds=["proxy"]).events
    assert proxy_events[0]["payload"] == {"event": "unavailable"}
