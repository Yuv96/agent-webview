from __future__ import annotations

import os
import stat
from http.cookies import SimpleCookie

import pytest

from agent_webview.cookies import SnapshotStore, normalize_pywebview_cookies


def test_normalize_simple_cookie() -> None:
    cookie = SimpleCookie()
    cookie["session"] = "abc"
    cookie["session"]["path"] = "/app"
    cookie["session"]["secure"] = True
    cookie["session"]["httponly"] = True
    cookie["session"]["samesite"] = "Lax"

    result = normalize_pywebview_cookies([cookie])

    assert len(result) == 1
    assert result[0].name == "session"
    assert result[0].path == "/app"
    assert result[0].secure is True
    assert result[0].http_only is True
    assert result[0].same_site == "Lax"


def test_normalize_session_cookie_expiry() -> None:
    cookie = SimpleCookie()
    cookie["session"] = "abc"
    cookie["session"]["expires"] = "Mon, 01 Jan 0001 00:00:00 GMT"

    result = normalize_pywebview_cookies([cookie])

    assert result[0].expires is None


def test_snapshot_store_round_trip(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    saved = store.save(
        session_id="session-1",
        url="https://example.com/",
        cookies=[{"name": "a", "value": "1"}],
        name="示例",
    )

    loaded = store.get(saved["snapshot_id"])

    assert loaded["name"] == "示例"
    assert loaded["cookies"] == [{"name": "a", "value": "1"}]
    assert store.list()[0]["snapshot_id"] == saved["snapshot_id"]
    if os.name != "nt":
        target = tmp_path / f"{saved['snapshot_id']}.json"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700

    store.delete(saved["snapshot_id"])
    with pytest.raises(FileNotFoundError):
        store.get(saved["snapshot_id"])
