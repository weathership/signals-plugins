"""Headless Chromium + CDP screencast: flags, JPEG decode, no Xvfb."""
from __future__ import annotations

import io

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


def test_bokeh_origins_are_loopback_only():
    hosts = webrtc_bokeh.origin_hosts(5006)
    assert hosts == ["127.0.0.1:5006", "localhost:5006"]
    url = webrtc_bokeh.document_url(5006, "abc123", nonce="n1")
    assert url.startswith("http://127.0.0.1:5006/hv?")
    assert "session=abc123" in url


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
