from __future__ import annotations

from agent_webview.events import EventBuffer


def test_event_buffer_reports_dropped_events() -> None:
    buffer = EventBuffer(capacity=2)
    buffer.append("dom", {"value": 1})
    buffer.append("network", {"value": 2})
    buffer.append("dom", {"value": 3})

    page = buffer.get(after=0, limit=10)

    assert [event["sequence"] for event in page.events] == [2, 3]
    assert page.latest_sequence == 3
    assert page.oldest_sequence == 2
    assert page.dropped_before == 2


def test_event_buffer_filters_kinds() -> None:
    buffer = EventBuffer()
    buffer.append("dom", {})
    buffer.append("network", {})

    page = buffer.get(after=0, kinds=["network"])

    assert [event["kind"] for event in page.events] == ["network"]
