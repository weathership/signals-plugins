"""Outbound WebRTC audio mix: agent speech over silence (clip bed omitted).

One audio track on the PeerConnection. File soundtrack is not mixed while
dialog is iterated. SpeechBoard PCM replaces silence when queued.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.mix")

CANON_RATE = 48000
# Thoughts/agenda spoken can run past two minutes. A ring that pops left
# ate the start of the utterance ("jumps in mid-sentence").
BOARD_SECONDS = 300
_SPEECH_FLOOR = 1e-4  # below this, treat as silence → clip plays


class SoundtrackGate:
    """Clip soundtrack is live only until the first video loop (or audio, if no video)."""

    def __init__(self, *, has_video: bool) -> None:
        self._has_video = bool(has_video)
        self._loops = 0
        self._lock = threading.Lock()

    def on_track_eof(self, kind: str) -> None:
        if kind == "video" or (kind == "audio" and not self._has_video):
            with self._lock:
                if self._loops == 0:
                    self._loops = 1
                    log.info("clip soundtrack ended after first %s pass", kind)

    def clip_live(self) -> bool:
        with self._lock:
            return self._loops == 0


def _as_float_mono(pcm: Any) -> Any:
    import numpy as np

    arr = np.asarray(pcm)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float32)
    if arr.dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    else:
        arr = arr.astype(np.float32)
        peak = float(np.max(np.abs(arr))) if arr.size else 0.0
        if peak > 1.5:
            arr = arr / 32768.0
    if arr.ndim == 2:
        arr = arr.mean(axis=0 if arr.shape[0] <= 8 else 1)
    return np.ascontiguousarray(arr.reshape(-1), dtype=np.float32)


def _resample_mono(pcm: Any, src_rate: int, dst_rate: int) -> Any:
    import numpy as np

    if src_rate == dst_rate or pcm.size == 0:
        return pcm
    n_out = max(1, int(round(pcm.size * dst_rate / src_rate)))
    return np.interp(
        np.linspace(0, pcm.size - 1, n_out, dtype=np.float64),
        np.arange(pcm.size, dtype=np.float64),
        pcm,
    ).astype(np.float32)


def _fit(mono: Any, n: int) -> Any:
    import numpy as np

    if mono.size == n:
        return mono
    if mono.size > n:
        return mono[:n]
    out = np.zeros(n, dtype=np.float32)
    out[: mono.size] = mono
    return out


def _to_clip_dtype(arr: Any, like: Any) -> Any:
    import numpy as np

    if like.dtype == np.int16:
        return np.clip(np.asarray(arr) * 32767.0, -32768, 32767).astype(np.int16)
    return np.asarray(arr, dtype=like.dtype)


def speech_like_clip(clip: Any, speech_mono: Any) -> Any:
    """Broadcast mono speech onto the clip frame's channel layout."""
    import numpy as np

    clip_arr = np.asarray(clip)
    if clip_arr.ndim == 1:
        return _fit(speech_mono, clip_arr.shape[0])
    if clip_arr.shape[0] <= 8:
        n = clip_arr.shape[1]
        mono = _fit(speech_mono, n)
        return np.stack([mono] * clip_arr.shape[0], axis=0)
    n = clip_arr.shape[0]
    mono = _fit(speech_mono, n)
    return np.stack([mono] * clip_arr.shape[1], axis=1)


def audio_frame_samples(frame: Any, arr: Any | None = None) -> int:
    """Time-sample count (not interleaved length). Packed stereo is N, not 2N."""
    n = int(getattr(frame, "samples", 0) or 0)
    if n > 0:
        return n
    layout = getattr(frame, "layout", None)
    ch = int(
        getattr(layout, "nb_channels", None) or getattr(layout, "channels", None) or 0
    )
    import numpy as np

    if arr is None:
        try:
            arr = frame.to_ndarray()
        except Exception:
            return 0
    size = int(np.asarray(arr).size)
    if ch > 1 and size >= ch and size % ch == 0:
        return size // ch
    if arr is not None:
        a = np.asarray(arr)
        if a.ndim == 1:
            return int(a.size)
        if a.shape[0] <= 8:
            return int(a.shape[1])
        if a.shape[1] <= 8:
            return int(a.shape[0])
        return int(a.shape[-1])
    return 0


def mix_pcm(clip: Any, speech: Any | None, n_samples: int | None = None) -> Any:
    """Replace clip samples with speech when speech is present and audible."""
    import numpy as np

    if speech is None:
        return clip
    mono = _as_float_mono(speech)
    if mono.size == 0 or float(np.max(np.abs(mono))) < _SPEECH_FLOOR:
        return clip
    clip_arr = np.asarray(clip)
    n = int(n_samples or 0)
    if n > 0 and clip_arr.size >= n and clip_arr.size % n == 0:
        ch = clip_arr.size // n
        fitted = _fit(mono, n)
        stacked = np.stack([fitted] * ch, axis=-1)
        return _to_clip_dtype(stacked.reshape(clip_arr.shape), clip_arr)
    return _to_clip_dtype(speech_like_clip(clip_arr, mono), clip_arr)


class SpeechBoard:
    """Serialized PCM from every agent source. One outbound voice later (TTS)."""

    def __init__(
        self, sample_rate: int = CANON_RATE, *, max_seconds: float = BOARD_SECONDS
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.max_samples = int(self.sample_rate * max(1.0, float(max_seconds)))
        self._lock = threading.Lock()
        self._buf: deque[float] = deque()

    def push(self, pcm: Any, *, source: str = "", sample_rate: int | None = None) -> None:
        import numpy as np

        mono = _as_float_mono(pcm)
        rate = int(sample_rate or self.sample_rate)
        if rate != self.sample_rate:
            mono = _resample_mono(mono, rate, self.sample_rate)
        if mono.size == 0:
            return
        with self._lock:
            self._buf.extend(float(x) for x in mono.tolist())
            overflow = len(self._buf) - self.max_samples
            if overflow > 0:
                for _ in range(overflow):
                    self._buf.popleft()
        log.debug("speech queued %s samples=%s source=%s", rate, mono.size, source or "-")

    def speaking(self) -> bool:
        with self._lock:
            return bool(self._buf)

    def pull(self, n: int, sample_rate: int) -> Any | None:
        """n samples at *sample_rate*, or None if no agent speech is queued."""
        import numpy as np

        if n <= 0:
            return None
        need = n if sample_rate == self.sample_rate else max(1, int(round(n * self.sample_rate / sample_rate)))
        with self._lock:
            if not self._buf:
                return None
            take = min(need, len(self._buf))
            chunk = np.fromiter((self._buf.popleft() for _ in range(take)), dtype=np.float32, count=take)
        if chunk.size < need:
            chunk = _fit(chunk, need)
        if sample_rate != self.sample_rate:
            chunk = _resample_mono(chunk, self.sample_rate, sample_rate)
            chunk = _fit(chunk, n)
        return chunk


def s16_stereo_frame(mono: Any, n: int, *, sample_rate: int, pts: int, time_base: Any) -> Any:
    """Packed s16 stereo — aiortc OpusEncoder asserts format s16 (not fltp)."""
    import numpy as np
    import av
    from fractions import Fraction

    fitted = _fit(_as_float_mono(mono), n)
    pcm = np.clip(fitted * 32767.0, -32768, 32767).astype(np.int16)
    packed = np.column_stack([pcm, pcm])  # (n, 2)
    try:
        out = av.AudioFrame.from_ndarray(packed, format="s16", layout="stereo")
    except ValueError:
        interleaved = np.empty((1, n * 2), dtype=np.int16)
        interleaved[0, 0::2] = pcm
        interleaved[0, 1::2] = pcm
        out = av.AudioFrame.from_ndarray(interleaved, format="s16", layout="stereo")
    out.sample_rate = sample_rate
    out.pts = pts
    out.time_base = time_base if time_base is not None else Fraction(1, sample_rate)
    return out


def apply_mix_frame(frame: Any, board: SpeechBoard, gate: SoundtrackGate | None = None) -> Any:
    """Return a new audio frame with speech mixed over the clip, or the original."""
    try:
        import numpy as np
        from fractions import Fraction
    except Exception:
        return frame
    try:
        arr = frame.to_ndarray()
        n = audio_frame_samples(frame, arr)
        if n <= 0:
            return frame
        rate = int(getattr(frame, "sample_rate", 0) or CANON_RATE)
        speech = board.pull(n, rate)
        if speech is None and (gate is None or gate.clip_live()):
            # Keep the original only if it is already s16 (OpusEncoder asserts that).
            fmt = getattr(getattr(frame, "format", None), "name", None)
            if fmt == "s16":
                return frame
            speech = np.zeros(n, dtype=np.float32)
        if speech is None:
            speech = np.zeros(n, dtype=np.float32)
        tb = getattr(frame, "time_base", None)
        pts = int(getattr(frame, "pts", 0) or 0)
        return s16_stereo_frame(speech, n, sample_rate=rate, pts=pts, time_base=tb)
    except Exception:
        log.warning("audio mix failed", exc_info=True)
        return frame


def _silence_track(sample_rate: int = CANON_RATE, frame_samples: int = 960) -> Any:
    """20 ms stereo silence so speech can still go out when the clip has no audio."""
    from aiortc import MediaStreamTrack
    from aiortc.mediastreams import MediaStreamError

    class SilenceTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._rate = sample_rate
            self._n = frame_samples
            self._pts = 0
            self._t0: float | None = None

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError
            import numpy as np

            if self._t0 is None:
                self._t0 = time.monotonic()
            else:
                due = self._t0 + (self._pts / self._rate)
                wait = due - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            frame = s16_stereo_frame(
                np.zeros(self._n, dtype=np.float32),
                self._n,
                sample_rate=self._rate,
                pts=self._pts,
                time_base=None,
            )
            self._pts += self._n
            return frame

    return SilenceTrack()


def mix_audio_track(
    clip: Any | None, board: SpeechBoard, gate: SoundtrackGate | None = None
) -> Any:
    from aiortc import MediaStreamTrack
    from aiortc.mediastreams import MediaStreamError

    inner = clip if clip is not None else _silence_track()

    class MixedAudioTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self._inner = inner

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError
            frame = await self._inner.recv()
            return apply_mix_frame(frame, board, gate)

        def stop(self) -> None:
            try:
                self._inner.stop()
            except Exception:
                pass
            super().stop()

    return MixedAudioTrack()
