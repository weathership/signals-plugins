"""Coordination Activities — hsengine's face on ``zndx.scheduler.v1`` at Signals.

An Activity is inter-project intent with a lifetime (signals-protocol
``specification/protocol/coordination_activities.md``): Signals materialises
it as a run of its own Airflow DAG and is the ONLY party that talks to
Airflow. Two hops, never one: Hermes's local processes (the interactive
session, the Nautilus resident) speak only to THIS engine; this engine is the
federated peer that declares, renews, releases and watches at the Signals
engine (``hermes.engine.coordination.target``), and re-exposes what it learns
on ``Engine/ServerQuery kind=ACTIVITIES`` and as supervision ``ActivityEvent``s.

Declare is fail-fast: a session that cannot be declared is DENIED, never
entered undeclared. Release failure is logged, not raised — the horizon is the
protocol's own release-by-absence, not a silent fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import grpc

from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc
from hsengine.engine.supervision_bus import get_bus

log = logging.getLogger("hsengine.engine.coordination")

PEER = "hermes"
KIND_INTERACTIVE = "interactive_session"
KIND_ACTIVITY = "activity"  # supervision bus kind (mirrored in supervision_bus)

GURU_DECLAREFAIL = "#HS.COORD.00000001.DECLAREFAIL"
GURU_RENEWFAIL = "#HS.COORD.00000002.RENEWFAIL"
GURU_RELEASEFAIL = "#HS.COORD.00000003.RELEASEFAIL"
GURU_WATCHDOWN = "#HS.COORD.00000004.WATCHDOWN"
GURU_WATCHUNIMPL = "#HS.COORD.00000005.WATCHUNIMPLEMENTED"

DEFAULT_TARGET = "127.0.0.1:50551"
DEFAULT_HORIZON_S = 3600
DEFAULT_HEARTBEAT_S = 60  # lease heartbeat cadence; Signals' lease TTL is 180 s
RPC_TIMEOUT_S = 15.0
WATCH_SILENCE_S = 150.0        # Signals heartbeats every ≤ 60 s; silence past this = dead stream
WATCH_UNIMPLEMENTED_RETRY_S = 300.0
WATCH_BACKOFF_MAX_S = 60.0
RENEW_RETRY_S = 30.0

_STATE_NAMES = {
    zpb.ACTIVITY_STATE_UNSPECIFIED: "unspecified",
    zpb.ACTIVITY_QUEUED: "queued",
    zpb.ACTIVITY_RUNNING: "running",
    zpb.ACTIVITY_RELEASED: "released",
    zpb.ACTIVITY_EXPIRED: "expired",
    zpb.ACTIVITY_FAILED: "failed",
    zpb.ACTIVITY_SUPERSEDED: "superseded",
}
_STATE_VALUES = {v: k for k, v in _STATE_NAMES.items()}
IN_FORCE = ("queued", "running")


# ── config ────────────────────────────────────────────────────────────────────

def _cfg(path: str, default: Any) -> Any:
    try:
        from hsengine.config import load_config

        value = load_config().get(path)
    except Exception:
        return default
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


def target() -> str:
    return str(_cfg("hermes.engine.coordination.target", DEFAULT_TARGET)).replace("grpc://", "").strip()


def watch_enabled() -> bool:
    raw = str(_cfg("hermes.engine.coordination.watch", "true")).strip().lower()
    return raw not in ("0", "false", "no", "off")


def interactive_horizon_s() -> int:
    try:
        v = int(str(_cfg("hermes.engine.webrtc.interactive.activity_horizon_s", DEFAULT_HORIZON_S)))
    except (TypeError, ValueError):
        v = DEFAULT_HORIZON_S
    return v if v > 0 else DEFAULT_HORIZON_S


def interactive_heartbeat_s() -> int:
    """Lease heartbeat cadence. Airflow OBSERVES the session: the Signals-held
    lease lapses when heartbeats stop (lease TTL 180 s at Signals), so this must
    be well under the TTL — 60 s. The horizon is the session's outer bound."""
    try:
        v = int(str(_cfg("hermes.engine.webrtc.interactive.activity_heartbeat_s", DEFAULT_HEARTBEAT_S)))
    except (TypeError, ValueError):
        v = DEFAULT_HEARTBEAT_S
    return v if v > 0 else DEFAULT_HEARTBEAT_S


def interactive_precludes() -> list[str]:
    raw = _cfg("hermes.engine.webrtc.interactive.activity_precludes", [])
    return [str(x).strip() for x in list(raw or []) if str(x).strip()]


def interactive_postures() -> dict[str, str]:
    # Empty: Gaius thinking (heavy TP=4) stays up while Cerebras does dialog.
    raw = _cfg(
        "hermes.engine.webrtc.interactive.activity_postures",
        [],
    )
    out: dict[str, str] = {}
    for item in list(raw or []):
        key, sep, val = str(item).partition("=")
        if sep and key.strip() and val.strip():
            out[key.strip()] = val.strip()
    return out


# ── identity ──────────────────────────────────────────────────────────────────

def uuid7() -> str:
    """RFC 9562 UUIDv7 (48-bit unix ms, version 7, variant 10). Python 3.11 lacks one."""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    hexs = f"{value:032x}"
    return f"{hexs[:8]}-{hexs[8:12]}-{hexs[12:16]}-{hexs[16:20]}-{hexs[20:]}"


def now_ns() -> int:
    return time.time_ns()


# ── shapes ────────────────────────────────────────────────────────────────────

def state_name(state: int) -> str:
    return _STATE_NAMES.get(int(state), "unspecified")


def activity_to_dict(a: zpb.Activity) -> dict[str, Any]:
    return {
        "activity_id": a.activity_id,
        "kind": a.kind,
        "peer": a.peer,
        "owner": a.owner,
        "dag_id": a.dag_id,
        "run_id": a.run_id,
        "state": state_name(a.state),
        "declared_ns": int(a.declared_ns),
        "horizon_ns": int(a.horizon_ns),
        "renewed_ns": int(a.renewed_ns),
        "ended_ns": int(a.ended_ns),
        "claims": [{"leaf": c.leaf, "gpu": int(c.gpu)} for c in a.claims],
        "precludes": list(a.precludes),
        "postures": dict(a.postures),
        "reason": a.reason,
        "note": a.note,
    }


def dict_to_activity(d: dict[str, Any]) -> zpb.Activity:
    out = zpb.Activity(
        activity_id=str(d.get("activity_id") or ""),
        kind=str(d.get("kind") or ""),
        peer=str(d.get("peer") or ""),
        owner=str(d.get("owner") or ""),
        dag_id=str(d.get("dag_id") or ""),
        run_id=str(d.get("run_id") or ""),
        state=_STATE_VALUES.get(str(d.get("state") or ""), zpb.ACTIVITY_STATE_UNSPECIFIED),
        declared_ns=int(d.get("declared_ns") or 0),
        horizon_ns=int(d.get("horizon_ns") or 0),
        renewed_ns=int(d.get("renewed_ns") or 0),
        ended_ns=int(d.get("ended_ns") or 0),
        reason=str(d.get("reason") or ""),
        note=str(d.get("note") or ""),
    )
    for c in d.get("claims") or []:
        out.claims.append(zpb.ActivityClaim(leaf=str(c.get("leaf") or ""), gpu=int(c.get("gpu") or 0)))
    out.precludes.extend(str(x) for x in (d.get("precludes") or []))
    for k, v in (d.get("postures") or {}).items():
        out.postures[str(k)] = str(v)
    return out


def _event_payload(d: dict[str, Any], transition: str) -> dict[str, Any]:
    # The bus's own `kind` is the event kind (KIND_ACTIVITY); the activity's
    # kind travels as `activity_kind` and lands in ActivityEvent.kind.
    return {
        "activity_id": d.get("activity_id", ""),
        "activity_kind": d.get("kind", ""),
        "peer": d.get("peer", ""),
        "owner": d.get("owner", ""),
        "dag_id": d.get("dag_id", ""),
        "run_id": d.get("run_id", ""),
        "state": d.get("state", ""),
        "declared_ns": int(d.get("declared_ns") or 0),
        "horizon_ns": int(d.get("horizon_ns") or 0),
        "ended_ns": int(d.get("ended_ns") or 0),
        "precludes": list(d.get("precludes") or []),
        "postures": dict(d.get("postures") or {}),
        "reason": d.get("reason", ""),
        "transition": transition,
        "ceded": [],  # hermes cedes nothing: it owns the interactive session
    }


_LOOP: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Remember the engine loop so sync threads publish to the bus safely."""
    global _LOOP
    _LOOP = loop


def publish_activity(d: dict[str, Any], transition: str) -> None:
    bus = get_bus()
    if bus is None:
        return
    payload = _event_payload(d, transition)
    loop = _LOOP
    try:
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                bus.publish(KIND_ACTIVITY, **payload)
            else:
                loop.call_soon_threadsafe(lambda: bus.publish(KIND_ACTIVITY, **payload))
        else:
            bus.publish(KIND_ACTIVITY, **payload)
    except Exception:
        log.debug("activity publish skipped", exc_info=True)


# ── channel ───────────────────────────────────────────────────────────────────

def _stub(addr: str) -> tuple[grpc.Channel, spb_grpc.SchedulerStub]:
    channel = grpc.insecure_channel(addr)
    return channel, spb_grpc.SchedulerStub(channel)


def _rpc_error(guru: str, verb: str, addr: str, e: Exception) -> RuntimeError:
    code = getattr(e, "code", None)
    details = getattr(e, "details", None)
    what = f"{code()} {details()}" if callable(code) and callable(details) else str(e)
    return RuntimeError(
        f"{guru} {verb} at Signals engine {addr} failed: {what}\n"
        f"  Try: check the signals-engine process (Scheduler on {addr})\n"
        f"  Or:  SIGNALS_ENGINE_TARGET=<host:port> if the Signals engine moved"
    )


# ── a declared activity ───────────────────────────────────────────────────────

@dataclass
class ActivityLease:
    """One declared Activity plus its heartbeat loop (daemon thread).

    RenewActivity is a HEARTBEAT on the Signals-held lease (it also re-sets the
    horizon to now + horizon_s). The Airflow run's `hold` sensor observes that
    lease: heartbeats stopping for the lease TTL = the session is gone = the run
    completes as lapsed, without anyone telling Airflow. Cadence
    `heartbeat_s` (60 s) must stay well under the TTL (180 s).
    """

    activity: dict[str, Any]
    horizon_s: int
    addr: str
    heartbeat_s: int = 60
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    renewals: int = 0

    @property
    def activity_id(self) -> str:
        return str(self.activity.get("activity_id") or "")

    def start_renewing(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._renew_loop, name=f"activity-renew-{self.activity_id[:8]}", daemon=True
        )
        self._thread.start()

    def _renew_loop(self) -> None:
        # Heartbeat cadence, never the half-horizon: the lease TTL at Signals is
        # what the Airflow sensor observes; a missed TTL reads as "session gone".
        wait_s = max(1.0, float(min(self.heartbeat_s, self.horizon_s / 2.0)))
        while not self._stop.wait(wait_s):
            try:
                self.renew()
                wait_s = max(1.0, float(min(self.heartbeat_s, self.horizon_s / 2.0)))
            except Exception as e:  # noqa: BLE001 — logged with guru; the lease TTL bounds the damage
                log.warning("%s", e)
                wait_s = min(RENEW_RETRY_S, float(self.heartbeat_s))

    def renew(self, horizon_s: int | None = None) -> dict[str, Any]:
        h = int(horizon_s or self.horizon_s)
        req = spb.RenewActivityRequest(
            peer=PEER, activity_id=self.activity_id, horizon_ns=now_ns() + h * 1_000_000_000
        )
        channel, stub = _stub(self.addr)
        try:
            resp = stub.RenewActivity(req, timeout=RPC_TIMEOUT_S)
        except grpc.RpcError as e:
            raise _rpc_error(GURU_RENEWFAIL, "RenewActivity", self.addr, e) from e
        finally:
            channel.close()
        if not resp.accepted:
            raise RuntimeError(f"{GURU_RENEWFAIL} RenewActivity refused: {resp.error or 'no reason given'}")
        with self._lock:
            self.activity = activity_to_dict(resp.activity)
            self.renewals += 1
        publish_activity(self.activity, "renewed")
        log.info("activity %s renewed (horizon +%ss, run %s)", self.activity_id, h, self.activity.get("run_id"))
        return self.activity

    def release(self, outcome: str) -> dict[str, Any] | None:
        """Release at Signals. Never raises: a failed release is logged; the
        horizon is the protocol's release-by-absence."""
        self._stop.set()
        req = spb.ReleaseActivityRequest(peer=PEER, activity_id=self.activity_id, outcome=outcome[:200])
        try:
            channel, stub = _stub(self.addr)
            try:
                resp = stub.ReleaseActivity(req, timeout=RPC_TIMEOUT_S)
            finally:
                channel.close()
        except grpc.RpcError as e:
            log.warning("%s", _rpc_error(GURU_RELEASEFAIL, "ReleaseActivity", self.addr, e))
            return None
        if not resp.accepted:
            log.warning("%s ReleaseActivity refused: %s", GURU_RELEASEFAIL, resp.error or "no reason given")
            return None
        with self._lock:
            self.activity = activity_to_dict(resp.activity)
        publish_activity(self.activity, "released")
        log.info("activity %s released (%s)", self.activity_id, outcome)
        return self.activity


def list_activities(
    *,
    kind: str = KIND_INTERACTIVE,
    active_only: bool = True,
    addr: str | None = None,
    peer: str | None = None,
) -> list[dict[str, Any]]:
    addr = addr or target()
    req = spb.ListActivitiesRequest(
        peer=PEER if peer is None else peer,
        kind=kind,
        active_only=active_only,
        limit=50,
    )
    channel, stub = _stub(addr)
    try:
        resp = stub.ListActivities(req, timeout=RPC_TIMEOUT_S)
    except grpc.RpcError as e:
        raise _rpc_error(GURU_DECLAREFAIL, "ListActivities", addr, e) from e
    finally:
        channel.close()
    return [activity_to_dict(a) for a in resp.activities]


def release_activity(activity_id: str, outcome: str, *, addr: str | None = None) -> None:
    addr = addr or target()
    req = spb.ReleaseActivityRequest(peer=PEER, activity_id=activity_id, outcome=outcome[:200])
    channel, stub = _stub(addr)
    try:
        resp = stub.ReleaseActivity(req, timeout=RPC_TIMEOUT_S)
    except grpc.RpcError as e:
        raise _rpc_error(GURU_RELEASEFAIL, "ReleaseActivity", addr, e) from e
    finally:
        channel.close()
    if not resp.accepted:
        raise RuntimeError(f"{GURU_RELEASEFAIL} ReleaseActivity refused: {resp.error or 'no reason given'}")
    log.info("activity %s released (%s)", activity_id, outcome)


def release_stale_interactive(*, addr: str | None = None) -> int:
    """Drop this peer's in-force interactive_session claims so Connect can re-declare.

    Engine restarts used to leave a 3600s horizon holding agent-rtc (max 1).
    """
    try:
        acts = list_activities(kind=KIND_INTERACTIVE, active_only=True, addr=addr)
    except Exception as e:
        log.warning("could not list interactive activities: %s", e)
        return 0
    n = 0
    for a in acts:
        if a.get("state") not in IN_FORCE:
            continue
        aid = str(a.get("activity_id") or "")
        if not aid:
            continue
        try:
            release_activity(aid, "reconnect", addr=addr)
            n += 1
        except Exception as e:
            log.warning("release stale %s failed: %s", aid, e)
    if n:
        log.info("released %s stale interactive_session activities", n)
    return n


def declare_interactive(
    owner: str,
    horizon_s: int | None = None,
    *,
    precludes: list[str] | None = None,
    postures: dict[str, str] | None = None,
    reason: str = (
        "agent-rtc interactive session (moshi 1 GPU; Cerebras dialog "
        "token-metered; CPU search; Gaius thinking stays up)"
    ),
    addr: str | None = None,
) -> ActivityLease:
    """Declare the interactive session to Signals. Fail-fast: raises with
    #HS.COORD.00000001.DECLAREFAIL when the activity cannot be declared."""
    from hsengine.engine.yk_sentinel import interactive_yk_claims

    addr = addr or target()
    h = int(horizon_s or interactive_horizon_s())
    release_stale_interactive(addr=addr)
    req = spb.DeclareActivityRequest(
        peer=PEER,
        request_id=uuid7(),
        kind=KIND_INTERACTIVE,
        owner=owner or "webrtc",
        horizon_ns=now_ns() + h * 1_000_000_000,
        precludes=list(interactive_precludes() if precludes is None else precludes),
        reason=reason,
    )
    for leaf, gpu in interactive_yk_claims():
        req.claims.append(zpb.ActivityClaim(leaf=leaf, gpu=int(gpu)))
    for k, v in (interactive_postures() if postures is None else postures).items():
        req.postures[k] = v
    channel, stub = _stub(addr)
    try:
        resp = stub.DeclareActivity(req, timeout=RPC_TIMEOUT_S)
    except grpc.RpcError as e:
        raise _rpc_error(GURU_DECLAREFAIL, "DeclareActivity", addr, e) from e
    finally:
        channel.close()
    if not resp.accepted:
        raise RuntimeError(
            f"{GURU_DECLAREFAIL} DeclareActivity refused by Signals: {resp.error or 'no reason given'}\n"
            f"  Try: is `hermes` an allowed peer at the Signals scheduler; is the coord_activity DAG registered"
        )
    lease = ActivityLease(
        activity=activity_to_dict(resp.activity),
        horizon_s=h,
        addr=addr,
        heartbeat_s=interactive_heartbeat_s(),
    )
    publish_activity(lease.activity, "declared")
    log.info(
        "activity %s declared: %s owner=%s horizon=%ss postures=%s precludes=%s run=%s",
        lease.activity_id, KIND_INTERACTIVE, req.owner, h, dict(req.postures), list(req.precludes),
        lease.activity.get("run_id"),
    )
    return lease


# ── the watcher (engine-side view of every peer's activities) ─────────────────

class ActivityWatcher:
    """Replaces its view on every WatchActivities event; publishes transitions.

    Runs as an asyncio task in the engine loop (grpc.aio). Signals heartbeats
    at least every 60 s; silence past WATCH_SILENCE_S reconnects. UNIMPLEMENTED
    (an older Signals) is logged once and retried every 5 min. Entries past
    their horizon are dropped locally when the stream is down — the horizon is
    the safety, Signals is the truth while it speaks.
    """

    def __init__(self, addr: str | None = None, *, peer: str = PEER) -> None:
        self.addr = addr or target()
        self.peer = peer
        self._view: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.observed_ns = 0
        self.connected = False
        self.events = 0
        self._unimplemented_logged = False
        self._task: asyncio.Task | None = None

    # view --------------------------------------------------------------------
    def view(self, *, in_force_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            items = [dict(v) for v in self._view.values()]
        if not self.connected:
            cutoff = now_ns()
            items = [
                it for it in items
                if it.get("state") not in IN_FORCE or int(it.get("horizon_ns") or 0) > cutoff
            ]
        if in_force_only:
            items = [it for it in items if it.get("state") in IN_FORCE]
        return sorted(items, key=lambda it: (it.get("declared_ns") or 0, it.get("activity_id") or ""))

    def activities_proto(self) -> list[zpb.Activity]:
        return [dict_to_activity(d) for d in self.view()]

    def apply(self, activities: list[dict[str, Any]], observed_ns: int) -> list[tuple[dict[str, Any], str]]:
        """Replace the view; return (activity, transition) pairs to publish."""
        incoming = {str(a.get("activity_id") or ""): a for a in activities if a.get("activity_id")}
        transitions: list[tuple[dict[str, Any], str]] = []
        with self._lock:
            old = self._view
            for aid, a in incoming.items():
                prev = old.get(aid)
                st = a.get("state")
                if prev is None:
                    transitions.append((a, "started" if st == "running" else "observed"))
                    continue
                if prev.get("state") != st:
                    if st == "running":
                        transitions.append((a, "started"))
                    elif st in ("released", "expired", "failed", "superseded"):
                        transitions.append((a, st))
                    else:
                        transitions.append((a, "observed"))
                elif prev.get("run_id") != a.get("run_id") or int(prev.get("horizon_ns") or 0) != int(a.get("horizon_ns") or 0):
                    transitions.append((a, "renewed"))
            self._view = incoming
            self.observed_ns = int(observed_ns or now_ns())
            self.events += 1
        return transitions

    # loop --------------------------------------------------------------------
    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task:
        bind_loop(loop or asyncio.get_running_loop())
        self._task = asyncio.create_task(self.run(), name="hsengine-activity-watch")
        return self._task

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._watch_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except grpc.aio.AioRpcError as e:
                self.connected = False
                if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                    if not self._unimplemented_logged:
                        log.warning(
                            "%s Signals at %s has no WatchActivities (older protocol); retrying every %ss",
                            GURU_WATCHUNIMPL, self.addr, int(WATCH_UNIMPLEMENTED_RETRY_S),
                        )
                        self._unimplemented_logged = True
                    await asyncio.sleep(WATCH_UNIMPLEMENTED_RETRY_S)
                    continue
                log.warning("%s WatchActivities at %s: %s %s; retry in %.0fs", GURU_WATCHDOWN, self.addr, e.code(), e.details(), backoff)
            except Exception as e:  # noqa: BLE001
                self.connected = False
                log.warning("%s WatchActivities at %s: %s; retry in %.0fs", GURU_WATCHDOWN, self.addr, e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(WATCH_BACKOFF_MAX_S, backoff * 2)

    async def _watch_once(self) -> None:
        async with grpc.aio.insecure_channel(self.addr) as channel:
            stub = spb_grpc.SchedulerStub(channel)
            call = stub.WatchActivities(spb.WatchActivitiesRequest(peer=self.peer))
            it = call.__aiter__()
            while True:
                try:
                    ev = await asyncio.wait_for(it.__anext__(), timeout=WATCH_SILENCE_S)
                except StopAsyncIteration:
                    self.connected = False
                    raise RuntimeError("stream ended")
                except asyncio.TimeoutError:
                    self.connected = False
                    call.cancel()
                    raise RuntimeError(f"no event for {int(WATCH_SILENCE_S)}s (dead stream)")
                if not self.connected:
                    log.info("WatchActivities connected to %s", self.addr)
                self.connected = True
                self._unimplemented_logged = False
                for a, transition in self.apply([activity_to_dict(x) for x in ev.activities], int(ev.observed_ns)):
                    publish_activity(a, transition)


_WATCHER: ActivityWatcher | None = None


def start_watcher(addr: str | None = None) -> ActivityWatcher | None:
    """Start the engine-side watcher in the running loop (idempotent)."""
    global _WATCHER
    if _WATCHER is not None:
        return _WATCHER
    if not watch_enabled():
        log.info("coordination watch disabled (hermes.engine.coordination.watch)")
        return None
    _WATCHER = ActivityWatcher(addr)
    _WATCHER.start()
    return _WATCHER


def get_watcher() -> ActivityWatcher | None:
    return _WATCHER


def set_watcher(w: ActivityWatcher | None) -> None:
    global _WATCHER
    _WATCHER = w


def activities_proto() -> list[zpb.Activity]:
    """What this engine knows — for Engine/ServerQuery kind=ACTIVITIES."""
    w = _WATCHER
    return w.activities_proto() if w is not None else []
