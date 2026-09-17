"""Headless Chromium + CDP screencast: flags, JPEG decode, no Xvfb."""
from __future__ import annotations

import asyncio
import base64
import io
import json

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


def test_bokeh_origins_are_loopback_only():
    hosts = webrtc_bokeh.origin_hosts(5006)
    assert hosts == ["127.0.0.1:5006", "localhost:5006"]
    url = webrtc_bokeh.document_url(5006, "abc123", nonce="n1")
    assert url.startswith("http://127.0.0.1:5006/hv?")
    assert "session=abc123" in url


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


def test_jpeg_screencast_frame_becomes_rgb_image():
    pytest.importorskip("PIL")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (12, 80, 200)).save(buf, format="JPEG", quality=70)
    img = webrtc_cdp.jpeg_to_image(buf.getvalue())
    assert img.size == (64, 36)
    assert img.mode == "RGB"
    assert img.getpixel((2, 2))[2] > 100


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
