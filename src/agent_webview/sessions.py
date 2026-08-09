from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

import httpx
import psutil
import structlog

from agent_webview.cookies import SnapshotStore
from agent_webview.files import ensure_private_directory, write_private_json
from agent_webview.models import CookieRecord, SessionCreateRequest

log = structlog.get_logger(__name__)
CookieItems = list[dict[str, Any]]


@dataclass
class Session:
    session_id: str
    window_id: str
    token: str
    process: subprocess.Popen
    pid: int
    port: int
    created_at: str
    config_file: Path
    ready_file: Path
    requested_url: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class SessionManager:
    def __init__(
        self,
        *,
        runtime_dir: Path,
        snapshot_store: SnapshotStore,
        log_level: str = "INFO",
        json_logs: bool = False,
    ) -> None:
        self.runtime_dir = ensure_private_directory(runtime_dir)
        self.snapshot_store = snapshot_store
        self.log_level = log_level
        self.json_logs = json_logs
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()
        self._client = httpx.Client(timeout=35)
        self._closed = False

    def create(self, request: SessionCreateRequest) -> dict[str, Any]:
        snapshot = (
            self.snapshot_store.get(request.snapshot_id)
            if request.snapshot_id
            else None
        )
        url = request.url or (snapshot or {}).get("url") or "about:blank"
        cookies = self._merge_cookies(
            (snapshot or {}).get("cookies", []),
            [cookie.model_dump() for cookie in request.cookies],
        )
        session_id = uuid4().hex
        window_id = uuid4().hex
        token = secrets.token_urlsafe(32)
        session_dir = self.runtime_dir / session_id
        ensure_private_directory(session_dir)
        config_file = session_dir / "worker.json"
        ready_file = session_dir / "ready.json"
        config = {
            **request.model_dump(exclude={"snapshot_id", "cookies"}),
            "url": url,
            "cookies": cookies,
            "session_id": session_id,
            "window_id": window_id,
            "token": token,
            "ready_file": str(ready_file),
            "event_capacity": 5000,
            "log_level": self.log_level,
            "json_logs": self.json_logs,
        }
        write_private_json(config_file, config)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agent_webview.worker",
                "--config",
                str(config_file),
            ],
            cwd=str(Path.cwd()),
        )
        try:
            ready = self._wait_ready(process, ready_file)
        except Exception:
            self._terminate_process_tree(process.pid)
            shutil.rmtree(session_dir, ignore_errors=True)
            raise

        session = Session(
            session_id=session_id,
            window_id=window_id,
            token=token,
            process=process,
            pid=int(ready["pid"]),
            port=int(ready["port"]),
            created_at=datetime.now(timezone.utc).isoformat(),
            config_file=config_file,
            ready_file=ready_file,
            requested_url=url,
        )
        with self._lock:
            self._sessions[session_id] = session
        log.info("会话已创建", session_id=session_id, pid=session.pid)
        return self.describe(session)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [self.describe(session) for session in sessions]

    def get(self, session_id: str) -> Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return session

    def describe(self, session: Session) -> dict[str, Any]:
        exit_code = session.process.poll()
        result: dict[str, Any] = {
            "session_id": session.session_id,
            "window_id": session.window_id,
            "pid": session.pid,
            "launcher_pid": (
                session.process.pid if session.process.pid != session.pid else None
            ),
            "created_at": session.created_at,
            "requested_url": session.requested_url,
            "state": "running" if exit_code is None else "exited",
            "exit_code": exit_code,
        }
        try:
            process = psutil.Process(session.pid)
            with process.oneshot():
                result["process"] = {
                    "pid": process.pid,
                    "status": process.status(),
                    "create_time": process.create_time(),
                    "num_threads": process.num_threads(),
                    "memory_rss": process.memory_info().rss,
                }
        except (psutil.Error, OSError):
            result["process"] = None
        if exit_code is None:
            try:
                result["window"] = self.request(session, "GET", "/v1/status")
            except httpx.HTTPError:
                result["window"] = None
        else:
            result["window"] = None
        return result

    def request(
        self,
        session: Session,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        if session.process.poll() is not None:
            raise ProcessLookupError("会话进程已退出")
        response = self._client.request(
            method,
            f"{session.base_url}{path}",
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {session.token}"},
            timeout=timeout,
        )
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = {"detail": response.text}
            raise WorkerResponseError(response.status_code, detail)
        if not response.content:
            return None
        return response.json()

    def destroy(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        if session.process.poll() is None:
            with suppress(
                httpx.HTTPError,
                WorkerResponseError,
                ProcessLookupError,
            ):
                self.request(session, "POST", "/v1/destroy", timeout=3)
            try:
                session.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_process_tree(session.process.pid)
        with self._lock:
            self._sessions.pop(session_id, None)
        shutil.rmtree(session.config_file.parent, ignore_errors=True)
        log.info("会话已销毁", session_id=session_id, pid=session.pid)
        return {
            "session_id": session_id,
            "pid": session.pid,
            "exit_code": session.process.returncode,
        }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            session_ids = list(self._sessions)
        for session_id in session_ids:
            try:
                self.destroy(session_id)
            except Exception:
                log.exception("会话清理失败", session_id=session_id)
        self._client.close()

    @staticmethod
    def _wait_ready(
        process: subprocess.Popen,
        ready_file: Path,
        timeout: float = 30,
    ) -> dict[str, Any]:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"子进程提前退出，代码 {process.returncode}")
            if ready_file.is_file():
                try:
                    return json.loads(ready_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            sleep(0.05)
        raise TimeoutError("等待子进程启动超时")

    @staticmethod
    def _terminate_process_tree(pid: int) -> None:
        try:
            parent = psutil.Process(pid)
            processes = [*parent.children(recursive=True), parent]
        except psutil.Error:
            return
        for process in processes:
            with suppress(psutil.Error):
                process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=5)
        for process in alive:
            with suppress(psutil.Error):
                process.kill()

    @staticmethod
    def _merge_cookies(
        base: CookieItems,
        overrides: CookieItems,
    ) -> CookieItems:
        merged: dict[tuple[str, str | None, str], dict[str, Any]] = {}
        for item in [*base, *overrides]:
            cookie = CookieRecord.model_validate(item).model_dump()
            key = (cookie["name"], cookie["domain"], cookie["path"])
            merged[key] = cookie
        return list(merged.values())


class WorkerResponseError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"子进程返回 {status_code}")
        self.status_code = status_code
        self.detail = detail
