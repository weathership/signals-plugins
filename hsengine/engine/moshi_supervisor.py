"""Resident moshi-server supervisor for devenv.

Always listens on the control port. CUDA moshi-server starts only on
POST /interactive/on (WebRTC session) and stops on POST /interactive/off.
YuniKorn claims are Signals' job (the engine declares the Activity first).
This process never talks to Kubernetes. No whisper/CPU path.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from hsengine.engine.yk_sentinel import (
    WORKLOAD_ID,
    lease_one_gpu,
    moshi_serving,
    release_gpu_lease,
)

log = logging.getLogger("hsengine.engine.moshi_supervisor")

CONTROL_PORT = int(os.environ.get("MOSHI_CONTROL_PORT", "5081"))
MOSHI_PORT = int(os.environ.get("MOSHI_STT_PORT", "5080"))
_CARGO = Path.home() / ".cargo" / "bin" / "moshi-server"


def package_dir() -> Path:
    """``hsengine/`` on disk (this file is ``hsengine/engine/moshi_supervisor.py``)."""
    return Path(__file__).resolve().parents[1]


def devenv_root() -> Path:
    """Hermes checkout that owns ``.devenv/`` (wrap, nvidia-libs, moshi state).

    Not the Python package path — after signals-hsengine moved, ``__file__``
    is under signals-plugins, not the devenv root.
    """
    for key in ("HERMES_ROOT", "DEVENV_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw)
    cwd = Path.cwd()
    if (cwd / ".devenv").is_dir():
        return cwd
    return cwd


def stt_config_path() -> Path:
    raw = (os.environ.get("MOSHI_STT_CONFIG") or "").strip()
    if raw:
        return Path(raw)
    packaged = package_dir() / "moshi" / "stt-1b.toml"
    if packaged.is_file():
        return packaged
    raise RuntimeError(f"STT config missing: {packaged}")


def _state_dir() -> Path:
    return devenv_root() / ".devenv" / "state" / "moshi"


def _wrap_bin() -> Path:
    return devenv_root() / ".devenv" / "profile" / "bin" / "moshi-server"


def _ld_library_path(torch_lib: Path | None) -> str:
    """Same layout as the devenv moshi-server wrap: nvidia + CUDA + Nix libs + torch."""
    nvidia = devenv_root() / ".devenv" / "nvidia-libs"
    parts = [str(nvidia), "/usr/local/cuda/lib64"]
    wrap = _wrap_bin()
    wrap = wrap.resolve() if wrap.exists() else wrap
    try:
        for line in wrap.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("libs="):
                raw = stripped.split("=", 1)[1].strip().strip('"')
                if raw:
                    parts.append(raw)
                break
    except OSError:
        pass
    if torch_lib is not None and torch_lib.is_dir():
        parts.append(str(torch_lib))
    return ":".join(parts)

_mu = threading.Lock()
_worker: subprocess.Popen | None = None


def _moshi_env(gpu: int) -> dict[str, str]:
    """CUDA_VISIBLE_DEVICES + CUDA/Nix/torch libs. Do not rely on the wrap alone."""
    env = os.environ.copy()
    root = devenv_root()
    profile_bin = root / ".devenv" / "profile" / "bin"
    cargo_bin = Path.home() / ".cargo" / "bin"
    env["PATH"] = f"{profile_bin}:{env.get('PATH', '')}:{cargo_bin}"
    env["CUDA_HOME"] = env.get("CUDA_HOME", "/usr/local/cuda")
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["HF_HOME"] = env.get("HF_HOME", "/raid/cache/huggingface")
    tts_site = root / ".devenv" / "state" / "tts-venv" / "lib" / "python3.11" / "site-packages"
    torch_lib = tts_site / "torch" / "lib" if tts_site.is_dir() else None
    if tts_site.is_dir():
        env["PYTHONPATH"] = f"{tts_site}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["LD_LIBRARY_PATH"] = _ld_library_path(torch_lib if torch_lib and torch_lib.is_dir() else None)
    env["MOSHI_EXTRA_LIBS"] = env["LD_LIBRARY_PATH"]
    return env


def _moshi_binary() -> str:
    wrap = _wrap_bin()
    if wrap.is_file():
        return str(wrap)
    if _CARGO.is_file():
        return str(_CARGO)
    raise RuntimeError("moshi-server not on PATH (need devenv wrap or ~/.cargo/bin)")


def activate() -> dict:
    global _worker
    with _mu:
        if _worker is not None and _worker.poll() is None and moshi_serving(port=MOSHI_PORT):
            return {"ok": True, "moshi": True, "already": True}
        if _worker is not None and _worker.poll() is not None:
            _worker = None
            release_gpu_lease()
        binary = _moshi_binary()
        gpu = lease_one_gpu(os.getpid())
        state = _state_dir()
        state.mkdir(parents=True, exist_ok=True)
        (state / "static").mkdir(exist_ok=True)
        (state / "logs").mkdir(exist_ok=True)
        config = stt_config_path()
        if not config.is_file():
            raise RuntimeError(f"moshi STT config not a file: {config}")
        log_path = state / "logs" / "moshi-server.log"
        env = _moshi_env(gpu)
        log.info("starting moshi-server binary=%s gpu=%s ld=%s", binary, gpu, env.get("LD_LIBRARY_PATH", "")[:180])
        log_f = open(log_path, "ab", buffering=0)
        _worker = subprocess.Popen(
            [binary, "worker", "--config", config, "--port", str(MOSHI_PORT)],
            cwd=str(state),
            env=env,
            stdout=log_f,
            stderr=log_f,
        )
        (state / "moshi-stt.pid").write_text(str(_worker.pid))
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if _worker.poll() is not None:
                tail = ""
                try:
                    tail = log_path.read_text(errors="replace")[-1500:]
                except OSError:
                    tail = ""
                raise RuntimeError(
                    f"moshi-server exited {_worker.returncode} binary={binary} gpu={gpu}\n{tail}"
                )
            if moshi_serving(port=MOSHI_PORT):
                log.info("moshi-server listening on :%s gpu=%s (stt+tts)", MOSHI_PORT, gpu)
                return {"ok": True, "moshi": True, "gpu": gpu, "tts": True}
            time.sleep(0.4)
        raise RuntimeError("moshi-server did not listen on :5080")


def deactivate() -> dict:
    global _worker
    with _mu:
        proc, _worker = _worker, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        (_state_dir() / "moshi-stt.pid").unlink(missing_ok=True)
        release_gpu_lease()
        return {"ok": True, "moshi": False}


def status() -> dict:
    alive = _worker is not None and _worker.poll() is None
    return {
        "ok": True,
        "supervisor": True,
        "moshi": moshi_serving(port=MOSHI_PORT),
        "worker": alive,
        "workload_id": WORKLOAD_ID,
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        log.info("%s " + fmt, self.address_string(), *args)

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._json(200, status())
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        try:
            if path == "/interactive/on":
                self._json(200, activate())
                return
            if path == "/interactive/off":
                self._json(200, deactivate())
                return
        except Exception as e:
            log.exception("supervisor %s failed", path)
            self._json(503, {"ok": False, "error": str(e)})
            return
        self._json(404, {"ok": False, "error": "not found"})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cargo_bin = Path.home() / ".cargo" / "bin"
    os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
    server = ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), _Handler)

    def _stop(*_args) -> None:
        try:
            deactivate()
        finally:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("moshi supervisor control :%s (moshi-server on :%s when interactive)", CONTROL_PORT, MOSHI_PORT)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
