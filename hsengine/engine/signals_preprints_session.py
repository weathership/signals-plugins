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


def reconcile() -> None:
    """Match the worker to the posture. Called on enter, leave, and boot."""
    if urgent():
        try:
            start()
        except Exception:
            log.warning("signals-preprints worker did not start", exc_info=True)
        return
    stop()
