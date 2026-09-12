"""Kyutai TTS (moshi-server /api/tts_streaming) → SpeechBoard PCM.

Cerebras return text is spoken in one voice on the WebRTC audio track.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode, urlparse

log = logging.getLogger("hsengine.engine.webrtc.tts")

TTS_RATE = 24000


def _cfg_str(path: str, default: str) -> str:
    try:
        from hsengine.config import get_str

        value = get_str(path)
        return value if value else default
    except Exception:
        return default


def tts_url() -> str:
    return _cfg_str(
        "hermes.engine.webrtc.tts.moshi_url",
        "ws://127.0.0.1:5080/api/tts_streaming",
    )


def tts_key() -> str:
    return _cfg_str("hermes.engine.webrtc.tts.moshi_key", "public_token")


def _tts_phrases(text: str, *, max_words: int = 12) -> list[str]:
    """Split spoken text into short phrases for Kyutai Text messages."""
    words = (text or "").split()
    out: list[str] = []
    buf: list[str] = []
    for w in words:
        buf.append(w)
        end = w.endswith((".", "?", "!", ";", ":"))
        if end or len(buf) >= max_words:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return out or [text]


def tts_voice() -> str:
    return _cfg_str(
        "hermes.engine.webrtc.tts.voice",
        "unmute-prod-website/p329_022.wav",
    )


def tts_host_port() -> tuple[str, int]:
    parsed = urlparse(tts_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5080
    return host, port


async def synthesize_chunks(text: str):
    """Yield float32 mono PCM chunks at 24 kHz as Kyutai produces them."""
    import msgpack
    import numpy as np
    import websockets

    cleaned = " ".join((text or "").split())
    if not cleaned:
        return
    voice = tts_voice()
    params = {"voice": voice, "format": "PcmMessagePack"}
    uri = f"{tts_url()}?{urlencode(params)}"
    log.info("tts voice=%s chars=%s", voice, len(cleaned))
    headers = {"kyutai-api-key": tts_key()}
    async with websockets.connect(
        uri, additional_headers=headers, open_timeout=10, max_size=2**24
    ) as ws:
        try:
            # Phrase-sized Text messages: word-at-a-time was closing the
            # socket (1005) on ~800-char answers before any Audio arrived.
            for phrase in _tts_phrases(cleaned):
                await ws.send(msgpack.packb({"type": "Text", "text": phrase}, use_bin_type=True))
            await ws.send(msgpack.packb({"type": "Eos"}, use_bin_type=True))
            async for raw in ws:
                data = msgpack.unpackb(raw, raw=False)
                if not isinstance(data, dict):
                    continue
                if data.get("type") == "Audio":
                    pcm = np.asarray(data.get("pcm") or [], dtype=np.float32).reshape(-1)
                    if pcm.size:
                        yield pcm
        except Exception as e:
            name = type(e).__name__
            if "ConnectionClosed" not in name:
                raise
            log.warning("tts websocket closed (%s); keeping audio already queued", e)


async def synthesize(text: str) -> Any:
    """Stream Kyutai TTS; return float32 mono PCM at 24 kHz, or empty array."""
    import numpy as np

    chunks = [c async for c in synthesize_chunks(text)]
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def _push_chunks(boards: list[Any], pcm: Any, source: str) -> int:
    n = int(getattr(pcm, "size", 0) or 0)
    if n == 0:
        return 0
    for board in boards:
        board.push(pcm, source=source, sample_rate=TTS_RATE)
    return n


def speak_into(board: Any, text: str, *, source: str = "cerebras") -> None:
    """Stream TTS onto *board* as chunks arrive (preempts clip audio)."""

    async def _run() -> int:
        total = 0
        async for pcm in synthesize_chunks(text):
            total += _push_chunks([board], pcm, source)
        return total

    n = asyncio.run(_run())
    if n == 0:
        raise RuntimeError("Kyutai TTS returned no audio")
    log.info("queued %s samples from %s (%s chars)", n, source, len(text or ""))


def speak_on_session_boards(text: str, *, source: str = "cerebras") -> None:
    from hsengine.engine.webrtc_session import HUB

    boards = [b for b in getattr(HUB, "_speech", {}).values() if b is not None]
    if not boards:
        return

    async def _run() -> int:
        total = 0
        async for pcm in synthesize_chunks(text):
            total += _push_chunks(boards, pcm, source)
        return total

    n = asyncio.run(_run())
    if n == 0:
        raise RuntimeError("Kyutai TTS returned no audio")
    log.info("spoke %s onto %s board(s) (%s samples)", source, len(boards), n)
