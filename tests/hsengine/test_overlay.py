"""Cerebras overlay while AgentRTC interactive is in force."""
from __future__ import annotations

from hsengine.overlay import overlay_runtime, session_wants_cerebras


def test_session_wants_cerebras_follows_in_process_flag(monkeypatch):
    monkeypatch.setattr("hsengine.engine.interactive.is_active", lambda: True)
    assert session_wants_cerebras() is True
    monkeypatch.setattr("hsengine.engine.interactive.is_active", lambda: False)
    monkeypatch.setattr(
        "hsengine.engine.coordination.list_activities",
        lambda **k: [{"kind": "interactive_session"}],
    )
    assert session_wants_cerebras() is False


def test_overlay_runtime_none_when_not_interactive(monkeypatch):
    monkeypatch.setattr("hsengine.overlay.session_wants_cerebras", lambda: False)
    assert overlay_runtime() is None


def test_overlay_runtime_pins_cerebras(monkeypatch):
    monkeypatch.setattr("hsengine.overlay.session_wants_cerebras", lambda: True)
    monkeypatch.setattr(
        "hsengine.engine.interactive._cerebras_key", lambda: "sk-test"
    )
    monkeypatch.setattr(
        "hsengine.engine.interactive._cfg",
        lambda path, default: default,
    )
    ov = overlay_runtime()
    assert ov is not None
    assert ov["provider"] == "cerebras"
    assert "cerebras.ai" in ov["base_url"]
    assert ov["model"]
    assert ov["api_mode"] == "chat_completions"
