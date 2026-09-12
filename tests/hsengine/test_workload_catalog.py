"""Workload catalogue — Hermes submits what it runs to Signals.

One entry: the interactive agent-rtc workflow, source=engine (declared at
session start via DeclareActivity, never scheduled). Exposed on this engine's
ServerQuery kind=SCHEDULES and submitted with Scheduler/SyncWorkloads (replace)
at start and every 30 min. Peers only ever see the Signals gRPC port.
"""
from __future__ import annotations

import asyncio
import time
from concurrent import futures

import grpc
import pytest

from hsengine.engine import coordination, s2s, workload_catalog as wc
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc
from hsengine.engine.yk_sentinel import (
    CEREBRAS_QUEUE,
    COMPUTE_QUEUE,
    QUEUE as AGENT_RTC_QUEUE,
    interactive_yk_claims,
)


class FakeScheduler(spb_grpc.SchedulerServicer):
    def __init__(self) -> None:
        self.syncs: list[spb.SyncWorkloadsRequest] = []
        self.declares: list[spb.DeclareActivityRequest] = []
        self.refuse = ""
        self.unimplemented = False

    def ListActivities(self, request, context):  # noqa: N802
        return spb.ListActivitiesResponse()

    def DeclareActivity(self, request, context):  # noqa: N802
        self.declares.append(request)
        a = zpb.Activity(
            activity_id="act-0001", kind=request.kind, peer=request.peer, owner=request.owner,
            dag_id="coord_interactive_session", run_id="act-0001", state=zpb.ACTIVITY_RUNNING,
            declared_ns=time.time_ns(), horizon_ns=request.horizon_ns,
        )
        a.claims.extend(request.claims)
        for k, v in request.postures.items():
            a.postures[k] = v
        return spb.ActivityResponse(accepted=True, activity=a)

    def SyncWorkloads(self, request, context):  # noqa: N802
        if self.unimplemented:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "Method not implemented!")
        self.syncs.append(request)
        if self.refuse:
            return spb.SyncWorkloadsResponse(accepted=False, error=self.refuse)
        recs = [
            spb.WorkloadRecord(
                workload=w, peer=request.peer, dag_id="",
                synced_ns=time.time_ns(),
                state="engine_declared" if w.source == "engine" else "materialized",
            )
            for w in request.workloads
        ]
        return spb.SyncWorkloadsResponse(accepted=True, records=recs)

    def ListWorkloads(self, request, context):  # noqa: N802
        last = self.syncs[-1] if self.syncs else None
        recs = [spb.WorkloadRecord(workload=w, peer=last.peer, state="engine_declared") for w in last.workloads] if last else []
        return spb.ListWorkloadsResponse(records=recs, observed_ns=time.time_ns())


@pytest.fixture
def signals():
    fake = FakeScheduler()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    spb_grpc.add_SchedulerServicer_to_server(fake, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    fake.addr = f"127.0.0.1:{port}"
    yield fake
    server.stop(0)


@pytest.fixture(autouse=True)
def _reset():
    wc.set_sync(None)
    yield
    wc.set_sync(None)


# ── the catalogue ─────────────────────────────────────────────────────────────

def test_catalogue_is_the_interactive_workflow_declared_by_the_engine():
    entries = wc.catalog()
    assert [e.id for e in entries] == ["interactive.agent_rtc"]
    e = entries[0]
    assert e.kind == coordination.KIND_INTERACTIVE == "interactive_session"
    assert e.source == "engine" and e.runner == "interactive"
    assert e.cron == "" and e.airflow_dag_id == "" and e.enabled is True
    assert e.horizon_s == coordination.interactive_horizon_s() == 3600
    assert e.timezone == "UTC"
    assert "agent-rtc" in e.description and "only while a session runs" in e.description
    assert [(c.leaf, c.gpu) for c in e.claims] == list(interactive_yk_claims())
    assert (AGENT_RTC_QUEUE, 1) in [(c.leaf, c.gpu) for c in e.claims]
    assert (CEREBRAS_QUEUE, 0) in [(c.leaf, c.gpu) for c in e.claims]
    assert (COMPUTE_QUEUE, 0) in [(c.leaf, c.gpu) for c in e.claims]
    assert all(c.gpu == 0 for c in e.claims if c.leaf != AGENT_RTC_QUEUE)
    assert dict(e.postures) == coordination.interactive_postures() == {}
    assert list(e.precludes) == coordination.interactive_precludes() == []


def test_catalogue_claims_match_what_declare_interactive_puts_on_the_activity(signals):
    """The catalogue entry's claims ARE the queue config the session asserts:
    what SyncWorkloads catalogues must equal what DeclareActivity claims."""
    lease = coordination.declare_interactive("webrtc", horizon_s=60, addr=signals.addr)
    assert lease is not None
    declared = [(c.leaf, c.gpu) for c in signals.declares[0].claims]
    catalogued = [(c.leaf, c.gpu) for c in wc.interactive_entry().claims]
    assert declared == catalogued == list(interactive_yk_claims())
    assert dict(signals.declares[0].postures) == dict(wc.interactive_entry().postures) == {}


def test_server_query_schedules_serves_the_catalogue():
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_SCHEDULES)
    assert resp.project == "hermes"
    assert [(s.id, s.kind, s.source, s.runner) for s in resp.schedules] == [
        ("interactive.agent_rtc", "interactive_session", "engine", "interactive")
    ]
    assert [(c.leaf, c.gpu) for c in resp.schedules[0].claims] == list(interactive_yk_claims())
    # other kinds do not carry schedules
    assert list(s2s.local_response(zpb.SERVER_QUERY_KIND_ACTIVITIES).schedules) == []


# ── submission ────────────────────────────────────────────────────────────────

def test_sync_once_submits_the_whole_catalogue_as_a_replace(signals):
    resp = wc.sync_once(signals.addr, engine_build="abc123")
    assert resp.accepted
    assert len(signals.syncs) == 1
    req = signals.syncs[0]
    assert req.peer == "hermes" and req.replace is True and req.engine_build == "abc123"
    assert [w.id for w in req.workloads] == ["interactive.agent_rtc"]
    assert [(r.workload.id, r.state) for r in resp.records] == [("interactive.agent_rtc", "engine_declared")]


def test_sync_refused_and_unreachable_carry_the_guru(signals):
    signals.refuse = "#CO.00000001.UNKNOWNPEER unknown peer hermes"
    with pytest.raises(RuntimeError, match=r"#HS\.COORD\.00000006\.SYNCFAIL.*unknown peer"):
        wc.sync_once(signals.addr, engine_build="x")
    with pytest.raises(RuntimeError, match=r"#HS\.COORD\.00000006\.SYNCFAIL"):
        wc.sync_once("127.0.0.1:1", engine_build="x")


def test_sync_unimplemented_is_reraised_for_the_loop_to_back_off(signals):
    signals.unimplemented = True
    with pytest.raises(grpc.RpcError) as ei:
        wc.sync_once(signals.addr, engine_build="x")
    assert ei.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_sync_loop_step_paces_success_and_failures(signals, monkeypatch):
    monkeypatch.setattr(wc, "_engine_build", lambda: "deadbeef")
    s = wc.WorkloadSync(signals.addr)
    assert asyncio.run(s.step()) == wc.SYNC_INTERVAL_S == 1800.0
    assert s.synced_at > 0 and s.last_error == ""
    assert [r.workload.id for r in s.records] == ["interactive.agent_rtc"]
    assert signals.syncs[-1].engine_build == "deadbeef"
    assert s.status()["records"][0]["state"] == "engine_declared"
    # an older Signals: UNIMPLEMENTED → retry cadence, logged once
    signals.unimplemented = True
    assert asyncio.run(s.step()) == wc.SYNC_RETRY_S == 300.0
    assert s.last_error == "UNIMPLEMENTED" and s._unimpl_logged is True
    assert asyncio.run(s.step()) == wc.SYNC_RETRY_S
    # refused → retry cadence with the guru recorded
    signals.unimplemented = False
    signals.refuse = "nope"
    assert asyncio.run(s.step()) == wc.SYNC_RETRY_S
    assert "SYNCFAIL" in s.last_error
    # recovery resets the once-only UNIMPLEMENTED log
    signals.refuse = ""
    assert asyncio.run(s.step()) == wc.SYNC_INTERVAL_S
    assert s._unimpl_logged is False and s.last_error == ""


def test_start_sync_is_idempotent_and_honours_the_config(monkeypatch, signals):
    async def go():
        a = wc.start_sync(signals.addr)
        b = wc.start_sync(signals.addr)
        assert a is b and a is not None and a._task is not None
        await asyncio.sleep(0.3)  # the first step runs at start
        a._task.cancel()
        return a

    s = asyncio.run(go())
    assert len(signals.syncs) >= 1 and signals.syncs[0].replace is True
    wc.set_sync(None)
    monkeypatch.setattr(wc, "sync_enabled", lambda: False)

    async def off():
        return wc.start_sync(signals.addr)

    assert asyncio.run(off()) is None
