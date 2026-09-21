"""Primary Hermes hop from AgentRTC uses CLI Grok, not the Cerebras overlay."""
from __future__ import annotations

import os

from hsengine.engine import primary_hermes


def test_partner_reply_is_steer_monologue_not_a_dump():
    out = primary_hermes.parse_partner_reply(
        "STEER: keep the Theta card in view\nMONOLOGUE: W38 is on the board."
    )
    assert out.steer == "keep the Theta card in view"
    assert out.monologue == "W38 is on the board."
    dump = primary_hermes.parse_partner_reply(
        "I created skill foo and scheduled a cron at 6am. Here is the JSON..."
    )
    assert dump.steer == ""
    assert dump.monologue == ""


def test_offer_steer_colors_the_next_spoken_turn(monkeypatch):
    class Taker:
        pending_steer = ""

    taker = Taker()
    monkeypatch.setattr(
        "hsengine.engine.webrtc_session.HUB._turns",
        {"cafe": taker},
        raising=False,
    )
    primary_hermes.offer_steer("pick up the lattice thread")
    assert taker.pending_steer == "pick up the lattice thread"


def test_cli_toolsets_include_kanban(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.tools_config._get_platform_tools",
        lambda cfg, platform: {"hermes-cli", "web", "skills", "cronjob"},
    )
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"toolsets": ["hermes-cli"]},
    )
    names = primary_hermes._cli_toolsets()
    assert "hermes-cli" in names
    assert "kanban" in names
    assert "skills" in names
    assert "cronjob" in names


def test_primary_surface_opens_kanban_and_cron_gates(monkeypatch):
    from tools import kanban_tools

    monkeypatch.setattr(kanban_tools, "_profile_has_kanban_toolset", lambda: False)
    monkeypatch.delenv("HERMES_INTERACTIVE", raising=False)
    assert kanban_tools._profile_has_kanban_toolset() is False
    assert not os.environ.get("HERMES_INTERACTIVE")
    with primary_hermes._primary_surface():
        assert kanban_tools._profile_has_kanban_toolset() is True
        assert os.environ.get("HERMES_INTERACTIVE") == "1"
    assert kanban_tools._profile_has_kanban_toolset() is False
    assert not os.environ.get("HERMES_INTERACTIVE")


def test_primary_surface_schema_includes_kanban_skills_cron():
    from model_tools import get_tool_definitions

    toolsets = ["hermes-cli", "kanban", "skills", "cronjob"]
    with primary_hermes._primary_surface():
        visible = {
            t["function"]["name"]
            for t in get_tool_definitions(enabled_toolsets=toolsets, quiet_mode=True)
        }
        catalog = {
            t["function"]["name"]
            for t in get_tool_definitions(
                enabled_toolsets=toolsets,
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
        }
    assert "kanban_create" in visible
    assert "kanban_list" in visible
    assert "skill_manage" in visible
    assert "skills_list" in visible
    assert "cronjob_manage" in catalog
    assert "cronjob_manage" in visible or "tool_search" in visible
