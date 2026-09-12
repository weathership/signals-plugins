"""Ripley and Bishop are Named Bots beside AgentRTC."""
from __future__ import annotations

from pathlib import Path

import yaml

from hsengine.engine.named_bots import (
    BISHOP,
    RIPLEY,
    BishopOutcome,
    bishop_delegation_cap,
    bishop_prompt,
    bishop_run,
    ensure_bots,
    parse_bishop_reply,
    ripley_spoken_system,
    template_soul,
)


def test_templates_exist():
    assert "Ripley" in template_soul(RIPLEY)
    assert "Bishop" in template_soul(BISHOP)
    assert "delegate_task" in template_soul(BISHOP)
    assert "MONOLOGUE" in template_soul(BISHOP)
    bishop = template_soul(BISHOP)
    assert "HERMES_HOME" in bishop
    assert "~/wiki" in bishop
    assert "Gaius" in bishop
    assert "session_search" in bishop
    assert "recall" in bishop.lower()


def test_parse_bishop_reply_labels_and_json():
    both = parse_bishop_reply(
        "STEER: float the Lilly gap\nMONOLOGUE: The 10-K keeps sitting next to the book."
    )
    assert both.steer == "float the Lilly gap"
    assert "10-K" in both.monologue
    js = parse_bishop_reply('{"steer": "NONE", "monologue": "A quiet thought on the tape."}')
    assert js.steer == ""
    assert "tape" in js.monologue
    loose = parse_bishop_reply("Steer: keep going on the book.")
    assert "book" in loose.steer
    assert parse_bishop_reply("") == BishopOutcome()


def test_bishop_prompt_varies_the_move():
    system, prompt, max_tokens = bishop_prompt(move="thought", last_steer="old idea")
    assert "Bishop" in system
    assert "recent_thoughts" in prompt
    assert "old idea" in prompt
    assert "do not repeat" in prompt.lower()
    assert max_tokens >= 120
    _, world, _ = bishop_prompt(move="world", glance="HN: Show HN: aperture")
    assert "aperture" in world
    _, open_p, n = bishop_prompt(move="open", glance="Latest thoughts brief: the Lilly gap")
    assert "Connect" in open_p
    assert "two-ideas" in open_p or "formula" in open_p.lower()
    assert "Lilly" in open_p
    assert n >= 200


def test_ripley_opening_prompts_prefer_monologue():
    from hsengine.engine.named_bots import ripley_opening_prompts

    system, user = ripley_opening_prompts(
        BishopOutcome(steer="float the gap", monologue="The 10-K is still sitting there.")
    )
    assert "Ripley" in system
    assert "float the gap" in system
    assert "10-K" in user
    assert "two-ideas" not in user.lower() or "formula" in user.lower()
    _, steer_only = ripley_opening_prompts(BishopOutcome(steer="keep going on the book."))
    assert "just connected" in steer_only.lower()
    try:
        ripley_opening_prompts(BishopOutcome())
        raise AssertionError("empty opening must fail")
    except RuntimeError as e:
        assert "no fallback" in str(e)


def test_ensure_bots_creates_managed_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    out = ensure_bots()
    assert RIPLEY in out and BISHOP in out
    ripley = tmp_path / ".hermes" / "profiles" / "ripley"
    bishop = tmp_path / ".hermes" / "profiles" / "bishop"
    assert (ripley / "SOUL.md").read_text(encoding="utf-8").startswith("You are Ripley")
    assert "Bishop" in (bishop / "SOUL.md").read_text(encoding="utf-8")
    rmeta = yaml.safe_load((ripley / "profile.yaml").read_text(encoding="utf-8"))
    bmeta = yaml.safe_load((bishop / "profile.yaml").read_text(encoding="utf-8"))
    assert rmeta["ui_meta"]["hermes-bots"]["title"] == "Ripley"
    assert bmeta["ui_meta"]["hermes-bots"]["title"] == "Bishop"
    bcfg = yaml.safe_load((bishop / "config.yaml").read_text(encoding="utf-8"))
    assert bcfg["delegation"]["max_concurrent_children"] == 2
    again = ensure_bots()
    assert again[RIPLEY] == out[RIPLEY]


def test_ensure_bots_does_not_clobber_custom_soul(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    ensure_bots()
    soul = tmp_path / ".hermes" / "profiles" / "ripley" / "SOUL.md"
    soul.write_text("You are Ripley, but louder.\n", encoding="utf-8")
    ensure_bots()
    assert soul.read_text(encoding="utf-8").strip() == "You are Ripley, but louder."


def test_ripley_spoken_system_includes_soul_and_voice_rails():
    text = ripley_spoken_system()
    assert "Ripley" in text
    assert "live voice call" in text.lower()
    assert "this minute" not in text.lower()


def test_bishop_delegation_cap_is_two():
    import tools.delegate_tool_config as dtc

    orig = dtc._get_max_concurrent_children()
    with bishop_delegation_cap(2):
        assert dtc._get_max_concurrent_children() == 2
    assert dtc._get_max_concurrent_children() == orig


def test_bishop_run_is_silent(monkeypatch):
    seen: dict = {}

    def _complete(**k):
        seen.update(k)
        return type("R", (), {"text": "STEER: float the gap\nMONOLOGUE: NONE", "model": "x"})()

    monkeypatch.setattr("hsengine.engine.interactive.complete_cerebras", _complete)
    out = bishop_run(session_id="s1", move="deepen", utterance="Nautilus notes")
    assert seen.get("speak") is False
    assert seen.get("recall_query") == "Nautilus notes"
    assert out.steer == "float the gap"
    assert out.monologue == ""
