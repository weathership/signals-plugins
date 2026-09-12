"""Hermes's WORKLOAD CATALOGUE — what this engine runs, submitted to Signals.

Spec: signals-protocol ``specification/protocol/coordination_activities.md``
§"The workload catalogue". Every project's engine submits the catalogue of the
workloads it runs (``Scheduler/SyncWorkloads``, one ``zndx.engine.v1.ScheduleHint``
per workload) so Signals can materialise them in its Airflow and apply each
workload's YuniKorn configuration (the entry's ``claims``) for exactly the
duration of the active run.

Hermes runs ONE workload: the interactive agent-rtc WebRTC session. It is not
scheduled — this engine declares it at session start
(``coordination.declare_interactive`` → ``Scheduler/DeclareActivity``) — so it is
catalogued with ``source = "engine"``: Signals lists it for federation
visibility, materialises no DAG for it, and the arbiter asserts its claims
only while a session's Activity RUNS: moshi on agent-rtc (GPU 1), Cerebras
dialog on token-metered (GPU 0), CPU search/Qdrant on compute (GPU 0).
Gaius thinking on heavy is not claimed and not ceded.

Two hops, never one: this ENGINE submits to the Signals engine; local processes
read the catalogue from this engine (``Engine/ServerQuery kind=SCHEDULES``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import grpc

from hsengine.engine import coordination
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from hsengine.engine.yk_sentinel import interactive_yk_claims

log = logging.getLogger("hsengine.engine.workload_catalog")

GURU_SYNCFAIL = "#HS.COORD.00000006.SYNCFAIL"

CATALOG_ID = "interactive.agent_rtc"
RUNNER_INTERACTIVE = "interactive"
SOURCE_ENGINE = "engine"
DESCRIPTION = (
    "agent-rtc interactive WebRTC: moshi 1 local GPU; Cerebras dialog "
    "token-metered; CPU search/Qdrant on compute; Gaius thinking stays up. "
    "Floors asserted only while a session runs"
)

SYNC_INTERVAL_S = 1800.0          # re-submit the catalogue every 30 min
SYNC_RETRY_S = 300.0              # after UNIMPLEMENTED (old Signals) or any failure
RPC_TIMEOUT_S = coordination.RPC_TIMEOUT_S


# ── the catalogue ─────────────────────────────────────────────────────────────

def interactive_claims() -> list[zpb.ActivityClaim]:
    """The interactive session's YuniKorn configuration — the same claims
    ``coordination.declare_interactive`` puts on the Activity.

    See ``yk_sentinel.interactive_yk_claims``: moshi GPU 1, Cerebras and
    CPU search at GPU 0 so Signals/Airflow see the full interactive split.
    """
    return [zpb.ActivityClaim(leaf=leaf, gpu=int(gpu)) for leaf, gpu in interactive_yk_claims()]


def interactive_entry() -> zpb.ScheduleHint:
    hint = zpb.ScheduleHint(
        id=CATALOG_ID,
        cron="",                       # unscheduled: declared by this engine at session start
        airflow_dag_id="",             # no DAG is materialised for an engine-declared workload
        source=SOURCE_ENGINE,
        enabled=True,
        kind=coordination.KIND_INTERACTIVE,
        horizon_s=int(coordination.interactive_horizon_s()),
        timezone="UTC",
        description=DESCRIPTION,
        runner=RUNNER_INTERACTIVE,
    )
    hint.claims.extend(interactive_claims())
    hint.precludes.extend(coordination.interactive_precludes())
    for k, v in coordination.interactive_postures().items():
        hint.postures[k] = v
    return hint


def catalog() -> list[zpb.ScheduleHint]:
    """Everything this engine runs — for ServerQuery kind=SCHEDULES and SyncWorkloads."""
    return [interactive_entry()]


def catalog_summary() -> list[dict[str, Any]]:
    return [
        {
            "id": h.id,
            "kind": h.kind,
            "source": h.source,
            "runner": h.runner,
            "claims": [{"leaf": c.leaf, "gpu": c.gpu} for c in h.claims],
            "postures": dict(h.postures),
            "precludes": list(h.precludes),
            "horizon_s": h.horizon_s,
            "enabled": h.enabled,
        }
        for h in catalog()
    ]


# ── submission ────────────────────────────────────────────────────────────────

def _engine_build() -> str:
    try:
        from hsengine.engine import s2s

        return str(s2s.advertised_head() or "")
    except Exception:  # noqa: BLE001 — provenance only; never block the sync on git
        return ""


def sync_request(engine_build: str | None = None) -> spb.SyncWorkloadsRequest:
    """A REPLACE sync: this engine's whole catalogue is the truth for peer hermes."""
    return spb.SyncWorkloadsRequest(
        peer=coordination.PEER,
        workloads=catalog(),
        replace=True,
        engine_build=engine_build if engine_build is not None else _engine_build(),
    )


def sync_once(addr: str | None = None, engine_build: str | None = None) -> spb.SyncWorkloadsResponse:
    """Submit the catalogue to Signals. Raises RuntimeError(#HS.COORD.00000006.SYNCFAIL)
    when Signals is unreachable or refuses; ``grpc.RpcError`` with UNIMPLEMENTED is
    re-raised as-is so the loop can back off on an older Signals."""
    addr = addr or coordination.target()
    req = sync_request(engine_build)
    channel, stub = coordination._stub(addr)
    try:
        resp = stub.SyncWorkloads(req, timeout=RPC_TIMEOUT_S)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            raise
        raise coordination._rpc_error(GURU_SYNCFAIL, "SyncWorkloads", addr, e) from e
    finally:
        channel.close()
    if not resp.accepted:
        raise RuntimeError(
            f"{GURU_SYNCFAIL} SyncWorkloads refused by Signals: {resp.error or 'no reason given'}\n"
            f"  Try: is `hermes` an allowed peer at the Signals scheduler ({addr})"
        )
    log.info(
        "workload catalogue synced to %s: %d entr%s → %s",
        addr,
        len(req.workloads),
        "y" if len(req.workloads) == 1 else "ies",
        ", ".join(f"{r.workload.id}={r.state}{('/' + r.dag_id) if r.dag_id else ''}" for r in resp.records)
        or "no records echoed",
    )
    return resp


class WorkloadSync:
    """Periodic submission of the catalogue to Signals (asyncio task on the engine loop).

    Success → every SYNC_INTERVAL_S; UNIMPLEMENTED (an older Signals) → logged once,
    retried every SYNC_RETRY_S; any other failure → logged with the guru, retried
    every SYNC_RETRY_S. Never raises out of the loop.
    """

    def __init__(self, addr: str | None = None):
        self.addr = addr or coordination.target()
        self.synced_at: float = 0.0
        self.last_error: str = ""
        self.records: list[spb.WorkloadRecord] = []
        self._unimpl_logged = False
        self._task: asyncio.Task | None = None

    async def step(self) -> float:
        """One sync attempt; returns the delay before the next."""
        try:
            resp = await asyncio.to_thread(sync_once, self.addr)
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                if not self._unimpl_logged:
                    self._unimpl_logged = True
                    log.warning(
                        "%s SyncWorkloads UNIMPLEMENTED at %s (Signals predates the workload "
                        "catalogue) — retrying every %.0fs",
                        GURU_SYNCFAIL, self.addr, SYNC_RETRY_S,
                    )
                self.last_error = "UNIMPLEMENTED"
                return SYNC_RETRY_S
            self.last_error = str(e)
            log.warning("%s SyncWorkloads at %s: %s", GURU_SYNCFAIL, self.addr, e)
            return SYNC_RETRY_S
        except Exception as e:  # noqa: BLE001 — the loop must survive a dark Signals
            self.last_error = str(e)
            log.warning("%s", e)
            return SYNC_RETRY_S
        self._unimpl_logged = False
        self.last_error = ""
        self.synced_at = time.time()
        self.records = list(resp.records)
        return SYNC_INTERVAL_S

    async def _run(self) -> None:
        while True:
            delay = await self.step()
            await asyncio.sleep(delay)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task:
        loop = loop or asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="hsengine-workload-sync")
        return self._task

    def status(self) -> dict[str, Any]:
        return {
            "target": self.addr,
            "synced_at": self.synced_at,
            "last_error": self.last_error,
            "records": [
                {"id": r.workload.id, "peer": r.peer, "dag_id": r.dag_id, "state": r.state, "error": r.error}
                for r in self.records
            ],
        }


def sync_enabled() -> bool:
    raw = str(coordination._cfg("hermes.engine.coordination.sync", "true")).strip().lower()
    return raw not in ("0", "false", "no", "off")


_SYNC: WorkloadSync | None = None


def start_sync(addr: str | None = None) -> WorkloadSync | None:
    """Start the periodic catalogue submission in the running loop (idempotent)."""
    global _SYNC
    if _SYNC is not None:
        return _SYNC
    if not sync_enabled():
        log.info("workload catalogue sync disabled (hermes.engine.coordination.sync)")
        return None
    _SYNC = WorkloadSync(addr)
    _SYNC.start()
    return _SYNC


def get_sync() -> WorkloadSync | None:
    return _SYNC


def set_sync(s: WorkloadSync | None) -> None:
    global _SYNC
    _SYNC = s
