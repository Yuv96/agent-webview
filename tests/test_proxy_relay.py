from __future__ import annotations

import base64
import socket
import socketserver
import ssl
import subprocess
from contextlib import contextmanager
from shutil import which
from threading import Event, Thread

import httpx
import pytest

from agent_webview.proxy_relay import ProxyRelay, ProxyTarget, _read_headers


@contextmanager
def upstream_proxy(
    label: str, *, auth: bytes | None = None, tls: ssl.SSLContext | None = None
):
    observed = []

    class Handler(socketserver.BaseRequestHandler):
        def setup(self):
            if tls is not None:
                self.request = tls.wrap_socket(self.request, server_side=True)

        def handle(self):
            self.request.settimeout(3)
            try:
                header, body = _read_headers(self.request)
            except OSError:
                return
            observed.append(header)
            if auth and b"Proxy-Authorization: " + auth not in header:
                self.request.sendall(
                    b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n"
                )
                return
            if header.startswith(b"CONNECT "):
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                while True:
                    try:
                        data = self.request.recv(100)
                        if not data:
                            return
                        self.request.sendall(label.encode() + b":" + data)
                    except OSError:
                        return
            else:
                size = next(
                    (
                        int(line.split(b":", 1)[1])
                        for line in header.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    ),
                    0,
                )
                while len(body) < size:
                    body += self.request.recv(size - len(body))
                output = label.encode() + b":" + body
                self.request.sendall(
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                    + str(len(output)).encode()
                    + b"\r\n\r\n"
                    + output
                )

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield (
            f"{'https' if tls else 'http'}://127.0.0.1:{server.server_address[1]}",
            observed,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def tunnel(relay: ProxyRelay) -> socket.socket:
    port = int(relay.url.rsplit(":", 1)[1])
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
    header, _ = _read_headers(client)
    assert b"200" in header
    return client


def test_switch_routes_http_and_post_body_without_exposing_browser_auth():
    credential = b"Basic " + base64.b64encode(b"user:secret")
    with (
        upstream_proxy("first", auth=credential) as (first, observed),
        upstream_proxy("second") as (second, _),
    ):
        relay = ProxyRelay(ProxyTarget(first, "user", "secret"))
        try:
            with httpx.Client(proxy=relay.url, trust_env=False) as client:
                result = client.post(
                    "http://example.com/",
                    content=b"payload",
                    headers={"Proxy-Authorization": "Basic browser-value"},
                )
                assert result.text == "first:payload"
                assert b"browser-value" not in observed[0]
                assert b"Proxy-Authorization: " + credential in observed[0]
                relay.replace(ProxyTarget(second))
                assert client.get("http://example.com/").text == "second:"
        finally:
            relay.close()


def test_switch_terminates_old_connect_tunnel_and_opens_new_one():
    with upstream_proxy("first") as (first, _), upstream_proxy("second") as (second, _):
        relay = ProxyRelay(ProxyTarget(first))
        try:
            with tunnel(relay) as old:
                old.sendall(b"hello")
                assert old.recv(100) == b"first:hello"
                relay.replace(ProxyTarget(second))
                assert old.recv(100) == b""
            with tunnel(relay) as new:
                new.sendall(b"hello")
                assert new.recv(100) == b"second:hello"
        finally:
            relay.close()


def test_connect_authentication_failure_has_no_direct_fallback():
    with upstream_proxy("private", auth=b"Basic required") as (url, observed):
        relay = ProxyRelay(ProxyTarget(url))
        try:
            with socket.create_connection(
                ("127.0.0.1", int(relay.url.rsplit(":", 1)[1])), timeout=2
            ) as client:
                client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
                assert b"502 Bad Gateway" in client.recv(1000)
            assert len(observed) == 1
        finally:
            relay.close()


def test_connection_finishing_after_switch_cannot_use_old_upstream(monkeypatch):
    connected, release = Event(), Event()
    original = socket.create_connection
    with (
        upstream_proxy("first") as (first, observed),
        upstream_proxy("second") as (second, _),
    ):
        first_port = int(first.rsplit(":", 1)[1])
        relay = ProxyRelay(ProxyTarget(first))

        def delayed(address, *args, **kwargs):
            connection = original(address, *args, **kwargs)
            if address[1] == first_port:
                connected.set()
                assert release.wait(2)
            return connection

        monkeypatch.setattr(socket, "create_connection", delayed)
        try:
            with original(
                ("127.0.0.1", int(relay.url.rsplit(":", 1)[1])), timeout=2
            ) as client:
                client.sendall(b"GET http://example.com/ HTTP/1.1\r\n\r\n")
                assert connected.wait(2)
                relay.replace(ProxyTarget(second))
                release.set()
                assert client.recv(100) == b""
            assert observed == []
        finally:
            release.set()
            relay.close()


def test_close_releases_listener_and_existing_connections():
    with upstream_proxy("first") as (url, _):
        relay = ProxyRelay(ProxyTarget(url))
        client = tunnel(relay)
        relay.close()
        relay.close()
        assert client.recv(100) == b""
        client.close()
        with pytest.raises(OSError):
            socket.create_connection(
                ("127.0.0.1", int(relay.url.rsplit(":", 1)[1])), timeout=1
            )
        with pytest.raises(RuntimeError):
            relay.replace(ProxyTarget(url))


@pytest.mark.skipif(which("openssl") is None, reason="需要 openssl 生成临时测试证书")
def test_https_upstream_with_auth_and_connect(tmp_path, monkeypatch):
    certificate, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    client_context = ssl.create_default_context(cafile=str(certificate))
    monkeypatch.setattr(
        "agent_webview.proxy_relay.ssl.create_default_context", lambda: client_context
    )
    credential = b"Basic " + base64.b64encode(b"user:secret")
    with upstream_proxy("encrypted", auth=credential, tls=server_context) as (url, _):
        relay = ProxyRelay(ProxyTarget(url, "user", "secret"))
        try:
            with tunnel(relay) as client:
                client.sendall(b"hello")
                assert client.recv(100) == b"encrypted:hello"
        finally:
            relay.close()
