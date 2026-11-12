from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agent_webview.files import ensure_private_directory, restrict_file_permissions
from agent_webview.models import ResourceCacheOptions

# 不重放连接状态或认证副作用；原始压缩实体和 Content-Encoding 一起保存。
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailer", "transfer-encoding", "upgrade"}


class ResourceCache:
    """跨进程事务缓存；文件只存哈希键，不保存请求凭证。"""

    def __init__(self, directory: Path, options: ResourceCacheOptions) -> None:
        self.options = options
        self.path = ensure_private_directory(directory) / "resources.sqlite3"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS resources (
                key TEXT PRIMARY KEY, base_key TEXT NOT NULL, vary TEXT NOT NULL,
                created REAL NOT NULL, headers TEXT NOT NULL, body BLOB NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS resources_base_key ON resources(base_key)")
        restrict_file_permissions(self.path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def eligible(self, request: Any) -> bool:
        parsed = urlsplit(request.url)
        return (request.method == "GET" and parsed.scheme in {"http", "https"}
                and Path(parsed.path).suffix.lower() in self.options.extensions
                and "range" not in request.headers and "upgrade" not in request.headers
                and "no-store" not in request.headers.get("cache-control", "").lower())

    @staticmethod
    def key(request: Any, vary: list[str] | None = None) -> str:
        parsed = urlsplit(request.url)
        url = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
        # 凭证、CORS 和压缩协商始终隔离；其他变体按响应 Vary 匹配。
        names = sorted({"cookie", "authorization", "origin", "accept-encoding", *(vary or [])})
        headers = [(name, request.headers.get(name, "")) for name in names]
        return hashlib.sha256(json.dumps([url, headers], ensure_ascii=True).encode()).hexdigest()

    def get(self, request: Any) -> tuple[list[tuple[bytes, bytes]], bytes] | None:
        if not self.eligible(request):
            return None
        with self._connect() as db:
            rows = db.execute("SELECT key, vary, created, headers, body FROM resources WHERE base_key=? ORDER BY created DESC",
                              (self.key(request),)).fetchall()
        for key, vary, created, raw_headers, body in rows:
            if time.time() - created > self.options.max_age_seconds:
                continue
            if self.key(request, json.loads(vary)) != key:
                continue
            headers = [(base64.b64decode(k), base64.b64decode(v)) for k, v in json.loads(raw_headers)]
            return headers, body
        return None

    def put(self, request: Any, response: Any) -> None:
        body = response.raw_content
        control = response.headers.get("cache-control", "").lower()
        vary = sorted({name.strip().lower() for name in response.headers.get("vary", "").split(",") if name.strip()})
        if (not self.eligible(request) or response.status_code != 200 or body is None
                or len(body) > min(self.options.max_resource_bytes, self.options.max_total_bytes)
                or "set-cookie" in response.headers or "no-store" in control
                or "private" in control or "*" in vary):
            return
        headers = [(base64.b64encode(k).decode(), base64.b64encode(v).decode())
                   for k, v in response.headers.fields
                   if k.decode("latin1").lower() not in _HOP_HEADERS]
        now = time.time()
        with self._connect() as db:
            db.execute("DELETE FROM resources WHERE created < ?", (now - self.options.max_age_seconds,))
            db.execute("DELETE FROM resources WHERE base_key=? AND vary != ?", (self.key(request), json.dumps(vary)))
            db.execute("INSERT OR REPLACE INTO resources VALUES (?, ?, ?, ?, ?, ?)",
                       (self.key(request, vary), self.key(request), json.dumps(vary), now, json.dumps(headers), body))
            total = db.execute("SELECT COALESCE(SUM(length(body)), 0) FROM resources").fetchone()[0]
            while total > self.options.max_total_bytes:
                oldest = db.execute("SELECT key, length(body) FROM resources ORDER BY created LIMIT 1").fetchone()
                db.execute("DELETE FROM resources WHERE key=?", (oldest[0],))
                total -= oldest[1]


class CacheAddon:
    def __init__(self, cache: ResourceCache) -> None:
        self.cache = cache

    def request(self, flow: Any) -> None:
        from mitmproxy import http

        try:
            cached = self.cache.get(flow.request)
        except (OSError, sqlite3.Error, ValueError):
            cached = None
        if cached is not None:
            headers, body = cached
            flow.response = http.Response.make(200, body, headers)
            flow.metadata["agent_cache_hit"] = True

    def responseheaders(self, flow: Any) -> None:
        # HTML、图片、视频、SSE 等默认直接流转，避免代理缓冲无限流。
        if not self.cache.eligible(flow.request):
            flow.response.stream = True

    def response(self, flow: Any) -> None:
        if not flow.metadata.get("agent_cache_hit"):
            # 磁盘满或缓存不可写时仍交付正常网络响应。
            with suppress(OSError, sqlite3.Error):
                self.cache.put(flow.request, flow.response)
