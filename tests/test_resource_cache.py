from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent_webview.models import ResourceCacheOptions
from agent_webview.resource_cache import ResourceCache


class Headers(dict):
    def items(self, multi=False):
        return super().items()

    @property
    def fields(self):
        return [(k.encode(), v.encode()) for k, v in self.items()]


def request(url="https://example.test/app.js?v=1", method="GET", **headers):
    return SimpleNamespace(url=url, method=method, headers=Headers(headers))


def response(body=b"const value = 1;", status=200, **headers):
    return SimpleNamespace(raw_content=body, status_code=status, headers=Headers(headers))


def test_cache_survives_reopen_and_distinguishes_url_and_credentials(tmp_path):
    options = ResourceCacheOptions(enabled=True)
    cache = ResourceCache(tmp_path, options)
    original = request()
    cache.put(original, response(**{"content-type": "application/javascript"}))
    reopened = ResourceCache(tmp_path, options)
    assert reopened.get(original)[1] == b"const value = 1;"
    for other in [request("https://other.test/app.js?v=1"), request("https://example.test/app.js?v=2"),
                  request("http://example.test/app.js?v=1"), request(cookie="session=other"),
                  request(authorization="Bearer other"), request(origin="https://other.test")]:
        assert reopened.get(other) is None
    assert reopened.get(request(**{"if-none-match": '"version"'})) is not None


@pytest.mark.parametrize("suffix", [".html", ".png", ".json", "", ".js.map"])
def test_only_allowlisted_extensions(tmp_path, suffix):
    cache = ResourceCache(tmp_path, ResourceCacheOptions())
    req = request(f"https://example.test/path{suffix}?fake=.js")
    cache.put(req, response())
    assert cache.get(req) is None


@pytest.mark.parametrize("req,res", [
    (request(method="POST"), response()),
    (request(range="bytes=0-2"), response()),
    (request(), response(status=304)),
    (request(), response(status=404)),
    (request(), response(**{"set-cookie": "session=value"})),
    (request(), response(**{"cache-control": "private, max-age=3600"})),
    (request(), response(**{"cache-control": "no-store"})),
    (request(), response(vary="*")),
    (request(), response(vary="Accept-Language, *")),
    (request(**{"cache-control": "no-store"}), response()),
    (request(), response(body=None)),
])
def test_do_not_cache_partial_private_or_failed_responses(tmp_path, req, res):
    cache = ResourceCache(tmp_path, ResourceCacheOptions())
    cache.put(req, res)
    assert cache.get(req) is None


def test_suffix_normalization_limits_and_expiry(tmp_path, monkeypatch):
    options = ResourceCacheOptions(extensions=["JS", ".css", ".js", "svg"], max_total_bytes=8, max_resource_bytes=6, max_age_seconds=10)
    assert options.extensions == [".js", ".css", ".svg"]
    cache = ResourceCache(tmp_path, options)
    monkeypatch.setattr("agent_webview.resource_cache.time.time", lambda: 100)
    cache.put(request(), response(b"1234567"))
    assert cache.get(request()) is None
    cache.put(request(), response(b"12345"))
    monkeypatch.setattr("agent_webview.resource_cache.time.time", lambda: 101)
    svg = request("https://example.test/image.svg")
    cache.put(svg, response(b"67890"))
    assert cache.get(request()) is None
    assert cache.get(svg)[1] == b"67890"
    monkeypatch.setattr("agent_webview.resource_cache.time.time", lambda: 112)
    assert cache.get(svg) is None


def test_concurrent_writes_are_atomic(tmp_path):
    cache = ResourceCache(tmp_path, ResourceCacheOptions())
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: cache.put(request(f"https://example.test/{n}.css"), response(str(n).encode())), range(30)))
    with closing(sqlite3.connect(cache.path)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for n in range(30):
        assert cache.get(request(f"https://example.test/{n}.css"))[1] == str(n).encode()


def test_vary_and_cross_page_resource_reuse(tmp_path):
    cache = ResourceCache(tmp_path, ResourceCacheOptions())
    first = request(referer="https://example.test/login", **{"accept-language": "zh"})
    cache.put(first, response(b"zh", vary="Accept-Language"))
    another_page = request(referer="https://example.test/home", **{"accept-language": "zh"})
    assert cache.get(another_page)[1] == b"zh"
    english = request(**{"accept-language": "en"})
    assert cache.get(english) is None
    cache.put(english, response(b"en", vary="Accept-Language"))
    assert cache.get(english)[1] == b"en"
    assert cache.get(first)[1] == b"zh"
