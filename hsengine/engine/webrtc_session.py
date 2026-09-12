"""Engine-local WebRTC: loop a forward-sim clip as the outbound media.

Not zndx.engine.v1. Signaling is HermesEngine.WebRtcOffer (SDP). Media is
UDP from this process (host net; bwrap shares net). Inbound tracks (laptop
mic) are accepted so the PC is duplex-ready; this slice does not STT them.

aiortc MediaPlayer(loop=True) seeks back to PTS 0; browsers freeze after
one pass. LoopingFileTrack reopens the file and keeps PTS increasing.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from hsengine.config import get_str

log = logging.getLogger("hsengine.engine.webrtc")

ICE_SERVERS = ["stun:stun.l.google.com:19302"]
ICE_TIMEOUT_S = 5.0

_FIXTURE = Path(__file__).resolve().parents[1] / "media" / "fixtures" / "demo.mp4"


class WebRtcUnavailable(RuntimeError):
    """aiortc extra is not installed."""


def video_path() -> Path | None:
    try:
        configured = get_str("hermes.engine.webrtc.video")
    except Exception:
        configured = ""
    for raw in (configured, str(_FIXTURE)):
        if not raw:
            continue
        path = Path(raw)
        if path.is_file():
            return path
    return None


def looping_tracks(src: Path) -> tuple[object | None, object | None, object]:
    """Looping video from *src*. Clip soundtrack is not used (agent speech only).

    Returns (video, None, soundtrack_gate). Gate is unused while the file
    bed is omitted; kept so we can restore clip audio later.
    """
    from aiortc import MediaStreamTrack
    from aiortc.contrib.media import MediaPlayer
    from aiortc.mediastreams import MediaStreamError

    from hsengine.engine.webrtc_mix import SoundtrackGate

    class LoopingFileTrack(MediaStreamTrack):
        def __init__(self, path: Path, kind: str, gate: SoundtrackGate) -> None:
            super().__init__()
            self.kind = kind
            self._path = path
            self._gate = gate
            self._player: object | None = None
            self._inner: object | None = None
            self._offset = 0
            self._last_pts: int | None = None

        def _ensure(self) -> None:
            if self._inner is not None:
                return
            player = MediaPlayer(str(self._path))
            inner = player.video if self.kind == "video" else player.audio
            if inner is None:
                raise FileNotFoundError(f"no {self.kind} track in {self._path}")
            self._player = player
            self._inner = inner

        def _close_inner(self) -> None:
            inner, self._inner = self._inner, None
            self._player = None
            if inner is None:
                return
            try:
                inner.stop()
            except Exception:
                log.debug("webrtc stop inner %s", self.kind, exc_info=True)

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError
            while True:
                self._ensure()
                try:
                    frame = await self._inner.recv()  # type: ignore[union-attr]
                except MediaStreamError:
                    self._gate.on_track_eof(self.kind)
                    self._close_inner()
                    if self._last_pts is not None:
                        self._offset = self._last_pts + 1
                    continue
                pts = getattr(frame, "pts", None)
                if pts is not None:
                    frame.pts = int(pts) + self._offset
                    self._last_pts = frame.pts
                return frame

        def stop(self) -> None:
            self._close_inner()
            super().stop()

    probe = MediaPlayer(str(src))
    has_video = probe.video is not None
    for media in (probe.video, probe.audio):
        if media is None:
            continue
        try:
            media.stop()
        except Exception:
            log.debug("webrtc stop probe", exc_info=True)
    gate = SoundtrackGate(has_video=has_video)
    video = LoopingFileTrack(src, "video", gate) if has_video else None
    return video, None, gate


class WebRtcHub:
    def __init__(self) -> None:
        self._pcs: dict[str, object] = {}
        self._tracks: dict[str, list[object]] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        self._speech: dict[str, object] = {}
        self._agenda: dict[str, str] = {}
        self._started: dict[str, float] = {}
        self._material: dict[str, dict] = {}

    async def offer(self, sdp: str, typ: str = "offer", agenda_id: str = "") -> dict[str, str]:
        try:
            from aiortc import (
                RTCConfiguration,
                RTCIceServer,
                RTCPeerConnection,
                RTCSessionDescription,
            )
        except ImportError as e:
            raise WebRtcUnavailable("aiortc is not installed (hermes-agent[engine])") from e

        src = video_path()
        if src is None:
            raise FileNotFoundError(
                "no WebRTC source clip; set HERMES_WEBRTC_VIDEO or place demo.mp4"
            )

        config = RTCConfiguration(
            iceServers=[RTCIceServer(urls=list(ICE_SERVERS))] if ICE_SERVERS else []
        )
        pc = RTCPeerConnection(configuration=config)
        session_id = uuid.uuid4().hex[:12]
        self._pcs[session_id] = pc
        self._started[session_id] = time.monotonic()

        from hsengine.engine import interactive
        from hsengine.engine.webrtc_captions import CaptionBoard, caption_track
        from hsengine.engine.webrtc_mix import SpeechBoard, mix_audio_track
        from hsengine.engine.webrtc_stt import follow_audio, stt_available

        await interactive.enter_async(owner=f"webrtc:{session_id}")
        from hsengine.engine import session_history

        session_history.open_session(session_id)
        aid = (agenda_id or "").strip()
        if aid:
            self._agenda[session_id] = aid
        log.info("webrtc offer session=%s agenda_id=%s", session_id, aid or "-")
        try:
            board = CaptionBoard()
            loop = asyncio.get_running_loop()
            captions = stt_available()
            if not captions:
                raise RuntimeError("agent-rtc STT unavailable after interactive enter")
        except Exception:
            await self._drop(session_id)
            raise
        video, _clip_audio, _gate = looping_tracks(src)
        speech = SpeechBoard()
        self._speech[session_id] = speech
        tracks: list[object] = []
        if video is not None:
            painted = caption_track(video, board) if captions else video
            pc.addTrack(painted)  # type: ignore[arg-type]
            tracks.append(painted)
        mixed = mix_audio_track(None, speech)
        pc.addTrack(mixed)  # type: ignore[arg-type]
        tracks.append(mixed)
        if video is None:
            await self._drop(session_id)
            raise FileNotFoundError(f"no video track in {src}")
        self._tracks[session_id] = tracks
        stt_started: set[str] = set()

        def _start_stt(track) -> None:
            if track is None or getattr(track, "kind", "") != "audio" or not captions:
                return
            tid = str(getattr(track, "id", "") or id(track))
            if tid in stt_started:
                return
            stt_started.add(tid)
            log.info(
                "webrtc %s inbound audio id=%s ready=%s",
                session_id,
                tid,
                getattr(track, "readyState", ""),
            )
            task = loop.create_task(
                follow_audio(track, board, session_id=session_id, speech=speech)
            )
            self._tasks.setdefault(session_id, []).append(task)

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            log.info("webrtc %s state=%s", session_id, pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self._drop(session_id)

        @pc.on("track")
        def _on_track(track) -> None:
            log.info("webrtc %s inbound %s", session_id, track.kind)
            _start_stt(track)

        audio_dir = [
            line
            for line in (sdp or "").splitlines()
            if line.startswith("m=audio") or line.startswith("a=send") or line.startswith("a=recv")
        ]
        log.info("webrtc %s offer audio %s", session_id, audio_dir[:8] or "none")

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ or "offer"))
        for tr in pc.getTransceivers():
            recv = getattr(tr, "receiver", None)
            _start_stt(getattr(recv, "track", None) if recv is not None else None)
        if captions and not stt_started:
            log.warning(
                "webrtc %s no inbound mic — captions and replies will stay silent",
                session_id,
            )
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await _ice_complete(pc)

        async def _opening() -> None:
            try:
                from hsengine.engine.agenda_deck import load_agenda_session
                from hsengine.engine.context_pack import (
                    conversational_context,
                    pipeline_block,
                )
                from hsengine.engine.named_bots import (
                    bishop_run,
                    ensure_bots,
                    ripley_opening_prompts,
                )

                aid = self._agenda.get(session_id, "")
                session = {}
                if aid:
                    session = await asyncio.to_thread(load_agenda_session, aid)
                    if session:
                        self._material[session_id] = session
                    log.info(
                        "webrtc opening agenda_id=%s title=%s deck=%s public=%s",
                        aid,
                        session.get("title") or "-",
                        "yes" if session.get("deck") else "no",
                        "yes" if session.get("public") else "no",
                    )
                pack = await asyncio.to_thread(conversational_context, agenda_id=aid)
                glance = pipeline_block(pack)
                log.info(
                    "webrtc opening pack=%s agent-mediated bishop→ripley",
                    ",".join(sorted(pack)) or "empty",
                )
                await asyncio.to_thread(ensure_bots)
                outcome = await asyncio.to_thread(
                    bishop_run,
                    session_id=session_id,
                    move="open",
                    glance=glance,
                )
                speak_s, speak_u = ripley_opening_prompts(outcome)
                log.info(
                    "webrtc opening bishop steer=%s monologue=%s",
                    "yes" if outcome.steer else "no",
                    "yes" if outcome.monologue else "no",
                )
                result = await asyncio.to_thread(
                    interactive.complete_cerebras,
                    prompt=speak_u,
                    system_prompt=speak_s,
                    max_tokens=280,
                    temperature=0.55,
                    reasoning_effort="none",
                    tools=False,
                    speak=True,
                    session_id=session_id,
                )
                from hsengine.engine import session_history

                session_history.record_turn(
                    session_id, assistant=result.text, model=result.model
                )
            except Exception:
                log.exception("cerebras opening line failed")

        loop.create_task(_opening())
        return {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
            "session_id": session_id,
            "source": str(src),
        }

    def speech(self, session_id: str) -> object | None:
        """The session's agent-speech board (None after hangup)."""
        return self._speech.get(session_id)

    def narrative_checkin(self, *, at_minute: float | None = None) -> dict:
        """Where the running story is, given elapsed time since Connect."""
        from hsengine.engine.agenda_deck import narrative_at

        if not self._pcs:
            return {"ok": False, "error": "no live AgentRTC session"}
        sid = next(iter(self._pcs))
        started = self._started.get(sid) or time.monotonic()
        elapsed = (
            float(at_minute) * 60.0
            if at_minute is not None
            else time.monotonic() - started
        )
        material = self._material.get(sid) or {}
        if not material:
            aid = self._agenda.get(sid) or ""
            if aid:
                from hsengine.engine.agenda_deck import load_agenda_session

                material = load_agenda_session(aid) or {}
                if material:
                    self._material[sid] = material
        if not material:
            return {
                "ok": True,
                "elapsed_min": round(max(0.0, elapsed) / 60.0, 2),
                "note": "no agenda deck on this call — lead from the live conversation",
            }
        place = narrative_at(material, elapsed_s=elapsed)
        place["ok"] = True
        place["session_id"] = sid
        return place

    async def hangup(self, session_id: str) -> bool:
        if session_id not in self._pcs and session_id not in self._tracks:
            return False
        await self._drop(session_id)
        return True

    async def _drop(self, session_id: str) -> None:
        for task in self._tasks.pop(session_id, []):
            task.cancel()
        self._speech.pop(session_id, None)
        self._agenda.pop(session_id, None)
        self._started.pop(session_id, None)
        self._material.pop(session_id, None)
        for track in self._tracks.pop(session_id, []):
            try:
                track.stop()  # type: ignore[union-attr]
            except Exception:
                log.debug("webrtc stop track %s", session_id, exc_info=True)
        pc = self._pcs.pop(session_id, None)
        if pc is None:
            return
        try:
            await pc.close()  # type: ignore[union-attr]
        except Exception:
            log.debug("webrtc close %s", session_id, exc_info=True)
        from hsengine.engine import session_history

        session_history.close_session(session_id)
        if not self._pcs:
            from hsengine.engine import interactive

            await interactive.leave_async()


async def _ice_complete(pc: object, timeout: float | None = None) -> None:
    limit = ICE_TIMEOUT_S if timeout is None else timeout
    if getattr(pc, "iceGatheringState", "") == "complete":
        return
    done = asyncio.Event()

    @pc.on("icegatheringstatechange")  # type: ignore[attr-defined]
    def _() -> None:
        if getattr(pc, "iceGatheringState", "") == "complete":
            done.set()

    try:
        await asyncio.wait_for(done.wait(), timeout=limit)
    except asyncio.TimeoutError:
        log.warning("webrtc ICE gathering timed out; sending partial SDP")


HUB = WebRtcHub()
