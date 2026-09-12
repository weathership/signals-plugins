"""Engine-local WebRTC: capability, error mapping, clip resolution."""
from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import grpc
import pytest

from hsengine.config import get_str, reset_config
from hsengine.engine import webrtc_session as ws
from hsengine.engine.generated import hermes_engine_pb2 as pb
from hsengine.engine.server import HermesEngineServicer


class _Ctx:
    def __init__(self) -> None:
        self.code = None
        self.details = None

    def set_code(self, code) -> None:
        self.code = code

    def set_details(self, details) -> None:
        self.details = details


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def test_engine_status_advertises_webrtc():
    reply = asyncio.run(HermesEngineServicer().EngineStatus(pb.EngineStatusRequest(), None))
    caps = list(reply.capabilities)
    assert "agent" in caps
    assert "webrtc" in caps


def test_video_path_uses_configured_file(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"not-a-real-mp4")
    monkeypatch.setenv("HERMES_WEBRTC_VIDEO", str(clip))
    reset_config()
    assert ws.video_path() == clip


def test_video_path_skips_missing_override(tmp_path, monkeypatch):
    missing = tmp_path / "gone.mp4"
    monkeypatch.setenv("HERMES_WEBRTC_VIDEO", str(missing))
    reset_config()
    hit = ws.video_path()
    assert hit is None or hit != missing


def test_webrtc_offer_missing_clip_is_failed_precondition():
    async def _run():
        ctx = _Ctx()
        with patch.object(ws.HUB, "offer", new=AsyncMock(side_effect=FileNotFoundError("no clip"))):
            reply = await HermesEngineServicer().WebRtcOffer(
                SimpleNamespace(sdp="v=0", type="offer"), ctx
            )
        return ctx, reply

    ctx, reply = asyncio.run(_run())
    assert ctx.code == grpc.StatusCode.FAILED_PRECONDITION
    assert "no clip" in (ctx.details or "")
    assert reply.sdp == ""


def test_webrtc_offer_missing_aiortc_is_unimplemented():
    async def _run():
        ctx = _Ctx()
        with patch.object(
            ws.HUB, "offer", new=AsyncMock(side_effect=ws.WebRtcUnavailable("aiortc is not installed"))
        ):
            reply = await HermesEngineServicer().WebRtcOffer(
                SimpleNamespace(sdp="v=0", type="offer"), ctx
            )
        return ctx, reply

    ctx, reply = asyncio.run(_run())
    assert ctx.code == grpc.StatusCode.UNIMPLEMENTED
    assert "aiortc" in (ctx.details or "")
    assert reply.sdp == ""


def test_webrtc_offer_success_returns_answer():
    async def _run():
        ctx = _Ctx()
        payload = {
            "sdp": "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\n",
            "type": "answer",
            "session_id": "abc123",
            "source": "/tmp/demo.mp4",
        }
        with patch.object(ws.HUB, "offer", new=AsyncMock(return_value=payload)):
            return await HermesEngineServicer().WebRtcOffer(
                SimpleNamespace(sdp="v=0", type="offer"), ctx
            ), ctx

    reply, ctx = asyncio.run(_run())
    assert ctx.code is None
    assert reply.type == "answer"
    assert reply.session_id == "abc123"
    assert reply.source.endswith("demo.mp4")
    assert reply.sdp.startswith("v=0")


def test_webrtc_video_config_is_an_mp4_path():
    path = get_str("hermes.engine.webrtc.video")
    assert path.endswith(".mp4")
    assert "webrtc" in path


def _write_tiny_mp4(path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=8000",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not path.is_file():
        pytest.skip(proc.stderr[-400:] if proc.stderr else "ffmpeg could not write a test clip")


@pytest.mark.skipif(importlib.util.find_spec("aiortc") is None, reason="aiortc extra not installed")
def test_offer_answers_a_recvonly_peer(tmp_path, monkeypatch):
    clip = tmp_path / "tiny.mp4"
    _write_tiny_mp4(clip)
    monkeypatch.setenv("HERMES_WEBRTC_VIDEO", str(clip))
    reset_config()
    monkeypatch.setattr(ws, "ICE_SERVERS", [])
    monkeypatch.setattr(ws, "ICE_TIMEOUT_S", 2.0)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr("hsengine.engine.interactive.enter_async", _noop)
    monkeypatch.setattr("hsengine.engine.interactive.leave_async", _noop)
    monkeypatch.setattr("hsengine.engine.webrtc_stt.stt_available", lambda: True)

    async def _run():
        from aiortc import RTCConfiguration, RTCPeerConnection

        client = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
        client.addTransceiver("video", direction="recvonly")
        client.addTransceiver("audio", direction="recvonly")
        offer = await client.createOffer()
        await client.setLocalDescription(offer)
        await ws._ice_complete(client, timeout=2.0)
        try:
            reply = await ws.HUB.offer(client.localDescription.sdp, client.localDescription.type)
            return reply
        finally:
            await client.close()
            for sid in list(ws.HUB._pcs):
                await ws.HUB._drop(sid)

    reply = asyncio.run(_run())
    assert reply["type"] == "answer"
    assert reply["session_id"]
    assert reply["source"] == str(clip)
    assert "m=video" in reply["sdp"]


def test_hangup_unknown_session_is_not_dropped():
    async def _run():
        return await HermesEngineServicer().WebRtcHangup(
            SimpleNamespace(session_id="nope"), _Ctx()
        )

    reply = asyncio.run(_run())
    assert reply.dropped is False


@pytest.mark.skipif(importlib.util.find_spec("aiortc") is None, reason="aiortc extra not installed")
def test_looping_track_pts_keep_increasing(tmp_path, monkeypatch):
    clip = tmp_path / "tiny.mp4"
    _write_tiny_mp4(clip)
    monkeypatch.setenv("HERMES_WEBRTC_VIDEO", str(clip))
    reset_config()

    async def _run():
        video, audio, gate = ws.looping_tracks(clip)
        assert video is not None
        assert audio is None
        assert gate.clip_live() is True
        pts = []
        try:
            for _ in range(15):
                frame = await video.recv()
                if getattr(frame, "pts", None) is not None:
                    pts.append(int(frame.pts))
        finally:
            video.stop()
        return pts, gate

    pts, gate = asyncio.run(_run())
    assert len(pts) >= 12
    assert pts == sorted(pts)
    assert len(set(pts)) == len(pts)
    assert gate.clip_live() is False
