"""Persona chips stay up for the in-flight turn and tick elapsed time."""
from __future__ import annotations

import time

import pytest

from hsengine.engine.webrtc_activity import (
    ActivityBoard,
    bind,
    format_line,
    paint_activity,
    pulse,
    unbind,
)


def test_format_line_names_the_persona():
    assert format_line("bishop") == "Bishop"
    assert "hermes" in format_line("hermes")
    assert format_line("viz_show").startswith("Vasquez")
    assert format_line("fmp").startswith("Ripley")
    assert format_line("grok_consult").startswith("Bishop")
    assert "consult" in format_line("grok_consult")
    assert format_line("hermes").startswith("Ripley")


def test_pulse_viz_and_fmp_show_on_the_board():
    board = ActivityBoard()
    bind(board)
    try:
        pulse("viz_show")
        assert "Vasquez" in board.get()
        pulse("fmp")
        text = board.get()
        assert "Ripley" in text
        assert "Vasquez" in text
        pulse("bishop")
        assert "Bishop" in board.get()
        pulse("grok_consult")
        assert "Bishop" in board.get()
        assert "consult" in board.get()
    finally:
        unbind(board)


def test_in_flight_slot_does_not_expire_at_three_seconds():
    board = ActivityBoard()
    board.begin("ripley", "thinking")
    board._slots["ripley"].t0 = time.monotonic() - 4
    board._slots["ripley"].last = time.monotonic() - 1
    line = board.get()
    assert "Ripley" in line
    assert "thinking" in line
    assert "4s" in line or "3s" in line


def test_stale_in_flight_reads_as_still():
    board = ActivityBoard()
    board.begin("ripley", "fmp")
    board._slots["ripley"].t0 = time.monotonic() - 12
    board._slots["ripley"].last = time.monotonic() - 8
    line = board.get()
    assert "still" in line
    assert "Ripley" in line


def test_end_clears_after_a_short_hold():
    board = ActivityBoard()
    board.begin("bishop", "invent")
    board.end("bishop")
    assert "Bishop" in board.get()
    board._slots["bishop"].last = time.monotonic() - 3
    assert board.get() == ""


def test_paint_activity_is_top_not_full_frame():
    pytest.importorskip("PIL")
    from PIL import Image

    image = Image.new("RGB", (320, 180), (10, 10, 10))
    paint_activity(image, "Ripley · thinking 4s")
    bottom = image.crop((0, 140, 320, 180))
    assert bottom.getpixel((0, 0)) == (10, 10, 10)
    top = image.crop((0, 0, 320, 50))
    assert top.getbbox() is not None
