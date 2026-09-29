"""Loopback Bokeh server for AgentRTC Chromium.

Not Aegir's /viz reverse proxy. The server is a child process: a plot
render holds the GIL, and this engine's asyncio loop is the 20 ms
audio clock. One server per engine; each Connect's Chromium holds its
own Bokeh websocket document.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.bokeh")

_mu = threading.Lock()
_proc: subprocess.Popen[Any] | None = None
_port = 0


def _free_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def origin_hosts(port: int) -> list[str]:
    """Bokeh --allow-websocket-origin values for loopback Chromium only."""
    return [f"127.0.0.1:{port}", f"localhost:{port}"]


def document_url(port: int, session_id: str, nonce: str = "") -> str:
    q = f"session={session_id}"
    if nonce:
        q += f"&n={nonce}"
    return f"http://127.0.0.1:{port}/hv?{q}"


def kanban_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/kanban"


def _alive() -> bool:
    return _proc is not None and _proc.poll() is None and _port > 0


def ensure_server() -> int:
    """Start the viz server if needed. Returns the bound port.

    Blocks the caller until it listens. Callers on the audio loop must
    use ``asyncio.to_thread`` — this wait is the plot process, not a
    few milliseconds.
    """
    global _proc, _port
    with _mu:
        if _alive():
            return _port
        ready = tempfile.NamedTemporaryFile(prefix="hsengine-viz-", delete=False)
        ready.close()
        env = os.environ.copy()
        env["HSENGINE_VIZ_READY"] = ready.name
        proc = subprocess.Popen(
            [sys.executable, "-m", "hsengine.engine.webrtc_viz_server"],
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + 90
        port = 0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"viz server exited {proc.returncode}")
            try:
                text = Path(ready.name).read_text().strip()
            except OSError:
                text = ""
            if text.isdigit():
                port = int(text)
                break
            time.sleep(0.05)
        if not port:
            proc.kill()
            raise RuntimeError("viz server did not listen")
        health_deadline = time.monotonic() + 15
        while time.monotonic() < health_deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"viz server exited {proc.returncode}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.4
                ) as resp:
                    body = json.loads(resp.read().decode())
            except Exception:
                time.sleep(0.05)
                continue
            if body.get("ok") and int(body.get("pid") or 0) not in (0, os.getpid()):
                break
        else:
            proc.kill()
            raise RuntimeError("viz server health check failed")
        _proc = proc
        _port = port
        log.info("viz server pid=%s http://127.0.0.1:%s/hv", proc.pid, port)
        return _port


def push_scene(session_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    """Store a scene in the viz process. Renders there, not on this interpreter."""
    port = ensure_server()
    payload = json.dumps({"session": session_id, "scene": scene}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/scene",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    if not isinstance(body, dict) or not body.get("ok"):
        detail = body.get("error") if isinstance(body, dict) else "viz scene rejected"
        raise RuntimeError(str(detail or "viz scene rejected"))
    return body


def stop_server() -> None:
    global _proc, _port
    with _mu:
        proc, _proc = _proc, None
        _port = 0
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
