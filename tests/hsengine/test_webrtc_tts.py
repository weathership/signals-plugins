"""Kyutai TTS client: Cerebras text → SpeechBoard PCM."""
from __future__ import annotations

import numpy as np

from hsengine.engine.webrtc_mix import SpeechBoard
from hsengine.engine.webrtc_tts import _tts_phrases, speak_into, tts_url, tts_voice


def test_tts_phrases_group_words_at_sentence_breaks():
    parts = _tts_phrases("Hello there. How are you doing today? Fine.")
    assert parts[0].endswith(".")
    assert all(len(p.split()) <= 12 for p in parts)
    assert " ".join(parts).startswith("Hello there")


def test_tts_url_is_the_moshi_streaming_path():
    assert tts_url().endswith("/api/tts_streaming")
    voice = tts_voice()
    assert "/" in voice and voice.endswith(".wav")


def test_speak_into_skips_when_epoch_already_moved(monkeypatch):
    pcm = np.ones(4800, dtype=np.float32) * 0.4

    async def _chunks(text: str):
        yield pcm

    monkeypatch.setattr("hsengine.engine.webrtc_tts.synthesize_chunks", _chunks)
    board = SpeechBoard()
    board.interrupt()
    speak_into(board, "hello from cerebras", source="cerebras", epoch=0)
    assert board.speaking() is False


def test_speak_into_aborts_remaining_chunks_after_interrupt(monkeypatch):
    board = SpeechBoard()

    async def _chunks(text: str):
        yield np.ones(2400, dtype=np.float32) * 0.4
        board.interrupt()
        yield np.ones(2400, dtype=np.float32) * 0.9

    monkeypatch.setattr("hsengine.engine.webrtc_tts.synthesize_chunks", _chunks)
    speak_into(board, "hello from cerebras", source="cerebras")
    assert board.speaking() is False


def test_speak_into_from_a_running_event_loop(monkeypatch):
    import asyncio

    pcm = np.ones(2400, dtype=np.float32) * 0.4

    async def _chunks(text: str):
        yield pcm

    monkeypatch.setattr("hsengine.engine.webrtc_tts.synthesize_chunks", _chunks)
    board = SpeechBoard()

    async def _inside():
        speak_into(board, "hello from the engine loop")
        return board.speaking()

    assert asyncio.run(_inside()) is True


def test_speak_into_preempts_clip_on_the_board(monkeypatch):
    pcm = np.ones(4800, dtype=np.float32) * 0.4

    async def _chunks(text: str):
        assert "hello" in text.lower()
        yield pcm

    monkeypatch.setattr("hsengine.engine.webrtc_tts.synthesize_chunks", _chunks)
    board = SpeechBoard()
    speak_into(board, "hello from cerebras", source="cerebras")
    assert board.speaking() is True
    got = board.pull(4800, 48000)
    assert got is not None
    assert float(np.max(np.abs(got))) > 0
