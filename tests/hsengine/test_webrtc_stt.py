"""WebRTC caption overlay and Kyutai STT helpers. No whisper path."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hsengine.engine.generated import hermes_engine_pb2 as pb
from hsengine.engine.server import HermesEngineServicer
from hsengine.engine.webrtc_captions import CaptionBoard, paint_caption
from hsengine.engine.webrtc_moshi import (
    MoshiCaptioner,
    TurnTaker,
    _TURN_QUIET_S,
    _ripley_spoken_max_tokens,
    utterance_ready,
)
from hsengine.engine.webrtc_stt import frame_to_mono16k, stt_available


def test_engine_status_omits_stt_when_moshi_is_down():
    with patch("hsengine.engine.webrtc_stt.stt_available", return_value=False):
        reply = asyncio.run(HermesEngineServicer().EngineStatus(pb.EngineStatusRequest(), None))
    assert "stt" not in list(reply.capabilities)
    assert "webrtc" in list(reply.capabilities)


def test_engine_status_lists_stt_when_moshi_is_up():
    with patch("hsengine.engine.webrtc_stt.stt_available", return_value=True):
        reply = asyncio.run(HermesEngineServicer().EngineStatus(pb.EngineStatusRequest(), None))
    assert "stt" in list(reply.capabilities)


def test_stt_available_is_the_live_moshi_probe():
    with patch("hsengine.engine.webrtc_stt.moshi_serving", return_value=False):
        assert stt_available() is False
    with patch("hsengine.engine.webrtc_stt.moshi_serving", return_value=True):
        assert stt_available() is True


def test_moshi_captioner_joins_word_events():
    board = CaptionBoard()
    cap = MoshiCaptioner(board, max_words=4)
    assert cap.on_message({"type": "Word", "text": "hello"}) == "hello"
    assert cap.on_message({"type": "Word", "text": "there"}) == "hello there"
    cap.on_message({"type": "Word", "text": "one"})
    cap.on_message({"type": "Word", "text": "two"})
    cap.on_message({"type": "Word", "text": "three"})
    assert board.get() == "there one two three"
    assert cap.on_message({"type": "Step", "prs": [0.1, 0.2]}) is None


def test_user_turn_quiet_gap_is_three_seconds():
    assert _TURN_QUIET_S == 3.0


def test_utterance_ready_needs_enough_text():
    assert utterance_ready(["hi"]) is None
    assert utterance_ready(["hello", "there"]) == "hello there"


class _NoopTask:
    def cancel(self):
        return None


class _NoopLoop:
    def create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass
        return _NoopTask()


def test_tts_echo_does_not_interrupt_a_short_fragment():
    from hsengine.engine.webrtc_mix import SpeechBoard

    board = SpeechBoard()
    board.push([0.2] * 480, sample_rate=48000)
    taker = TurnTaker(_NoopLoop(), speech=board)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    taker.on_word("um")
    assert interrupted == []
    assert taker._words == ["um"]


def test_real_user_speech_still_barges_in_over_tts():
    from hsengine.engine.webrtc_mix import SpeechBoard

    board = SpeechBoard()
    board.push([0.2] * 480, sample_rate=48000)
    taker = TurnTaker(_NoopLoop(), speech=board)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    for w in ("note", "that", "we", "just", "got", "cut"):
        taker.on_word(w)
    assert interrupted


def test_ripley_spoken_ceiling_is_not_a_280_token_clip():
    assert _ripley_spoken_max_tokens() >= 4096


def test_caption_board_holds_then_clears(monkeypatch):
    board = CaptionBoard()
    board.set("hello there")
    assert board.get() == "hello there"
    board._at = time.monotonic() - 10
    assert board.get() == ""


def test_paint_caption_changes_pixels():
    pytest.importorskip("PIL")
    from PIL import Image

    image = Image.new("RGB", (320, 180), (0, 0, 0))
    paint_caption(image, "caption overlay")
    assert image.getbbox() is not None


def test_frame_to_mono16k_downsamples_stereo():
    np = pytest.importorskip("numpy")
    frame = SimpleNamespace(
        sample_rate=48000,
        to_ndarray=lambda: np.ones((2, 4800), dtype=np.int16) * 16384,
    )
    pcm = frame_to_mono16k(frame)
    assert pcm is not None
    assert pcm.ndim == 1
    assert 1500 < pcm.size < 1800
    assert float(pcm.max()) <= 1.0


def test_frame_to_mono_uses_samples_not_interleaved_length():
    np = pytest.importorskip("numpy")
    from hsengine.engine.webrtc_stt import frame_to_mono

    packed = np.ones((1, 1920), dtype=np.int16) * 16384
    frame = SimpleNamespace(
        sample_rate=48000,
        samples=960,
        layout=SimpleNamespace(nb_channels=2),
        to_ndarray=lambda: packed,
    )
    pcm = frame_to_mono(frame, rate=24000)
    assert pcm is not None
    assert pcm.size == 480
