"""AgentRTC live viz: Bokeh document × headless Chromium × CDP screencast.

Standalone Signals-hsengine path. Aegir is optional data, not a deploy
requirement. Humans spectate the WebRTC track; agents drive the page via
CDP. No Xvfb, no PipeWire, no operator-profile cookies, no human takeover.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.viz")

_cameras: dict[str, Any] = {}
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _engine_loop() -> asyncio.AbstractEventLoop | None:
    if _loop is not None and _loop.is_running():
        return _loop
    try:
        from hsengine.engine.webrtc_session import HUB

        loop = getattr(HUB, "_loop", None)
        if loop is not None and loop.is_running():
            return loop
    except Exception:
        pass
    return None


def _session_id() -> str:
    try:
        from hsengine.engine.webrtc_session import HUB

        if HUB._pcs:
            return next(iter(HUB._pcs))
    except Exception:
        pass
    return ""


def _run(coro: Any, timeout: float = 90.0) -> Any:
    loop = _engine_loop()
    if loop is None:
        return asyncio.run(coro)
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


def try_live(
    *,
    kind: str = "chord",
    title: str = "",
    highlight: str = "",
    source: str = "",
    data: str = "",
    fade_s: float = 0.7,
) -> dict[str, Any]:
    """Start or retarget the Chromium camera. Falls back to caller on failure."""
    from hsengine.engine.webrtc_cdp import chromium_executable

    if not chromium_executable():
        return {"ok": False, "error": "chromium-missing"}
    sid = _session_id() or "anon"
    try:
        return _run(
            _show_live(
                sid,
                kind=kind,
                title=title,
                highlight=highlight,
                source=source,
                data=data,
                fade_s=fade_s,
            )
        )
    except Exception as e:
        log.exception("holoviews live viz failed")
        return {"ok": False, "error": str(e)[:240]}


async def _show_live(
    session_id: str,
    *,
    kind: str,
    title: str,
    highlight: str,
    source: str,
    data: str,
    fade_s: float,
) -> dict[str, Any]:
    from hsengine.engine import webrtc_bokeh, webrtc_program, webrtc_viz_apps
    from hsengine.engine.webrtc_cdp import CdpCamera

    scene = webrtc_viz_apps.put_scene(
        session_id,
        kind=kind,
        title=title,
        highlight=highlight,
        source=source,
        data=data,
    )
    port = webrtc_bokeh.ensure_server()

    def _push(image: Any) -> None:
        webrtc_program.PROGRAM.replace_image(image)

    cam = _cameras.get(session_id)
    in_place = cam is not None and webrtc_viz_apps.replace_object(session_id, scene)
    if in_place:
        url = webrtc_bokeh.document_url(port, session_id)
        await asyncio.sleep(0.35)
        if cam.latest_image is None and not cam._screencast:
            await cam.start_screencast()
            await cam._wait_first_frame()
    elif cam is None:
        url = webrtc_bokeh.document_url(port, session_id, nonce=uuid.uuid4().hex[:8])
        cam = CdpCamera(session_id)
        _cameras[session_id] = cam
        await cam.start(url, on_image=_push)
    else:
        url = webrtc_bokeh.document_url(port, session_id, nonce=uuid.uuid4().hex[:8])
        await cam.navigate(url)
        if not cam._screencast:
            await cam.start_screencast()
            await cam._wait_first_frame()
    frame = cam.latest_image
    if frame is None:
        raise RuntimeError("HoloViews compositor produced no frame")
    webrtc_program.PROGRAM.set(
        frame,
        title=str(scene.get("title") or ""),
        kind=str(scene.get("kind") or kind),
        fade_s=fade_s,
        meta={
            **scene,
            "backend": "holoviews-cdp",
            "url": url,
            "capture": "Page.startScreencast",
            "frames": cam.frames,
            "in_place": in_place,
        },
    )
    return {"ok": True, **webrtc_program.PROGRAM.status()}


def pointer(*, x: float, y: float, type: str = "mousePressed", button: str = "left") -> dict:
    sid = _session_id()
    cam = _cameras.get(sid)
    if cam is None:
        return {"ok": False, "error": "no live viz camera"}
    try:
        _run(cam.pointer(x=x, y=y, type=type, button=button))
    except Exception as e:
        return {"ok": False, "error": str(e)[:240]}
    return {"ok": True, "x": x, "y": y, "type": type}


async def close_session(session_id: str) -> None:
    from hsengine.engine import webrtc_viz_apps

    webrtc_viz_apps.drop_session(session_id)
    cam = _cameras.pop(session_id, None)
    if cam is None:
        return
    try:
        await cam.close()
    except Exception:
        log.debug("viz camera close", exc_info=True)


def close_session_sync(session_id: str) -> None:
    try:
        _run(close_session(session_id), timeout=8.0)
    except Exception:
        log.debug("viz camera close sync", exc_info=True)
