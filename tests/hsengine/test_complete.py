"""Complete routes agent/instruct to Cerebras during AgentRTC; thinking stays Gaius."""
from __future__ import annotations

from types import SimpleNamespace

from hsengine.engine import complete as complete_mod


def test_interactive_agent_uses_cerebras_thinking_does_not(monkeypatch):
    seen: list[str] = []

    def _cerebras(**k):
        seen.append("cerebras")
        return SimpleNamespace(text="fast", peer="cerebras", model="qwen-3.8-27b")

    def _routes(cap, **k):
        seen.append(cap)
        return SimpleNamespace(text="gaius", peer="gaius", model="Qwen")

    monkeypatch.setattr("hsengine.engine.interactive.is_active", lambda: True)
    monkeypatch.setattr(
        "hsengine.engine.interactive.complete_cerebras", _cerebras
    )
    monkeypatch.setattr(complete_mod, "complete_routes", _routes)
    monkeypatch.setattr(
        "hsengine.engine.oip_client.configured_oip_peers", lambda: []
    )
    a = complete_mod.complete(capability="agent", prompt="hi")
    assert a.peer == "cerebras"
    t = complete_mod.complete(capability="thinking", prompt="hi")
    assert t.peer == "gaius"
    assert seen == ["cerebras", "thinking"]
