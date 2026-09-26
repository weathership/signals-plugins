"""AgentRTC speaker diarization. Part of the interactive workload, not a second GPU floor.

The engine does not import torch. A child process uses the cu129 venv and the
host libcuda (see ``nemotron-diar-session/run.sh``). Moshi keeps the agent-rtc
GPU lease; this worker is pinned to that same index. If the worker is down,
captions stay labeled Room and the call continues.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger("hsengine.engine.diarization")

PORT = int(os.environ.get("NEMOTRON_DIAR_PORT", "5092"))
_DEFAULT_PYTHON = "/home/rch/local/src/wxs/nemotron-diar-session/.venv/bin/python"
_ZLIB = "/nix/store/ri9paa3mri4kqakljak8ldvbcp7lpmif-zlib-1.3.1/lib"
_proc: subprocess.Popen | None = None
_mu = threading.Lock()
_labels: dict[str, str] = {}
_started = False


def python_path() -> Path:
    raw = (os.environ.get("NEMOTRON_DIAR_PYTHON") or _DEFAULT_PYTHON).strip()
    return Path(raw)


def healthy(timeout: float = 0.3) -> bool:
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout)
        sock.close()
        return True
    except OSError:
        return False


def speaker_label(session_id: str) -> str:
    """Arrival-ordered label, or Room when diarization has not spoken yet."""
    return _labels.get(session_id) or "Room"


def _ld_library_path() -> str:
    """Host driver first. Same rule as Gaius devenv: no Nix libstdc++."""
    nvidia = Path("/home/rch/local/src/zndx/gaius/.devenv/nvidia-libs")
    parts = [str(nvidia), "/usr/local/cuda/lib64", "/usr/local/cuda/extras/CUPTI/lib64", _ZLIB]
    return ":".join(parts)


def _agent_rtc_gpu() -> str:
    """Same index as the interactive lease. Empty if the session has not leased one."""
    forced = (os.environ.get("NEMOTRON_CUDA_VISIBLE_DEVICES") or "").strip()
    if forced:
        return forced
    try:
        from hsengine.engine.yk_sentinel import our_gpu_ids

        ids = our_gpu_ids()
    except Exception:
        ids = []
    if not ids:
        return ""
    return str(ids[-1])


def ensure_started() -> bool:
    """Start the worker if the venv exists. Never raises into the audio path."""
    global _proc, _started
    if healthy():
        return True
    py = python_path()
    if not py.is_file():
        if not _started:
            log.info("diarization venv missing at %s — captions stay Room", py)
            _started = True
        return False
    gpu = _agent_rtc_gpu()
    if not gpu:
        if not _started:
            log.info("diarization waiting for the agent-rtc GPU lease")
            _started = True
        return False
    with _mu:
        if healthy():
            return True
        if _proc is not None and _proc.poll() is None:
            return False
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = _ld_library_path()
        env["CUDA_VISIBLE_DEVICES"] = gpu
        env["CUDA_HOME"] = "/usr/local/cuda-12.4"
        env["NEMOTRON_DIAR_PORT"] = str(PORT)
        worker = Path(__file__).resolve().parent / "diarization_worker.py"
        log.info("starting nemotron diarization gpu=%s python=%s", gpu, py)
        _proc = subprocess.Popen(  # noqa: S603
            [str(py), str(worker)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _started = True
    return False


def note_pcm(session_id: str, pcm_24k) -> None:
    """Fire-and-forget 24 kHz mic audio. Drops the chunk if the worker is busy."""
    if not session_id:
        return
    try:
        import numpy as np
    except Exception:
        return
    samples = np.asarray(pcm_24k, dtype=np.float32).reshape(-1)
    if samples.size < 2:
        return
    n_out = max(1, int(round(samples.size * 16000 / 24000)))
    pcm16 = np.interp(
        np.linspace(0, samples.size - 1, n_out, dtype=np.float64),
        np.arange(samples.size, dtype=np.float64),
        samples,
    ).astype(np.float32)
    raw = pcm16.tobytes()

    def _post() -> None:
        if not healthy() and not ensure_started():
            return
        if not healthy(timeout=0.05):
            return
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/v1/pcm",
            data=raw,
            headers={"X-Session": session_id, "Content-Type": "application/octet-stream"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                body = json.loads(resp.read().decode() or "{}")
        except Exception:
            return
        label = str(body.get("label") or "").strip()
        if label:
            _labels[session_id] = label

    threading.Thread(target=_post, daemon=True, name="diar-post").start()


def apply_label(payload: dict, session_id: str) -> str:
    """Testable parse of a worker reply."""
    label = str((payload or {}).get("label") or "").strip()
    if label:
        _labels[session_id] = label
    return speaker_label(session_id)
