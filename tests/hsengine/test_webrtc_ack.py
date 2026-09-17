"""Spoken ack space is large; consecutive lines are not a catchphrase."""
from __future__ import annotations

import random
import re

from datetime import datetime, timezone

from hsengine.engine.webrtc_ack import _recent, ack_line, press_return_line, space_size


def test_ack_space_is_thousands():
    assert space_size() >= 1000


def test_ack_lines_are_short_spoken_english():
    rng = random.Random(7)
    lines = [ack_line("show the SLB filings", rng=rng) for _ in range(80)]
    assert all(8 <= len(ln) <= 160 for ln in lines)
    assert all(ln[0].isupper() or ln[0].isdigit() for ln in lines)
    assert all(ln[-1] in ".!?" for ln in lines)
    assert all(len(ln.split()) <= 22 for ln in lines)


def test_two_hundred_draws_are_mostly_unique():
    rng = random.Random(11)
    _recent.clear()
    lines = [ack_line(rng=rng) for _ in range(400)]
    assert len(set(lines)) >= 250


def test_hook_from_utterance_sometimes_lands():
    rng = random.Random(3)
    _recent.clear()
    hits = [ack_line("pull the SLB 8-K", rng=rng) for _ in range(80)]
    assert any("SLB" in h or "8-K" in h or "8-k" in h.lower() for h in hits)


def test_press_return_states_the_clock():
    rng = random.Random(0)
    now = datetime(2026, 9, 17, 3, 42, 7, tzinfo=timezone.utc)
    line = press_return_line(now=now, rng=rng)
    assert "03:42:07" in line
    assert "Press return" in line
    assert line[0].isupper() or line[0].isdigit()


def test_no_immediate_repeat():
    rng = random.Random(99)
    _recent.clear()
    a = ack_line(rng=rng)
    b = ack_line(rng=rng)
    assert a != b


def test_default_acks_are_not_about_the_tape():
    rng = random.Random(1)
    _recent.clear()
    lines = [ack_line(rng=rng) for _ in range(80)]
    assert not any(re.search(r"\btape\b", ln, re.I) for ln in lines)


def test_film_register_shows_up():
    rng = random.Random(5)
    _recent.clear()
    blob = " ".join(ack_line(rng=rng) for _ in range(150)).lower()
    markers = (
        "game",
        "secrets",
        "passport",
        "planet",
        "choose life",
        "holiday",
        "jack",
        "true sentence",
        "fight",
        "feast",
        "joshua",
        "gibson",
        "gigawatts",
        "streams",
        "clever",
        "horizon",
        "butts",
        "ghost",
        "scott",
        "return",
        "sun",
        "dissolve",
        "216",
        "pie",
        "max",
    )
    assert sum(1 for m in markers if m in blob) >= 3
