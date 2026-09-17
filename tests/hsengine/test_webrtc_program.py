"""Live compositor pixels on the AgentRTC clip clock. No HoloViews required."""
from __future__ import annotations

import json

import pytest

from hsengine.engine import webrtc_program as wp


@pytest.fixture(autouse=True)
def _reset_board(monkeypatch):
    monkeypatch.setattr(
        "hsengine.engine.webrtc_cdp.chromium_executable", lambda: None
    )
    wp.PROGRAM.clear(fade_s=0.05)
    wp.PROGRAM._image = None
    wp.PROGRAM._alpha0 = 0.0
    wp.PROGRAM._alpha1 = 0.0
    yield
    wp.PROGRAM.clear(fade_s=0.05)
    wp.PROGRAM._image = None


def test_program_set_is_live_immediately_with_zero_fade():
    pytest.importorskip("PIL")
    from PIL import Image

    img = Image.new("RGB", (64, 64), (200, 40, 40))
    st = wp.PROGRAM.set(img, title="demo", kind="chord", fade_s=0.05)
    assert st["live"] is True
    assert st["kind"] == "chord"
    assert wp.PROGRAM.active() is True


def test_composite_is_the_figure_not_a_blend():
    pytest.importorskip("PIL")
    from PIL import Image

    base = Image.new("RGB", (80, 80), (0, 0, 0))
    viz = Image.new("RGB", (80, 80), (255, 0, 0))
    wp.PROGRAM.set(viz, kind="density", fade_s=10.0)
    out = wp.PROGRAM.composite(base)
    assert out.size == (80, 80)
    px = out.getpixel((40, 40))
    assert px[0] > 200


def test_mix_frame_stamps_compositor_on_clip_clock():
    pytest.importorskip("av")
    pytest.importorskip("PIL")
    pytest.importorskip("numpy")
    from fractions import Fraction

    import av
    import numpy as np
    from PIL import Image

    clip = av.VideoFrame.from_ndarray(
        np.zeros((72, 128, 3), dtype=np.uint8), format="rgb24"
    )
    clip.pts = 9000
    clip.time_base = Fraction(1, 90000)
    viz = Image.new("RGB", (128, 72), (10, 200, 40))
    wp.PROGRAM.set(viz, kind="density", fade_s=0.05)
    out = wp.mix_frame(clip)
    assert out.pts == 9000
    assert out.time_base == clip.time_base
    arr = out.to_ndarray(format="rgb24")
    assert int(arr[36, 64, 1]) > 150


def test_replace_image_drops_white_plates():
    pytest.importorskip("PIL")
    from PIL import Image

    first = Image.new("RGB", (32, 32), (0, 180, 40))
    white = Image.new("RGB", (32, 32), (255, 255, 255))
    wp.PROGRAM.set(first, kind="density", fade_s=0.05)
    wp.PROGRAM.replace_image(white)
    assert wp.PROGRAM._image is first


def test_viz_show_without_chromium_is_an_error():
    from hsengine.engine import ops

    raw = ops.dispatch("viz_show", {"kind": "chord", "title": "Ontology chord", "fade_s": 0.05})
    data = json.loads(raw)
    assert data["ok"] is False
    assert "chromium" in (data.get("error") or "").lower()
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    assert "viz_show" in names


def test_viz_clear_is_ok_when_idle():
    from hsengine.engine import ops

    data = json.loads(ops.dispatch("viz_clear", {"fade_s": 0.05}))
    assert data["ok"] is True
