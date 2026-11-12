#!/usr/bin/env python3
"""用本机 HTTP 页面验证快照恢复时序和跨 worker 资源缓存。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import httpx
from smoke_service import free_port, stop_process, wait_until


def main() -> None:
    counts: Counter[str] = Counter()

    class Handler(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            if self.path != "cache.example.test:80":
                self.send_error(502)
                return
            self.send_response(200, "Connection Established")
            self.end_headers()
            self.close_connection = False
            while not self.close_connection:
                self.handle_one_request()

        def do_GET(self):
            self.path = urlsplit(self.path).path + ("?" + urlsplit(self.path).query if urlsplit(self.path).query else "")
            counts[self.path] += 1
            if self.path.startswith("/app.js"):
                content, kind = b"window.resourceLoaded = true;", "application/javascript"
            elif self.path == "/style.css":
                content, kind = b"body { color: rgb(1, 2, 3); }", "text/css"
            elif self.path == "/image.svg":
                content, kind = b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml"
            else:
                content, kind = (b'<html><head><script>window.firstToken = localStorage.getItem("token");'
                                 b'</script><script src="/app.js?v=1"></script><link rel="stylesheet" href="/style.css">'
                                 b'</head><body><img src="/image.svg"></body></html>'), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=origin.serve_forever, daemon=True).start()
    target = "http://cache.example.test/"
    upstream = f"http://127.0.0.1:{origin.server_port}"
    with tempfile.TemporaryDirectory(prefix="agent-storage-cache-smoke-") as name:
        root = Path(name)
        port = free_port()
        runtime = root / "controller.json"
        log = root / "controller.log"
        with log.open("w") as output:
            process = subprocess.Popen([sys.executable, "-m", "agent_webview", "--port", str(port),
                                        "--data-dir", str(root / "data"), "--runtime-dir", str(root / "runtime"),
                                        "--runtime-file", str(runtime)], stdout=output, stderr=subprocess.STDOUT)
        try:
            wait_until(runtime.exists, timeout=30, message="控制器未启动")
            token = json.loads(runtime.read_text())["token"]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}/v1", headers={"Authorization": f"Bearer {token}"}, timeout=40) as client:
                def api(method, path, **kwargs):
                    response = client.request(method, path, **kwargs)
                    response.raise_for_status()
                    return response.json()

                def create(**kwargs):
                    session = api("POST", "/sessions", json={"url": target, "proxy": upstream, **kwargs})["session_id"]
                    wait_until(lambda: api("GET", f"/sessions/{session}")["window"]["ready"], timeout=40, message="窗口未就绪")
                    return session

                def evaluate(session, code):
                    return api("POST", f"/sessions/{session}/javascript/evaluate", json={"code": "(() => { return (" + code + "); })()"})["value"]

                cache = {"enabled": True}
                first = create(resource_cache=cache)
                assert evaluate(first, "window.resourceLoaded") is True
                evaluate(first, 'localStorage.setItem("token", "中文凭证\\n😀"), localStorage.setItem("__proto__", "value"), true')
                evaluate(first, '(() => { for (let i = 0; i < 550; i++) localStorage.setItem("key" + i, "value" + i); return true; })()')
                snapshot = api("POST", f"/sessions/{first}/cookie-snapshots", json={"name": "smoke"})
                assert snapshot["local_storage"][target.rstrip("/")]["token"] == "中文凭证\n😀"
                assert snapshot["local_storage"][target.rstrip("/")]["__proto__"] == "value"
                assert len(snapshot["local_storage"][target.rstrip("/")]) == 552
                api("DELETE", f"/sessions/{first}")
                for private in (True, False):
                    second = create(resource_cache=cache, private_mode=private, snapshot_id=snapshot["snapshot_id"])
                    assert evaluate(second, "window.firstToken") == "中文凭证\n😀"
                    assert evaluate(second, 'localStorage.getItem("__proto__")') == "value"
                    assert evaluate(second, "window.resourceLoaded") is True
                    evaluate(second, 'localStorage.setItem("token", "changed"), true')
                    api("POST", f"/sessions/{second}/navigate", json={"url": target})
                    wait_until(lambda second=second: api("GET", f"/sessions/{second}")["window"]["ready"], timeout=30, message="再次导航未完成")
                    assert evaluate(second, "window.firstToken") == "changed"
                    api("DELETE", f"/sessions/{second}")
                assert counts["/app.js?v=1"] == 1, counts
                assert counts["/style.css"] == 1, counts
                assert counts["/"] >= 3, counts
                assert counts["/image.svg"] >= 3, counts
                plain = create()
                api("DELETE", f"/sessions/{plain}")
                assert counts["/app.js?v=1"] == 2, counts
                # HTTPS 代理证书仅在当前原生窗口受信任。
                secure = create(url="https://example.com/", proxy=None, resource_cache=cache)
                assert evaluate(secure, "document.title") == "Example Domain"
                api("DELETE", f"/sessions/{secure}")
        except Exception:
            print(log.read_text()[-12000:], file=sys.stderr)
            raise
        finally:
            stop_process(process)
            origin.shutdown()
            origin.server_close()
    print("localStorage 首次脚本恢复、跨进程缓存、普通/无痕模式、HTTPS 验证通过")


if __name__ == "__main__":
    main()
