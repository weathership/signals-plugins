"""Primary Hermes hop from AgentRTC uses CLI Grok, not the Cerebras overlay."""
from __future__ import annotations

from hsengine.engine import primary_hermes


def test_cli_toolsets_include_kanban(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.tools_config._get_platform_tools",
        lambda cfg, platform: {"hermes-cli", "web"},
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"toolsets": ["hermes-cli"]},
    )
    names = primary_hermes._cli_toolsets()
    assert "hermes-cli" in names
    assert "kanban" in names
    assert "web" in names


def test_kanban_visible_flips_the_profile_gate(monkeypatch):
    from tools import kanban_tools

    monkeypatch.setattr(kanban_tools, "_profile_has_kanban_toolset", lambda: False)
    assert kanban_tools._profile_has_kanban_toolset() is False
    with primary_hermes._kanban_visible():
        assert kanban_tools._profile_has_kanban_toolset() is True
    assert kanban_tools._profile_has_kanban_toolset() is False
