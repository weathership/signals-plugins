"""The signals-preprints worker follows the AgentRTC session.

Mistral is the urgent path while a call is up. The worker process is
started on enter and stopped on the last hangup. With no session, Gaius
extracts the preprint on local GPUs and this worker is not running.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

log = logging.getLogger("hsengine.engine.signals_preprints_session")

_PROC: subprocess.Popen | None = None


def urgent() -> bool:
    from hsengine.engine.interactive import is_active

    return is_active()


def _script() -> Path:
    import hsengine

    return Path(hsengine.__file__).resolve().parents[1] / "scripts" / "signals_preprints_worker.sh"


def _pidfile() -> Path:
    from hermes_constants import get_hermes_home

    path = get_hermes_home() / "run" / "signals-preprints.pid"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _recorded_pid() -> int:
    path = _pidfile()
    if not path.is_file():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return 0


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start() -> int:
    """Start the worker if this session does not already have one."""
    global _PROC
    pid = _recorded_pid()
    if _alive(pid):
        return pid
    script = _script()
    if not script.is_file():
        raise RuntimeError(f"signals-preprints worker missing: {script}")
    _PROC = subprocess.Popen(
        [str(script)],
        start_new_session=True,
        cwd=str(script.parents[1]),
    )
    _pidfile().write_text(str(_PROC.pid), encoding="utf-8")
    log.info("signals-preprints worker started pid=%s", _PROC.pid)
    return _PROC.pid


def _worker_pids() -> list[int]:
    """Pids whose command is the signals-preprints worker script."""
    found: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace")
        if "signals_preprints.py" in cmd:
            found.append(int(entry.name))
    return found


def _terminate(pid: int) -> None:
    if not _alive(pid):
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    log.info("signals-preprints worker stopped pid=%s", pid)


def stop() -> None:
    """Stop the worker. A hangup with no remaining session calls this."""
    global _PROC
    pids = set(_worker_pids())
    recorded = _recorded_pid()
    if recorded:
        pids.add(recorded)
    if _PROC is not None and _PROC.poll() is None:
        pids.add(_PROC.pid)
    for pid in sorted(pids):
        _terminate(pid)
    _PROC = None
    path = _pidfile()
    if path.is_file():
        path.unlink()


_LEASE = None


def _ensure_declared() -> None:
    """Declare the Mistral window at Signals. The worker starts only after."""
    global _LEASE
    if _LEASE is not None:
        return
    from hsengine.engine.coordination import declare_mistral_preprint

    _LEASE = declare_mistral_preprint("webrtc")
    _LEASE.start_renewing()


def _release_declared(outcome: str) -> None:
    global _LEASE
    lease, _LEASE = _LEASE, None
    if lease is not None:
        lease.release(outcome)
        return
    from hsengine.engine.coordination import KIND_MISTRAL_PREPRINT, release_stale_kind

    release_stale_kind(KIND_MISTRAL_PREPRINT)


def reconcile() -> None:
    """Match the worker and the Signals activity to the AgentRTC posture.

    Airflow sees the activity because Signals materialises every Declare.
    This process never talks to Airflow.
    """
    if urgent():
        try:
            _ensure_declared()
        except Exception:
            log.warning("mistral_preprint activity was not declared", exc_info=True)
            return
        try:
            start()
        except Exception:
            log.warning("signals-preprints worker did not start", exc_info=True)
        return
    try:
        _release_declared("hangup")
    except Exception:
        log.warning("mistral_preprint activity was not released", exc_info=True)
    stop()
