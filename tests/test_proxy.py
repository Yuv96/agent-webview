from __future__ import annotations

import os

import pytest

from agent_webview.proxy import (
    IP_LOOKUP_URL,
    configure_browser_proxy,
    format_proxy_title,
    lookup_proxy_identity,
    normalize_proxy_url,
    parse_ip_lookup_document,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
        ("https://proxy.example", "https://proxy.example:443"),
        ("http://[::1]:8080/", "http://[::1]:8080"),
    ],
)
def test_proxy_url_normalization(value: str, expected: str) -> None:
    assert normalize_proxy_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "socks5://127.0.0.1:1080",
        "http://user:" + "value" + "@127.0.0.1:8080",
        "http://127.0.0.1:8080/path",
        "http://127.0.0.1:8080?mode=test",
        "http://127.0.0.1:0",
        "http://proxy host:8080",
    ],
)
def test_invalid_proxy_urls_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_proxy_url(value)


def test_ip_lookup_document_builds_location_and_title() -> None:
    identity = parse_ip_lookup_document(
        '{"success":true,"ip":"203.0.113.8","country":"中国",'
        '"region":"上海市","city":"上海"}'
    )

    assert identity.ip == "203.0.113.8"
    assert identity.location == "上海"
    assert format_proxy_title(
        "调试窗口",
        state="active",
        ip=identity.ip,
        location=identity.location,
    ) == "[203.0.113.8 · 上海] 调试窗口"


def test_failed_ip_lookup_document_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_ip_lookup_document('{"success":false,"message":"rate limited"}')
    with pytest.raises(ValueError):
        parse_ip_lookup_document("<html>error</html>")


def test_proxy_identity_lookup_uses_fixed_service_and_explicit_proxy(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    class Response:
        text = '{"success":true,"ip":"203.0.113.9","country":"中国"}'

        def raise_for_status(self) -> None:
            return None

    class Client:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url: str) -> Response:
            observed["url"] = url
            return Response()

    monkeypatch.setattr("agent_webview.proxy.httpx.Client", Client)

    identity = lookup_proxy_identity("http://127.0.0.1:7890")

    assert identity.ip == "203.0.113.9"
    assert identity.location == "未知归属地"
    assert format_proxy_title(
        "调试窗口", state="active", ip=identity.ip, location=identity.location
    ) == "[203.0.113.9] 调试窗口"
    assert observed["proxy"] == "http://127.0.0.1:7890"
    assert observed["trust_env"] is False
    assert observed["url"] == IP_LOOKUP_URL


def test_linux_proxy_configures_browser_process_environment(monkeypatch) -> None:
    monkeypatch.setattr("agent_webview.proxy.platform.system", lambda: "Linux")
    for name in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "QTWEBENGINE_CHROMIUM_FLAGS",
    ):
        monkeypatch.delenv(name, raising=False)

    configure_browser_proxy("http://127.0.0.1:7890")

    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"
    assert (
        "--proxy-server=http://127.0.0.1:7890"
        in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
    )
    assert (
        "--proxy-bypass-list=<-loopback>"
        in os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    )
