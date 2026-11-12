from __future__ import annotations

import ssl
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest

pytest.importorskip("mitmproxy", reason="安装 cache extra 后运行 HTTPS 缓存集成测试")

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agent_webview.cache_proxy import CacheProxy
from agent_webview.models import ResourceCacheOptions


def tls_context(directory: Path) -> tuple[ssl.SSLContext, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .sign(key, hashes.SHA256()))
    cert_file, key_file = directory / "origin.pem", directory / "origin.key"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    return context, cert_file


def test_https_cache_survives_proxy_restart_with_origin_offline(tmp_path):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body = b"window.fromCache = true;"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    context, origin_ca = tls_context(tmp_path)
    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin.socket = context.wrap_socket(origin.socket, server_side=True)
    thread = Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    url = f"https://localhost:{origin.server_port}/app.js?v=1"
    options = ResourceCacheOptions(enabled=True)
    try:
        with closing(CacheProxy(tmp_path / "cache", options, None)) as proxy:
            # 测试源站 CA 只添加到测试代理的上游校验；生产仍用系统/默认可信根。
            configured = Event()

            def trust_fixture():
                proxy._master.options.update(ssl_verify_upstream_trusted_ca=str(origin_ca))
                configured.set()

            proxy._loop.call_soon_threadsafe(trust_fixture)
            assert configured.wait(5)
            trust = ssl.create_default_context(cafile=str(proxy.ca_file))
            with httpx.Client(proxy=proxy.url, verify=trust, trust_env=False) as client:
                result = client.get(url)
                assert result.status_code == 200
                assert result.content == b"window.fromCache = true;"
                assert client.get(url).content == result.content
            assert calls == ["/app.js?v=1"]
    finally:
        origin.shutdown()
        origin.server_close()
        thread.join(timeout=5)
    with closing(CacheProxy(tmp_path / "cache", options, None)) as restarted:
        trust = ssl.create_default_context(cafile=str(restarted.ca_file))
        with httpx.Client(proxy=restarted.url, verify=trust, trust_env=False) as client:
            result = client.get(url)
            assert result.status_code == 200
            assert result.content == b"window.fromCache = true;"
            assert client.get(url.replace("v=1", "v=2")).status_code == 502


def test_proxy_rejects_untrusted_upstream_certificate(tmp_path):
    context, _ = tls_context(tmp_path)
    origin = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    origin.socket = context.wrap_socket(origin.socket, server_side=True)
    Thread(target=origin.serve_forever, daemon=True).start()
    try:
        with closing(CacheProxy(tmp_path / "cache", ResourceCacheOptions(enabled=True), None)) as proxy:
            trust = ssl.create_default_context(cafile=str(proxy.ca_file))
            with httpx.Client(proxy=proxy.url, verify=trust, trust_env=False) as client:
                assert client.get(f"https://localhost:{origin.server_port}/app.js").status_code == 502
    finally:
        origin.shutdown()
        origin.server_close()


def test_cache_worker_does_not_import_tornado(tmp_path):
    import subprocess
    import sys

    source = Path(__file__).resolve().parents[1] / "src"
    program = r'''
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
class RejectTornado(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tornado" or fullname.startswith("tornado."):
            raise RuntimeError("缓存引擎不得加载 Tornado")
sys.meta_path.insert(0, RejectTornado())
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import httpx
from agent_webview.cache_proxy import CacheProxy
from agent_webview.models import ResourceCacheOptions
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"window.ok = true;"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
Thread(target=server.serve_forever, daemon=True).start()
proxy = CacheProxy(Path(sys.argv[2]), ResourceCacheOptions(enabled=True), None)
try:
    assert proxy._master.options.onboarding is False
    with httpx.Client(proxy=proxy.url, trust_env=False) as client:
        assert client.get(f"http://127.0.0.1:{server.server_port}/app.js").status_code == 200
    assert not any(name == "tornado" or name.startswith("tornado.") for name in sys.modules)
finally:
    proxy.close()
    server.shutdown()
    server.server_close()
'''
    subprocess.run([sys.executable, "-I", "-c", program, str(source), str(tmp_path)], check=True, capture_output=True, timeout=30)
