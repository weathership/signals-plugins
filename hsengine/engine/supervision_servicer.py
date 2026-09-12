"""zndx.supervision.v1.EngineSupervision — Hermes-local, no Postgres.

Nautilus dials Supervise on the same lattice port as Engine. This servicer:

- requires Subscribe first (#SV.00000003.NOSUBSCRIBE);
- Hello + empty-or-ring ReplayComplete + heartbeats;
- refuses actuation (observe-only) but answers every directive;
- Backlog is honest-empty (Nautilus owns the store; no warehouse here).

Innovations vs Gaius: no DB pool, no UNAVAILABLE when Postgres is absent,
capabilities advertised truthfully (replay:ring, directive:observe_only).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

import grpc
from grpc import aio

from hsengine.config import get_int, get_str
from hsengine.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv
from hsengine.engine.generated.zndx.supervision.v1 import supervision_pb2_grpc as sv_grpc
from hsengine.engine.supervision_bus import (
    KIND_ACTIVITY,
    KIND_DIRECTIVE_RESULT,
    KIND_GOODBYE,
    KIND_SERVING,
    SupervisionEvent,
    get_bus,
    init_bus,
    now_ms,
)
from hsengine.engine.supervision_spec import load_spec

log = logging.getLogger("hsengine.engine.supervision")

PROJECT = "hermes"
GURU_NOSUBSCRIBE = "#SV.00000003.NOSUBSCRIBE"
GURU_OBSERVE = "#SV.HERMES.OBSERVE"
HEARTBEAT_S = 30.0
CAPABILITIES = (
    "replay:ring",
    "directive:observe_only",
    "serving:status",
)


def _engine_build() -> str:
    try:
        from hsengine.engine import s2s
        sha = s2s._RUNNING_SHA or s2s.advertised_head()
        if sha:
            return sha[:12]
    except Exception:
        pass
    return "rch/devenv"


def _epoch() -> tuple[str, str, str]:
    spec = load_spec()
    version = spec.spec_version if spec else ""
    sha = spec.sha256 if spec else ""
    rev = _engine_build()
    return f"{version}+{rev}", version, sha


def event_to_proto(ev: SupervisionEvent, epoch: str) -> sv.EngineEvent:
    out = sv.EngineEvent(seq=ev.seq, at_unix_ms=ev.at_unix_ms, epoch=epoch, replayed=ev.replayed)
    p = ev.payload
    if ev.kind == KIND_SERVING:
        actual = str(p.get("actual") or "serving").lower()
        status = {
            "serving": sv.SERVING_STATUS_SERVING,
            "starting": sv.SERVING_STATUS_STARTING,
            "degraded": sv.SERVING_STATUS_DEGRADED,
            "failed": sv.SERVING_STATUS_FAILED,
            "absent": sv.SERVING_STATUS_ABSENT,
        }.get(actual, sv.SERVING_STATUS_SERVING)
        out.serving.CopyFrom(sv.ServingEvent(
            phase=sv.SERVING_PHASE_SETTLED,
            generation=int(p.get("generation") or 0),
            capability=str(p.get("capability") or "agent"),
            alias=str(p.get("alias") or "hermes"),
            model=str(p.get("model") or ""),
            actual=status,
            warmup_seconds=int(p.get("warmup_seconds") or 15),
            settled_unix_ms=int(p.get("settled_unix_ms") or ev.at_unix_ms),
        ))
    elif ev.kind == KIND_DIRECTIVE_RESULT:
        out.directive_result.CopyFrom(sv.DirectiveResult(
            directive_id=str(p.get("directive_id") or ""),
            accepted=bool(p.get("accepted")),
            applied=bool(p.get("applied")),
            note=str(p.get("note") or "")[:500],
            forecast_id=str(p.get("forecast_id") or ""),
            judge_status=str(p.get("judge_status") or "not_invoked"),
            at_unix_ms=ev.at_unix_ms,
        ))
    elif ev.kind == KIND_GOODBYE:
        out.goodbye.CopyFrom(sv.Goodbye(
            reason=int(p.get("reason") or sv.GOODBYE_REASON_UNSPECIFIED),
            note=str(p.get("note") or ""),
        ))
    elif ev.kind == KIND_ACTIVITY:
        # A coordination Activity as THIS engine saw it (learned from Signals
        # or declared here). The resident never reads Airflow or Signals.
        act = sv.ActivityEvent(
            activity_id=str(p.get("activity_id") or ""),
            kind=str(p.get("activity_kind") or ""),
            peer=str(p.get("peer") or ""),
            owner=str(p.get("owner") or ""),
            dag_id=str(p.get("dag_id") or ""),
            run_id=str(p.get("run_id") or ""),
            state=str(p.get("state") or ""),
            declared_ns=int(p.get("declared_ns") or 0),
            horizon_ns=int(p.get("horizon_ns") or 0),
            ended_ns=int(p.get("ended_ns") or 0),
            reason=str(p.get("reason") or "")[:500],
            transition=str(p.get("transition") or "observed"),
        )
        act.precludes.extend(str(x) for x in (p.get("precludes") or []))
        for k, v in (p.get("postures") or {}).items():
            act.postures[str(k)] = str(v)
        act.ceded.extend(str(x) for x in (p.get("ceded") or []))
        out.activity.CopyFrom(act)
    return out


class EngineSupervisionServicer(sv_grpc.EngineSupervisionServicer):
    def __init__(self) -> None:
        self._sessions: dict[str, asyncio.Queue] = {}

    async def Supervise(self, request_iterator: AsyncIterator[sv.SupervisorMessage], context: aio.ServicerContext):
        try:
            first = await request_iterator.__anext__()
        except StopAsyncIteration:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{GURU_NOSUBSCRIBE} stream closed before Subscribe")
            return
        if first.WhichOneof("message") != "subscribe":
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"{GURU_NOSUBSCRIBE} first message must be Subscribe")
            return
        sub = first.subscribe
        epoch, spec_version, spec_sha = _epoch()
        if sub.project and sub.project != PROJECT:
            yield sv.EngineEvent(
                seq=0, at_unix_ms=now_ms(), epoch=epoch,
                goodbye=sv.Goodbye(
                    reason=sv.GOODBYE_REASON_PROJECT_MISMATCH,
                    note=f"engine project is {PROJECT}",
                ),
            )
            return

        bus = get_bus() or init_bus()
        q = bus.subscribe()
        old = self._sessions.get(sub.supervisor_id)
        if old is not None and old is not q:
            bus.publish_to(
                old, KIND_GOODBYE,
                reason=sv.GOODBYE_REASON_SUPERSEDED,
                note=f"superseded by a newer Subscribe from {sub.supervisor_id}",
            )
        self._sessions[sub.supervisor_id] = q
        log.info(
            "supervision: session open id=%s since=%s resume=%s/%s",
            sub.supervisor_id, sub.since_unix_ms, sub.resume_session, sub.resume_seq,
        )
        reader: asyncio.Task | None = None
        try:
            grpc_host = get_str("hermes.engine.grpc.host") or "127.0.0.1"
            grpc_port = get_int("hermes.engine.grpc.port") or 50651
            yield sv.EngineEvent(
                seq=0, at_unix_ms=now_ms(), epoch=epoch,
                hello=sv.EngineHello(
                    project=PROJECT,
                    engine_build=_engine_build(),
                    spec_version=spec_version,
                    spec_sha256=spec_sha,
                    boot_unix_ms=int(bus.session * 1000),
                    session=int(bus.session),
                    engine_grpc=f"{grpc_host}:{grpc_port}",
                    capabilities=list(CAPABILITIES),
                ),
            )
            replayed: list[SupervisionEvent] = []
            tables: list[str] = []
            if sub.resume_session and int(sub.resume_session) == int(bus.session):
                ring = bus.ring_since(int(sub.resume_seq))
                if ring is not None:
                    replayed = ring
                    tables = ["ring"]
            for ev in replayed:
                yield event_to_proto(ev, epoch)
            yield sv.EngineEvent(
                seq=bus.seq, at_unix_ms=now_ms(), epoch=epoch,
                replay_complete=sv.ReplayComplete(
                    since_unix_ms=int(sub.since_unix_ms or 0),
                    through_seq=bus.seq,
                    events=len(replayed),
                    tables=tables,
                    clamped=False,
                ),
            )
            bus.publish(
                KIND_SERVING,
                capability="agent",
                alias="hermes",
                actual="serving",
                generation=0,
                settled_unix_ms=now_ms(),
            )
            reader = asyncio.create_task(self._pump(request_iterator, q))
            while not context.cancelled():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield sv.EngineEvent(
                        seq=bus.seq, at_unix_ms=now_ms(), epoch=epoch,
                        heartbeat=sv.EngineHeartbeat(
                            at_unix_ms=now_ms(), last_seq=bus.seq, claimed_tasks=0,
                        ),
                    )
                    continue
                yield event_to_proto(ev, epoch)
                if ev.kind == KIND_GOODBYE:
                    break
                if reader.done():
                    break
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
            bus.unsubscribe(q)
            if self._sessions.get(sub.supervisor_id) is q:
                self._sessions.pop(sub.supervisor_id, None)
            log.info("supervision: session closed id=%s", sub.supervisor_id)

    async def _pump(self, request_iterator: AsyncIterator[sv.SupervisorMessage], q: asyncio.Queue) -> None:
        bus = get_bus()
        try:
            async for msg in request_iterator:
                which = msg.WhichOneof("message")
                if which in (None, "ack", "heartbeat", "subscribe"):
                    continue
                if which in ("reclaim_orphan", "escalation", "backlog_transition"):
                    if bus is not None:
                        bus.publish_to(
                            q, KIND_DIRECTIVE_RESULT,
                            directive_id=msg.directive_id,
                            accepted=True,
                            applied=False,
                            note=f"{GURU_OBSERVE} directives=observe; no actuation",
                            judge_status="not_invoked",
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.info("supervision: reader ended: %s", e)

    async def Backlog(self, request: sv.BacklogRequest, context: aio.ServicerContext) -> sv.BacklogResponse:
        epoch, _, _ = _epoch()
        # Honest empty: Nautilus's journal is the Backlog SoR. We do not
        # warehouse cells in hsengine (no Postgres). A connected stream is
        # still a live supervisor.
        return sv.BacklogResponse(
            project=PROJECT,
            epoch=epoch,
            supervisor_connected=bool(self._sessions),
        )
