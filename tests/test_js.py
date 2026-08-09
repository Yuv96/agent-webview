from __future__ import annotations

from agent_webview.js import (
    command_script,
    cookie_restore_expression,
    dom_input_expression,
    instrumentation_script,
)


def test_command_script_uses_bridge_result() -> None:
    script = command_script("request-1", "document.title", expression=True)

    assert "agent_result" in script
    assert "request-1" in script
    assert "await (document.title)" in script


def test_generated_scripts_escape_values() -> None:
    input_script = dom_input_expression("#name", 'a"b', 0)
    cookie_script = cookie_restore_expression(
        [{"name": "token", "value": 'a"b', "http_only": False}]
    )

    assert 'a\\"b' in input_script
    assert 'a\\"b' in cookie_script


def test_instrumentation_covers_common_network_apis() -> None:
    script = instrumentation_script(
        {
            "network": True,
            "mutations": False,
            "mutation_selector": None,
            "capture_request_bodies": False,
            "capture_response_bodies": False,
            "max_body_chars": 20000,
        }
    )

    assert "window.fetch" in script
    assert "XMLHttpRequest.prototype.send" in script
    assert "window.WebSocket" in script
    assert "PerformanceObserver" in script
