"""Host occupancy for the agent-rtc CUDA worker (Kyutai STT).

YuniKorn configuration is Signals' job: this engine declares the interactive
Activity (claims = queue config) over signals-protocol, and Signals applies
it. This module never talks to Kubernetes.

Physical GPU index comes from signals-protocol ``Engine/Status.gpu_ids``
plus first-fit-from-zero packing (heavy 0–3, extract 4, agent-rtc last).
``/tmp/zndx-gpu-leases`` only refuses a pin another local process already
holds. nvidia-smi is not the planner.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
from pathlib import Path

log = logging.getLogger("hsengine.engine.yk_sentinel")

WORKLOAD_ID = "hermes-agent-rtc"
QUEUE = "root.internal.inference.agent-rtc"
RESOURCE_CLASS = "internal.inference.agent-rtc"
GPU_TOKENS = 1
CEREBRAS_WORKLOAD_ID = "hermes-cerebras-thinking"
CEREBRAS_QUEUE = "root.external.token-metered"
CEREBRAS_CLASS = "external.token-metered"
COMPUTE_QUEUE = "root.internal.compute"
COMPUTE_CLASS = "internal.compute"


def interactive_yk_claims() -> list[tuple[str, int]]:
    """YK leaves the interactive session occupies while its Activity RUNS.

    agent-rtc GPU 1 — moshi STT/TTS on the high-end token.
    token-metered GPU 0 — Cerebras dialog (apps, no local GPU).
    compute GPU 0 — CPU search / Qdrant (no GPU at this scale).
    Heavy thinking (GPUs 0–3) is Gaius's standing claim and is not ceded.
    """
    return [
        (QUEUE, GPU_TOKENS),
        (CEREBRAS_QUEUE, 0),
        (COMPUTE_QUEUE, 0),
    ]
LEASE_DIR = Path(os.environ.get("ZNDX_GPU_LEASE_DIR", "/tmp/zndx-gpu-leases"))
DEFAULT_TOTAL_GPUS = 6  # lab tinybox; same as advertise_federation_gpu.sh


def total_gpus() -> int:
    try:
        from hsengine.config import load_config

        raw = load_config().get("hermes.engine.total_gpus")
        n = int(raw) if raw is not None else 0
    except Exception:
        n = 0
    return n if n > 0 else DEFAULT_TOTAL_GPUS


def pick_agent_rtc_gpu(held: set[int] | frozenset[int], n: int) -> int:
    """Last free index: heavy packs from 0, agent-rtc is the high-end token."""
    if n < 1:
        raise RuntimeError("DENY: total_gpus is 0 — cannot pack agent-rtc")
    free = [i for i in range(int(n)) if i not in held]
    if not free:
        raise RuntimeError(
            f"DENY: no free GPU after Status.gpu_ids {sorted(held)!r} (total={n})"
        )
    return free[-1]


def _live_lease_gpus() -> set[int]:
    held: set[int] = set()
    if not LEASE_DIR.is_dir():
        return held
    for path in LEASE_DIR.glob("*.owner.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = payload.get("pid")
        if not isinstance(pid, int) or not Path(f"/proc/{pid}").exists():
            continue
        gpus = payload.get("gpus") or payload.get("gpu") or []
        if isinstance(gpus, int):
            held.add(gpus)
        elif isinstance(gpus, list):
            for g in gpus:
                try:
                    held.add(int(g))
                except (TypeError, ValueError):
                    continue
        stem = path.stem  # gpu-5 or gpu-0-1
        if stem.startswith("gpu-"):
            for part in stem[4:].split("-"):
                if part.isdigit():
                    held.add(int(part))
    return held


def our_gpu_ids() -> list[int]:
    """GPUs this workload currently pins (for Engine/Status.gpu_ids)."""
    ids: set[int] = set()
    if not LEASE_DIR.is_dir():
        return []
    for path in LEASE_DIR.glob("gpu-*.owner.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("workload_id") != WORKLOAD_ID:
            continue
        pid = payload.get("pid")
        if not isinstance(pid, int) or not Path(f"/proc/{pid}").exists():
            continue
        gpus = payload.get("gpus") or payload.get("gpu") or []
        if isinstance(gpus, int):
            ids.add(gpus)
        elif isinstance(gpus, list):
            for g in gpus:
                try:
                    ids.add(int(g))
                except (TypeError, ValueError):
                    continue
    return sorted(ids)


def lease_one_gpu(pid: int, project: str = "hermes") -> int:
    """Pin the agent-rtc token: last free index after peer Status.gpu_ids."""
    from hsengine.engine import federation

    LEASE_DIR.mkdir(parents=True, exist_ok=True)
    proto_held, proto_n = federation.peer_gpu_occupancy()
    held = set(proto_held) | _live_lease_gpus()
    held -= set(our_gpu_ids())
    n = proto_n if proto_n > 0 else total_gpus()
    payload = {
        "pid": pid,
        "project": project,
        "gpus": [],
        "workload_id": WORKLOAD_ID,
        "queue": QUEUE,
    }
    while True:
        idx = pick_agent_rtc_gpu(held, n)
        owner = LEASE_DIR / f"gpu-{idx}.owner.json"
        payload["gpus"] = [idx]
        try:
            fd = os.open(str(owner), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            held.add(idx)
            continue
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        log.info("leased GPU %s for %s (Status held=%s total=%s)", idx, WORKLOAD_ID, sorted(held), n)
        return idx


def release_gpu_lease() -> None:
    for path in LEASE_DIR.glob("gpu-*.owner.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("workload_id") == WORKLOAD_ID:
            path.unlink(missing_ok=True)


def moshi_serving(host: str = "127.0.0.1", port: int = 5080, timeout: float = 0.4) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout)
        sock.close()
        return True
    except OSError:
        return False


def pid_file() -> Path:
    return Path(
        os.environ.get("HERMES_MOSHI_PID_FILE")
        or Path(__file__).resolve().parents[2] / ".devenv/state/moshi/moshi-stt.pid"
    )


def kill_moshi() -> bool:
    path = pid_file()
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        path.unlink(missing_ok=True)
        return False
    path.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {"lease", "release"}:
        print("usage: python -m hsengine.engine.yk_sentinel lease|release", file=sys.stderr)
        return 2
    if args[0] == "lease":
        print(lease_one_gpu(os.getpid()))
        return 0
    release_gpu_lease()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
