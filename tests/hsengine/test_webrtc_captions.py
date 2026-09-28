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

    def slow_stamp(frame, text, activity):
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
