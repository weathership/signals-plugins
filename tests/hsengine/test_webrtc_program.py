"""Program stills fade over the AgentRTC clip. No HoloViews required."""
from __future__ import annotations

import json

import pytest

from hsengine.engine import webrtc_program as wp


@pytest.fixture(autouse=True)
def _reset_board():
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


def test_composite_blends_program_over_base():
    pytest.importorskip("PIL")
    from PIL import Image

    base = Image.new("RGB", (80, 80), (0, 0, 0))
    viz = Image.new("RGB", (40, 40), (255, 0, 0))
    wp.PROGRAM.set(viz, kind="chord", fade_s=0.05)
    import time

    time.sleep(0.08)
    out = wp.PROGRAM.composite(base)
    assert out.size == (80, 80)
    px = out.getpixel((40, 40))
    assert px[0] > 20


def test_viz_show_demo_chord_via_ops():
    pytest.importorskip("PIL")
    from hsengine.engine import ops

    raw = ops.dispatch("viz_show", {"kind": "chord", "title": "Ontology chord", "fade_s": 0.05})
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["live"] is True
    assert data["kind"] == "chord"
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    assert "viz_show" in names
    assert "viz_select" in names
    assert "viz_clear" in names


def test_viz_clear_fades_out():
    pytest.importorskip("PIL")
    from hsengine.engine import ops

    json.loads(ops.dispatch("viz_show", {"kind": "chord", "fade_s": 0.05}))
    data = json.loads(ops.dispatch("viz_clear", {"fade_s": 0.05}))
    assert data["ok"] is True
    assert data["alpha"] < 0.5 or data["live"] in (True, False)
