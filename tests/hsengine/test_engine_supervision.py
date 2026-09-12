"""Hermes-local EngineSupervision: Subscribe, Hello, empty replay, no Postgres."""
from __future__ import annotations

import asyncio

import pytest

from hsengine.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv
from hsengine.engine.supervision_bus import init_bus
import hsengine.engine.supervision_servicer as ss
from hsengine.engine.supervision_servicer import EngineSupervisionServicer


class _Ctx:
    def __init__(self, cancel_after: int = 6):
        self._n = 0
        self._cancel_after = cancel_after

    def cancelled(self) -> bool:
        self._n += 1
        return self._n > self._cancel_after

    async def abort(self, code, details):
        raise RuntimeError(f"{code} {details}")


async def _collect(sub: sv.Subscribe, extra=None, cancel_after: int = 8) -> list[sv.EngineEvent]:
    ss.HEARTBEAT_S = 0.05
    init_bus()
    svc = EngineSupervisionServicer()

    async def msgs():
        yield sv.SupervisorMessage(subscribe=sub)
        if extra:
            yield extra
        await asyncio.sleep(0.05)

    out: list[sv.EngineEvent] = []
    async for ev in svc.Supervise(msgs(), _Ctx(cancel_after=cancel_after)):
        out.append(ev)
        if ev.HasField("replay_complete") and cancel_after <= 4:
            break
    return out


def test_subscribe_hello_and_replay_complete():
    events = asyncio.run(_collect(sv.Subscribe(supervisor_id="nautilus:hermes@test", project="hermes")))
    kinds = [ev.WhichOneof("event") for ev in events]
    assert "hello" in kinds
    assert "replay_complete" in kinds
    hello = next(ev.hello for ev in events if ev.HasField("hello"))
    assert hello.project == "hermes"
    assert "replay:ring" in list(hello.capabilities)
    assert "directive:observe_only" in list(hello.capabilities)
    rc = next(ev.replay_complete for ev in events if ev.HasField("replay_complete"))
    assert rc.clamped is False


def test_project_mismatch_goodbye():
    events = asyncio.run(_collect(
        sv.Subscribe(supervisor_id="x", project="gaius"),
        cancel_after=2,
    ))
    assert events
    assert events[0].HasField("goodbye")
    assert events[0].goodbye.reason == sv.GOODBYE_REASON_PROJECT_MISMATCH


def test_backlog_empty_without_postgres():
    init_bus()
    svc = EngineSupervisionServicer()
    resp = asyncio.run(svc.Backlog(sv.BacklogRequest(), _Ctx()))
    assert resp.project == "hermes"
    assert resp.supervisor_connected is False
    assert list(resp.rows) == []


def test_first_message_must_be_subscribe():
    async def _bad():
        init_bus()
        svc = EngineSupervisionServicer()

        async def msgs():
            yield sv.SupervisorMessage(heartbeat=sv.SupervisorHeartbeat(at_unix_ms=1))

        with pytest.raises(RuntimeError, match="NOSUBSCRIBE"):
            async for _ in svc.Supervise(msgs(), _Ctx()):
                pass

    asyncio.run(_bad())
