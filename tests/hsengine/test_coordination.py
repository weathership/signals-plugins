"""Coordination Activities — hsengine declares the interactive session to Signals.

Two hops, never one: interactive.enter() (inside the engine process) → this
engine's coordination client → Signals Scheduler. No Yield at a peer. The
engine re-exposes Activities on ServerQuery ACTIVITIES and as ActivityEvents.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent import futures

import grpc
import pytest

from hsengine.engine import coordination, interactive, s2s
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc
from hsengine.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv
from hsengine.engine.supervision_bus import KIND_ACTIVITY, SupervisionEvent, get_bus, init_bus
from hsengine.engine.supervision_servicer import event_to_proto
from hsengine.engine.yk_sentinel import QUEUE as AGENT_RTC_QUEUE, interactive_yk_claims


# ── fake Signals scheduler ────────────────────────────────────────────────────

class FakeScheduler(spb_grpc.SchedulerServicer):
    """Records requests; answers like Signals would (Airflow behind it is faked)."""

    def __init__(self) -> None:
        self.declares: list[spb.DeclareActivityRequest] = []
        self.renews: list[spb.RenewActivityRequest] = []
        self.releases: list[spb.ReleaseActivityRequest] = []
        self.watch_events: list[list[zpb.Activity]] = []
        self.watch_hold = threading.Event()
        self._n = 0
        self.refuse = ""
        self.listed: list[zpb.Activity] = []

    def _activity(self, req, *, state, run_n: int, horizon_ns: int, ended_ns: int = 0, note: str = "") -> zpb.Activity:
        a = zpb.Activity(
            activity_id=f"act-{self._n:04d}",
            kind=req.kind if hasattr(req, "kind") and req.kind else "interactive_session",
            peer=req.peer,
            owner=getattr(req, "owner", "") or "webrtc",
            dag_id="coord_activity",
            run_id=f"act-{self._n:04d}-{run_n}",
            state=state,
            declared_ns=time.time_ns(),
            horizon_ns=horizon_ns,
            ended_ns=ended_ns,
            reason=getattr(req, "reason", "") or "",
            note=note,
        )
        return a

    def DeclareActivity(self, request, context):  # noqa: N802
        self.declares.append(request)
        if self.refuse:
            return spb.ActivityResponse(accepted=False, error=self.refuse)
        self._n += 1
        a = self._activity(request, state=zpb.ACTIVITY_RUNNING, run_n=1, horizon_ns=request.horizon_ns)
        a.claims.extend(request.claims)
        a.precludes.extend(request.precludes)
        for k, v in request.postures.items():
            a.postures[k] = v
        self.last = a
        return spb.ActivityResponse(accepted=True, activity=a)

    def RenewActivity(self, request, context):  # noqa: N802
        self.renews.append(request)
        a = zpb.Activity()
        a.CopyFrom(self.last)
        a.run_id = f"{request.activity_id}-{len(self.renews) + 1}"
        a.horizon_ns = request.horizon_ns
        a.renewed_ns = time.time_ns()
        self.last = a
        return spb.ActivityResponse(accepted=True, activity=a)

    def ReleaseActivity(self, request, context):  # noqa: N802
        self.releases.append(request)
        a = zpb.Activity(activity_id=request.activity_id, state=zpb.ACTIVITY_RELEASED, ended_ns=time.time_ns())
        if getattr(self, "last", None) is not None:
            a.CopyFrom(self.last)
            a.activity_id = request.activity_id
            a.state = zpb.ACTIVITY_RELEASED
            a.ended_ns = time.time_ns()
        a.note = f"released by {request.peer}: {request.outcome}"
        return spb.ActivityResponse(accepted=True, activity=a)

    def ListActivities(self, request, context):  # noqa: N802
        return spb.ListActivitiesResponse(activities=list(self.listed), observed_ns=time.time_ns())

    def WatchActivities(self, request, context):  # noqa: N802
        for acts in self.watch_events:
            yield spb.ActivityWatchEvent(activities=acts, observed_ns=time.time_ns())
        self.watch_hold.wait(5.0)


@pytest.fixture
def signals():
    fake = FakeScheduler()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    spb_grpc.add_SchedulerServicer_to_server(fake, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    fake.addr = f"127.0.0.1:{port}"
    yield fake
    fake.watch_hold.set()
    server.stop(0)


@pytest.fixture(autouse=True)
def _reset_state():
    with interactive._mu:
        interactive._refcount = 0
        interactive._active = False
        interactive._lease = None
    coordination.set_watcher(None)
    coordination.bind_loop(None)
    init_bus()
    yield
    with interactive._mu:
        interactive._refcount = 0
        interactive._active = False
        interactive._lease = None
    coordination.set_watcher(None)
    coordination.bind_loop(None)


# ── identity ──────────────────────────────────────────────────────────────────

def test_uuid7_is_version_7_and_time_ordered():
    a, b = coordination.uuid7(), coordination.uuid7()
    ua, ub = uuid.UUID(a), uuid.UUID(b)
    assert ua.version == 7 and ub.version == 7
    assert ua.variant == uuid.RFC_4122
    assert (ua.int >> 80) <= (ub.int >> 80)  # 48-bit ms prefix never goes backwards


# ── declare / renew / release shapes ─────────────────────────────────────────

def test_declare_interactive_request_shape(signals):
    before = time.time_ns()
    lease = coordination.declare_interactive("webrtc:abc123", horizon_s=1800, addr=signals.addr)
    req = signals.declares[0]
    assert req.peer == "hermes"
    assert req.kind == "interactive_session"
    assert req.owner == "webrtc:abc123"
    assert uuid.UUID(req.request_id).version == 7
    assert [(c.leaf, c.gpu) for c in req.claims] == list(interactive_yk_claims())
    assert dict(req.postures) == {}
    assert list(req.precludes) == []
    assert "interactive" in req.reason
    assert before + 1799 * 10**9 < req.horizon_ns <= time.time_ns() + 1800 * 10**9
    assert lease.activity["state"] == "running"
    assert lease.activity["run_id"].endswith("-1")
    assert lease.horizon_s == 1800
    assert [(c["leaf"], c["gpu"]) for c in lease.activity["claims"]] == list(interactive_yk_claims())


def test_renew_moves_the_horizon_forward_and_release_carries_outcome(signals):
    lease = coordination.declare_interactive("webrtc", horizon_s=600, addr=signals.addr)
    h0 = signals.declares[0].horizon_ns
    time.sleep(0.01)
    lease.renew()
    assert signals.renews[0].activity_id == lease.activity_id
    assert signals.renews[0].peer == "hermes"
    assert signals.renews[0].horizon_ns > h0
    assert lease.renewals == 1
    assert lease.activity["run_id"].endswith("-2")
    out = lease.release("hangup")
    assert signals.releases[0].outcome == "hangup"
    assert signals.releases[0].activity_id == lease.activity_id
    assert out["state"] == "released"


def test_renew_loop_heartbeats_under_the_lease_ttl(signals):
    # Airflow observes the Signals-held lease: the loop must HEARTBEAT at
    # heartbeat_s (60 s default, well under the 180 s TTL), never at the
    # half-horizon (1800 s for a 3600 s session — that would lapse the lease).
    lease = coordination.declare_interactive("webrtc", horizon_s=3600, addr=signals.addr)
    lease.heartbeat_s = 1
    lease.start_renewing()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not signals.renews:
        time.sleep(0.05)
    lease.release("done")
    assert signals.renews, "heartbeat loop never fired at heartbeat_s with a 3600 s horizon"
    # every heartbeat re-sets the horizon to now + horizon_s
    assert signals.renews[0].horizon_ns > coordination.now_ns() + 3000 * 1_000_000_000


def test_default_heartbeat_is_well_under_signals_lease_ttl():
    assert coordination.DEFAULT_HEARTBEAT_S == 60
    assert coordination.interactive_heartbeat_s() * 3 <= 180


def test_declare_unreachable_signals_is_denied_with_guru():
    with pytest.raises(RuntimeError, match=coordination.GURU_DECLAREFAIL.replace(".", r"\.")):
        coordination.declare_interactive("webrtc", horizon_s=60, addr="127.0.0.1:1")


def test_declare_releases_stale_in_force_interactive(signals):
    stale = zpb.Activity(
        activity_id="old-act",
        kind="interactive_session",
        peer="hermes",
        state=zpb.ACTIVITY_RUNNING,
    )
    signals.listed = [stale]
    coordination.declare_interactive("webrtc", horizon_s=60, addr=signals.addr)
    assert signals.releases[0].activity_id == "old-act"
    assert signals.releases[0].outcome == "reconnect"
    assert len(signals.declares) == 1


def test_declare_refused_by_signals_is_denied(signals):
    signals.refuse = "#YK.00000007.SHAREFAIL unknown peer hermes"
    with pytest.raises(RuntimeError, match="unknown peer"):
        coordination.declare_interactive("webrtc", horizon_s=60, addr=signals.addr)


def test_declare_publishes_activity_event_on_bus(signals):
    bus = get_bus()
    q = bus.subscribe()
    coordination.declare_interactive("webrtc", horizon_s=60, addr=signals.addr)
    ev = q.get_nowait()
    assert ev.kind == KIND_ACTIVITY
    assert ev.payload["transition"] == "declared"
    assert ev.payload["activity_kind"] == "interactive_session"
    assert ev.payload["postures"] == {}
    assert ev.payload["ceded"] == []


# ── interactive.enter / leave sequencing ──────────────────────────────────────

class _Lease:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.activity = {
            "activity_id": "act-x",
            "state": "running",
            "claims": [{"leaf": AGENT_RTC_QUEUE, "gpu": 1}],
        }
        self.activity_id = "act-x"
        self.released: list[str] = []

    def start_renewing(self) -> None:
        self.calls.append("renew_loop")

    def release(self, outcome: str) -> None:
        self.calls.append(f"release:{outcome}")
        self.released.append(outcome)


def _wire(monkeypatch, calls: list[str], *, moshi_fails: bool = False) -> _Lease:
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    lease = _Lease(calls)

    def _declare(owner, *a, **k):
        calls.append(f"declare:{owner}")
        return lease

    monkeypatch.setattr(interactive.coordination, "declare_interactive", _declare)

    def _moshi_on():
        calls.append("moshi_on")
        if moshi_fails:
            raise RuntimeError("moshi supervisor 503: no GPU")

    monkeypatch.setattr(interactive, "_moshi_on", _moshi_on)
    monkeypatch.setattr(interactive, "_moshi_off", lambda: calls.append("moshi_off"))
    return lease


def test_enter_declares_before_moshi_and_leave_releases(monkeypatch):
    calls: list[str] = []
    _wire(monkeypatch, calls)
    interactive.enter(owner="webrtc:s1")
    assert interactive.is_active()
    assert calls.index("declare:webrtc:s1") < calls.index("moshi_on")
    assert "sentinel" not in calls
    assert calls[-1] == "renew_loop"
    assert interactive.current_activity()["activity_id"] == "act-x"
    interactive.enter(owner="webrtc:s2")  # second session: refcount only
    assert calls.count("declare:webrtc:s1") == 1 and "declare:webrtc:s2" not in calls
    interactive.leave()
    assert interactive.is_active()  # one session still up
    interactive.leave()
    assert not interactive.is_active()
    assert calls[-2:] == ["moshi_off", "release:hangup"]
    assert interactive.current_activity() is None


def test_enter_failure_releases_the_declared_activity(monkeypatch):
    calls: list[str] = []
    lease = _wire(monkeypatch, calls, moshi_fails=True)
    with pytest.raises(RuntimeError, match="moshi supervisor 503"):
        interactive.enter()
    assert not interactive.is_active()
    assert lease.released and lease.released[0].startswith("aborted: moshi supervisor 503")
    assert "renew_loop" not in calls


def test_enter_denied_when_declare_fails_touches_nothing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    def _declare(owner, *a, **k):
        raise RuntimeError(f"{coordination.GURU_DECLAREFAIL} DeclareActivity at Signals engine 127.0.0.1:50551 failed")

    monkeypatch.setattr(interactive.coordination, "declare_interactive", _declare)
    monkeypatch.setattr(interactive, "_moshi_on", lambda: calls.append("moshi_on"))
    monkeypatch.setattr(interactive, "_moshi_off", lambda: calls.append("moshi_off"))
    with pytest.raises(RuntimeError, match="DECLAREFAIL"):
        interactive.enter()
    assert "moshi_on" not in calls
    assert not interactive.is_active()


def test_enter_denied_when_signals_omits_workload_claims(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")

    class Blank:
        activity = {"activity_id": "act-x", "state": "running", "claims": []}
        activity_id = "act-x"
        released: list[str] = []

        def start_renewing(self) -> None:
            calls.append("renew_loop")

        def release(self, outcome: str) -> None:
            calls.append(f"release:{outcome}")
            self.released.append(outcome)

    blank = Blank()
    monkeypatch.setattr(interactive.coordination, "declare_interactive", lambda *a, **k: blank)
    monkeypatch.setattr(interactive, "_moshi_on", lambda: calls.append("moshi_on"))
    monkeypatch.setattr(interactive, "_moshi_off", lambda: calls.append("moshi_off"))
    with pytest.raises(RuntimeError, match="did not echo the agent-rtc workload claims"):
        interactive.enter()
    assert "moshi_on" not in calls
    assert "renew_loop" not in calls
    assert any(c.startswith("release:aborted") for c in calls)
    assert not interactive.is_active()


def test_interactive_no_longer_yields_at_a_peer():
    import inspect

    src = inspect.getsource(interactive)
    assert "Yield" not in src
    assert "_yield_gaius_thinking" not in src
    assert "_gaius_target" not in src
    assert "engine_pb2_grpc" not in src  # no peer Engine stub in the interactive module
    cfg = (interactive.__file__.rsplit("/hsengine/", 1)[0]) + "/config/base.conf"
    with open(cfg, encoding="utf-8") as fh:
        assert "thinking_workload" not in fh.read()


# ── supervision face ──────────────────────────────────────────────────────────

def test_activity_event_to_proto():
    ev = SupervisionEvent(
        seq=7, at_unix_ms=1, kind=KIND_ACTIVITY,
        payload={
            "activity_id": "act-1", "activity_kind": "interactive_session", "peer": "hermes", "owner": "webrtc:s1",
            "dag_id": "coord_activity", "run_id": "act-1-1", "state": "running",
            "declared_ns": 10, "horizon_ns": 20, "ended_ns": 0,
            "precludes": ["root.internal.inference.heavy"],
            "postures": {"gaius.endpoint.thinking": "hold-uptime"},
            "reason": "r", "transition": "started", "ceded": [],
        },
    )
    out = event_to_proto(ev, "epoch")
    assert out.WhichOneof("event") == "activity"
    a = out.activity
    assert a.activity_id == "act-1" and a.state == "running" and a.transition == "started"
    assert a.kind == "interactive_session"
    assert a.postures["gaius.endpoint.thinking"] == "hold-uptime"
    assert list(a.precludes) == ["root.internal.inference.heavy"]
    assert list(a.ceded) == []


# ── watcher + ServerQuery ACTIVITIES ──────────────────────────────────────────

def _act(aid: str, state: int, *, run: int = 1, horizon_ns: int | None = None) -> zpb.Activity:
    return zpb.Activity(
        activity_id=aid, kind="interactive_session", peer="hermes", owner="webrtc",
        dag_id="coord_activity", run_id=f"{aid}-{run}", state=state,
        declared_ns=time.time_ns(), horizon_ns=horizon_ns or (time.time_ns() + 3600 * 10**9),
    )


def test_watcher_replaces_view_and_publishes_transitions(signals):
    signals.watch_events = [
        [_act("a1", zpb.ACTIVITY_RUNNING)],
        [_act("a1", zpb.ACTIVITY_RUNNING, run=2), _act("a2", zpb.ACTIVITY_QUEUED)],
        [_act("a1", zpb.ACTIVITY_RELEASED, run=2)],
    ]

    async def _run():
        bus = get_bus()
        q = bus.subscribe()
        w = coordination.ActivityWatcher(signals.addr)
        task = w.start()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and w.events < 3:
            await asyncio.sleep(0.02)
        task.cancel()
        transitions = []
        while not q.empty():
            ev = q.get_nowait()
            transitions.append((ev.payload["activity_id"], ev.payload["transition"]))
        return w, transitions

    w, transitions = asyncio.run(_run())
    assert w.events == 3
    assert ("a1", "started") in transitions
    assert ("a1", "renewed") in transitions
    assert ("a2", "observed") in transitions
    assert ("a1", "released") in transitions
    view = {a["activity_id"]: a for a in w.view()}
    assert view["a1"]["state"] == "released" and "a2" not in view  # replaced, not merged


def test_server_query_activities_serves_the_engine_view():
    w = coordination.ActivityWatcher("127.0.0.1:1")
    w.connected = True
    w.apply([coordination.activity_to_dict(_act("a9", zpb.ACTIVITY_RUNNING))], time.time_ns())
    coordination.set_watcher(w)
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_ACTIVITIES)
    assert resp.project == "hermes"
    assert [(a.activity_id, a.state) for a in resp.activities] == [("a9", zpb.ACTIVITY_RUNNING)]
    coordination.set_watcher(None)
    assert list(s2s.local_response(zpb.SERVER_QUERY_KIND_ACTIVITIES).activities) == []


def test_disconnected_view_drops_in_force_entries_past_horizon():
    w = coordination.ActivityWatcher("127.0.0.1:1")
    w.connected = True
    past = time.time_ns() - 10**9
    w.apply([
        coordination.activity_to_dict(_act("old", zpb.ACTIVITY_RUNNING, horizon_ns=past)),
        coordination.activity_to_dict(_act("live", zpb.ACTIVITY_RUNNING)),
    ], time.time_ns())
    assert {a["activity_id"] for a in w.view()} == {"old", "live"}
    w.connected = False
    assert {a["activity_id"] for a in w.view()} == {"live"}  # the horizon is the safety


def test_config_defaults_for_the_activity():
    assert coordination.interactive_horizon_s() == 3600
    assert coordination.interactive_precludes() == []
    assert coordination.interactive_postures() == {}
    assert coordination.target().endswith(":50551")
    assert coordination.watch_enabled() is True
