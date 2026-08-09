from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from typing import Any

import structlog
import uvicorn

from agent_webview.bridge import AgentApi, AgentBridge
from agent_webview.events import EventBuffer
from agent_webview.files import write_private_json
from agent_webview.logging import configure_logging
from agent_webview.models import CookieRecord
from agent_webview.runtime import BrowserRuntime
from agent_webview.worker_api import create_worker_app

log = structlog.get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent Webview 子进程")
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    write_private_json(path, value)


def run_worker(config: dict[str, Any]) -> int:
    import webview

    events = EventBuffer(capacity=int(config.get("event_capacity", 5000)))
    bridge = AgentBridge(events)
    api = AgentApi(bridge)
    runtime = BrowserRuntime(
        session_id=config["session_id"],
        window_id=config["window_id"],
        bridge=bridge,
        events=events,
        initial_cookies=[
            CookieRecord.model_validate(item)
            for item in config.get("cookies", [])
        ],
    )

    app = create_worker_app(runtime, config["token"])
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_config=None,
            log_level="critical",
            access_log=False,
        )
    )
    server_thread = Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
        name="调试接口",
    )
    server_thread.start()
    deadline = monotonic() + 10
    while not server.started and monotonic() < deadline:
        sleep(0.02)
    if not server.started:
        raise RuntimeError("子进程接口启动失败")

    remote_debugging_port = config.get("remote_debugging_port")
    if remote_debugging_port:
        webview.settings["REMOTE_DEBUGGING_PORT"] = remote_debugging_port
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False

    window = webview.create_window(
        config["title"],
        url=config["url"],
        width=config["width"],
        height=config["height"],
        hidden=not config["visible"],
        js_api=api,
        text_select=True,
        zoomable=True,
    )
    runtime.attach_window(window, visible=config["visible"])

    def mark_ready() -> None:
        _write_json(
            Path(config["ready_file"]),
            {
                "session_id": config["session_id"],
                "window_id": config["window_id"],
                "pid": os.getpid(),
                "port": port,
            },
        )
        log.info("子进程已启动", session_id=config["session_id"], pid=os.getpid())

    try:
        webview.start(
            func=mark_ready,
            gui=config.get("gui"),
            debug=False,
            private_mode=True,
            user_agent=config.get("user_agent"),
        )
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        log.info("子进程已退出", session_id=config["session_id"], pid=os.getpid())
    return 0


def main() -> None:
    args = _parse_args()
    config = _load_config(Path(args.config))
    configure_logging(
        config.get("log_level", "INFO"),
        json_logs=bool(config.get("json_logs")),
    )
    raise SystemExit(run_worker(config))


if __name__ == "__main__":
    main()
