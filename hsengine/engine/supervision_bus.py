"""In-process bus for EngineSupervision.Supervise. No protobuf, no Postgres.

Doctrine: bookkeeping never disturbs the run. publish() is sync, never raises,
drops the oldest event of a slow subscriber (#SV.00000002.BUSDROP).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("hsengine.engine.supervision_bus")

GURU_BUSDROP = "#SV.00000002.BUSDROP"
QUEUE_MAXSIZE = 512
RING_MAXLEN = 4096

KIND_TASK = "task"
KIND_ADMISSION = "admission"
KIND_POSITION = "position"
KIND_OBJECTIVE = "objective"
KIND_INCIDENT = "incident"
KIND_SERVING = "serving"
KIND_DIRECTIVE_RESULT = "directive_result"
KIND_GOODBYE = "goodbye"
KIND_ACTIVITY = "activity"  # coordination Activities as this engine saw them (ActivityEvent)


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class SupervisionEvent:
    seq: int
    at_unix_ms: int
    kind: str
    payload: dict[str, Any]
    replayed: bool = False


@dataclass
class _SubStats:
    delivered: int = 0
    dropped: int = 0


@dataclass
class SupervisionBus:
    _seq: int = 0
    _subs: dict[int, tuple[asyncio.Queue, _SubStats]] = field(default_factory=dict)
    _ring: deque = field(default_factory=lambda: deque(maxlen=RING_MAXLEN))
    _dropped_total: int = 0
    session: int = field(default_factory=lambda: int(time.time()))

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subs[id(q)] = (q, _SubStats())
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.pop(id(q), None)

    def publish(self, kind: str, *, at_unix_ms: int | None = None, **payload: Any) -> SupervisionEvent:
        self._seq += 1
        ev = SupervisionEvent(
            seq=self._seq,
            at_unix_ms=int(at_unix_ms if at_unix_ms is not None else now_ms()),
            kind=kind,
            payload=dict(payload),
        )
        self._ring.append(ev)
        for q, stats in list(self._subs.values()):
            self._offer(q, stats, ev)
        return ev

    def publish_to(
        self, q: asyncio.Queue, kind: str, *, at_unix_ms: int | None = None, **payload: Any
    ) -> SupervisionEvent | None:
        self._seq += 1
        ev = SupervisionEvent(
            seq=self._seq,
            at_unix_ms=int(at_unix_ms if at_unix_ms is not None else now_ms()),
            kind=kind,
            payload=dict(payload),
        )
        self._ring.append(ev)
        stats = self._subs.get(id(q), (None, _SubStats()))[1]
        self._offer(q, stats, ev)
        return ev

    def ring_since(self, seq: int) -> list[SupervisionEvent] | None:
        if not self._ring:
            return []
        oldest = self._ring[0].seq
        if seq > 0 and seq < oldest:
            return None
        return [SupervisionEvent(
            seq=ev.seq, at_unix_ms=ev.at_unix_ms, kind=ev.kind,
            payload=ev.payload, replayed=True,
        ) for ev in self._ring if ev.seq > seq]

    @property
    def seq(self) -> int:
        return self._seq

    def _offer(self, q: asyncio.Queue, stats: _SubStats, ev: SupervisionEvent) -> None:
        try:
            q.put_nowait(ev)
            stats.delivered += 1
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
            stats.dropped += 1
            self._dropped_total += 1
            if self._dropped_total % 100 == 1:
                log.warning("%s dropped %s events (slow subscriber)", GURU_BUSDROP, self._dropped_total)


_BUS: SupervisionBus | None = None


def init_bus() -> SupervisionBus:
    global _BUS
    _BUS = SupervisionBus()
    return _BUS


def get_bus() -> SupervisionBus | None:
    return _BUS
