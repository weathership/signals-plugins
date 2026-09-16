"""Agent-driven program overlay on the outbound WebRTC video track.

Not a HoloViews dependency. A plugin (or test) pushes RGB frames; this
board fades them over the looping clip. Captions stay on top.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.webrtc.program")

Renderer = Callable[..., tuple[Any, dict]]


class ProgramBoard:
    """One program still, faded onto the clip. Thread-safe for tool + recv."""

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
            live = self._image is not None and (
                self._alpha1 > 0.01 or alpha > 0.01
            )
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
            cur = self._alpha(now)
            self._alpha0 = cur
            self._alpha1 = 0.0
            self._t0 = now
            self._fade_s = max(0.05, float(fade_s))
            self._gen += 1
        log.info("program clear fade_s=%s", fade_s)
        return self.status()

    def active(self) -> bool:
        with self._lock:
            return self._image is not None and (
                self._alpha1 > 0.01 or self._alpha() > 0.01
            )

    def composite(self, base: Any) -> Any:
        """Blend the program still onto a PIL RGB image. No-op when faded out."""
        with self._lock:
            img = self._image
            alpha = self._alpha()
            title = self._title
            if img is None or alpha <= 0.01:
                if img is not None and alpha <= 0.01 and self._alpha1 == 0.0:
                    self._image = None
                return base
            try:
                from PIL import Image
            except Exception:
                return base
            if not isinstance(base, Image.Image):
                return base
            fitted = _fit(img, base.size)
            blended = Image.blend(base, fitted, alpha)
            if title:
                _paint_title(blended, title)
            return blended


def _fit(viz: Any, size: tuple[int, int]) -> Any:
    from PIL import Image

    tw, th = int(size[0]), int(size[1])
    if viz.size == (tw, th):
        return viz.convert("RGB")
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


def mix_frame(frame: Any) -> Any:
    """Blend the program still onto an av.VideoFrame. Identity if idle."""
    if not PROGRAM.active():
        return frame
    try:
        import numpy as np
        from PIL import Image
        import av
    except Exception:
        return frame
    try:
        arr = frame.to_ndarray(format="rgb24")
        mixed = PROGRAM.composite(Image.fromarray(arr))
        out = av.VideoFrame.from_ndarray(np.asarray(mixed), format="rgb24")
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
    fn = _ensure_renderer()
    if fn is None:
        return {"ok": False, "error": "signals-holoviews plugin renderer not found"}
    image, meta = fn(
        kind=kind or "chord",
        title=title,
        highlight=highlight,
        source=source,
        data=data,
    )
    if image is None:
        return {"ok": False, "error": meta.get("error") or "render returned no image", **meta}
    PROGRAM.set(
        image,
        title=title or str(meta.get("title") or ""),
        kind=kind or str(meta.get("kind") or ""),
        fade_s=fade_s,
        meta=meta,
    )
    return {"ok": True, **PROGRAM.status()}


def select(*, node: str = "", fade_s: float = 0.35) -> dict:
    st = PROGRAM.status()
    kind = st.get("kind") or "chord"
    title = st.get("title") or ""
    source = str((st.get("meta") or {}).get("source") or "")
    return show(kind=kind, title=title, highlight=node, source=source, fade_s=fade_s)


def clear(*, fade_s: float = 0.7) -> dict:
    return PROGRAM.clear(fade_s=fade_s)
