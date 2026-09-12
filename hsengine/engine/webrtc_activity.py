"""Burn a one-line 'work is proceeding' chip onto outbound WebRTC video.

Independent of captions (those stay on the bottom). Not a thought dump:
one short confirmation while Bishop, hermes, or a search is in flight.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.activity")

_HOLD_S = 2.8
_MAX_CHARS = 22
_PULSE = frozenset(
    {
        "bishop",
        "hermes",
        "delegate_task",
        "kb_search",
        "web_search",
        "session_search",
        "fmp",
    }
)
_LABEL = {
    "bishop": "Bishop",
    "hermes": "hermes",
    "delegate_task": "delegate",
    "kb_search": "search",
    "web_search": "search",
    "session_search": "search",
    "fmp": "markets",
}

_mu = threading.Lock()
_board: "ActivityBoard | None" = None


class ActivityBoard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._at = 0.0

    def set(self, text: str) -> None:
        cleaned = " ".join((text or "").split())[:_MAX_CHARS]
        with self._lock:
            self._text = cleaned
            self._at = time.monotonic()

    def get(self) -> str:
        with self._lock:
            if not self._text:
                return ""
            if time.monotonic() - self._at > _HOLD_S:
                return ""
            return self._text


def bind(board: ActivityBoard) -> None:
    global _board
    with _mu:
        _board = board


def unbind(board: ActivityBoard | None = None) -> None:
    global _board
    with _mu:
        if board is None or _board is board:
            _board = None


def format_line(kind: str) -> str:
    key = (kind or "").strip().lower().replace(" ", "_")
    label = _LABEL.get(key, "")
    if key == "bishop":
        return "Bishop"
    if not label:
        return "working"
    return f"working · {label}"


def pulse(kind: str) -> None:
    """Show a proceeding chip if *kind* is in the small allow-list."""
    key = (kind or "").strip().lower().replace(" ", "_")
    if key not in _PULSE:
        return
    with _mu:
        board = _board
    if board is None:
        return
    board.set(format_line(key))


def paint_activity(image: Any, text: str) -> Any:
    """One-line chip at the top-left. Does not touch the caption band."""
    from PIL import ImageDraw

    cleaned = " ".join((text or "").split())[:_MAX_CHARS]
    if not cleaned:
        return image
    width, height = image.size
    size = max(14, width // 56)
    font = _font(size)
    draw = ImageDraw.Draw(image)
    pad = max(6, size // 3)
    try:
        bbox = draw.textbbox((0, 0), cleaned, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = size * max(1, len(cleaned)) // 2, size
    box_w = min(width, tw + pad * 2)
    box_h = th + pad * 2
    draw.rectangle((pad, pad, pad + box_w, pad + box_h), fill=(0, 0, 0))
    try:
        draw.text(
            (pad * 2, pad * 1.5),
            cleaned,
            font=font,
            fill=(220, 220, 220),
            stroke_width=1,
            stroke_fill=(0, 0, 0),
        )
    except TypeError:
        draw.text((pad * 2, pad * 1.5), cleaned, font=font, fill=(220, 220, 220))
    return image


def _font(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()
