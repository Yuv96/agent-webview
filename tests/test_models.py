from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_webview.models import SessionCreateRequest


def test_session_url_accepts_supported_schemes() -> None:
    assert SessionCreateRequest(url="https://example.com").url == "https://example.com"
    assert SessionCreateRequest(url=None).url is None


def test_session_url_rejects_file_scheme() -> None:
    with pytest.raises(ValidationError):
        SessionCreateRequest(url="file:///tmp/a.html")


def test_session_url_rejects_data_scheme() -> None:
    with pytest.raises(ValidationError):
        SessionCreateRequest(url="data:text/html,example")


def test_session_proxy_accepts_http_and_https() -> None:
    assert (
        SessionCreateRequest(proxy="http://127.0.0.1:7890").proxy
        == "http://127.0.0.1:7890"
    )
    assert (
        SessionCreateRequest(proxy="https://proxy.example").proxy
        == "https://proxy.example:443"
    )


@pytest.mark.parametrize(
    "proxy",
    [
        "socks5://127.0.0.1:1080",
        "http://user:" + "value" + "@127.0.0.1:7890",
        "http://127.0.0.1:7890/path",
    ],
)
def test_session_proxy_rejects_unsupported_values(proxy: str) -> None:
    with pytest.raises(ValidationError):
        SessionCreateRequest(proxy=proxy)


def test_proxy_credentials_are_separate_from_public_server_and_require_pair():
    from agent_webview.models import ProxyUpdateRequest

    request = ProxyUpdateRequest(proxy="http://proxy.example", proxy_username="user", proxy_password="secret")  # pragma: allowlist secret
    assert request.proxy == "http://proxy.example:80"
    assert "secret" not in repr(request)
    assert SessionCreateRequest(proxy=request.proxy, proxy_username="user", proxy_password="secret").proxy_password == "secret"  # pragma: allowlist secret
    for values in (
        {"proxy_username": "user"},
        {"proxy_password": "secret"},  # pragma: allowlist secret
        {"proxy_username": "invalid:user", "proxy_password": "secret"},  # pragma: allowlist secret
        {"proxy_username": "user", "proxy_password": ""},
    ):
        with pytest.raises(ValidationError):
            ProxyUpdateRequest(proxy="http://proxy.example", **values)
    with pytest.raises(ValidationError):
        SessionCreateRequest(proxy_username="user", proxy_password="secret")  # pragma: allowlist secret
    with pytest.raises(ValidationError):
        ProxyUpdateRequest(proxy=None)
