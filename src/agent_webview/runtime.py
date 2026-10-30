from __future__ import annotations

import os
from collections.abc import Callable
from threading import Event, Lock, RLock, Thread
from typing import Any, Literal

import structlog

from agent_webview.bridge import AgentBridge
from agent_webview.cookies import normalize_pywebview_cookies
from agent_webview.errors import BrowserNotReadyError
from agent_webview.events import EventBuffer
from agent_webview.js import (
    cookie_restore_expression,
    dom_click_expression,
    dom_dispatch_expression,
    dom_input_expression,
    dom_listener_script,
    dom_query_expression,
    instrumentation_script,
    remove_dom_listener_script,
)
from agent_webview.models import (
    CookieRecord,
    DomClickRequest,
    DomDispatchRequest,
    DomInputRequest,
    DomListenerRequest,
    DomQueryRequest,
    InstrumentationRequest,
    ProxyUpdateRequest,
)
from agent_webview.proxy import (
    ProxyIdentity,
    format_proxy_title,
    lookup_proxy_identity,
)
from agent_webview.proxy_relay import ProxyRelay, ProxyTarget

log = structlog.get_logger(__name__)


class BrowserRuntime:
    def __init__(
        self,
        *,
        session_id: str,
        window_id: str,
        bridge: AgentBridge,
        events: EventBuffer,
        initial_cookies: list[CookieRecord] | None = None,
        title: str = "Agent Webview",
        requested_url: str = "about:blank",
        proxy_url: str | None = None,
        proxy_scope: Literal["global", "window"] | None = None,
        proxy_lookup: Callable[[str], ProxyIdentity] = lookup_proxy_identity,
        proxy_relay: ProxyRelay | None = None,
        proxy_authenticated: bool = False,
    ) -> None:
        self.session_id = session_id
        self.window_id = window_id
        self.bridge = bridge
        self.events = events
        self.window: Any = None
        self.visible = False
        self.closed = False
        self.operational_ready = Event()
        self.instrumentation = InstrumentationRequest()
        self.dom_listeners: dict[str, DomListenerRequest] = {}
        self._initial_cookies = list(initial_cookies or [])
        self._initial_cookies_attempted = not bool(self._initial_cookies)
        self._setup_lock = Lock()
        self._base_title = title
        self._requested_url = requested_url
        self._proxy_url = proxy_url
        self._proxy_lookup = proxy_lookup
        self._proxy_relay = proxy_relay
        self._proxy_lock = RLock()
        self._proxy_lookup_started = False
        self._proxy_lookup_finished = Event()
        if proxy_url is None:
            self._proxy_lookup_finished.set()
        self._proxy_status: dict[str, Any] = {
            "enabled": proxy_url is not None,
            "scope": proxy_scope,
            "server": proxy_url,
            "state": "checking" if proxy_url else "disabled",
            "ip": None,
            "location": None,
            "revision": 0,
            "mutable": proxy_relay is not None and proxy_scope == "window",
            "authenticated": proxy_authenticated,
        }

    @property
    def startup_url(self) -> str:
        return self._requested_url

    @property
    def initial_title(self) -> str:
        return format_proxy_title(
            self._base_title,
            state=str(self._proxy_status["state"]),
        )

    def attach_window(self, window: Any, *, visible: bool) -> None:
        self.window = window
        self.visible = visible
        self.bridge.attach_window(window)
        window.events.before_load += self._on_before_load
        window.events.loaded += self._on_loaded
        window.events.shown += self._on_shown
        window.events.closed += self._on_closed

    def _on_before_load(self, *_: Any) -> None:
        self.bridge.ready.clear()
        self.operational_ready.clear()
        self.events.append("lifecycle", {"event": "before_load"})

    def _on_loaded(self, *_: Any) -> None:
        self.bridge.ready.set()
        self.events.append(
            "lifecycle",
            {"event": "loaded", "url": self._safe_current_url()},
        )
        Thread(target=self._post_load_setup, daemon=True).start()

    def _on_shown(self, *_: Any) -> None:
        self.visible = True
        self.events.append("lifecycle", {"event": "shown"})

    def _on_closed(self, *_: Any) -> None:
        with self._proxy_lock:
            self.closed = True
            self._proxy_lookup_finished.set()
        if self._proxy_relay is not None:
            self._proxy_relay.close()
        self.bridge.ready.clear()
        self.events.append("lifecycle", {"event": "closed"})

    def start_proxy_lookup(self) -> None:
        with self._proxy_lock:
            if not self._proxy_url or self._proxy_lookup_started:
                return
            self._proxy_lookup_started = True
            revision = self._proxy_status["revision"]
            proxy_url = self._proxy_relay.url if self._proxy_relay else self._proxy_url
            finished = self._proxy_lookup_finished
        Thread(
            target=self._complete_proxy_lookup,
            args=(revision, proxy_url, finished),
            daemon=True,
        ).start()

    def _complete_proxy_lookup(self, revision: int, proxy_url: str, finished: Event) -> None:
        try:
            identity = self._proxy_lookup(proxy_url)
        except Exception as error:
            log.debug(
                "代理出口 IP 查询未完成",
                session_id=self.session_id,
                error_type=type(error).__name__,
            )
            identity = None
        with self._proxy_lock:
            if self.closed or revision != self._proxy_status["revision"]:
                finished.set()
                return
            if identity is None:
                self._set_proxy_unavailable()
            else:
                self._set_proxy_active(identity.ip, identity.location)

    def update_proxy(self, request: ProxyUpdateRequest) -> dict[str, Any]:
        target = ProxyTarget(request.proxy, request.proxy_username, request.proxy_password)
        with self._proxy_lock:
            if self.closed:
                raise BrowserNotReadyError("窗口已经关闭")
            if not self._proxy_status["mutable"] or self._proxy_relay is None:
                raise BrowserNotReadyError("仅创建时配置单窗口代理的会话支持切换；全局代理不可修改")
            revision = self._proxy_status["revision"]
            if request.expected_revision is not None and request.expected_revision != revision:
                raise BrowserNotReadyError("代理版本已变化，请读取当前状态后重试")
            try:
                self._proxy_relay.replace(target)
            except (ValueError, RuntimeError) as error:
                raise BrowserNotReadyError(str(error)) from error
            self._proxy_url = target.url
            self._proxy_lookup_finished.set()
            self._proxy_lookup_finished = Event()
            self._proxy_lookup_started = False
            self._proxy_status.update(
                server=target.url,
                state="checking",
                ip=None,
                location=None,
                revision=revision + 1,
                authenticated=target.username is not None,
            )
            self._update_proxy_title()
            self.events.append("proxy", {"event": "changed", "revision": revision + 1, "server": target.url})
            # 返回已应用代次的快照；出口检查异步完成，不阻塞窗口使用。
            result = dict(self._proxy_status)
            self.start_proxy_lookup()
            return result

    def _set_proxy_active(self, ip: str, location: str) -> None:
        with self._proxy_lock:
            self._proxy_status.update(
                state="active",
                ip=ip,
                location=location,
            )
        self._update_proxy_title()
        self.events.append(
            "proxy",
            {"event": "active", "ip": ip, "location": location},
        )
        self._proxy_lookup_finished.set()

    def _set_proxy_unavailable(self) -> None:
        with self._proxy_lock:
            self._proxy_status.update(
                state="unavailable",
                ip=None,
                location=None,
            )
        self._update_proxy_title()
        self.events.append("proxy", {"event": "unavailable"})
        self._proxy_lookup_finished.set()

    def _update_proxy_title(self) -> None:
        with self._proxy_lock:
            status = dict(self._proxy_status)
        title = format_proxy_title(
            self._base_title,
            state=str(status["state"]),
            ip=status["ip"],
            location=status["location"],
        )
        try:
            self.window.set_title(title)
        except Exception:
            log.debug("代理状态标题更新失败", session_id=self.session_id)

    def _post_load_setup(self) -> None:
        if not self._setup_lock.acquire(blocking=False):
            return
        reload_started = False
        try:
            if not self._initial_cookies_attempted:
                self._initial_cookies_attempted = True
                result = self.bridge.execute(
                    cookie_restore_expression(
                        [cookie.model_dump() for cookie in self._initial_cookies]
                    ),
                    expression=True,
                    timeout=30,
                )
                self.events.append("cookies", {"event": "initial_restore", **result})
                self.window.run_js("location.reload();")
                reload_started = True
                return
            self._inject_instrumentation()
            for listener in list(self.dom_listeners.values()):
                self.window.run_js(dom_listener_script(listener.model_dump()))
        except Exception:
            log.exception("页面初始化失败", session_id=self.session_id)
        finally:
            if not reload_started:
                self.operational_ready.set()
                self.events.append(
                    "lifecycle",
                    {"event": "ready", "url": self._safe_current_url()},
                )
            self._setup_lock.release()

    def status(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "window_id": self.window_id,
            "native_window_id": self._native_window_id(),
            "pid": os.getpid(),
            "ready": self.operational_ready.is_set(),
            "closed": self.closed,
            "visible": self.visible,
            "url": self._safe_current_url(),
            "title": self._safe_property("title"),
            "proxy": self.proxy_status(),
            "bounds": {
                "x": self._safe_property("x"),
                "y": self._safe_property("y"),
                "width": self._safe_property("width"),
                "height": self._safe_property("height"),
            },
            "latest_event_sequence": self.events.latest_sequence,
        }

    def proxy_status(self, timeout: float = 0) -> dict[str, Any]:
        if timeout > 0:
            self._proxy_lookup_finished.wait(timeout)
        with self._proxy_lock:
            return dict(self._proxy_status)

    def show(self) -> dict[str, Any]:
        self.window.show()
        self.visible = True
        return self.status()

    def hide(self) -> dict[str, Any]:
        self.window.hide()
        self.visible = False
        return self.status()

    def navigate(self, url: str) -> dict[str, Any]:
        self.bridge.ready.clear()
        self.operational_ready.clear()
        self.window.load_url(url)
        return {"accepted": True, "url": url}

    def evaluate(self, code: str, timeout: float) -> Any:
        self._require_ready()
        return self.bridge.execute(code, expression=True, timeout=timeout)

    def execute(self, code: str, timeout: float) -> Any:
        self._require_ready()
        return self.bridge.execute(code, expression=False, timeout=timeout)

    def dom_query(self, request: DomQueryRequest) -> Any:
        return self.evaluate(
            dom_query_expression(request.selector, request.limit),
            timeout=30,
        )

    def dom_click(self, request: DomClickRequest) -> Any:
        return self.evaluate(
            dom_click_expression(request.selector, request.index, request.scroll),
            timeout=request.timeout,
        )

    def dom_input(self, request: DomInputRequest) -> Any:
        return self.evaluate(
            dom_input_expression(request.selector, request.value, request.index),
            timeout=request.timeout,
        )

    def dom_dispatch(self, request: DomDispatchRequest) -> Any:
        return self.evaluate(
            dom_dispatch_expression(
                request.selector,
                request.event,
                request.index,
                request.detail,
            ),
            timeout=request.timeout,
        )

    def add_dom_listener(self, request: DomListenerRequest) -> dict[str, Any]:
        self.dom_listeners[request.id] = request
        if self.bridge.ready.is_set():
            self.window.run_js(dom_listener_script(request.model_dump()))
        return {"installed": request.model_dump()}

    def remove_dom_listener(self, listener_id: str) -> dict[str, Any]:
        removed = self.dom_listeners.pop(listener_id, None)
        if removed and self.bridge.ready.is_set():
            self.window.run_js(remove_dom_listener_script(listener_id))
        return {"removed": bool(removed), "id": listener_id}

    def set_instrumentation(
        self,
        request: InstrumentationRequest,
    ) -> dict[str, Any]:
        self.instrumentation = request
        if self.bridge.ready.is_set():
            self._inject_instrumentation()
        return request.model_dump()

    def get_cookies(self) -> list[dict[str, Any]]:
        self._require_ready()
        cookies = normalize_pywebview_cookies(self.window.get_cookies())
        return [cookie.model_dump() for cookie in cookies]

    def clear_cookies(self) -> dict[str, Any]:
        self._require_ready()
        self.window.clear_cookies()
        return {"cleared": True}

    def restore_cookies(
        self,
        cookies: list[CookieRecord],
        *,
        reload: bool,
        timeout: float,
    ) -> dict[str, Any]:
        self._require_ready()
        result = self.bridge.execute(
            cookie_restore_expression([cookie.model_dump() for cookie in cookies]),
            expression=True,
            timeout=timeout,
        )
        if reload:
            self.operational_ready.clear()
            try:
                self.window.run_js("location.reload();")
            except Exception:
                self.operational_ready.set()
                raise
        return result

    def destroy(self) -> None:
        if not self.closed:
            self.window.destroy()

    def _inject_instrumentation(self) -> None:
        self.window.run_js(instrumentation_script(self.instrumentation.model_dump()))

    def _safe_current_url(self) -> str | None:
        if not self.window:
            return None
        try:
            return self.window.get_current_url()
        except Exception:
            return None

    def _safe_property(self, name: str) -> Any:
        if not self.window:
            return None
        try:
            return getattr(self.window, name)
        except Exception:
            return None

    def _native_window_id(self) -> int | str | None:
        if not self.window:
            return None
        try:
            native = self.window.native
            handle = getattr(native, "Handle", None)
            if handle is not None:
                converter = getattr(handle, "ToInt64", None)
                return int(converter()) if converter else int(handle)
            win_id = getattr(native, "winId", None)
            if callable(win_id):
                return int(win_id())
            return None
        except Exception:
            return None

    def _require_ready(self) -> None:
        if not self.operational_ready.is_set():
            raise BrowserNotReadyError("页面正在加载")
