"""Persona activity chips on outbound WebRTC video.

Slots stay up for the whole in-flight turn (not a 3s flash). Elapsed
seconds tick every frame so a hang reads as 'Ripley · fmp · 14s · still'
instead of a blank picture. Independent of captions.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.activity")

_END_HOLD_S = 1.4
_STUCK_S = 6.0
_MAX_AGE_S = 90.0
_MAX_LINE = 42

_WHO = {
    "bishop": "bishop",
    "vasquez": "vasquez",
    "ripley": "ripley",
    "viz_show": "vasquez",
    "viz_select": "vasquez",
    "viz_input": "vasquez",
    "viz_clear": "vasquez",
    "viz_hover": "vasquez",
    "hermes": "ripley",
    "delegate_task": "bishop",
    "kb_search": "ripley",
    "web_search": "ripley",
    "grok_consult": "bishop",
    "session_search": "ripley",
    "fmp": "ripley",
    "conversation": "ripley",
    "thinking": "ripley",
    "speaking": "ripley",
    "on it": "ripley",
    "on_it": "ripley",
}

_LABEL = {
    "bishop": "Bishop",
    "vasquez": "Vasquez",
    "ripley": "Ripley",
}

_COLOR = {
    "bishop": (200, 212, 224),
    "vasquez": (140, 190, 90),
    "ripley": (232, 195, 106),
}

_VERB = {
    "viz_show": "viz",
    "viz_select": "select",
    "viz_input": "pointer",
    "viz_clear": "clear",
    "viz_hover": "hover",
    "kb_search": "search",
    "web_search": "search",
    "session_search": "search",
    "delegate_task": "delegate",
    "fmp": "fmp",
    "grok_consult": "consult",
    "hermes": "hermes",
    "thinking": "thinking",
    "speaking": "speaking",
    "on_it": "on it",
    "on it": "on it",
    "bishop": "invent",
    "vasquez": "glance",
    "ripley": "working",
}

_mu = threading.Lock()
_board: "ActivityBoard | None" = None


@dataclass
class _Slot:
    who: str
    verb: str
    t0: float
    last: float
    done: bool = False


class ActivityBoard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {}

    def begin(self, who: str, verb: str = "") -> None:
        now = time.monotonic()
        key = (who or "ripley").strip().lower()
        with self._lock:
            prev = self._slots.get(key)
            self._slots[key] = _Slot(
                who=key,
                verb=(verb or (prev.verb if prev else "") or "working"),
                t0=prev.t0 if prev and not prev.done else now,
                last=now,
                done=False,
            )

    def end(self, who: str) -> None:
        key = (who or "").strip().lower()
        with self._lock:
            slot = self._slots.get(key)
            if slot is None:
                return
            slot.done = True
            slot.last = time.monotonic()

    def get(self) -> str:
        now = time.monotonic()
        lines: list[str] = []
        with self._lock:
            dead = []
            for key, slot in self._slots.items():
                if slot.done and now - slot.last > _END_HOLD_S:
                    dead.append(key)
                    continue
                if now - slot.t0 > _MAX_AGE_S:
                    dead.append(key)
                    continue
                elapsed = int(now - slot.t0)
                verb = slot.verb or "working"
                stuck = (not slot.done) and (now - slot.last >= _STUCK_S)
                clock = f" {elapsed}s" if elapsed >= 1 else ""
                still = " · still" if stuck else ""
                name = _LABEL.get(slot.who, slot.who.title())
                line = f"{name} · {verb}{clock}{still}"
                lines.append(line[:_MAX_LINE])
            for key in dead:
                self._slots.pop(key, None)
        return "\n".join(lines[:3])


def bind(board: ActivityBoard) -> None:
    global _board
    with _mu:
        _board = board


def unbind(board: ActivityBoard | None = None) -> None:
    global _board
    with _mu:
        if board is None or _board is board:
            _board = None


def _who_verb(kind: str) -> tuple[str, str]:
    key = (kind or "").strip().lower().replace(" ", "_")
    who = _WHO.get(key, "")
    verb = _VERB.get(key, key.replace("_", " ") if key else "working")
    if not who:
        if key.startswith("viz_"):
            who = "vasquez"
        else:
            who = "ripley"
    return who, verb


def format_line(kind: str) -> str:
    who, verb = _who_verb(kind)
    name = _LABEL.get(who, who.title())
    if who == "bishop" and verb in ("invent", "bishop", "working"):
        return "Bishop"
    return f"{name} · {verb}"[:_MAX_LINE]


def begin(who: str, verb: str = "") -> None:
    with _mu:
        board = _board
    if board is None:
        return
    board.begin(who, verb)


def end(who: str) -> None:
    with _mu:
        board = _board
    if board is None:
        return
    board.end(who)


def pulse(kind: str) -> None:
    """Refresh a persona chip. Unknown kinds still show as Ripley working."""
    who, verb = _who_verb(kind)
    begin(who, verb)


def paint_activity(image: Any, text: str) -> Any:
    """Persona chips at the top-right. Does not touch the caption band."""
    from PIL import ImageDraw

    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:3]
    if not lines:
        return image
    width, height = image.size
    size = max(13, width // 58)
    font = _font(size)
    draw = ImageDraw.Draw(image)
    pad = max(6, size // 3)
    line_h = size + pad
    y = pad
    for line in lines:
        who = "ripley"
        low = line.lower()
        if low.startswith("bishop"):
            who = "bishop"
        elif low.startswith("vasquez"):
            who = "vasquez"
        fill = _COLOR.get(who, (220, 220, 220))
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = size * max(1, len(line)) // 2, size
        box_w = min(width - pad * 2, tw + pad * 2)
        box_h = th + pad
        x0 = max(pad, width - box_w - pad)
        draw.rectangle((x0, y, x0 + box_w, y + box_h), fill=(0, 0, 0))
        try:
            draw.text(
                (x0 + pad, y + pad // 3),
                line,
                font=font,
                fill=fill,
                stroke_width=1,
                stroke_fill=(0, 0, 0),
            )
        except TypeError:
            draw.text((x0 + pad, y + pad // 3), line, font=font, fill=fill)
        y += box_h + 2
        if y > height // 2:
            break
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
