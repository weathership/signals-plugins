# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""One AdmitSession per AgentRTC call, then the Mistral system-one workflow.

The caller appends only the new characters. Aegir returns genus offsets.
This module slices the text it already holds and asks signals-system-one
to confirm that genus. UNIMPLEMENTED and a down peer leave the turn in place.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

import grpc

from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc
from hsengine.engine.sdg_aperture import attach, links_in_message, slice_for_mistral, stamp_message

log = logging.getLogger("hsengine.engine.sdg_session")

_LOCK = threading.Lock()
_LIVE: dict[str, "_Stream"] = {}


def unimplemented(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if not callable(code):
        return False
    try:
        return code() == grpc.StatusCode.UNIMPLEMENTED
    except Exception:
        return False


def aegir_target() -> str:
    """Directory target for the aegir engine, else the local lattice port."""
    try:
        from hsengine.engine.federation import peer_target_for_project

        found = (peer_target_for_project("aegir") or "").strip()
    except Exception:
        log.debug("aegir peer lookup failed", exc_info=True)
        found = ""
    return found or "127.0.0.1:50151"


def dial(target: str):
    channel = grpc.insecure_channel(target)
    return channel, zpb_grpc.EngineStub(channel)


def overlapping(spans: list[dict], start: int, end: int) -> list[dict]:
    return [span for span in spans if not (end <= span["start"] or start >= span["end"])]


def apply_span(span: dict, admission: dict, *, workflow_name: str, run: Callable[[str, dict], Any]) -> dict:
    """Map one admission onto one stored span and, when it qualifies, ask the workflow."""
    links = links_in_message(span["start"], span["text"], [admission])
    if not links:
        return {"links": list(span.get("links") or []), "text_len": len(span["text"])}
    piece = slice_for_mistral(span["text"], links[0])
    deliverable = None
    name = ""
    try:
        deliverable = run(piece, links[0])
        if deliverable:
            name = workflow_name
    except Exception:
        log.warning("system-one workflow failed", exc_info=True)
    fresh = attach(span["text"], links, workflow_name=name, deliverable=deliverable)["links"]
    merged = list(span.get("links") or []) + fresh
    return {"links": merged, "text_len": len(span["text"])}


def _admission(row: Any) -> dict:
    return {
        "start": int(row.start),
        "end": int(row.end),
        "genus_iri": str(row.genus_iri or ""),
        "genus_code": str(row.genus_code or ""),
        "genus_label": str(row.genus_label or ""),
        "rel_margin_h": float(row.rel_margin_h or 0.0),
        "tau": float(row.tau or 0.0),
    }


def _stamp(hermes_id: str, role: str, text: str, metadata: dict) -> None:
    from hsengine.engine.session_history import _store

    db = _store()
    if db is None:
        return
    stamp_message(db, hermes_id, text, metadata, role=role)


def _run(piece: str, link: dict) -> dict | None:
    from hsengine.engine.source_drop import run_system_one

    return run_system_one(piece, link)


class _Stream:
    def __init__(self, webrtc_id: str, hermes_id: str) -> None:
        self.webrtc_id = webrtc_id
        self.hermes_id = hermes_id
        self.seq = 0
        self.cursor = 0
        self.spans: list[dict] = []
        self.queue: queue.Queue = queue.Queue()
        self.dead = False
        self.error: BaseException | None = None
        self.run = _run
        self._mu = threading.Lock()
        self.thread: threading.Thread | None = None

    def frames(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            yield item

    def append(self, role: str, text: str) -> None:
        with self._mu:
            if self.dead:
                return
            self.seq += 1
            start = self.cursor
            self.cursor += len(text)
            self.spans.append({"start": start, "end": self.cursor, "role": role, "text": text, "links": []})
            frame = zpb.SessionText(session_id=self.webrtc_id, seq=self.seq, text=text)
        self.queue.put(frame)

    def finish(self) -> None:
        with self._mu:
            if self.dead:
                self.queue.put(None)
                return
            self.seq += 1
            seq = self.seq
            self.dead = True
        self.queue.put(zpb.SessionText(session_id=self.webrtc_id, seq=seq, text="", end=True))
        self.queue.put(None)

    def start(self, target: str, dial_fn: Callable[[str], Any]) -> None:
        def run() -> None:
            chosen = target or aegir_target()
            channel = None
            try:
                channel, stub = dial_fn(chosen)
                for row in stub.AdmitSession(self.frames()):
                    self._apply(_admission(row))
            except Exception as exc:
                self.error = None if unimplemented(exc) else exc
                if self.error is not None:
                    log.warning("admit session %s closed", self.webrtc_id, exc_info=True)
                else:
                    log.info("aegir %s does not serve AdmitSession", chosen)
            finally:
                with self._mu:
                    self.dead = True
                close = getattr(channel, "close", None)
                if callable(close):
                    close()

        self.thread = threading.Thread(target=run, name=f"admit-{self.webrtc_id}", daemon=True)
        self.thread.start()

    def _apply(self, admission: dict) -> None:
        from hsengine.engine.source_drop import SYSTEM_ONE_WORKFLOW, system_one_name

        with self._mu:
            chosen = list(overlapping(self.spans, admission["start"], admission["end"]))
        name = system_one_name() or SYSTEM_ONE_WORKFLOW
        for span in chosen:
            meta = apply_span(span, admission, workflow_name=name, run=self.run)
            with self._mu:
                span["links"] = meta["links"]
                stamped = {"links": list(span["links"]), "text_len": len(span["text"])}
            _stamp(self.hermes_id, span["role"], span["text"], stamped)


def begin(webrtc_id: str, hermes_id: str, *, target: str = "", dial_fn: Callable[[str], Any] | None = None) -> None:
    """Open the aperture stream. A second begin for the same call does nothing."""
    if not webrtc_id or not hermes_id:
        return
    with _LOCK:
        if webrtc_id in _LIVE:
            return
        stream = _Stream(webrtc_id, hermes_id)
        _LIVE[webrtc_id] = stream
    stream.start(target, dial_fn or dial)


def note(webrtc_id: str, hermes_id: str, role: str, text: str) -> None:
    """Append this turn's new characters. No open stream means no call."""
    if not webrtc_id or not text:
        return
    stream = _LIVE.get(webrtc_id)
    if stream is None:
        return
    stream.append(role, text)


def end(webrtc_id: str) -> None:
    """Flush the aperture and drop the stream. Safe when the call never opened one."""
    with _LOCK:
        stream = _LIVE.pop(webrtc_id, None)
    if stream is not None:
        stream.finish()
