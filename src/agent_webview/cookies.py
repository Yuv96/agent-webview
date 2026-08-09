from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookies import Morsel
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_webview.files import ensure_private_directory, write_private_json
from agent_webview.models import CookieRecord


def _truthy_attribute(value: Any) -> bool:
    return bool(value) and str(value).lower() not in {"false", "0", "none"}


def _normalize_expires(value: Any) -> str | int | float | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return value if value > 0 else None
    text = str(value)
    year = re.search(r"\b(\d{4})\b", text)
    if year and int(year.group(1)) <= 1970:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return text
    return text if parsed.year > 1970 else None


def normalize_pywebview_cookies(raw_cookies: Iterable[Any]) -> list[CookieRecord]:
    normalized: list[CookieRecord] = []
    for container in raw_cookies:
        if isinstance(container, Morsel):
            items = [(container.key, container)]
        elif hasattr(container, "items"):
            items = list(container.items())
        else:
            continue
        for name, morsel in items:
            if isinstance(morsel, Morsel):
                same_site = morsel["samesite"] or None
                if same_site:
                    same_site = same_site.title()
                normalized.append(
                    CookieRecord(
                        name=str(name),
                        value=morsel.value,
                        domain=morsel["domain"] or None,
                        path=morsel["path"] or "/",
                        expires=_normalize_expires(morsel["expires"]),
                        secure=_truthy_attribute(morsel["secure"]),
                        http_only=_truthy_attribute(morsel["httponly"]),
                        same_site=same_site
                        if same_site in {"Strict", "Lax", "None"}
                        else None,
                    )
                )
            else:
                normalized.append(CookieRecord(name=str(name), value=str(morsel)))
    return normalized


class SnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = ensure_private_directory(directory)

    def save(
        self,
        *,
        session_id: str,
        url: str | None,
        cookies: list[dict[str, Any]],
        name: str | None,
    ) -> dict[str, Any]:
        snapshot_id = uuid4().hex
        document = {
            "snapshot_id": snapshot_id,
            "name": name,
            "session_id": session_id,
            "url": url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cookies": cookies,
            "limitations": [
                "通过 document.cookie 恢复，无法恢复 HttpOnly Cookie。",
                "浏览器策略可能拒绝部分 Cookie 属性。",
            ],
        }
        target = self.directory / f"{snapshot_id}.json"
        write_private_json(target, document)
        return document

    def get(self, snapshot_id: str) -> dict[str, Any]:
        path = self._path(snapshot_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        snapshots = []
        for path in sorted(
            self.directory.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            snapshots.append(
                {
                    key: document.get(key)
                    for key in ("snapshot_id", "name", "session_id", "url", "created_at")
                }
            )
        return snapshots

    def delete(self, snapshot_id: str) -> None:
        self._path(snapshot_id).unlink()

    def _path(self, snapshot_id: str) -> Path:
        if not snapshot_id or any(char not in "0123456789abcdef" for char in snapshot_id):
            raise FileNotFoundError(snapshot_id)
        path = self.directory / f"{snapshot_id}.json"
        if not path.is_file():
            raise FileNotFoundError(snapshot_id)
        return path
