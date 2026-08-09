from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
import signal
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import structlog
import uvicorn
from filelock import FileLock, Timeout
from platformdirs import PlatformDirs

from agent_webview.controller_api import create_controller_app
from agent_webview.cookies import SnapshotStore
from agent_webview.files import (
    ensure_private_parent,
    restrict_file_permissions,
    write_private_json,
)
from agent_webview.logging import configure_logging
from agent_webview.sessions import SessionManager

log = structlog.get_logger(__name__)


class RuntimeFileInUseError(RuntimeError):
    """运行信息文件已被其他控制器占用。"""


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("端口必须是整数") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return port


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _base_url(host: str, port: int) -> str:
    normalized = host.strip().strip("[]")
    try:
        address = ipaddress.ip_address(normalized)
        formatted = f"[{normalized}]" if address.version == 6 else normalized
    except ValueError:
        formatted = normalized
    return f"http://{formatted}:{port}"


@contextmanager
def _claim_runtime_file(path: Path) -> Iterator[None]:
    ensure_private_parent(path.parent)
    lock = FileLock(f"{path}.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout as error:
        raise RuntimeFileInUseError("运行信息文件已被其他服务占用") from error
    restrict_file_permissions(Path(lock.lock_file))
    try:
        yield
    finally:
        lock.release()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    directories = PlatformDirs("agent-webview", appauthor=False)
    runtime_path = directories.user_runtime_path
    parser = argparse.ArgumentParser(description="Agent Webview 调试服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8765)
    parser.add_argument("--token", default=os.getenv("AGENT_WEBVIEW_TOKEN"))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=directories.user_data_path,
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=runtime_path / "sessions",
    )
    parser.add_argument(
        "--runtime-file",
        type=Path,
        default=runtime_path / "controller.json",
    )
    parser.add_argument(
        "--print-runtime-file",
        action="store_true",
        help="输出运行信息文件路径后退出",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="允许监听非本机地址",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--json-logs", action="store_true")
    args = parser.parse_args(argv)
    if not _is_loopback_host(args.host) and not args.allow_remote:
        parser.error("监听非本机地址时必须显式指定 --allow-remote")
    return args


def _write_runtime_file(
    path: Path,
    *,
    host: str,
    port: int,
    token: str,
) -> None:
    write_private_json(
        path,
        {
            "pid": os.getpid(),
            "base_url": _base_url(host, port),
            "token": token,
            "docs_url": f"{_base_url(host, port)}/docs",
        },
    )


def _serve(args: argparse.Namespace, token: str, runtime_file: Path) -> None:
    data_dir = args.data_dir.resolve()
    manager = SessionManager(
        runtime_dir=args.runtime_dir.resolve(),
        snapshot_store=SnapshotStore(data_dir / "cookie-snapshots"),
        log_level=args.log_level,
        json_logs=args.json_logs,
    )
    original_handlers: dict[int, Any] = {}
    try:
        app = create_controller_app(manager, token)
        _write_runtime_file(
            runtime_file,
            host=args.host,
            port=args.port,
            token=token,
        )
        log.info(
            "服务已启动",
            url=_base_url(args.host, args.port),
            runtime_file=str(runtime_file),
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                log_config=None,
                log_level="critical",
                access_log=False,
            )
        )

        def defer_exit(signum: int, _: Any) -> None:
            # 让 Uvicorn 返回后再清理敏感运行文件。
            server.should_exit = True

        handled_signals: list[int] = [int(signal.SIGINT), int(signal.SIGTERM)]
        if hasattr(signal, "SIGBREAK"):
            handled_signals.append(int(signal.SIGBREAK))
        for handled_signal in handled_signals:
            original_handlers[handled_signal] = signal.signal(
                handled_signal,
                defer_exit,
            )
        server.run()
    finally:
        try:
            manager.close()
        finally:
            runtime_file.unlink(missing_ok=True)
            for handled_signal, handler in original_handlers.items():
                signal.signal(handled_signal, handler)
            log.info("服务已停止")


def main() -> None:
    args = _parse_args()
    if args.print_runtime_file:
        print(args.runtime_file.resolve())
        return
    configure_logging(args.log_level, json_logs=args.json_logs)
    token = args.token or secrets.token_urlsafe(32)
    runtime_file = args.runtime_file.resolve()
    try:
        with _claim_runtime_file(runtime_file):
            _serve(args, token, runtime_file)
    except RuntimeFileInUseError:
        log.error("运行信息文件已被其他服务占用", runtime_file=str(runtime_file))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
