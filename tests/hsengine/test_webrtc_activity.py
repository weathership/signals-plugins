"""One-line proceeding chip on outbound video. Not a thought dump."""
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


def test_format_line_stays_short():
    assert format_line("bishop") == "Bishop"
    assert format_line("hermes") == "working · hermes"
    assert format_line("kb_search") == "working · search"
    assert format_line("web_search") == "working · search"
    assert len(format_line("delegate_task")) <= 22
    assert format_line("conversation") == "working"


def test_pulse_only_allowlisted_kinds():
    board = ActivityBoard()
    bind(board)
    try:
        pulse("conversation")
        assert board.get() == ""
        pulse("recent_thoughts")
        assert board.get() == ""
        pulse("hermes")
        assert board.get() == "working · hermes"
        pulse("bishop")
        assert board.get() == "Bishop"
    finally:
        unbind(board)


def test_activity_board_expires(monkeypatch):
    board = ActivityBoard()
    board.set("Bishop")
    assert board.get() == "Bishop"
    board._at = time.monotonic() - 10
    assert board.get() == ""


def test_paint_activity_is_top_not_full_frame():
    pytest.importorskip("PIL")
    from PIL import Image

    image = Image.new("RGB", (320, 180), (10, 10, 10))
    paint_activity(image, "working · hermes")
    # Chip lives in the top band; bottom caption region stays untouched.
    bottom = image.crop((0, 140, 320, 180))
    assert bottom.getpixel((0, 0)) == (10, 10, 10)
    top = image.crop((0, 0, 120, 40))
    assert top.getbbox() is not None
