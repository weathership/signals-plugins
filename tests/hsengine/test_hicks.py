"""Hicks: conversation work lands in triage; a figure keeps the video."""
from __future__ import annotations

import asyncio
import json

import pytest

from hsengine.engine import hicks
from hsengine.engine import ops
from hsengine.engine.named_bots import BishopOutcome


@pytest.fixture(autouse=True)
def _isolate_board(tmp_path, monkeypatch):
    root = tmp_path / "kanban-home"
    root.mkdir()
    hermes = tmp_path / ".hermes"
    hermes.mkdir()
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.setattr(hicks, "refresh_view", lambda: None, raising=False)
    # file_implied imports refresh_view lazily from webrtc_kanban.
    import hsengine.engine.webrtc_kanban as kb

    monkeypatch.setattr(kb, "refresh_view", lambda: None)
    return hermes


def test_speech_does_not_become_a_card():
    """A promise is not ingress. The board gets a task only when one is placed."""
    filed = hicks.note_turn(
        session_id="cafe",
        user="put an afternoon planning session on the Gaius agenda",
        assistant="I'll set up a short afternoon planning session on Gaius.",
        tools_used=(),
    )
    assert filed["created"] is False
    assert hicks.board_aside() == ""


def test_several_lanes_invite_bishop_and_one_lane_does_not(monkeypatch):
    monkeypatch.setattr(
        "hsengine.engine.named_bots.bishop_run",
        lambda **k: (_ for _ in ()).throw(AssertionError("bishop should wait")),
    )
    empty = json.loads(ops.dispatch("bishop_suggest", {"topic": "movers"}))
    assert empty["ok"] is False
    hicks.file_implied(
        session_id="cafe",
        title="Pull the week's movers",
        user="pull the week's movers",
        assistant="I'll pull the week's movers.",
    )
    hicks.file_implied(
        session_id="cafe",
        title="Redesign the week aperture",
        user="we should redesign the aperture",
        assistant="The aperture still matters.",
    )
    aside = hicks.board_aside()
    assert "bishop_suggest" in aside
    seen: dict = {}

    def _bishop(**kwargs):
        seen.update(kwargs)
        return BishopOutcome(steer="", monologue="Leave the aperture on the board and keep talking.")

    monkeypatch.setattr("hsengine.engine.named_bots.bishop_run", _bishop)
    data = json.loads(ops.dispatch("bishop_suggest", {"topic": "the aperture"}))
    assert data["ok"] is True
    assert "aperture" in data["suggestion"].lower()
    assert seen.get("move") == "board"


def test_figure_keeps_the_video():
    assert hicks.kanban_would_cover_figure(live=True, current_kind="density", requested="kanban")
    assert not hicks.kanban_would_cover_figure(live=True, current_kind="kanban", requested="kanban")
    assert not hicks.kanban_would_cover_figure(live=False, current_kind="density", requested="kanban")
    assert not hicks.kanban_would_cover_figure(live=True, current_kind="density", requested="chord")

    from hsengine.engine import webrtc_program as wp
    from hsengine.engine import webrtc_viz

    class _Board:
        def status(self):
            return {"ok": True, "live": True, "kind": "density", "title": "SLB"}

    original = wp.PROGRAM
    wp.PROGRAM = _Board()  # type: ignore[assignment]
    try:
        out = asyncio.run(
            webrtc_viz._show_live(
                "cafe",
                kind="kanban",
                title="Kanban",
                highlight="",
                source="",
                data="",
                fade_s=0.2,
            )
        )
    finally:
        wp.PROGRAM = original
    assert out["ok"] is False
    assert out["precedence"] == "holoviews"
    assert out["kind"] == "density"


def test_pin_orchestrator_rewrites_only_the_grok_default():
    text = "kanban:\n  orchestrator_profile: grok\n  default_assignee: grok\n"
    pinned = hicks.pin_orchestrator_text(text)
    assert "orchestrator_profile: hicks" in pinned
    assert "default_assignee: grok" in pinned
    custom = hicks.pin_orchestrator_text(
        "kanban:\n  orchestrator_profile: specialist\n"
    )
    assert "specialist" in custom
    assert hicks.pin_orchestrator_text(pinned) == pinned


def test_spoken_contract_names_hicks_and_figure_precedence():
    from hsengine.engine.webrtc_moshi import SPOKEN_SYSTEM

    text = SPOKEN_SYSTEM.lower()
    assert "hicks" in text
    assert "agenda_create" in text
    assert "a sentence does not become a card" in text
    assert "bishop_suggest" in text
    assert "kind=kanban" in text
    assert "precedence" in text or "takes precedence" in text
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    assert "bishop_suggest" in names
    assert "kanban_create" not in names
