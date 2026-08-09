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
