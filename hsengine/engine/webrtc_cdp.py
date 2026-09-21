"""Headless Chromium camera: CDP screencast on loopback, one context per Connect.

No Xvfb, no PipeWire, no operator profile. --headless=new compositor.
JPEG frames are capture encoding; the product is a paced WebRTC track.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.webrtc.cdp")

VIEW_W = 1280
VIEW_H = 720
JPEG_QUALITY = 65
PUMP_HZ = 12
# Keep the headless compositor dirty so Page.screencastFrame is a video,
# not one JPEG after first paint.
_CAST_KEEPALIVE_JS = """
(() => {
  if (window.__hvCast) return true;
  const s = document.createElement('style');
  s.textContent = '@keyframes __hvcast{from{filter:brightness(1)}to{filter:brightness(1.002)}}html{animation:__hvcast 90ms infinite alternate;}';
  document.documentElement.appendChild(s);
  window.__hvCast = true;
  return true;
})()
"""


def chromium_executable() -> str | None:
    env = (os.environ.get("HERMES_CHROMIUM") or os.environ.get("CHROMIUM_PATH") or "").strip()
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        found = shutil.which(name)
        if found:
            return found
    root = (os.environ.get("HERMES_ROOT") or "").strip()
    if root:
        profile = Path(root) / ".devenv" / "profile" / "bin" / "chromium"
        if profile.is_file() and os.access(profile, os.X_OK):
            return str(profile)
    return None


def _free_loopback_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def chromium_cmd(
    *,
    binary: str,
    user_data_dir: str,
    debug_port: int,
    url: str,
) -> list[str]:
    """Flags for a jailed, loopback-only compositor. No desktop stack."""
    return [
        binary,
        "--headless=new",
        f"--remote-debugging-port={debug_port}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-allow-origins=http://127.0.0.1:{debug_port}",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={VIEW_W},{VIEW_H}",
        "--force-device-scale-factor=1",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--autoplay-policy=no-user-gesture-required",
        "--hide-scrollbars",
        "--mute-audio",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
        "--disable-popup-blocking",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-default-apps",
        "--disable-component-extensions-with-background-pages",
        "--ozone-platform=headless",
        f"--ozone-override-screen-size={VIEW_W},{VIEW_H}",
        url,
    ]


def pick_cdp_page(pages: list) -> str:
    """WebSocket URL of the HoloViews page — never a background extension."""
    rows = [p for p in (pages or []) if isinstance(p, dict)]
    for page in rows:
        url = str(page.get("url") or "")
        kind = str(page.get("type") or "")
        ws = page.get("webSocketDebuggerUrl")
        if kind == "page" and ("/hv" in url or "/kanban" in url) and ws:
            return str(ws)
    for page in rows:
        if str(page.get("type") or "") == "page" and page.get("webSocketDebuggerUrl"):
            if str(page.get("url") or "").startswith("chrome-extension:"):
                continue
            return str(page["webSocketDebuggerUrl"])
    raise TimeoutError("no CDP page target for the HoloViews document")


def jpeg_to_image(data: bytes) -> Any:
    import io

    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def is_blank_plate(image: Any) -> bool:
    """Reject 500-page / empty-canvas captures so Listen does not go white."""
    try:
        import numpy as np

        arr = np.asarray(image.convert("RGB"), dtype=np.float32)
        step = max(1, arr.shape[0] // 24)
        mean = float(arr[::step, ::step].mean())
    except Exception:
        return False
    return mean >= 248.0 or mean <= 6.0


class CdpCamera:
    """One Chromium + one page target + screencast → latest RGB image."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.proc: Any = None
        self.user_data_dir = ""
        self.debug_port = 0
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._write_lock: asyncio.Lock | None = None
        self._on_image: Callable[[Any], None] | None = None
        self._screencast = False
        self.latest_image: Any = None
        self.frames = 0
        self._last_frame_at = 0.0
        self._pump_task: asyncio.Task | None = None

    async def start(
        self, url: str, *, on_image: Callable[[Any], None] | None = None, wait: str = "plot"
    ) -> None:
        binary = chromium_executable()
        if not binary:
            raise FileNotFoundError(
                "no Chromium on PATH; set HERMES_CHROMIUM to a --headless=new binary"
            )
        self._on_image = on_image
        self.user_data_dir = tempfile.mkdtemp(prefix=f"agentrtc-cdp-{self.session_id}-")
        self.debug_port = _free_loopback_port()
        cmd = chromium_cmd(
            binary=binary,
            user_data_dir=self.user_data_dir,
            debug_port=self.debug_port,
            url=url,
        )
        log.info("chromium session=%s port=%s", self.session_id, self.debug_port)
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ws_url = await self._wait_ws_url()
        import websockets

        self._ws = await websockets.connect(ws_url, max_size=8 * 1024 * 1024)
        self._write_lock = asyncio.Lock()
        self._reader = asyncio.create_task(self._read_loop())
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": VIEW_W,
                "height": VIEW_H,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        await self._wait_ready(wait)
        await self.start_screencast()
        await self._wait_first_frame()

    async def _wait_ws_url(self, timeout: float = 12.0) -> str:
        import urllib.request

        deadline = time.monotonic() + timeout
        list_url = f"http://127.0.0.1:{self.debug_port}/json/list"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(list_url, timeout=0.4) as resp:
                    pages = json.loads(resp.read().decode())
                try:
                    picked = pick_cdp_page(pages)
                except TimeoutError:
                    picked = ""
                if picked:
                    return picked
            except Exception:
                await asyncio.sleep(0.1)
        raise TimeoutError(f"CDP not listening on 127.0.0.1:{self.debug_port}")

    async def _write(self, payload: dict) -> None:
        if self._ws is None:
            raise RuntimeError("CDP websocket closed")
        lock = self._write_lock
        if lock is None:
            await self._ws.send(json.dumps(payload))
            return
        async with lock:
            await self._ws.send(json.dumps(payload))

    async def send(self, method: str, params: dict | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError("CDP websocket closed")
        self._next_id += 1
        msg_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await self._write({"id": msg_id, "method": method, "params": params or {}})
        try:
            reply = await asyncio.wait_for(fut, timeout=15.0)
        except TimeoutError:
            self._pending.pop(msg_id, None)
            raise
        if reply.get("error"):
            raise RuntimeError(f"CDP {method}: {reply['error']}")
        return reply.get("result") or {}

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(msg)
                    continue
                if msg.get("method") == "Page.screencastFrame":
                    # Never await send() here — that deadlocks the reader
                    # waiting for an Ack reply it cannot read.
                    asyncio.create_task(self._on_screencast(msg.get("params") or {}))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("cdp reader closed session=%s", self.session_id, exc_info=True)

    async def _on_screencast(self, params: dict) -> None:
        sid = params.get("sessionId")
        try:
            self._next_id += 1
            await self._write(
                {
                    "id": self._next_id,
                    "method": "Page.screencastFrameAck",
                    "params": {"sessionId": sid},
                }
            )
        except Exception:
            log.debug("screencast ack failed", exc_info=True)
        blob = params.get("data") or ""
        if not blob:
            return
        try:
            image = jpeg_to_image(base64.b64decode(blob))
        except Exception:
            log.debug("screencast jpeg decode failed", exc_info=True)
            return
        self._accept_image(image)

    def _accept_image(self, image: Any) -> None:
        if image is None or is_blank_plate(image):
            return
        self.latest_image = image
        self.frames += 1
        self._last_frame_at = time.monotonic()
        if self._on_image is not None:
            self._on_image(image)

    async def _wait_ready(self, wait: str = "plot", timeout: float = 20.0) -> None:
        """Wait until the page has painted (HoloViews canvas or kanban board)."""
        deadline = time.monotonic() + timeout
        if wait == "kanban":
            expr = "!!document.querySelector('[data-kanban-board]')"
        else:
            expr = """
        (() => {
          const walk = (root) => {
            if (!root) return 0;
            let n = root.querySelectorAll ? root.querySelectorAll('canvas').length : 0;
            if (root.querySelectorAll) {
              root.querySelectorAll('*').forEach((el) => {
                if (el.shadowRoot) n += walk(el.shadowRoot);
              });
            }
            return n;
          };
          return walk(document) > 0;
        })()
        """
        while time.monotonic() < deadline:
            try:
                result = await self.send(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True},
                )
                if (result.get("result") or {}).get("value"):
                    log.info("compositor ready wait=%s session=%s", wait, self.session_id)
                    return
            except Exception:
                pass
            await asyncio.sleep(0.2)
        raise TimeoutError(f"compositor wait={wait} never painted in Chromium")

    async def _wait_first_frame(self, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.latest_image is not None and self.frames > 0:
                return
            await asyncio.sleep(0.1)
        # Same compositor — seed one surface capture so we never start
        # the track on a black placeholder.
        shot = await self.send("Page.captureScreenshot", {"format": "jpeg", "quality": JPEG_QUALITY, "fromSurface": True})
        blob = shot.get("data") or ""
        if not blob:
            raise TimeoutError("CDP screencast produced no frames")
        jpeg = base64.b64decode(blob)
        image = jpeg_to_image(jpeg)
        self._accept_image(image)
        if self.latest_image is None:
            raise TimeoutError("CDP screencast produced no usable frames")

    async def navigate(self, url: str, *, wait: str = "plot") -> None:
        await self.send("Page.navigate", {"url": url})
        await self._wait_ready(wait)

    async def start_screencast(self) -> None:
        await self.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": JPEG_QUALITY,
                "maxWidth": VIEW_W,
                "maxHeight": VIEW_H,
                "everyNthFrame": 1,
            },
        )
        self._screencast = True
        try:
            await self.send(
                "Runtime.evaluate",
                {"expression": _CAST_KEEPALIVE_JS, "returnByValue": True},
            )
        except Exception:
            log.debug("screencast kick failed", exc_info=True)
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.create_task(self._frame_pump())

    async def _frame_pump(self) -> None:
        """Screenshot the live page when screencast goes idle — still video, not a still."""
        interval = 1.0 / max(1, PUMP_HZ)
        while self._screencast and self._ws is not None:
            await asyncio.sleep(interval)
            if not self._screencast:
                return
            if time.monotonic() - self._last_frame_at < interval * 0.8:
                continue
            try:
                shot = await self.send(
                    "Page.captureScreenshot",
                    {
                        "format": "jpeg",
                        "quality": JPEG_QUALITY,
                        "fromSurface": True,
                    },
                )
            except Exception:
                log.debug("viz frame pump failed", exc_info=True)
                return
            blob = shot.get("data") or ""
            if not blob:
                continue
            try:
                self._accept_image(jpeg_to_image(base64.b64decode(blob)))
            except Exception:
                log.debug("viz frame pump decode failed", exc_info=True)

    async def stop_screencast(self) -> None:
        if not self._screencast:
            return
        self._screencast = False
        task = self._pump_task
        self._pump_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await self.send("Page.stopScreencast")
        except Exception:
            log.debug("stopScreencast", exc_info=True)

    async def pointer(
        self,
        *,
        x: float,
        y: float,
        type: str = "mousePressed",
        button: str = "left",
    ) -> None:
        params: dict[str, Any] = {
            "type": type,
            "x": float(x),
            "y": float(y),
            "button": button,
        }
        if type in ("mousePressed", "mouseReleased"):
            params["clickCount"] = 1
        await self.send("Input.dispatchMouseEvent", params)

    async def close(self) -> None:
        await self.stop_screencast()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self.proc is not None and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None
        if self.user_data_dir:
            shutil.rmtree(self.user_data_dir, ignore_errors=True)
            self.user_data_dir = ""
