"""Kyutai TTS client: Cerebras text → SpeechBoard PCM."""
from __future__ import annotations

import numpy as np

from hsengine.engine.webrtc_mix import SpeechBoard
from hsengine.engine.webrtc_tts import _tts_phrases, speak_into, tts_url, tts_voice


def test_silence_cap_drops_a_spike_inside_a_phrase_hole():
    """One loud sample in a Kyutai pause must not preserve the pause."""
    from hsengine.engine.webrtc_tts import SilenceCap

    rate = 24000
    speech = np.ones(rate // 5, dtype=np.float32) * 0.3
    hole = np.zeros(rate // 2, dtype=np.float32)
    hole[hole.size // 2] = 0.25
    cap = SilenceCap(rate=rate)
    out = cap.feed(np.concatenate([speech, hole, speech]))
    assert float(np.max(out[: speech.size])) > 0.2
    # The half-second hole is gone. A breath of it is kept.
    assert out.size < speech.size * 2 + int(0.25 * rate)
    assert out.size > speech.size * 2 + int(0.05 * rate)


def test_silence_cap_keeps_a_quiet_syllable():
    """A soft ending is speech. The gate must not trim it away."""
    from hsengine.engine.webrtc_tts import SilenceCap

    rate = 24000
    quiet = np.ones(rate // 5, dtype=np.float32) * 0.08
    out = SilenceCap(rate=rate).feed(quiet)
    assert out.size > int(quiet.size * 0.9)


def test_silence_cap_keeps_speech_and_shortens_holes():
    from hsengine.engine.webrtc_tts import SilenceCap

    rate = 24000
    speech = np.ones(rate // 10, dtype=np.float32) * 0.3
    hole = np.zeros(rate // 2, dtype=np.float32)
    cap = SilenceCap(rate=rate, keep_s=0.09)
    out = np.concatenate([cap.feed(speech), cap.feed(hole), cap.feed(speech)])
    assert float(np.max(out[: speech.size])) > 0.2
    assert float(np.max(out[-speech.size :])) > 0.2
    assert out.size < speech.size * 2 + int(0.12 * rate)


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
        t0 = asyncio.get_running_loop().time()
        speak_into(board, "hello from the engine loop")
        # Synthesis is on a side thread. This wait is the loop staying alive.
        for _ in range(50):
            if board.speaking():
                return asyncio.get_running_loop().time() - t0
            await asyncio.sleep(0.01)
        return None

    elapsed = asyncio.run(_inside())
    assert elapsed is not None and elapsed < 0.5


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
