"""Live compositor pixels on the outbound WebRTC video track.

The looping clip is the RTP clock. While a HoloViews camera is live,
outbound video pixels are that compositor — not a still faded over
demo.mp4. Captions stay on top.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.webrtc.program")

Renderer = Callable[..., tuple[Any, dict]]


class ProgramBoard:
    """Latest compositor frame for the video track. Thread-safe for tool + recv."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._image: Any | None = None
        self._title = ""
        self._kind = ""
        self._meta: dict = {}
        self._alpha0 = 0.0
        self._alpha1 = 0.0
        self._t0 = 0.0
        self._fade_s = 0.7
        self._gen = 0

    def _alpha(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        dur = max(0.05, float(self._fade_s))
        t = min(1.0, max(0.0, (now - self._t0) / dur))
        return self._alpha0 + (self._alpha1 - self._alpha0) * t

    @property
    def generation(self) -> int:
        with self._lock:
            return self._gen

    def status(self) -> dict:
        with self._lock:
            alpha = self._alpha()
            live = self._image is not None and self._alpha1 > 0.01
            return {
                "ok": True,
                "live": live,
                "kind": self._kind,
                "title": self._title,
                "alpha": round(alpha, 3),
                "generation": self._gen,
                "meta": dict(self._meta),
            }

    def set(
        self,
        image: Any,
        *,
        title: str = "",
        kind: str = "",
        fade_s: float = 0.7,
        meta: dict | None = None,
    ) -> dict:
        with self._lock:
            now = time.monotonic()
            cur = self._alpha(now)
            self._image = image
            self._title = (title or "").strip()
            self._kind = (kind or "").strip()
            self._meta = dict(meta or {})
            self._alpha0 = cur
            self._alpha1 = 1.0 if image is not None else 0.0
            self._t0 = now
            self._fade_s = max(0.05, float(fade_s))
            self._gen += 1
            gen = self._gen
        log.info("program set kind=%s title=%r gen=%s", kind or "-", title[:80], gen)
        return self.status()

    def clear(self, *, fade_s: float = 0.7) -> dict:
        with self._lock:
            now = time.monotonic()
            self._image = None
            self._alpha0 = 0.0
            self._alpha1 = 0.0
            self._t0 = now
            self._fade_s = max(0.05, float(fade_s))
            self._gen += 1
        log.info("program clear fade_s=%s", fade_s)
        return self.status()

    def active(self) -> bool:
        with self._lock:
            return self._image is not None and self._alpha1 > 0.01

    def replace_image(self, image: Any) -> None:
        """Swap the live compositor frame without resetting fade."""
        if image is None:
            return
        try:
            from hsengine.engine.webrtc_cdp import is_blank_plate

            if is_blank_plate(image):
                return
        except Exception:
            pass
        with self._lock:
            self._image = image

    def composite(self, base: Any) -> Any:
        """Fit the live frame onto a PIL RGB canvas. No-op when idle."""
        with self._lock:
            img = self._image
            title = self._title
            if img is None or self._alpha1 <= 0.01:
                if self._alpha1 <= 0.01:
                    self._image = None
                return base
            try:
                from PIL import Image
            except Exception:
                return base
            if not isinstance(base, Image.Image):
                return base
            fitted = _fit(img, base.size)
            if title:
                _paint_title(fitted, title)
            return fitted


def _fit(viz: Any, size: tuple[int, int]) -> Any:
    from PIL import Image

    tw, th = int(size[0]), int(size[1])
    if viz.size == (tw, th):
        return viz.convert("RGB").copy()
    vw, vh = viz.size
    scale = min(tw / max(1, vw), th / max(1, vh))
    nw = max(1, int(vw * scale))
    nh = max(1, int(vh * scale))
    resized = viz.convert("RGB").resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), (11, 11, 18))
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def _paint_title(image: Any, title: str) -> None:
    from PIL import ImageDraw, ImageFont

    text = " ".join((title or "").split())[:80]
    if not text:
        return
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22
        )
    except Exception:
        font = ImageFont.load_default()
    pad = 10
    draw.rectangle((0, 0, image.size[0], 36), fill=(11, 11, 18))
    try:
        draw.text((pad, 6), text, font=font, fill=(232, 236, 244))
    except TypeError:
        draw.text((pad, 6), text, font=font, fill=(232, 236, 244))


PROGRAM_FPS = 15


def alpha() -> float:
    return PROGRAM._alpha()


def compositor_image() -> Any | None:
    """Latest HoloViews RGB, fitted to 1280×720, or None."""
    with PROGRAM._lock:
        img = PROGRAM._image
        title = PROGRAM._title
        live = img is not None and PROGRAM._alpha1 > 0.01
    if not live:
        return None
    fitted = _fit(img, (1280, 720))
    if title:
        _paint_title(fitted, title)
    return fitted


def image_to_video_frame(image: Any, *, pts: int, time_base: Any) -> Any:
    import numpy as np
    import av

    frame = av.VideoFrame.from_ndarray(np.asarray(image.convert("RGB")), format="rgb24")
    frame.pts = pts
    frame.time_base = time_base
    return frame


def mix_frame(frame: Any) -> Any:
    """Stamp live compositor pixels onto the clip RTP clock. Identity if idle."""
    if not PROGRAM.active():
        return frame
    try:
        import numpy as np
        import av
    except Exception:
        return frame
    with PROGRAM._lock:
        img = PROGRAM._image
        title = PROGRAM._title
        live = img is not None and PROGRAM._alpha1 > 0.01
    if not live:
        return frame
    try:
        try:
            w = int(frame.width)
            h = int(frame.height)
        except Exception:
            arr = frame.to_ndarray(format="rgb24")
            h, w = int(arr.shape[0]), int(arr.shape[1])
        fitted = _fit(img, (w, h))
        if title:
            _paint_title(fitted, title)
        out = av.VideoFrame.from_ndarray(np.asarray(fitted), format="rgb24")
        out.pts = frame.pts
        tb = getattr(frame, "time_base", None)
        if tb is not None:
            out.time_base = tb
        return out
    except Exception:
        log.debug("program mix failed", exc_info=True)
        return frame


_renderer: Renderer | None = None
PROGRAM = ProgramBoard()


def register_renderer(fn: Renderer | None) -> None:
    global _renderer
    _renderer = fn


def _ensure_renderer() -> Renderer | None:
    global _renderer
    if _renderer is not None:
        return _renderer
    fn = _load_plugin_renderer()
    if fn is not None:
        _renderer = fn
    return _renderer


def _load_plugin_renderer() -> Renderer | None:
    import importlib.util
    import os
    from pathlib import Path

    roots: list[Path] = []
    env = (os.environ.get("SIGNALS_PLUGINS") or "").strip()
    if env:
        roots.append(Path(env) / "plugins" / "signals-holoviews")
    roots.append(Path(__file__).resolve().parents[2] / "plugins" / "signals-holoviews")
    for root in roots:
        path = root / "render.py"
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("signals_holoviews_render", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "render_scene", None)
        if callable(fn):
            log.info("program renderer loaded from %s", path)
            return fn
    return None


def show(
    *,
    kind: str = "chord",
    title: str = "",
    highlight: str = "",
    source: str = "",
    data: str = "",
    fade_s: float = 0.7,
) -> dict:
    from hsengine.engine import webrtc_viz

    live = webrtc_viz.try_live(
        kind=kind,
        title=title,
        highlight=highlight,
        source=source,
        data=data,
        fade_s=fade_s,
    )
    if live.get("ok"):
        return live
    return {
        "ok": False,
        "error": live.get("error") or "HoloViews Chromium compositor failed",
    }


def select(*, node: str = "", fade_s: float = 0.35) -> dict:
    st = PROGRAM.status()
    kind = st.get("kind") or "chord"
    title = st.get("title") or ""
    source = str((st.get("meta") or {}).get("source") or "")
    return show(kind=kind, title=title, highlight=node, source=source, fade_s=fade_s)


def clear(*, fade_s: float = 0.7) -> dict:
    return PROGRAM.clear(fade_s=fade_s)
