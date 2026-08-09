from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from typing import Any
from uuid import uuid4

from agent_webview.errors import (
    BrowserCommandError,
    BrowserCommandTimeoutError,
    BrowserNotReadyError,
)
from agent_webview.events import EventBuffer
from agent_webview.js import command_script


@dataclass
class _PendingResult:
    event: Event
    payload: dict[str, Any] | None = None


class AgentBridge:
    def __init__(self, events: EventBuffer) -> None:
        self.events = events
        self.window: Any = None
        self.ready = Event()
        self._command_lock = Lock()
        self._pending_lock = Lock()
        self._pending: dict[str, _PendingResult] = {}

    def attach_window(self, window: Any) -> None:
        self.window = window

    def execute(self, code: str, *, expression: bool, timeout: float) -> Any:
        if not self.window or not self.ready.wait(min(timeout, 5)):
            raise BrowserNotReadyError("页面尚未就绪")

        request_id = uuid4().hex
        pending = _PendingResult(event=Event())
        with self._pending_lock:
            self._pending[request_id] = pending

        try:
            with self._command_lock:
                try:
                    self.window.run_js(
                        command_script(request_id, code, expression=expression)
                    )
                except Exception as error:
                    raise BrowserCommandError(
                        "脚本发送失败",
                        details={"name": type(error).__name__},
                    ) from error
                if not pending.event.wait(timeout):
                    raise BrowserCommandTimeoutError(
                        f"脚本执行超过 {timeout:g} 秒"
                    )
            payload = pending.payload or {}
            if not payload.get("ok"):
                error_details = payload.get("error") or {}
                raise BrowserCommandError(
                    error_details.get("message", "脚本执行失败"),
                    details=error_details,
                )
            return payload.get("value")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def agent_result(self, request_id: str, payload: dict[str, Any]) -> bool:
        with self._pending_lock:
            pending = self._pending.get(request_id)
            if not pending:
                return False
            pending.payload = payload
            pending.event.set()
            return True

    def agent_event(self, payload: dict[str, Any]) -> bool:
        kind = str(payload.get("kind") or "page")
        self.events.append(kind, payload)
        return True


class AgentApi:
    def __init__(self, bridge: AgentBridge) -> None:
        self._bridge = bridge

    def agent_result(self, request_id: str, payload: dict[str, Any]) -> bool:
        return self._bridge.agent_result(request_id, payload)

    def agent_event(self, payload: dict[str, Any]) -> bool:
        return self._bridge.agent_event(payload)
