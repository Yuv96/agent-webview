from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from agent_webview.cli import (
    RuntimeFileInUseError,
    _base_url,
    _claim_runtime_file,
    _parse_args,
    _write_runtime_file,
    main,
)


def test_default_paths_are_outside_current_directory() -> None:
    args = _parse_args([])

    assert args.data_dir.is_absolute()
    assert args.runtime_dir.is_absolute()
    assert args.runtime_file.is_absolute()


def test_remote_host_requires_explicit_opt_in() -> None:
    with pytest.raises(SystemExit) as error:
        _parse_args(["--host", "0.0.0.0"])

    assert error.value.code == 2
    assert _parse_args(["--host", "0.0.0.0", "--allow-remote"]).allow_remote


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_is_rejected(port: str) -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--port", port])


def test_global_proxy_accepts_cli_and_environment(monkeypatch) -> None:
    assert _parse_args(["--proxy", "http://127.0.0.1:7890"]).proxy == (
        "http://127.0.0.1:7890"
    )

    monkeypatch.setenv("AGENT_WEBVIEW_PROXY", "https://proxy.example")
    assert _parse_args([]).proxy == "https://proxy.example:443"


@pytest.mark.parametrize(
    "proxy",
    [
        "socks5://127.0.0.1:1080",
        "http://user:" + "value" + "@127.0.0.1:7890",
    ],
)
def test_invalid_global_proxy_is_rejected(proxy: str) -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--proxy", proxy])


def test_runtime_file_is_private(tmp_path) -> None:
    target = tmp_path / "runtime" / "controller.json"

    _write_runtime_file(
        target,
        host="127.0.0.1",
        port=8765,
        token="测试令牌",
        proxy="http://127.0.0.1:7890",
    )

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["token"] == "测试令牌"
    assert document["proxy"] == {
        "enabled": True,
        "server": "http://127.0.0.1:7890",
    }
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_ipv6_base_url_uses_brackets() -> None:
    assert _base_url("::1", 8765) == "http://[::1]:8765"
    assert _base_url("localhost", 8765) == "http://localhost:8765"


def test_runtime_file_lock_rejects_concurrent_owner(tmp_path) -> None:
    target = tmp_path / "controller.json"

    with (
        _claim_runtime_file(target),
        pytest.raises(RuntimeFileInUseError),
        _claim_runtime_file(target),
    ):
        pass

    with _claim_runtime_file(target):
        assert target.with_name("controller.json.lock").exists()


def test_print_runtime_file_exits_without_starting(monkeypatch, capsys, tmp_path) -> None:
    target = tmp_path / "controller.json"
    monkeypatch.setattr(
        "sys.argv",
        ["agent-webview", "--runtime-file", str(target), "--print-runtime-file"],
    )

    main()

    assert Path(capsys.readouterr().out.strip()) == target
