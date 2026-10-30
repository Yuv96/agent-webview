from __future__ import annotations

import base64
import select
import socket
import socketserver
import ssl
from contextlib import suppress
from dataclasses import dataclass, field
from threading import RLock, Thread
from urllib.parse import urlsplit

from agent_webview.proxy import normalize_proxy_url


@dataclass(frozen=True)
class ProxyTarget:
    url: str
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", normalize_proxy_url(self.url))
        if (self.username is None) != (self.password is None):
            raise ValueError("代理用户名和密码必须同时提供")
        if self.username is not None and (
            not self.username or ":" in self.username or not self.password
        ):
            raise ValueError("代理认证信息无效")

    @property
    def authorization(self) -> bytes | None:
        if self.username is None:
            return None
        value = f"{self.username}:{self.password}".encode()
        return b"Basic " + base64.b64encode(value)


def _close_socket(connection: socket.socket) -> None:
    with suppress(OSError):
        connection.shutdown(socket.SHUT_RDWR)
    with suppress(OSError):
        connection.close()


def _read_headers(connection: socket.socket) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(8192)
        if not chunk:
            raise OSError("代理连接已关闭")
        data += chunk
        if len(data.split(b"\r\n\r\n", 1)[0]) > 65536:
            raise ValueError("代理请求头过长")
    header, remainder = data.split(b"\r\n\r\n", 1)
    return header, remainder


class _RelayServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address) -> None:
        # 不把请求内容或认证数据写入默认 traceback。
        pass


class ProxyRelay:
    """窗口使用固定本地端口，上游切换时关闭所有旧连接；从不回退直连。"""

    def __init__(self, target: ProxyTarget) -> None:
        self._lock = RLock()
        self._target = target
        self._revision = 0
        self._closed = False
        self._connections: set[socket.socket] = set()
        relay = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                relay._handle(self.request)

        self._server = _RelayServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="窗口代理转发",
        )
        self._thread.start()

    def replace(self, target: ProxyTarget) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("窗口代理已经关闭")
            if target.url == self.url:
                raise ValueError("上游不能指向窗口代理自身")
            self._target = target
            self._revision += 1
            for connection in self._connections:
                _close_socket(connection)
            self._connections.clear()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for connection in self._connections:
                _close_socket(connection)
            self._connections.clear()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def _track(self, connection: socket.socket, revision: int) -> None:
        with self._lock:
            if self._closed or revision != self._revision:
                _close_socket(connection)
                raise OSError("代理已切换")
            self._connections.add(connection)

    def _handle(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        started = False
        try:
            with self._lock:
                target, revision = self._target, self._revision
                self._track(client, revision)
            client.settimeout(10)
            header, remainder = _read_headers(client)
            lines = header.split(b"\r\n")
            method, destination, version = lines[0].split(b" ")
            if version not in {b"HTTP/1.0", b"HTTP/1.1"}:
                raise ValueError("不支持的代理请求")
            is_tunnel = method == b"CONNECT"
            if not is_tunnel and not destination.startswith(b"http://"):
                raise ValueError("需要 HTTP 代理请求或 CONNECT 隧道")
            headers = []
            for line in lines[1:]:
                name, separator, _ = line.partition(b":")
                if not separator or name[:1] in {b" ", b"\t"}:
                    raise ValueError("代理请求头无效")
                if name.lower() not in {
                    b"proxy-authorization",
                    b"proxy-connection",
                    b"connection",
                }:
                    headers.append(line)
            authorization = target.authorization
            if authorization:
                headers.append(b"Proxy-Authorization: " + authorization)
            if not is_tunnel:
                # 每个明文 HTTP 连接只处理一个请求，避免后续请求遗漏代理认证。
                upgrade = any(line.lower().startswith(b"upgrade:") for line in headers)
                headers.append(
                    b"Connection: Upgrade" if upgrade else b"Connection: close"
                )
            parsed = urlsplit(target.url)
            upstream = socket.create_connection(
                (parsed.hostname or "", parsed.port or 80), timeout=10
            )
            self._track(upstream, revision)
            if parsed.scheme == "https":
                raw = upstream
                wrapped = ssl.create_default_context().wrap_socket(
                    raw,
                    server_hostname=parsed.hostname,
                    do_handshake_on_connect=False,
                )
                with self._lock:
                    self._connections.discard(raw)
                    upstream = wrapped
                    self._track(upstream, revision)
                upstream.do_handshake()
            # DNS/TLS 建连期间可能已发生切换，发送前再次检查代次。
            self._track(upstream, revision)
            upstream.sendall(b"\r\n".join([lines[0], *headers]) + b"\r\n\r\n")
            if is_tunnel:
                response, extra = _read_headers(upstream)
                if response.split(b"\r\n", 1)[0].split(b" ")[1:2] != [b"200"]:
                    raise OSError("上游代理拒绝隧道")
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n" + extra)
            started = True
            if remainder:
                upstream.sendall(remainder)
            self._pipe(client, upstream)
        except (OSError, ValueError, RuntimeError):
            if not started:
                with suppress(OSError):
                    client.sendall(
                        b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                    )
        finally:
            with self._lock:
                for connection in (client, upstream):
                    if connection is not None:
                        self._connections.discard(connection)
                        _close_socket(connection)

    @staticmethod
    def _pipe(client: socket.socket, upstream: socket.socket) -> None:
        connections = (client, upstream)
        while True:
            pending = [
                connection
                for connection in connections
                if isinstance(connection, ssl.SSLSocket) and connection.pending()
            ]
            readable = pending or select.select(connections, [], [], 60)[0]
            if not readable:
                continue
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                destination = upstream if source is client else client
                destination.sendall(data)
