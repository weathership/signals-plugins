"""Ripley and Bishop are Named Bots beside AgentRTC."""
from __future__ import annotations

from pathlib import Path

import yaml

from hsengine.engine.named_bots import (
    BISHOP,
    RIPLEY,
    VASQUEZ,
    bishop_max_tokens,
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
    assert "Vasquez" in template_soul(VASQUEZ)
    assert "viz_show" in template_soul(VASQUEZ)
    assert "viz_hover" in template_soul(VASQUEZ)
    assert "hover" in template_soul(VASQUEZ).lower()
    assert "grok_consult" in template_soul(VASQUEZ)
    assert "grok_consult" in template_soul(BISHOP)
    assert "grok_consult" in template_soul(RIPLEY)
    assert "delegate_task" in template_soul(BISHOP)
    assert "MONOLOGUE" in template_soul(BISHOP)
    bishop = template_soul(BISHOP)
    assert "HERMES_HOME" in bishop
    assert "~/wiki" in bishop
    assert "Gaius" in bishop
    assert "session_search" in bishop
    assert "recall" in bishop.lower()
    assert "user-provided" in bishop.lower() or "their paste" in bishop.lower()


def test_bishop_open_prompt_treats_zettel_as_user_material():
    from hsengine.engine.named_bots import bishop_prompt

    _, prompt, _ = bishop_prompt(move="open")
    low = prompt.lower()
    assert "user-provided" in low
    assert "interior monologue" in low or "federated" in low
    assert "recent_thoughts" in low


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
    assert n >= bishop_max_tokens()
    assert "do not grok_consult" in open_p.lower()
    assert "calendar session" in open_p.lower()
    assert "owner session prompt" in open_p.lower()
    assert "do not call recent_thoughts" in open_p.lower() or "do not lead with" in open_p.lower()
    _, deepen, _ = bishop_prompt(move="deepen")
    assert "grok_consult" in deepen


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
    assert RIPLEY in out and BISHOP in out and VASQUEZ in out
    ripley = tmp_path / ".hermes" / "profiles" / "ripley"
    bishop = tmp_path / ".hermes" / "profiles" / "bishop"
    vasquez = tmp_path / ".hermes" / "profiles" / "vasquez"
    assert (ripley / "SOUL.md").read_text(encoding="utf-8").startswith("You are Ripley")
    assert "Bishop" in (bishop / "SOUL.md").read_text(encoding="utf-8")
    assert "Vasquez" in (vasquez / "SOUL.md").read_text(encoding="utf-8")
    rmeta = yaml.safe_load((ripley / "profile.yaml").read_text(encoding="utf-8"))
    bmeta = yaml.safe_load((bishop / "profile.yaml").read_text(encoding="utf-8"))
    assert rmeta["ui_meta"]["hermes-bots"]["title"] == "Ripley"
    assert bmeta["ui_meta"]["hermes-bots"]["title"] == "Bishop"
    bcfg = yaml.safe_load((bishop / "config.yaml").read_text(encoding="utf-8"))
    assert bcfg["delegation"]["max_concurrent_children"] == 2
    again = ensure_bots()
    assert again[RIPLEY] == out[RIPLEY]


def test_ensure_bots_refreshes_stale_vasquez_soul(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    ensure_bots()
    soul = tmp_path / ".hermes" / "profiles" / "vasquez" / "SOUL.md"
    soul.write_text(
        "You are Vasquez, the silent visual gunner on this AgentRTC call. You are not heard.\n\n"
        "You may only call viz_show, viz_select, viz_hover, viz_input, and viz_clear.\n"
        "Never hermes, never delegate_task, never sitrep. Never speak.\n",
        encoding="utf-8",
    )
    ensure_bots()
    text = soul.read_text(encoding="utf-8")
    assert "grok_consult" in text
    assert "You may only call viz_show" not in text


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


def test_bishop_invent_budget_is_generous_and_above_spoken_ripley():
    from hsengine.engine.webrtc_moshi import _ripley_spoken_max_tokens

    n = bishop_max_tokens()
    assert n >= 16384
    assert n > _ripley_spoken_max_tokens()
    _, _, thought_n = bishop_prompt(move="thought")
    _, _, open_n = bishop_prompt(move="open")
    assert thought_n == n
    assert open_n == n


def test_bishop_execute_uses_the_spoken_ceiling(monkeypatch):
    import asyncio

    from hsengine.engine.named_bots import BishopOutcome, ripley_speak_outcome
    from hsengine.engine.webrtc_moshi import _ripley_spoken_max_tokens

    seen: list[int] = []

    def _complete(**k):
        seen.append(int(k.get("max_tokens") or 0))
        return type("R", (), {"text": "hello from the execute pass", "model": "x"})()

    monkeypatch.setattr("hsengine.engine.interactive.complete_cerebras", _complete)
    out = asyncio.run(
        ripley_speak_outcome(
            BishopOutcome(monologue="Speak the thought."),
            session_id="s1",
        )
    )
    assert "hello" in out
    assert seen
    assert all(n >= _ripley_spoken_max_tokens() for n in seen)
    assert all(n > 280 for n in seen)


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


def test_vasquez_run_skips_without_a_frame(monkeypatch):
    from hsengine.engine.named_bots import vasquez_run

    monkeypatch.setattr("hsengine.engine.named_bots.reference_jpeg", lambda: None)
    assert vasquez_run(session_id="s1", reason="user-turn") == ""


def test_vasquez_run_sends_one_jpeg_and_only_viz_tools(monkeypatch):
    from hsengine.engine.named_bots import _VASQUEZ_LAST, vasquez_run
    import hsengine.engine.named_bots as nb

    nb._VASQUEZ_LAST = 0.0
    seen: dict = {}

    def _complete(**k):
        seen.update(k)
        return type("R", (), {"text": "ACTION: NONE", "model": "x"})()

    monkeypatch.setattr("hsengine.engine.named_bots.reference_jpeg", lambda: b"\xff\xd8fakejpeg")
    monkeypatch.setattr("hsengine.engine.interactive.complete_cerebras", _complete)
    out = vasquez_run(session_id="s1", reason="user-turn", narrative="show the chord", spoken="here is the lattice")
    assert seen.get("speak") is False
    assert seen.get("reasoning_effort") == "none"
    assert seen.get("images") == [b"\xff\xd8fakejpeg"]
    names = [t["function"]["name"] for t in (seen.get("tool_defs") or [])]
    assert set(names) <= {
        "viz_show",
        "viz_select",
        "viz_input",
        "viz_clear",
        "viz_hover",
        "grok_consult",
    }
    assert "viz_hover" in names
    assert "grok_consult" in names
    assert "hermes" not in names
    assert "grok_consult" in seen.get("prompt", "")
    assert "show the chord" in seen.get("prompt", "")
    assert out == "ACTION: NONE"
