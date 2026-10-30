#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import socketserver
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

import httpx
from smoke_service import free_port, stop_process, wait_until

from agent_webview.proxy_relay import _read_headers


@contextmanager
def test_proxy(label: str):
    expected = b"Basic " + base64.b64encode(f"test:{label}".encode())
    requests = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            try:
                header, _ = _read_headers(self.request)
                if b"Proxy-Authorization: " + expected not in header:
                    self.request.sendall(
                        b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n"
                    )
                    return
                method, destination, _ = header.split(b"\r\n")[0].split(b" ")
                if method == b"CONNECT":
                    if destination != b"proxy-switch.invalid:80":
                        self.request.sendall(
                            b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
                        )
                        return
                    self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    header, _ = _read_headers(self.request)
                requests.append(header)
                path = header.split(b"\r\n")[0].split(b" ")[1]
                if b"/identity" in path:
                    body = label.encode()
                    mime = b"text/plain"
                else:
                    body = b'<html><head><title>Proxy test</title></head><body><input id="draft"><div id="marker">original</div></body></html>'
                    mime = b"text/html"
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Type: "
                    + mime
                    + b"\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
            except (OSError, ValueError):
                return

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def main():
    with (
        tempfile.TemporaryDirectory(prefix="webview-proxy-smoke-") as name,
        test_proxy("first") as (first, first_requests),
        test_proxy("second") as (second, second_requests),
    ):
        root = Path(name)
        runtime_file = root / "controller.json"
        log_file = root / "controller.log"
        port = free_port()
        with log_file.open("w") as output:
            process = subprocess.Popen(
                [
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
                ],
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
            )
        try:
            wait_until(runtime_file.exists, timeout=20, message="控制器启动超时")
            token = json.loads(runtime_file.read_text())["token"]
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=55,
                trust_env=False,
            ) as client:
                response = client.post(
                    "/v1/sessions",
                    json={
                        "url": "http://proxy-switch.invalid/",
                        "visible": False,
                        "proxy": first,
                        "proxy_username": "test",
                        "proxy_password": "first",  # pragma: allowlist secret
                    },
                )
                response.raise_for_status()
                initial = response.json()
                path = f"/v1/sessions/{initial['session_id']}"

                def ready():
                    result = client.get(path)
                    result.raise_for_status()
                    window = result.json().get("window") or {}
                    return window.get("ready")

                wait_until(ready, timeout=40, message="窗口页面加载超时")

                def evaluate(code):
                    result = client.post(
                        path + "/javascript/evaluate",
                        json={"code": code, "timeout": 10},
                    )
                    result.raise_for_status()
                    return result.json()["value"]

                assert (
                    evaluate("fetch('/identity', {cache:'no-store'}).then(r=>r.text())")
                    == "first"
                )
                evaluate(
                    "(() => { document.cookie='smoke=preserved; path=/'; window.marker=42; document.querySelector('#draft').value='unfinished'; return true; })()"
                )
                before = client.get(path).json()
                changed = client.put(
                    path + "/proxy",
                    json={
                        "proxy": second,
                        "proxy_username": "test",
                        "proxy_password": "second",  # pragma: allowlist secret
                        "expected_revision": 0,
                    },
                )
                changed.raise_for_status()
                assert changed.json()["revision"] == 1
                assert changed.json()["mutable"] is True
                assert (
                    evaluate("fetch('/identity', {cache:'no-store'}).then(r=>r.text())")
                    == "second"
                )
                assert evaluate(
                    "({cookie:document.cookie, marker:window.marker, draft:document.querySelector('#draft').value})"
                ) == {
                    "cookie": "smoke=preserved",
                    "marker": 42,
                    "draft": "unfinished",
                }
                after = client.get(path).json()
                assert before["pid"] == after["pid"]
                assert before["window_id"] == after["window_id"]
                assert (
                    before["window"]["native_window_id"]
                    == after["window"]["native_window_id"]
                )
                assert first_requests and second_requests
                response = client.delete(path)
                response.raise_for_status()
        except Exception:
            print(log_file.read_text()[-4000:], file=sys.stderr)
            raise
        finally:
            stop_process(process)
    print(
        "真实窗口代理切换通过：账密验证、出口路径切换、Cookie、JS 状态和未提交输入均保留"
    )


if __name__ == "__main__":
    main()
