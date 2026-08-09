from __future__ import annotations

import os
import stat

from agent_webview.files import ensure_private_directory, write_private_text


def test_private_directory_tightens_existing_permissions(tmp_path) -> None:
    target = tmp_path / "private"
    target.mkdir(mode=0o755)

    ensure_private_directory(target)

    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_private_text_replaces_content_and_permissions(tmp_path) -> None:
    target = tmp_path / "private" / "value.txt"
    write_private_text(target, "第一版")
    write_private_text(target, "第二版")

    assert target.read_text(encoding="utf-8") == "第二版"
    assert not list(target.parent.glob("*.tmp"))
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_private_text_does_not_tighten_existing_parent(tmp_path) -> None:
    target = tmp_path / "public"
    target.mkdir(mode=0o755)

    write_private_text(target / "value.txt", "内容")

    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
