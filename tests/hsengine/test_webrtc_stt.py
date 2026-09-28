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
    assert board.get() == "Room: there one two three"
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


def test_the_last_word_arrives_after_the_mic_drops_and_stays_in_the_turn():
    """Kyutai emits the final word after the level falls. It is part of the turn, not a barge-in."""
    import time

    from hsengine.engine.webrtc_mix import SpeechBoard
    from hsengine.engine.webrtc_moshi import MicGate

    board = SpeechBoard()
    board.push([0.2] * 4800, sample_rate=48000)
    gate = MicGate()
    now = time.monotonic()
    gate._hot_at = now - 1.2
    assert gate.hot() is False
    assert gate.heard() is True
    taker = TurnTaker(_NoopLoop(), speech=board, mic=gate)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    for w in ("circle", "back", "to"):
        taker.on_word(w)
    taker.on_word("Nvidia")
    assert interrupted == []
    assert taker._words[-1] == "Nvidia"


def test_a_mic_that_has_been_cold_does_not_take_a_late_word():
    import time

    from hsengine.engine.webrtc_moshi import MicGate

    gate = MicGate()
    gate._hot_at = time.monotonic() - 5.0
    assert gate.heard() is False
    taker = TurnTaker(_NoopLoop(), mic=gate)
    taker.on_word("Nvidia")
    assert taker._words == []


def test_a_quiet_mic_does_not_cut_her_off():
    from hsengine.engine.webrtc_mix import SpeechBoard
    from hsengine.engine.webrtc_moshi import MicGate

    board = SpeechBoard()
    board.push([0.2] * 4800, sample_rate=48000)
    gate = MicGate()
    taker = TurnTaker(_NoopLoop(), speech=board, mic=gate)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    for w in ("note", "that", "we", "just", "got", "cut"):
        taker.on_word(w)
    assert interrupted == []
    assert taker._words == []


def test_a_short_phrase_does_not_dump_queued_speech():
    from hsengine.engine.webrtc_mix import SpeechBoard

    board = SpeechBoard()
    board.push([0.2] * 480, sample_rate=48000)
    taker = TurnTaker(_NoopLoop(), speech=board)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    taker.on_word("hello")
    taker.on_word("there")
    assert interrupted == []


def test_stop_still_barges_in_over_tts():
    from hsengine.engine.webrtc_mix import SpeechBoard

    board = SpeechBoard()
    board.push([0.2] * 480, sample_rate=48000)
    taker = TurnTaker(_NoopLoop(), speech=board)
    interrupted = []
    board.interrupt = lambda: interrupted.append(1) or 0
    taker.on_word("stop")
    assert interrupted


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


def test_agent_line_stays_on_the_picture_after_room_caption_expires(monkeypatch):
    board = CaptionBoard()
    board.set_agent("The 10-K names the fiber network, not a numbered plan.", label="Ripley")
    board.note_progress(played=8_000_000, queued=8_000_000, closed=True)
    board.set("tell me about the card")
    shown = board.get()
    assert shown.startswith("Ripley:")
    assert "10-K" in shown
    assert "Room: tell me about the card" in shown
    board._at = time.monotonic() - 10
    later = board.get()
    assert "10-K" in later
    assert "card" not in later


def test_agent_caption_is_empty_until_audio_plays():
    from hsengine.engine.webrtc_captions import revealed_words

    text = "one two three four five six seven eight"
    assert revealed_words(text, 0, sample_rate=48000) == ""
    early = revealed_words(text, 48000, sample_rate=48000)
    assert early.startswith("one")
    assert early != text
    done = revealed_words(text, 500_000, sample_rate=48000, samples_total=500_000, closed=True)
    assert done == text


def test_last_word_paints_when_its_audio_starts_not_after_it_ends():
    """'now' was missing: the slice only opened at frac == 1, after the word."""
    from hsengine.engine.webrtc_captions import revealed_words

    text = "pulling up that headline for you right now"
    words = text.split()
    total = 48000 * 2
    start = int(total * (len(words) - 1) / len(words))
    got = revealed_words(
        text, start, sample_rate=48000, samples_total=total, closed=True
    )
    assert got.split()[-1] == "now"
    earlier = revealed_words(
        text, start - 4800, sample_rate=48000, samples_total=total, closed=True
    )
    assert earlier.split()[-1] == "right"
    board = CaptionBoard()
    board.set_agent(text, label="Agent")
    assert board.get() == ""


def test_caption_board_holds_then_clears(monkeypatch):
    board = CaptionBoard()
    board.set("hello there")
    assert board.get() == "Room: hello there"
    board._at = time.monotonic() - 10
    assert board.get() == ""


def test_caption_lines_stay_inside_the_frame():
    pytest.importorskip("PIL")
    from PIL import Image

    from hsengine.engine.webrtc_captions import _font, _text_px, wrap_to_width

    width = 320
    size = max(18, width // 36)
    font = _font(size)
    pad = max(10, size // 3)
    budget = width - pad * 2
    text = "Room: " + " ".join(["filament"] * 40)
    lines = wrap_to_width(text, font, budget, 8)
    assert lines
    assert all(_text_px(font, line) <= budget + 1 for line in lines)
    image = Image.new("RGB", (width, 180), (180, 180, 180))
    paint_caption(image, text)
    assert image.getpixel((width - 1, 170)) != (180, 180, 180)


def test_caption_plate_is_translucent():
    pytest.importorskip("PIL")
    from PIL import Image

    image = Image.new("RGB", (640, 360), (180, 180, 180))
    paint_caption(image, "Room: a short line")
    # Right edge of the lower band, clear of the glyphs.
    pixel = image.getpixel((630, 340))
    assert pixel != (0, 0, 0)
    assert pixel != (180, 180, 180)
    assert 40 < pixel[0] < 170


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
