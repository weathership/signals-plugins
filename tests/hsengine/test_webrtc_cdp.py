"""Headless Chromium + CDP screencast: flags, JPEG decode, no Xvfb."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
import urllib.request

import pytest

from hsengine.engine import webrtc_bokeh, webrtc_cdp


def test_chromium_cmd_is_headless_new_on_loopback():
    cmd = webrtc_cdp.chromium_cmd(
        binary="/nix/store/fake/bin/chromium",
        user_data_dir="/tmp/agentrtc-cdp-test",
        debug_port=9333,
        url="http://127.0.0.1:5006/hv?session=abc",
    )
    joined = " ".join(cmd)
    assert "--headless=new" in cmd
    assert "--remote-debugging-address=127.0.0.1" in cmd
    assert "--remote-debugging-port=9333" in cmd
    assert "http://127.0.0.1:5006/hv?session=abc" in cmd
    assert "--user-data-dir=/tmp/agentrtc-cdp-test" in cmd
    assert "xvfb" not in joined.lower()
    assert "pipewire" not in joined.lower()
    assert "--no-sandbox" in cmd
    assert "--ozone-platform=headless" in cmd
    assert "--ozone-override-screen-size=1280,720" in cmd
    assert "--disable-component-extensions-with-background-pages" in cmd


def test_pick_cdp_page_skips_extension_background():
    pages = [
        {
            "type": "background_page",
            "url": "chrome-extension://nkeimhogjdpnpccoofpliimaahmaaome/background.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:56119/devtools/page/ext",
        },
        {
            "type": "page",
            "url": "http://127.0.0.1:51131/hv?session=abc",
            "webSocketDebuggerUrl": "ws://127.0.0.1:56119/devtools/page/hv",
        },
    ]
    assert webrtc_cdp.pick_cdp_page(pages).endswith("/page/hv")


def test_pick_cdp_page_accepts_kanban():
    pages = [
        {
            "type": "background_page",
            "url": "chrome-extension://nkeimhogjdpnpccoofpliimaahmaaome/background.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:56119/devtools/page/ext",
        },
        {
            "type": "page",
            "url": "http://127.0.0.1:51131/kanban",
            "webSocketDebuggerUrl": "ws://127.0.0.1:56119/devtools/page/kanban",
        },
    ]
    assert webrtc_cdp.pick_cdp_page(pages).endswith("/page/kanban")


def test_bokeh_origins_are_loopback_only():
    hosts = webrtc_bokeh.origin_hosts(5006)
    assert hosts == ["127.0.0.1:5006", "localhost:5006"]
    url = webrtc_bokeh.document_url(5006, "abc123", nonce="n1")
    assert url.startswith("http://127.0.0.1:5006/hv?")
    assert "session=abc123" in url
    kanban = webrtc_bokeh.kanban_url(5006)
    assert kanban == "http://127.0.0.1:5006/kanban"


@pytest.mark.asyncio
async def test_screencast_ack_does_not_wait_for_a_cdp_reply():
    """Ack must not use send() — that deadlocks the reader on the reply."""
    pytest.importorskip("PIL")
    from PIL import Image

    from hsengine.engine.webrtc_cdp import CdpCamera

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (20, 80, 200)).save(buf, format="JPEG", quality=70)
    cam = CdpCamera("t")

    class _WS:
        def __init__(self) -> None:
            self.out: list[str] = []

        async def send(self, raw: str) -> None:
            self.out.append(raw)

    cam._ws = _WS()
    cam._write_lock = asyncio.Lock()
    await asyncio.wait_for(
        cam._on_screencast(
            {"sessionId": "s1", "data": base64.b64encode(buf.getvalue()).decode()}
        ),
        timeout=1.0,
    )
    assert cam.frames == 1
    assert cam.latest_image is not None
    assert any("screencastFrameAck" in m for m in cam._ws.out)


@pytest.mark.asyncio
async def test_screencast_decode_yields_the_audio_clock(monkeypatch):
    """JPEG decode is off the loop, so a short audio wait wakes during it."""
    pytest.importorskip("PIL")
    from PIL import Image

    from hsengine.engine.webrtc_cdp import CdpCamera

    def slow_jpeg(_data: bytes):
        time.sleep(0.2)
        return Image.new("RGB", (8, 8), (20, 80, 200))

    monkeypatch.setattr(webrtc_cdp, "jpeg_to_image", slow_jpeg)
    cam = CdpCamera("t")

    class _WS:
        async def send(self, raw: str) -> None:
            return None

    cam._ws = _WS()
    cam._write_lock = asyncio.Lock()
    order: list[str] = []

    async def audio() -> None:
        await asyncio.sleep(0.05)
        order.append("audio")

    task = asyncio.create_task(audio())
    await cam._on_screencast({"sessionId": "s1", "data": "aaaa"})
    order.append("decode")
    await task
    assert order == ["audio", "decode"]
    assert cam.frames == 1


@pytest.mark.asyncio
async def test_show_live_publishes_the_plot_off_the_audio_loop(monkeypatch):
    """Server start and the scene push must not run on the sender loop."""
    from hsengine.engine import webrtc_bokeh, webrtc_viz, webrtc_viz_apps

    where: dict[str, str] = {}

    def _where() -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return "thread"
        return "loop"

    def ensure_server() -> int:
        where["server"] = _where()
        return 9

    def push_scene(_sid: str, _scene: dict) -> dict:
        where["push"] = _where()
        return {"ok": True, "replaced": False}

    def put_scene(*_a, **_k) -> dict:
        where["scene"] = _where()
        return {"kind": "chord", "title": "t", "nodes": [], "edges": []}

    monkeypatch.setattr(webrtc_bokeh, "ensure_server", ensure_server)
    monkeypatch.setattr(webrtc_bokeh, "push_scene", push_scene)
    monkeypatch.setattr(webrtc_viz_apps, "put_scene", put_scene)

    class _Cam:
        def __init__(self, _sid: str) -> None:
            self.latest_image = None
            self.frames = 0
            self._screencast = False

        async def start(self, _url: str, *, on_image=None) -> None:
            raise RuntimeError("stop-after-schedule")

    monkeypatch.setattr(webrtc_cdp, "CdpCamera", _Cam)
    webrtc_viz._cameras.clear()
    try:
        with pytest.raises(RuntimeError, match="stop-after-schedule"):
            await webrtc_viz._show_live(
                "s",
                kind="chord",
                title="",
                highlight="",
                source="",
                data="",
                fade_s=0.1,
            )
    finally:
        webrtc_viz._cameras.clear()
    assert where == {"server": "thread", "scene": "thread", "push": "thread"}


def test_white_screencast_frame_is_not_accepted():
    pytest.importorskip("PIL")
    from PIL import Image

    from hsengine.engine.webrtc_cdp import CdpCamera, is_blank_plate

    white = Image.new("RGB", (32, 32), (255, 255, 255))
    green = Image.new("RGB", (32, 32), (12, 180, 40))
    assert is_blank_plate(white) is True
    assert is_blank_plate(green) is False
    cam = CdpCamera("t")
    cam._accept_image(green)
    cam._accept_image(white)
    assert cam.frames == 1
    assert cam.latest_image.getpixel((2, 2))[1] > 100


def test_screencast_keepalive_is_a_css_animation():
    assert "@keyframes __hvcast" in webrtc_cdp._CAST_KEEPALIVE_JS
    assert "infinite" in webrtc_cdp._CAST_KEEPALIVE_JS


def test_jpeg_screencast_frame_becomes_rgb_image():
    pytest.importorskip("PIL")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (12, 80, 200)).save(buf, format="JPEG", quality=70)
    img = webrtc_cdp.jpeg_to_image(buf.getvalue())
    assert img.size == (64, 36)
    assert img.mode == "RGB"
    assert img.getpixel((2, 2))[2] > 100


def test_hover_xy_puts_later_lanes_lower():
    from hsengine.engine.webrtc_viz import hover_xy

    x0, y0 = hover_xy(lane="SLB", t=0.2, nodes=["SLB", "HAL", "BKR", "NOV"])
    x1, y1 = hover_xy(lane="NOV", t=0.8, nodes=["SLB", "HAL", "BKR", "NOV"])
    assert x1 > x0
    assert y1 > y0
    assert 0 < x0 < 1280 and 0 < y1 < 720


def test_try_live_without_chromium_is_not_ok(monkeypatch):
    monkeypatch.setattr(webrtc_cdp, "chromium_executable", lambda: None)
    from hsengine.engine import webrtc_viz

    out = webrtc_viz.try_live(kind="chord")
    assert out["ok"] is False
    assert out["error"] == "chromium-missing"


def test_live_screencast_frame_replaces_program_image_without_resetting_fade():
    pytest.importorskip("PIL")
    from PIL import Image

    from hsengine.engine.webrtc_program import PROGRAM

    first = Image.new("RGB", (32, 32), (255, 0, 0))
    second = Image.new("RGB", (32, 32), (0, 255, 0))
    PROGRAM.set(first, kind="chord", fade_s=0.05)
    gen = PROGRAM.generation
    PROGRAM.replace_image(second)
    assert PROGRAM.generation == gen
    assert PROGRAM._image is second


def test_viz_server_is_a_different_process():
    """Plot render must not share the interpreter that sends audio."""
    pytest.importorskip("bokeh")
    webrtc_bokeh.stop_server()
    try:
        port = webrtc_bokeh.ensure_server()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            body = json.loads(resp.read().decode())
        assert body.get("ok") is True
        assert int(body.get("pid") or 0) not in (0, os.getpid())
        pushed = webrtc_bokeh.push_scene("s", {"kind": "chord", "title": "t"})
        assert pushed.get("ok") is True
        assert pushed.get("replaced") is False
        assert int(pushed.get("pid") or 0) not in (0, os.getpid())
    finally:
        webrtc_bokeh.stop_server()
