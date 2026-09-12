"""Outbound mix: combined agent speech preempts the clip soundtrack."""
from __future__ import annotations

import numpy as np

from hsengine.engine.webrtc_mix import (
    BOARD_SECONDS,
    SoundtrackGate,
    SpeechBoard,
    audio_frame_samples,
    mix_pcm,
)


def test_audio_frame_samples_uses_time_not_interleaved_length():
    class _Layout:
        nb_channels = 2

    class _Frame:
        samples = 960
        layout = _Layout()

    packed = np.zeros((1, 1920), dtype=np.int16)
    assert audio_frame_samples(_Frame(), packed) == 960
    planar = np.zeros((2, 960), dtype=np.float32)
    assert audio_frame_samples(_Frame(), planar) == 960


def test_mix_pcm_does_not_double_time_on_packed_stereo():
    clip = np.zeros((1, 8), dtype=np.int16)
    speech = np.linspace(0.1, 0.8, 4, dtype=np.float32)
    out = mix_pcm(clip, speech, n_samples=4)
    assert out.shape == (1, 8)


def test_clip_plays_when_no_speech():
    clip = np.arange(8, dtype=np.int16)
    out = mix_pcm(clip, None)
    assert np.array_equal(out, clip)


def test_silent_speech_does_not_preempt_clip():
    clip = np.arange(8, dtype=np.int16) + 100
    out = mix_pcm(clip, np.zeros(8, dtype=np.float32))
    assert np.array_equal(out, clip)


def test_speech_replaces_clip_samples():
    clip = np.ones(8, dtype=np.int16) * 1000
    speech = np.ones(8, dtype=np.float32) * 0.5
    out = mix_pcm(clip, speech)
    assert not np.array_equal(out, clip)
    assert int(out[0]) > 10000


def test_speech_fills_stereo_clip_both_channels():
    clip = np.ones((2, 4), dtype=np.int16) * 200
    speech = np.array([0.25, 0.25, 0.25, 0.25], dtype=np.float32)
    out = mix_pcm(clip, speech)
    assert out.shape == (2, 4)
    assert int(out[0, 0]) == int(out[1, 0])
    assert int(out[0, 0]) != 200


def test_board_pull_none_when_empty():
    board = SpeechBoard()
    assert board.speaking() is False
    assert board.pull(16, 48000) is None


def test_board_default_holds_five_minutes_of_speech():
    """A 2-minute ring clipped long thoughts/agenda turns; 5 minutes is the floor."""
    board = SpeechBoard()
    assert BOARD_SECONDS >= 300
    assert board.max_samples >= 48000 * 300


def test_board_keeps_the_start_of_a_long_utterance():
    """A thoughts briefing is longer than the old 30s ring; popping left skipped the first sentence."""
    board = SpeechBoard()
    n = 48000 * 40
    pcm = np.linspace(0.1, 0.9, n, dtype=np.float32)
    board.push(pcm, sample_rate=48000)
    first = board.pull(4800, 48000)
    assert first is not None
    assert abs(float(first[0]) - 0.1) < 0.02


def test_board_overflow_drops_the_oldest_samples():
    board = SpeechBoard(max_seconds=1)
    board.push(np.linspace(0.1, 0.2, 48000, dtype=np.float32), sample_rate=48000)
    board.push(np.linspace(0.8, 0.9, 48000, dtype=np.float32), sample_rate=48000)
    first = board.pull(4800, 48000)
    assert first is not None
    assert float(first[0]) > 0.5


def test_board_24k_speech_keeps_wall_clock_at_48k():
    """Kyutai TTS is 24 kHz; playing it as 48 kHz is a chipmunk (pitched-up) voice."""
    board = SpeechBoard()
    board.push(np.ones(24000, dtype=np.float32) * 0.3, sample_rate=24000)
    got = 0
    while True:
        chunk = board.pull(960, 48000)
        if chunk is None:
            break
        got += int(chunk.size)
    assert got == 48000


def test_board_serializes_sources_and_preempts():
    board = SpeechBoard()
    a = np.ones(4, dtype=np.float32) * 0.4
    b = np.ones(4, dtype=np.float32) * 0.8
    board.push(a, source="cerebras")
    board.push(b, source="other")
    assert board.speaking() is True
    first = board.pull(4, 48000)
    second = board.pull(4, 48000)
    assert first is not None and second is not None
    assert float(first.mean()) < float(second.mean())
    clip = np.zeros(4, dtype=np.int16)
    mixed = mix_pcm(clip, first)
    assert int(np.max(np.abs(mixed))) > 0
    assert board.pull(4, 48000) is None
    assert board.speaking() is False


def test_soundtrack_gate_dies_after_first_video_eof():
    gate = SoundtrackGate(has_video=True)
    assert gate.clip_live() is True
    gate.on_track_eof("audio")
    assert gate.clip_live() is True
    gate.on_track_eof("video")
    assert gate.clip_live() is False
    gate.on_track_eof("video")
    assert gate.clip_live() is False


def test_soundtrack_gate_audio_only_dies_on_audio_eof():
    gate = SoundtrackGate(has_video=False)
    gate.on_track_eof("audio")
    assert gate.clip_live() is False


def test_clip_is_silence_after_first_loop_unless_speech():
    clip = np.ones(8, dtype=np.int16) * 1000
    silent = np.zeros_like(clip)
    assert np.array_equal(mix_pcm(silent, None), silent)
    speech = np.ones(8, dtype=np.float32) * 0.5
    out = mix_pcm(silent, speech)
    assert int(out[0]) > 10000


def test_apply_mix_frame_puts_speech_on_silence():
    import av
    from fractions import Fraction

    from hsengine.engine.webrtc_mix import SpeechBoard, apply_mix_frame

    zeros = np.zeros((2, 960), dtype=np.float32)
    frame = av.AudioFrame.from_ndarray(zeros, format="fltp", layout="stereo")
    frame.sample_rate = 48000
    frame.pts = 0
    frame.time_base = Fraction(1, 48000)
    board = SpeechBoard()
    board.push(np.ones(960, dtype=np.float32) * 0.4, sample_rate=48000)
    out = apply_mix_frame(frame, board)
    assert out.format.name == "s16"
    assert int(np.max(np.abs(out.to_ndarray()))) > 1000


def test_apply_mix_frame_does_not_keep_clip_after_gate():
    import av

    from hsengine.engine.webrtc_mix import SpeechBoard, SoundtrackGate, apply_mix_frame

    clip = np.ones((2, 960), dtype=np.float32) * 0.4
    frame = av.AudioFrame.from_ndarray(clip, format="fltp", layout="stereo")
    from fractions import Fraction

    frame.sample_rate = 48000
    frame.pts = 0
    frame.time_base = Fraction(1, 48000)
    gate = SoundtrackGate(has_video=True)
    gate.on_track_eof("video")
    out = apply_mix_frame(frame, SpeechBoard(), gate)
    assert out.format.name == "s16"
    assert int(np.max(np.abs(out.to_ndarray()))) == 0
