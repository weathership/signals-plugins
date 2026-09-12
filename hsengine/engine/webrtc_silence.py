"""Silence clock for AgentRTC: a silent Cerebras turn that composes /steer.

True quiet (no user words, no agent TTS) must last a few minutes before we
nudge. The cue is never spoken: it writes a pending steer the next live turn
drains. Director cues never barge TTS or a user turn.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.webrtc.silence")

IDLE_ARM_S = 180.0       # a few minutes of real quiet before the first nudge
IDLE_FULL_S = 300.0      # five minutes → richer look (thoughts / KB / news)
TICK_S = 2.0
LAMBDA_ARM = 1.0 / 22.0  # ~74% of first fires by 30s after arm
LAMBDA_FULL = 1.0 / 7.0
GAP_ARM_S = 90.0
GAP_FULL_S = 45.0

STEER_MOVES = ("deepen", "thought", "kb", "world")

_STEER_RAILS = (
    "You compose a /steer for the next spoken turn of this AgentRTC call. "
    "You will not be heard. Output ONLY the steer text — no /steer prefix, "
    "no quotes, no preamble, no markdown. "
    "Never mention elapsed time, minute marks, slides as a clock, silence, "
    "or that the call paused. Never greet. Never reset the conversation. "
    "One or two sentences of guidance the speaker can follow as a natural "
    "next move. Vary the idea; do not repeat a previous steer."
)


def idle_frac(idle_s: float) -> float:
    if idle_s < IDLE_ARM_S:
        return 0.0
    return min(1.0, (idle_s - IDLE_ARM_S) / (IDLE_FULL_S - IDLE_ARM_S))


def hazard_lambda(idle_s: float) -> float:
    x = idle_frac(idle_s)
    if x <= 0.0:
        return 0.0
    return LAMBDA_ARM + (LAMBDA_FULL - LAMBDA_ARM) * (x * x)


def cue_gap_s(idle_s: float) -> float:
    x = idle_frac(idle_s)
    return GAP_ARM_S + (GAP_FULL_S - GAP_ARM_S) * x


def fire_probability(idle_s: float, dt: float = TICK_S) -> float:
    lam = hazard_lambda(idle_s)
    if lam <= 0.0 or dt <= 0.0:
        return 0.0
    return 1.0 - math.exp(-lam * dt)


def exploration_phase(idle_s: float) -> str:
    if idle_s < IDLE_ARM_S + 60.0:
        return "nudge"
    if idle_s < IDLE_FULL_S:
        return "adjacent"
    return "novel"


def pick_move(rng: Callable[[], float], last: str = "") -> str:
    choices = [m for m in STEER_MOVES if m != last] or list(STEER_MOVES)
    idx = int(rng() * len(choices)) % len(choices)
    return choices[idx]


def strip_steer(text: str) -> str:
    """Keep the steer only. Empty means the silent turn produced nothing."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        first, _, rest = t.partition("\n")
        if first.lower() in ("text", "markdown", "md"):
            t = rest
        t = t.strip("`").strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    low = t.lower()
    for prefix in ("/steer ", "steer:", "the steer:", "steering:"):
        if low.startswith(prefix):
            t = t[len(prefix) :].strip()
            break
    if len(t) < 8:
        return ""
    return t


def apply_steer_system(system: str, steer: str) -> str:
    text = (steer or "").strip()
    if not text:
        return system
    return (
        system.rstrip()
        + "\n\nSteering for this turn only — do not mention this note, do not "
        "greet from it, do not say how long we have been talking:\n"
        + text
    )


def director_prompts(
    idle_s: float,
    glance: str = "",
    *,
    move: str = "deepen",
    last_steer: str = "",
) -> tuple[str, str, int, bool]:
    """system, user prompt, max_tokens, tools — a silent /steer composer."""
    phase = exploration_phase(idle_s)
    glance = " ".join((glance or "").strip().split())
    last = " ".join((last_steer or "").split())
    last_bit = f"Previous steer (do not repeat): {last}\n\n" if last else ""
    if move == "thought":
        system = (
            _STEER_RAILS
            + " Call conversation, then recent_thoughts. If a thought is "
            "adjacent to what you just said, weave it in; otherwise deepen "
            "the last live thread."
        )
        prompt = last_bit + "Compose a steer from the live thread and a thought if one fits."
    elif move == "kb":
        system = (
            _STEER_RAILS
            + " Call conversation, then kb_search once on something from "
            "that thread. Steer with one note-grounded angle."
        )
        prompt = last_bit + "Compose a steer grounded in our notes."
    elif move == "world":
        if glance:
            system = (
                _STEER_RAILS
                + " Call conversation first. You already have a dual-cognition "
                "glance (attention-schema plus live HN/FMP). Steer one novel "
                "thread from that glance only if it can sit next to what you "
                "were just talking about; otherwise deepen. Do not web-search "
                "unless the glance is empty."
            )
            prompt = (
                last_bit
                + "Cognition glance:\n"
                + glance
                + "\n\nCompose a steer from this if it fits the live thread."
            )
        else:
            system = (
                _STEER_RAILS
                + " Call conversation first. Then web_search or fmp once for "
                "something that could sit next to the live thread — HN, a "
                "market, a surprising adjacent fact. Steer with that spark. "
                "Do not announce it as news-check."
            )
            prompt = last_bit + "Compose a steer with one fresh world spark if it fits."
    else:
        system = (
            _STEER_RAILS
            + " Call conversation. Steer that continues the last live thread "
            "with one new angle. Do not web-search."
        )
        prompt = last_bit + "Compose a steer that deepens the last thread."
        if phase == "nudge":
            return system, prompt, 120, True
    return system, prompt, 160, True


class SilenceDirector:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        session_id: str,
        turns: Any,
        speech: Any | None,
        rng: Callable[[], float] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._loop = loop
        self._session_id = session_id
        self._turns = turns
        self._speech = speech
        self._rng = rng or random.random
        self._now = now or time.monotonic
        self._last_cue = 0.0
        self._quiet_since = self._now()
        self._last_move = ""
        self._last_steer = ""

    def note_speech_playing(self, playing: bool) -> None:
        if not playing:
            self._quiet_since = self._now()

    def _idle_s(self) -> float:
        last_user = float(getattr(self._turns, "last_user_at", 0.0) or 0.0)
        last_agent = float(getattr(self._turns, "last_agent_at", 0.0) or 0.0)
        origin = max(last_user, last_agent, self._quiet_since)
        return max(0.0, self._now() - origin)

    def _speaking(self) -> bool:
        sp = self._speech
        if sp is None:
            return False
        fn = getattr(sp, "speaking", None)
        if not callable(fn):
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    def should_fire(self) -> bool:
        if self._speaking() or getattr(self._turns, "busy", False):
            return False
        pending = str(getattr(self._turns, "pending_steer", "") or "")
        idle = self._idle_s()
        if pending and idle < IDLE_FULL_S:
            return False
        if idle < IDLE_ARM_S:
            return False
        if self._now() - self._last_cue < cue_gap_s(idle):
            return False
        return self._rng() < fire_probability(idle, TICK_S)

    async def run(self) -> None:
        log.info("silence director on %s", self._session_id)
        was_playing = False
        try:
            while True:
                await asyncio.sleep(TICK_S)
                playing = self._speaking()
                if playing:
                    now = self._now()
                    if hasattr(self._turns, "last_agent_at"):
                        self._turns.last_agent_at = now
                    was_playing = True
                    continue
                if was_playing:
                    self._quiet_since = self._now()
                    was_playing = False
                if not self.should_fire():
                    continue
                await self._cue()
        except asyncio.CancelledError:
            log.info("silence director off %s", self._session_id)
            raise

    async def _cue(self) -> None:
        claim = getattr(self._turns, "try_claim", None)
        if callable(claim):
            if not claim():
                return
        else:
            if getattr(self._turns, "busy", False):
                return
            self._turns._busy = True
        idle = self._idle_s()
        move = pick_move(self._rng, self._last_move)
        glance = ""
        if move == "world" and exploration_phase(idle) == "novel":
            try:
                from hsengine.engine import ops

                glance = ops.glance_spoken(ops.cognition_glance())
            except Exception:
                log.warning("cognition glance failed", exc_info=True)
        self._last_cue = self._now()
        self._last_move = move
        log.info(
            "silence bishop session=%s idle=%.0fs phase=%s move=%s glance=%s",
            self._session_id,
            idle,
            exploration_phase(idle),
            move,
            "yes" if glance else "no",
        )
        try:
            from hsengine.engine import interactive, session_history
            from hsengine.engine.named_bots import bishop_run

            outcome = await asyncio.to_thread(
                bishop_run,
                session_id=self._session_id,
                idle_s=idle,
                last_steer=self._last_steer,
                move=move,
                glance=glance,
            )
            if outcome.steer:
                self._last_steer = outcome.steer
                self._turns.pending_steer = outcome.steer
                log.info(
                    "bishop steer ready session=%s %r",
                    self._session_id,
                    outcome.steer[:160],
                )
            if outcome.monologue:
                spoken = interactive.spoken_text(outcome.monologue)
                if spoken:
                    interactive._speak_cerebras(spoken)
                    session_history.record_turn(
                        self._session_id, assistant=spoken, model="ripley"
                    )
                    log.info("bishop monologue spoken session=%s", self._session_id)
        except Exception:
            log.exception("bishop silent turn failed")
        finally:
            rel = getattr(self._turns, "release", None)
            if callable(rel):
                rel()
            else:
                self._turns._busy = False
