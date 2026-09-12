"""Inbound WebRTC audio → Kyutai STT (moshi-server). No whisper/CPU path."""
from __future__ import annotations

import logging
from typing import Any

from hsengine.engine.webrtc_moshi import follow_audio as follow_moshi
from hsengine.engine.webrtc_moshi import moshi_host_port
from hsengine.engine.yk_sentinel import moshi_serving

log = logging.getLogger("hsengine.engine.webrtc.stt")

_RATE = 16000


def stt_available() -> bool:
    """True only when moshi-server is actually listening."""
    host, port = moshi_host_port()
    return moshi_serving(host, port)


def frame_to_mono(frame: Any, rate: int = _RATE) -> Any:
    """Return float32 mono PCM at *rate* Hz, or None."""
    import numpy as np

    try:
        arr = frame.to_ndarray()
    except Exception:
        return None
    arr = np.asarray(arr)
    if arr.size == 0:
        return None
    if arr.dtype == np.int16:
        pcm = arr.astype(np.float32) / 32768.0
    else:
        pcm = arr.astype(np.float32)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak > 1.5:
            pcm = pcm / 32768.0
    n = 0
    try:
        from hsengine.engine.webrtc_mix import audio_frame_samples

        n = audio_frame_samples(frame, arr)
    except Exception:
        n = 0
    if n > 0 and pcm.size >= n and pcm.size % n == 0:
        ch = pcm.size // n
        pcm = pcm.reshape(n, ch).mean(axis=1) if ch > 1 else pcm.reshape(n)
    elif pcm.ndim == 2:
        pcm = pcm.mean(axis=0 if pcm.shape[0] <= 8 else 1)
    src_rate = int(getattr(frame, "sample_rate", 0) or rate)
    if src_rate != rate and pcm.size:
        n_out = max(1, int(round(pcm.size * rate / src_rate)))
        pcm = np.interp(
            np.linspace(0, pcm.size - 1, n_out, dtype=np.float64),
            np.arange(pcm.size, dtype=np.float64),
            pcm,
        ).astype(np.float32)
    return pcm


def frame_to_mono16k(frame: Any) -> Any:
    return frame_to_mono(frame, rate=_RATE)


async def follow_audio(
    track: Any, board: Any, *, session_id: str = "", speech: Any | None = None
) -> None:
    if not stt_available():
        log.error("agent-rtc STT unavailable (moshi-server not listening)")
        return
    await follow_moshi(track, board, session_id=session_id, speech=speech)
