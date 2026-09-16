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
        if kind == "page" and "/hv" in url and ws:
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
        self._on_image: Callable[[Any], None] | None = None
        self._screencast = False
        self.latest_image: Any = None
        self.frames = 0

    async def start(self, url: str, *, on_image: Callable[[Any], None] | None = None) -> None:
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
        self._reader = asyncio.create_task(self._read_loop())
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self._wait_plot()
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

    async def send(self, method: str, params: dict | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError("CDP websocket closed")
        self._next_id += 1
        msg_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(payload))
        try:
            reply = await asyncio.wait_for(fut, timeout=8.0)
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
                    await self._on_screencast(msg.get("params") or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("cdp reader closed session=%s", self.session_id, exc_info=True)

    async def _on_screencast(self, params: dict) -> None:
        sid = params.get("sessionId")
        try:
            await self.send("Page.screencastFrameAck", {"sessionId": sid})
        except Exception:
            log.debug("screencast ack failed", exc_info=True)
        blob = params.get("data") or ""
        if not blob:
            return
        try:
            jpeg = base64.b64decode(blob)
            image = jpeg_to_image(jpeg)
        except Exception:
            log.debug("screencast jpeg decode failed", exc_info=True)
            return
        self.latest_image = image
        self.frames += 1
        if self._on_image is not None:
            self._on_image(image)

    async def _wait_plot(self, timeout: float = 20.0) -> None:
        """Wait until HoloViews has painted a canvas, not merely loaded BokehJS."""
        deadline = time.monotonic() + timeout
        expr = (
            "(document.querySelectorAll('canvas').length > 0) || "
            "(document.querySelectorAll('.bk-Canvas, canvas.bk-canvas').length > 0)"
        )
        while time.monotonic() < deadline:
            try:
                result = await self.send(
                    "Runtime.evaluate",
                    {"expression": expr, "returnByValue": True},
                )
                if (result.get("result") or {}).get("value"):
                    log.info("holoviews canvas present session=%s", self.session_id)
                    return
            except Exception:
                pass
            await asyncio.sleep(0.2)
        raise TimeoutError("HoloViews canvas never painted in Chromium")

    async def _wait_first_frame(self, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.latest_image is not None and self.frames > 0:
                return
            await asyncio.sleep(0.1)
        # Same compositor, still HoloViews — seed one surface capture so we
        # never fade in a black placeholder.
        shot = await self.send("Page.captureScreenshot", {"format": "jpeg", "quality": JPEG_QUALITY, "fromSurface": True})
        blob = shot.get("data") or ""
        if not blob:
            raise TimeoutError("CDP screencast produced no frames")
        jpeg = base64.b64decode(blob)
        image = jpeg_to_image(jpeg)
        self.latest_image = image
        self.frames += 1
        if self._on_image is not None:
            self._on_image(image)

    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})
        await self._wait_plot()

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

    async def stop_screencast(self) -> None:
        if not self._screencast:
            return
        self._screencast = False
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
