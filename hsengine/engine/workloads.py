"""Local process table for Engine/Yield. Idempotent; unknown ids are not an error."""
from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass, field
from threading import Lock
import time

log = logging.getLogger("hsengine.engine.workloads")


@dataclass
class AttachedWorkload:
    workload_id: str
    pid: int
    started_at: float = field(default_factory=time.time)


class WorkloadTable:
    def __init__(self) -> None:
        self._mu = Lock()
        self._rows: dict[str, AttachedWorkload] = {}

    def register(self, workload_id: str, pid: int) -> AttachedWorkload:
        wid = (workload_id or "").strip()
        if not wid:
            raise ValueError("workload_id required")
        row = AttachedWorkload(workload_id=wid, pid=int(pid))
        with self._mu:
            self._rows[wid] = row
        return row

    def yield_one(self, workload_id: str) -> tuple[bool, str]:
        """End the process. Returns (process_ended, message). Idempotent."""
        wid = (workload_id or "").strip()
        with self._mu:
            row = self._rows.pop(wid, None) if wid else None
        if row is None and wid:
            from hsengine.engine.yk_sentinel import WORKLOAD_ID, kill_moshi

            if wid == WORKLOAD_ID:
                ended = kill_moshi()
                return ended, "agent-rtc moshi-stt signaled" if ended else "agent-rtc already idle"
        if row is None:
            return False, f"no local process for workload_id={wid or '(empty)'}"
        ended = _terminate(row.pid)
        msg = (
            f"ended pid={row.pid} workload_id={wid}"
            if ended
            else f"pid={row.pid} already gone workload_id={wid}"
        )
        log.info("yield %s", msg)
        return ended, msg


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return not _pid_alive(pid)
    return not _pid_alive(pid)
