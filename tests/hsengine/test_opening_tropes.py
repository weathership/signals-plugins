"""Connect rumination frames are rejected, not only discouraged."""
from __future__ import annotations

from hsengine.engine.opening_tropes import opening_tropes, tropes_retry_line
from hsengine.engine.named_bots import bishop_run, ripley_opening_prompts
from hsengine.engine.named_bots import BishopOutcome


def test_detects_sitting_with_and_returning_thread():
    hits = opening_tropes(
        "Good afternoon. I've been sitting with something that keeps surfacing for me."
    )
    assert hits
    assert any("sitting" in h.lower() for h in hits)
    hits2 = opening_tropes(
        "There's a thread I'm returning to — the same sensors as last time."
    )
    assert hits2
    clean = opening_tropes(
        "Good afternoon. Hospital surfaces keep showing up as sensors. What's on your mind?"
    )
    assert not any("sitting" in h.lower() for h in clean)
    assert opening_tropes("Good afternoon. The light's gone gold. What's up?") == []


def test_retry_line_names_the_hit():
    line = tropes_retry_line(["I've been sitting with"])
    assert "sitting" in line.lower()
    assert "Rewrite" in line


def test_bishop_open_retries_once_on_tropes(monkeypatch):
    calls: list[str] = []

    def _complete(**k):
        calls.append(k["prompt"])
        if len(calls) == 1:
            text = (
                "STEER: NONE\n"
                "MONOLOGUE: I've been sitting with something that keeps surfacing."
            )
        else:
            text = (
                "STEER: NONE\n"
                "MONOLOGUE: Hospital surfaces keep showing up as sensors. What's on your mind?"
            )
        return type("R", (), {"text": text, "model": "x"})()

    monkeypatch.setattr("hsengine.engine.interactive.complete_cerebras", _complete)
    out = bishop_run(session_id="s1", move="open")
    assert len(calls) == 2
    assert "sitting" in calls[1].lower() or "Rewrite" in calls[1]
    assert "sitting" not in (out.monologue or "").lower()
    assert "Hospital surfaces" in out.monologue


def test_ripley_opening_prompts_ban_rumination_frames():
    system, user = ripley_opening_prompts(
        BishopOutcome(monologue="Hospital surfaces as sensors.")
    )
    blob = (system + "\n" + user).lower()
    assert "sitting with" in blob or "rumination" in blob
    assert "Hospital surfaces" in user
