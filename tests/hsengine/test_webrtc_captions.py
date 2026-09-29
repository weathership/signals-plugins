"""Caption paint must not hold the audio sender's clock."""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

av = pytest.importorskip("av")


def test_caption_stamp_yields_the_audio_clock(monkeypatch):
    """A slow caption paint runs off the loop, so a 20 ms audio wait still wakes."""
    from hsengine.engine import webrtc_captions as caps

    def slow_stamp(frame, text, activity, cache=None):
        time.sleep(0.2)
        return frame

    monkeypatch.setattr(caps, "stamp_frame", slow_stamp)

    class Inner:
        kind = "video"
        readyState = "live"

        def stop(self) -> None:
            self.readyState = "ended"

        async def recv(self):
            frame = av.VideoFrame.from_ndarray(
                np.zeros((32, 32, 3), dtype=np.uint8), format="rgb24"
            )
            frame.pts = 0
            return frame

    board = caps.CaptionBoard()
    board.set("the room is talking")

    async def scenario():
        track = caps.caption_track(Inner(), board)
        order: list[str] = []

        async def audio() -> None:
            await asyncio.sleep(0.05)
            order.append("audio")

        task = asyncio.create_task(audio())
        await track.recv()
        order.append("video")
        await task
        track.stop()
        return order

    assert asyncio.run(scenario()) == ["audio", "video"]


def test_stamp_refits_only_when_the_picture_changes(monkeypatch):
    """LANCZOS follows the compositor, not the 24 fps clip clock."""
    pytest.importorskip("PIL")
    from fractions import Fraction

    from PIL import Image

    from hsengine.engine import webrtc_program as wp
    from hsengine.engine.webrtc_captions import stamp_frame

    calls = {"n": 0}
    real = wp.mix_frame

    def counting(frame):
        calls["n"] += 1
        return real(frame)

    monkeypatch.setattr(wp, "mix_frame", counting)
    clip_px = np.zeros((72, 128, 3), dtype=np.uint8)

    def clip(pts: int):
        frame = av.VideoFrame.from_ndarray(clip_px, format="rgb24")
        frame.pts = pts
        frame.time_base = Fraction(1, 90000)
        return frame

    wp.PROGRAM.set(Image.new("RGB", (128, 72), (10, 200, 40)), kind="density", fade_s=0.05)
    cache: dict = {}
    try:
        first = stamp_frame(clip(1), "hello", "", cache)
        second = stamp_frame(clip(2), "hello there", "", cache)
        assert calls["n"] == 1
        assert first.pts == 1 and second.pts == 2
        assert second.time_base == first.time_base
        assert not np.array_equal(
            first.to_ndarray(format="rgb24"), second.to_ndarray(format="rgb24")
        )
        # The clip was black. A cache hit must still be the compositor.
        # Sample above the caption plate; the plate covers the lower band.
        assert int(second.to_ndarray(format="rgb24")[8, 64, 1]) > 150
        wp.PROGRAM.replace_image(Image.new("RGB", (128, 72), (200, 10, 10)))
        third = stamp_frame(clip(3), "hello there", "", cache)
        same = stamp_frame(clip(4), "hello there", "", cache)
        assert calls["n"] == 2
        assert third.pts == 3 and same.pts == 4
        assert int(third.to_ndarray(format="rgb24")[8, 64, 0]) > 150
    finally:
        wp.PROGRAM.clear(fade_s=0.05)
