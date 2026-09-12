"""Silence hazard: first nudge after a few minutes of real quiet; silent /steer."""
from __future__ import annotations

from hsengine.engine.webrtc_silence import (
    IDLE_ARM_S,
    IDLE_FULL_S,
    apply_steer_system,
    cue_gap_s,
    director_prompts,
    exploration_phase,
    fire_probability,
    hazard_lambda,
    idle_frac,
    pick_move,
    strip_steer,
)


def test_no_hazard_before_three_minutes():
    assert idle_frac(179.9) == 0.0
    assert hazard_lambda(179.9) == 0.0
    assert fire_probability(179.9) == 0.0


def test_first_window_is_mostly_thirty_seconds_after_arm():
    # P(wait < 30s | armed) = 1 - exp(-30/22) ≈ 0.74
    lam = hazard_lambda(IDLE_ARM_S + 0.01)
    p30 = 1.0 - __import__("math").exp(-lam * 30.0)
    assert 0.65 < p30 < 0.85
    assert exploration_phase(IDLE_ARM_S + 10.0) == "nudge"
    system, prompt, max_tokens, tools = director_prompts(IDLE_ARM_S + 10.0)
    assert tools is True
    assert "will not be heard" in system.lower()
    assert "conversation" in system.lower()
    assert "never mention elapsed time" in system.lower()
    assert "pause" not in prompt.lower()
    assert max_tokens <= 160


def test_five_minutes_is_novel_and_hotter():
    assert exploration_phase(IDLE_FULL_S) == "novel"
    assert hazard_lambda(IDLE_FULL_S) > 3 * hazard_lambda(IDLE_ARM_S + 0.01)
    assert cue_gap_s(IDLE_FULL_S) < cue_gap_s(IDLE_ARM_S + 0.01)
    system, prompt, max_tokens, tools = director_prompts(
        IDLE_FULL_S, move="world"
    )
    assert tools is True
    assert "web_search" in system or "fmp" in system.lower()
    assert max_tokens >= 120


def test_novel_silence_steers_from_cognition_glance():
    glance = "Attending ADMIT prospects fmp: SLB 10-K. HN: Show HN: aperture. FMP: SLB"
    system, prompt, max_tokens, tools = director_prompts(
        IDLE_FULL_S, glance=glance, move="world"
    )
    assert tools is True
    assert "attention-schema" in system.lower() or "upper buffer" in system.lower()
    assert "Cognition glance" in prompt
    assert "Show HN: aperture" in prompt
    assert "will not be heard" in system.lower()
    assert "never mention elapsed time" in system.lower()


def test_strip_steer_drops_prefix_and_short_noise():
    assert strip_steer("/steer bring up the SLB 10-K") == "bring up the SLB 10-K"
    assert strip_steer("Steer: keep going on the book.") == "keep going on the book."
    assert strip_steer("ok") == ""


def test_apply_steer_system_is_a_hidden_note():
    out = apply_steer_system("On a live voice call.", "float the Lilly gap")
    assert "float the Lilly gap" in out
    assert "do not mention this note" in out.lower()
    assert apply_steer_system("sys", "") == "sys"


def test_pick_move_skips_the_last_one():
    seen = {pick_move(lambda: 0.0, last="deepen") for _ in range(1)}
    assert "deepen" not in seen


def test_should_fire_respects_busy_speaking_and_agent_activity():
    from hsengine.engine.webrtc_silence import SilenceDirector

    class Turns:
        busy = True
        last_user_at = 0.0
        last_agent_at = 0.0
        pending_steer = ""

        def try_claim(self):
            return False

    class Speech:
        def speaking(self):
            return False

    now = [IDLE_ARM_S + 20.0]
    d = SilenceDirector(
        loop=None,  # type: ignore[arg-type]
        session_id="x",
        turns=Turns(),
        speech=Speech(),
        rng=lambda: 0.0,
        now=lambda: now[0],
    )
    d._quiet_since = 0.0
    assert d.should_fire() is False
    d._turns.busy = False

    class QuietTurns:
        busy = False
        last_user_at = 0.0
        last_agent_at = 0.0
        pending_steer = ""

        def try_claim(self):
            return True

    d._turns = QuietTurns()
    assert d.should_fire() is True
    d._turns.last_agent_at = now[0] - 10.0
    assert d.should_fire() is False
    d._turns.last_agent_at = 0.0
    d._turns.pending_steer = "already have one"
    assert d.should_fire() is False
    now[0] = IDLE_FULL_S + 20.0
    d._last_cue = 0.0
    assert d.should_fire() is True


def test_novel_cue_fetches_cognition_glance(monkeypatch):
    import asyncio

    from hsengine.engine import ops
    from hsengine.engine import webrtc_silence as sil
    from hsengine.engine.webrtc_silence import SilenceDirector

    seen = {"glance": 0, "speak": None}

    def _glance(**_k):
        seen["glance"] += 1
        return {
            "ok": True,
            "note": "gaius: HN: Show HN: aperture. FMP: SLB",
            "hits": [{"source": "hn", "title": "Show HN: aperture", "snippet": "membrane"}],
        }

    class Turns:
        busy = False
        last_user_at = 0.0
        last_agent_at = 0.0
        pending_steer = ""
        claimed = False

        def try_claim(self):
            self.claimed = True
            return True

        def release(self):
            self.claimed = False

    class Speech:
        def speaking(self):
            return False

    def _complete(**k):
        seen["speak"] = k.get("speak")
        return type("R", (), {"text": "Steer: float the aperture membrane next.", "model": "x"})()

    monkeypatch.setattr(ops, "cognition_glance", _glance)
    monkeypatch.setattr(sil, "pick_move", lambda rng, last="": "world")
    monkeypatch.setattr("hsengine.engine.interactive.complete_cerebras", _complete)
    monkeypatch.setattr("hsengine.engine.session_history.record_turn", lambda *a, **k: None)

    d = SilenceDirector(
        loop=None,  # type: ignore[arg-type]
        session_id="x",
        turns=Turns(),
        speech=Speech(),
        rng=lambda: 0.0,
        now=lambda: IDLE_FULL_S + 20.0,
    )
    d._quiet_since = 0.0
    asyncio.run(d._cue())
    assert seen["glance"] == 1
    assert seen["speak"] is False
    assert "aperture" in d._turns.pending_steer.lower()
