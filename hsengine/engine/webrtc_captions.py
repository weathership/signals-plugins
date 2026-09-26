"""Burn STT text into outbound WebRTC video frames."""
from __future__ import annotations

import logging
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.captions")

_HOLD_S = 4.0
# ~15 characters a second at 24 kHz, from a measured spoken turn. Used only
# until the utterance's real sample count is known.
_SAMPLES_PER_CHAR_24K = 1800
ROOM_LABEL = "Room"
_CAPTION_LINES = 14
# Lower portion of the frame, kept for the dialog. Leaves the activity chips.
_BAND_FRAC = 0.42
_PLATE_RGBA = (8, 10, 14, 108)


def revealed_words(
    text: str,
    samples_played: int,
    *,
    sample_rate: int,
    samples_total: int = 0,
    closed: bool = False,
) -> str:
    """Words of *text* that the played audio has reached. Empty before audio."""
    words = [w for w in (text or "").split() if w]
    if not words or samples_played <= 0:
        return ""
    if closed and samples_total > 0:
        denom = samples_total
    else:
        estimate = max(1, int(len(text) * _SAMPLES_PER_CHAR_24K * sample_rate / 24000))
        denom = max(samples_total, estimate)
    frac = min(1.0, samples_played / denom)
    if closed and samples_total > 0 and samples_played >= samples_total:
        return " ".join(words)
    n = int(len(words) * frac)
    if n <= 0:
        return ""
    return " ".join(words[:n])


class CaptionBoard:
    """Labeled lines. Room STT expires. The spoken reply reveals with playback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._room_label = ROOM_LABEL
        self._at = 0.0
        self._agent = ""
        self._agent_label = "Agent"
        self._shown_words = 0
        self._progress = lambda: (0, 0, False, 48000)

    def set(self, text: str, *, label: str = ROOM_LABEL) -> None:
        cleaned = " ".join((text or "").split())
        with self._lock:
            self._text = cleaned
            self._room_label = (label or ROOM_LABEL).strip() or ROOM_LABEL
            self._at = time.monotonic()

    def set_agent(self, text: str, *, label: str = "Agent") -> None:
        cleaned = " ".join((text or "").split())
        with self._lock:
            self._agent = cleaned
            self._agent_label = (label or "Agent").strip() or "Agent"
            self._shown_words = 0

    def bind_progress(self, fn: Any) -> None:
        """fn() -> played samples, queued samples, closed, sample rate."""
        with self._lock:
            self._progress = fn

    def note_progress(
        self, *, played: int, queued: int, closed: bool = False, sample_rate: int = 48000
    ) -> None:
        self.bind_progress(lambda: (played, queued, closed, sample_rate))

    def get(self) -> str:
        with self._lock:
            room = ""
            if self._text and time.monotonic() - self._at <= _HOLD_S:
                room = self._text
            agent = self._agent_visible()
            parts: list[str] = []
            if agent:
                parts.append(f"{self._agent_label}: {agent}")
            if room:
                parts.append(f"{self._room_label}: {room}")
            return "\n".join(parts)

    def _agent_visible(self) -> str:
        if not self._agent:
            return ""
        try:
            played, queued, closed, rate = self._progress()
        except Exception:
            return ""
        target = revealed_words(
            self._agent,
            int(played or 0),
            sample_rate=int(rate or 48000),
            samples_total=int(queued or 0),
            closed=bool(closed),
        )
        n = len(target.split()) if target else 0
        if n > self._shown_words:
            self._shown_words = n
        if self._shown_words <= 0:
            return ""
        return " ".join(self._agent.split()[: self._shown_words])


def _font(size: int) -> Any:
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_px(font: Any, text: str) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(text))
    bbox = getattr(font, "getbbox", None)
    if callable(bbox):
        box = bbox(text)
        return float(box[2] - box[0])
    return float(len(text) * 8)


def wrap_to_width(text: str, font: Any, budget: int, max_lines: int) -> list[str]:
    """Wrap on measured glyph width so a line cannot cross the frame."""
    lines: list[str] = []
    for part in (text or "").split("\n"):
        words = part.split()
        if not words:
            continue
        cur = ""
        for word in words:
            trial = word if not cur else f"{cur} {word}"
            if not cur or _text_px(font, trial) <= budget:
                cur = trial
                continue
            lines.append(cur)
            cur = word
        if cur:
            lines.append(cur)
    if max_lines > 0:
        lines = lines[-max_lines:]
    return lines


def paint_caption(image: Any, text: str) -> Any:
    """Draw the dialog on a translucent plate. Returns the same RGB image."""
    from PIL import Image, ImageDraw

    cleaned = (text or "").strip()
    if not cleaned:
        return image
    width, height = image.size
    size = max(18, width // 36)
    font = _font(size)
    pad = max(10, size // 3)
    budget = max(8, width - pad * 2)
    lines = wrap_to_width(cleaned, font, budget, _CAPTION_LINES)
    line_h = size + pad
    band_h = max(int(height * _BAND_FRAC), line_h + pad * 2)
    band_h = min(band_h, max(line_h + pad, height - 56))
    fit = max(1, (band_h - pad * 2) // line_h)
    lines = lines[-min(_CAPTION_LINES, fit) :]
    top = height - band_h
    plate = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rectangle((0, top, width, height), fill=_PLATE_RGBA)
    composed = Image.alpha_composite(image.convert("RGBA"), plate)
    draw = ImageDraw.Draw(composed)
    y = top + pad
    for line in lines:
        try:
            draw.text(
                (pad, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=1,
                stroke_fill=(0, 0, 0, 180),
            )
        except TypeError:
            draw.text((pad, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    image.paste(composed.convert("RGB"))
    return image


def overlay_frame(frame: Any, text: str, activity: str = "") -> Any:
    """Return a new VideoFrame with caption and optional activity chip burned in."""
    if not text and not activity:
        return frame
    try:
        import numpy as np
        from PIL import Image
        import av
    except Exception:
        return frame
    try:
        arr = frame.to_ndarray(format="rgb24")
        image = Image.fromarray(arr)
        if text:
            paint_caption(image, text)
        if activity:
            from hsengine.engine.webrtc_activity import paint_activity

            paint_activity(image, activity)
        out = av.VideoFrame.from_ndarray(np.asarray(image), format="rgb24")
        out.pts = frame.pts
        tb = getattr(frame, "time_base", None)
        if tb is not None:
            out.time_base = tb
        return out
    except Exception:
        log.warning("caption overlay failed", exc_info=True)
        return frame


def caption_track(inner: Any, board: CaptionBoard, activity: Any | None = None) -> Any:
    from aiortc import MediaStreamTrack
    from aiortc.mediastreams import MediaStreamError

    class CaptionOverlayTrack(MediaStreamTrack):
        kind = "video"

        def __init__(self) -> None:
            super().__init__()
            self._inner = inner

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError
            from hsengine.engine.webrtc_program import mix_frame

            frame = await self._inner.recv()
            try:
                # Keep the clip's PTS/time_base. Replacing the RTP clock with
                # a 15 fps rgb24 stream made Listen show a white plate.
                frame = mix_frame(frame)
            except Exception:
                pass
            act = activity.get() if activity is not None else ""
            return overlay_frame(frame, board.get(), act)

        def stop(self) -> None:
            try:
                self._inner.stop()
            except Exception:
                pass
            super().stop()

    return CaptionOverlayTrack()
