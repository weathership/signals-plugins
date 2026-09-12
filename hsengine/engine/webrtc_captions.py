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


class CaptionBoard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._at = 0.0

    def set(self, text: str) -> None:
        cleaned = " ".join((text or "").split())
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


def paint_caption(image: Any, text: str) -> Any:
    """Draw wrapped caption onto a PIL RGB image; returns the same image."""
    from PIL import ImageDraw

    cleaned = " ".join((text or "").split())
    if not cleaned:
        return image
    width, height = image.size
    size = max(18, width // 42)
    font = _font(size)
    draw = ImageDraw.Draw(image)
    cols = max(16, width // max(10, size // 2))
    lines = textwrap.wrap(cleaned, width=cols)[-2:]
    pad = max(8, size // 4)
    line_h = size + pad
    box_h = line_h * len(lines) + pad
    top = height - box_h - pad
    draw.rectangle((0, top, width, height), fill=(0, 0, 0))
    y = top + pad // 2
    for line in lines:
        try:
            draw.text((pad, y), line, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        except TypeError:
            draw.text((pad, y), line, font=font, fill=(255, 255, 255))
        y += line_h
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
            frame = await self._inner.recv()
            act = activity.get() if activity is not None else ""
            return overlay_frame(frame, board.get(), act)

        def stop(self) -> None:
            try:
                self._inner.stop()
            except Exception:
                pass
            super().stop()

    return CaptionOverlayTrack()
