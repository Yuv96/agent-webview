#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until(predicate, *, timeout: float, message: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise TimeoutError(message)


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行真实浏览器冒烟测试")
    parser.add_argument("--timeout", type=float, default=45)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="agent-webview-smoke-") as name:
        root = Path(name)
        runtime_file = root / "controller.json"
        log_file = root / "controller.log"
        port = free_port()
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        controller_command = [
            sys.executable,
            "-m",
            "agent_webview",
            "--port",
            str(port),
            "--data-dir",
            str(root / "data"),
            "--runtime-dir",
            str(root / "runtime"),
            "--runtime-file",
            str(runtime_file),
        ]
        with log_file.open("w", encoding="utf-8") as log_stream:
            process = subprocess.Popen(
                controller_command,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
            )

        base_url = f"http://127.0.0.1:{port}"
        session_id: str | None = None
        headers: dict[str, str] = {}
        client = httpx.Client(timeout=10)
        try:
            def controller_ready() -> bool:
                if process.poll() is not None:
                    raise RuntimeError("控制器提前退出")
                try:
                    return client.get(f"{base_url}/health").is_success
                except httpx.HTTPError:
                    return False

            wait_until(
                controller_ready,
                timeout=args.timeout,
                message="等待控制器启动超时",
            )
            runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
            headers = {"Authorization": f"Bearer {runtime['token']}"}

            duplicate = subprocess.run(
                controller_command,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=creation_flags,
            )
            if duplicate.returncode != 2:
                raise RuntimeError("并发控制器未被运行信息文件锁拒绝")
            current_runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
            if current_runtime["token"] != runtime["token"]:
                raise RuntimeError("并发控制器覆盖了现有运行信息文件")

            response = client.post(
                f"{base_url}/v1/sessions",
                headers=headers,
                json={"url": "https://example.com/"},
            )
            response.raise_for_status()
            session_id = str(response.json()["session_id"])

            def window_ready() -> dict[str, Any] | None:
                response = client.get(
                    f"{base_url}/v1/sessions/{session_id}",
                    headers=headers,
                )
                response.raise_for_status()
                document = response.json()
                return document if (document.get("window") or {}).get("ready") else None

            wait_until(
                window_ready,
                timeout=args.timeout,
                message="等待浏览器窗口就绪超时",
            )
            response = client.post(
                f"{base_url}/v1/sessions/{session_id}/javascript/evaluate",
                headers=headers,
                json={"code": "document.title", "timeout": 10},
            )
            response.raise_for_status()
            if response.json().get("value") != "Example Domain":
                raise RuntimeError("页面脚本结果不符合预期")

            response = client.delete(
                f"{base_url}/v1/sessions/{session_id}",
                headers=headers,
            )
            response.raise_for_status()
            session_id = None

            if os.name != "nt":
                mode = stat.S_IMODE(runtime_file.stat().st_mode)
                if mode != 0o600:
                    raise RuntimeError(f"运行信息文件权限错误：{mode:o}")

            stop_process(process)
            if runtime_file.exists():
                raise RuntimeError("控制器停止后仍残留运行信息文件")
        except Exception:
            if session_id and headers and process.poll() is None:
                with suppress(httpx.HTTPError):
                    client.delete(
                        f"{base_url}/v1/sessions/{session_id}",
                        headers=headers,
                    )
            stop_process(process)
            print(log_file.read_text(encoding="utf-8")[-8000:], file=sys.stderr)
            raise
        finally:
            client.close()

    print("真实浏览器冒烟测试通过")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
        print(f"真实浏览器冒烟测试失败：{error}", file=sys.stderr)
        raise SystemExit(1) from error
