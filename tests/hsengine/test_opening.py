"""Opening catalog (textproto) + sequence sampler + listener clock."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from hsengine.engine.opening import (
    bishop_handoff,
    compose_opening,
    facts_from_pack,
    load_catalog,
    local_clock,
    sample_sequence,
    split_spoken_beats,
)


def test_catalog_is_textproto_and_iterable():
    cat = load_catalog()
    ids = [g.id for g in cat.gesture]
    assert "greet_tod" in ids
    assert "headline" in ids
    assert "pause" in ids
    assert cat.sequence.max_gestures >= 2
    assert any(p.after == 1 for p in cat.sequence.pause_after)


def test_local_clock_uses_iana_zone():
    listener = local_clock(
        "America/Los_Angeles",
        now=datetime(2026, 9, 12, 7, 15, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    assert listener.timezone == "America/Los_Angeles"
    assert listener.tod == "morning"
    assert listener.hour == 7
    night = local_clock(
        "America/Los_Angeles",
        now=datetime(2026, 9, 12, 22, 40, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    assert night.tod == "night"


def test_headline_eligible_when_fresh_thoughts():
    cat = load_catalog()
    facts = facts_from_pack(
        {
            "workspace": "fresh",
            "thoughts_spoken": "The Lilly 10-K is still the live thread on the board.",
            "agenda_spoken": "",
        },
        returning=False,
    )
    assert "has_fresh" in facts and "has_thoughts" in facts
    seqs = [sample_sequence(cat, facts, rng=lambda: 0.01, recent=[]) for _ in range(1)]
    assert seqs[0]
    assert "welcome_back" not in seqs[0]


def test_welcome_back_only_when_returning():
    cat = load_catalog()
    facts = facts_from_pack({"workspace": "fresh", "thoughts_spoken": "x" * 30}, returning=True)
    seq = sample_sequence(cat, facts, rng=lambda: 0.0, recent=[])
    # rng 0 picks the first remaining weighted id; welcome_back is eligible
    assert "welcome_back" in {
        g.id for g in cat.gesture if "returning" in g.when
    }
    cold = facts_from_pack({"workspace": "fresh", "thoughts_spoken": "x" * 30}, returning=False)
    cold_seq = sample_sequence(cat, cold, rng=lambda: 0.0, recent=[])
    assert "welcome_back" not in cold_seq


def test_pause_can_follow_first_gesture():
    cat = load_catalog()
    facts = frozenset({"always", "has_fresh", "has_thoughts"})
    seq = sample_sequence(cat, facts, rng=lambda: 0.0, recent=[])
    assert "pause" in seq
    assert seq.index("pause") >= 1


def test_anti_repeat_downweights_last_sequence():
    from hsengine.engine.opening import _anti_repeat

    assert _anti_repeat(1.15, "greet_tod", [["greet_tod"]]) < 0.4
    assert _anti_repeat(1.15, "offer_floor", [["greet_tod"]]) == 1.15


def test_handoff_names_timezone_and_sequence():
    cat = load_catalog()
    listener = local_clock("America/New_York", now=datetime(2026, 9, 12, 19, 0, tzinfo=ZoneInfo("America/New_York")))
    text = bishop_handoff(
        ["greet_tod", "pause", "headline"],
        listener=listener,
        facts=frozenset({"always", "has_fresh", "has_thoughts"}),
        glance="Latest thoughts brief: the Lilly gap",
        catalog=cat,
    )
    assert "America/New_York" in text
    assert "evening" in text
    assert "greet_tod → pause → headline" in text
    assert "[pause]" in text
    assert "Lilly" in text


def test_split_spoken_beats():
    assert split_spoken_beats("Hi. [pause] The 10-K is still there.") == [
        "Hi.",
        "The 10-K is still there.",
    ]


def test_sample_sequence_pins_headline_when_zettel():
    cat = load_catalog()
    facts = frozenset({"always", "has_zettel", "has_fresh"})
    seq = sample_sequence(cat, facts, rng=lambda: 0.9, recent=[["greet_tod", "pause"]])
    assert "headline" in seq
    content = [g for g in seq if g != "pause"]
    assert content[0] in {"headline", "greet_tod"}
    if content[0] == "greet_tod":
        assert content[1] == "headline"
    else:
        assert content[0] == "headline"


def test_compose_opening_handoff_uses_zettel_entropy(monkeypatch, tmp_path):
    from hsengine.engine import opening as op

    monkeypatch.setattr(op, "_ledger_path", lambda: tmp_path / "seq.jsonl")
    monkeypatch.setattr(op, "_returning", lambda exclude="": False)
    monkeypatch.setattr(
        op,
        "_fresh_zettel_glance",
        lambda: "just now wiki/scratch/x.md (Acquaintance): Atiq on attention as agency.",
    )
    plan = compose_opening(
        pack={"workspace": "empty", "thoughts_spoken": "", "agenda_spoken": ""},
        timezone="America/Denver",
        session_id="z1",
        returning=False,
        rng=lambda: 0.5,
    )
    assert "has_zettel" in plan.facts
    assert "headline" in plan.sequence
    assert "opening's entropy" in plan.handoff
    assert "USER-PROVIDED" in plan.handoff
    assert "not lattice" in plan.handoff.lower() or "not interior" in plan.handoff.lower()
    assert "Atiq" in plan.handoff
    assert "required entropy" in plan.handoff


def test_compose_opening_handoff_for_bishop(monkeypatch, tmp_path):
    from hsengine.engine import opening as op

    monkeypatch.setattr(op, "_ledger_path", lambda: tmp_path / "seq.jsonl")
    monkeypatch.setattr(op, "_returning", lambda exclude="": False)
    monkeypatch.setattr(op, "_fresh_zettel_glance", lambda: "")
    plan = compose_opening(
        pack={
            "workspace": "fresh",
            "thoughts_spoken": "The Lilly 10-K is the live thread this morning.",
            "agenda_spoken": "",
        },
        timezone="America/Los_Angeles",
        session_id="abc",
        returning=False,
        rng=lambda: 0.0,
    )
    assert plan.listener.timezone == "America/Los_Angeles"
    assert plan.handoff
    assert "Opening sequence" in plan.handoff
    assert "greet_tod" in plan.sequence or plan.sequence


def test_wants_mediation_for_whats_next():
    from hsengine.engine.opening import wants_mediation

    assert wants_mediation("what's up next")
    assert wants_mediation("What's next on the agenda")
    assert wants_mediation("how's it going")
    assert not wants_mediation("tell me about the Lilly 10-K")


def test_next_lane_includes_whats_next_not_greet():
    cat = load_catalog()
    facts = frozenset({"always", "has_agenda"})
    seq = sample_sequence(cat, facts, lane="next", rng=lambda: 0.0, recent=[])
    assert "greet_tod" not in seq
    assert "whats_next" in seq or "offer_floor" in seq


def test_bishop_open_prompt_includes_handoff():
    from hsengine.engine.named_bots import bishop_prompt

    _, prompt, _ = bishop_prompt(
        move="open",
        handoff="Listener: timezone=America/Los_Angeles tod=morning\nOpening sequence: greet_tod → pause",
    )
    assert "America/Los_Angeles" in prompt
    assert "Handoff" in prompt
    assert "formula" in prompt.lower() or "two-ideas" in prompt


def test_bishop_next_prompt_is_not_a_scheduler():
    from hsengine.engine.named_bots import bishop_prompt

    _, prompt, _ = bishop_prompt(move="next", handoff="Opening sequence: whats_next → offer_floor")
    assert "whats_next" in prompt
    assert "not a briefing" in prompt.lower() or "scheduler" in prompt.lower()
