"""Kyutai STT over moshi-server (Candle) for WebRTC captions.

Same Rust server Unmute uses. Streams 24 kHz PCM, receives Word events.
Moshi 7B dialogue is a different module: its text stream is the assistant
inner monologue, not a transcript of the user.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("hsengine.engine.webrtc.moshi")

_MOSHI_RATE = 24000
_CHUNK = 1920  # 80 ms at 24 kHz
_TURN_QUIET_S = 1.2
_TURN_MIN_CHARS = 8
SPOKEN_SYSTEM = (
    "On a live voice call. Plain spoken words only — no markdown, lists, "
    "code, or URLs. Never introduce yourself by name or as Hermes. "
    "For greetings and small talk that is "
    "not about the systems, one or two short sentences and do not call tools. "
    "When they ask how things are going, what's happening, whether anything "
    "is down, a briefing, or any operational check-in — even casually — "
    "call sitrep first (and list_activities only if you need a closer look), "
    "then talk about what you found in a few sentences. When they ask what "
    "you have been thinking about, what's on your mind, whether you've had any "
    "new ideas, insights or connections, or what the research has turned up — "
    "call recent_thoughts: it returns a ready Thoughts Brief in plain speech "
    "(briefs[].spoken) written by the cognition itself — say that in your own "
    "words as the federation's cognition, then offer detail from the individual "
    "thoughts only if they want more; if there is no brief or the note says "
    "cognition is idle, say so plainly instead of inventing thoughts. When they "
    "ask about the agenda, the schedule, meetings, reminders, or what's coming up "
    "today, tomorrow or this week — call agenda: it returns a ready Agenda Brief "
    "in plain speech (briefs[].spoken) plus an index of items with ids; speak the "
    "brief, and when they ask about one item, call agenda again with that item's "
    "id as item_id and tell them from its content. When they ask what we already "
    "know, to follow a note from the deck, or to look something up in our notes "
    "— call kb_search. When they ask about the wider world, news, or a fact you "
    "do not have — call web_search. When they ask about a ticker, a listed "
    "company, or markets — call fmp (search, news, or quote) instead of web_search. "
    "When they need Hermes proper (skills, files, terminal, browser, "
    "subagents, memory) — call hermes; it shares this same session, so "
    "this call's transcript and memories are already there. "
    "Recent turns of this call are already in context. After a pause, "
    "interruption, or whenever you have lost the thread — call "
    "conversation. Do not announce how long we have been talking or "
    "which slide a clock thinks we are on unless they ask. If an earlier "
    "part of this call (or another Hermes session) is missing from context "
    "— call session_search; do not invent earlier turns. After a "
    "search, if you were presenting, call conversation then resume. "
    "Do not ask "
    "them to use special words. Do not invent who is healthy, what is running, "
    "or URLs you did not retrieve."
)


def _cfg_str(path: str, default: str) -> str:
    try:
        from hsengine.config import get_str

        value = get_str(path)
        return value if value else default
    except Exception:
        return default


def moshi_url() -> str:
    return _cfg_str(
        "hermes.engine.webrtc.stt.moshi_url",
        "ws://127.0.0.1:5080/api/asr-streaming",
    )


def moshi_key() -> str:
    return _cfg_str("hermes.engine.webrtc.stt.moshi_key", "public_token")


def moshi_host_port() -> tuple[str, int]:
    parsed = urlparse(moshi_url())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    if parsed.scheme == "ws" and parsed.port is None:
        port = 5080
    return host, port


def utterance_ready(words: list[str], *, min_chars: int = _TURN_MIN_CHARS) -> str | None:
    text = " ".join(w for w in words if w).strip()
    if len(text) < min_chars:
        return None
    return text


class TurnTaker:
    """Flush a user utterance after a quiet gap, then Cerebras → TTS."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        quiet_s: float = _TURN_QUIET_S,
        *,
        session_id: str = "",
    ) -> None:
        self._loop = loop
        self._quiet_s = quiet_s
        self._session_id = session_id
        self._words: list[str] = []
        self._gen = 0
        self._task: asyncio.Task | None = None
        self._busy = False
        self.last_user_at = 0.0
        self.last_agent_at = 0.0
        self.pending_steer = ""

    @property
    def busy(self) -> bool:
        return self._busy

    def try_claim(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self) -> None:
        self._busy = False

    def on_word(self, word: str) -> None:
        import time

        self.last_user_at = time.monotonic()
        self._words.append(word)
        self._gen += 1
        gen = self._gen
        if self._task is not None:
            self._task.cancel()
        self._task = self._loop.create_task(self._flush(gen))

    async def _flush(self, gen: int) -> None:
        try:
            await asyncio.sleep(self._quiet_s)
        except asyncio.CancelledError:
            return
        if gen != self._gen or self._busy:
            return
        text = utterance_ready(self._words)
        self._words.clear()
        if not text:
            return
        self._busy = True
        try:
            log.info("user utterance %r", text)
            from hsengine.engine import interactive, session_history
            from hsengine.engine.named_bots import ripley_spoken_system
            from hsengine.engine.webrtc_silence import apply_steer_system

            session_history.record_turn(self._session_id, user=text)
            steer = self.pending_steer
            self.pending_steer = ""
            result = await asyncio.to_thread(
                interactive.complete_cerebras,
                prompt=text,
                system_prompt=apply_steer_system(ripley_spoken_system(), steer),
                max_tokens=280,
                temperature=0.5,
                reasoning_effort="none",
                tools=True,
                session_id=self._session_id,
            )
            session_history.record_turn(
                self._session_id, assistant=result.text, model=result.model
            )
            session_history.remember_turn(
                self._session_id, user=text, assistant=result.text
            )
        except Exception:
            log.exception("cerebras turn failed")
        finally:
            self._busy = False


class MoshiCaptioner:
    """Accumulate streaming Word events into a caption line."""

    def __init__(self, board: Any, max_words: int = 16) -> None:
        self.board = board
        self.max_words = max_words
        self.words: list[str] = []

    def on_message(self, data: dict) -> str | None:
        kind = data.get("type")
        if kind == "Word":
            word = str(data.get("text") or "").strip()
            if not word:
                return None
            self.words.append(word)
            del self.words[: -self.max_words]
            line = " ".join(self.words)
            self.board.set(line)
            log.info("stt word %r line=%r", word, line)
            return line
        if kind == "Step":
            return None
        return None


def frame_to_mono24k(frame: Any) -> Any:
    from hsengine.engine.webrtc_stt import frame_to_mono

    return frame_to_mono(frame, rate=_MOSHI_RATE)


async def follow_audio(
    track: Any, board: Any, *, session_id: str = "", speech: Any | None = None
) -> None:
    """Drain inbound WebRTC audio into moshi-server ASR."""
    import msgpack
    import numpy as np
    import websockets

    captioner = MoshiCaptioner(board)
    turns = TurnTaker(asyncio.get_running_loop(), session_id=session_id)
    from hsengine.engine.webrtc_silence import SilenceDirector

    director = SilenceDirector(
        asyncio.get_running_loop(),
        session_id=session_id,
        turns=turns,
        speech=speech,
    )
    url = moshi_url()
    if "auth_id=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}auth_id={moshi_key()}"
    headers = {"kyutai-api-key": moshi_key()}
    chunks: asyncio.Queue[Any] = asyncio.Queue(maxsize=48)

    async def ingest() -> None:
        pending = np.zeros((0,), dtype=np.float32)
        try:
            while True:
                frame = await track.recv()
                pcm = frame_to_mono24k(frame)
                if pcm is None or getattr(pcm, "size", 0) == 0:
                    continue
                pending = np.concatenate([pending, np.asarray(pcm, dtype=np.float32).reshape(-1)])
                while pending.size >= _CHUNK:
                    piece = pending[:_CHUNK]
                    pending = pending[_CHUNK:]
                    if chunks.full():
                        try:
                            chunks.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await chunks.put(piece)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.info("moshi stt ingest ended")

    async def pump() -> None:
        while True:
            try:
                async with websockets.connect(
                    url, additional_headers=headers, open_timeout=5, max_size=2**22
                ) as ws:
                    log.info("moshi stt connected %s", url)

                    async def sender() -> None:
                        from websockets.exceptions import ConnectionClosed

                        try:
                            silence = np.zeros(_MOSHI_RATE, dtype=np.float32)
                            await ws.send(
                                msgpack.packb(
                                    {"type": "Audio", "pcm": [float(x) for x in silence]},
                                    use_bin_type=True,
                                    use_single_float=True,
                                )
                            )
                            while True:
                                piece = await chunks.get()
                                msg = msgpack.packb(
                                    {"type": "Audio", "pcm": [float(x) for x in piece]},
                                    use_bin_type=True,
                                    use_single_float=True,
                                )
                                await ws.send(msg)
                        except ConnectionClosed:
                            log.info("moshi stt send closed")

                    async def receiver() -> None:
                        from websockets.exceptions import ConnectionClosed

                        try:
                            async for raw in ws:
                                data = msgpack.unpackb(raw, raw=False)
                                if isinstance(data, dict):
                                    line = captioner.on_message(data)
                                    if line and data.get("type") == "Word":
                                        word = str(data.get("text") or "").strip()
                                        if word:
                                            turns.on_word(word)
                        except ConnectionClosed:
                            log.info("moshi stt recv closed")

                    send_task = asyncio.create_task(sender())
                    recv_task = asyncio.create_task(receiver())
                    _done, pending_tasks = await asyncio.wait(
                        {send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending_tasks:
                        task.cancel()
                    await asyncio.gather(send_task, recv_task, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("moshi stt reconnecting (%s)", exc)
                await asyncio.sleep(1.0)

    ingest_task = asyncio.create_task(ingest())
    pump_task = asyncio.create_task(pump())
    director_task = asyncio.create_task(director.run())
    try:
        await asyncio.wait({ingest_task, pump_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        ingest_task.cancel()
        pump_task.cancel()
        director_task.cancel()
        await asyncio.gather(
            ingest_task, pump_task, director_task, return_exceptions=True
        )
