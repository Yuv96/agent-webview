from __future__ import annotations

from agent_webview.bridge import AgentApi, AgentBridge
from agent_webview.events import EventBuffer


def test_agent_api_exposes_only_bridge_methods() -> None:
    api = AgentApi(AgentBridge(EventBuffer()))
    public = {name for name in dir(api) if not name.startswith("_")}

    assert public == {"agent_event", "agent_result"}
