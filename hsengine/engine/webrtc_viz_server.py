"""Bokeh/HoloViews server for AgentRTC, in its own process.

The engine's asyncio loop is also the WebRTC audio clock (one frame
every 20 ms). A plot render holds the GIL for a long stretch. Running
it here means that stretch is not the process that sends audio.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import signal
from pathlib import Path

log = logging.getLogger("hsengine.engine.webrtc.viz.server")


def _die_with_parent() -> None:
    """Exit if the engine dies. A restarted voice process must not leave this behind."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(1, int(signal.SIGTERM)) != 0:
            log.warning("viz server will not exit with the engine")
    except Exception:
        log.debug("pdeathsig unavailable", exc_info=True)


def _build(port: int):
    from bokeh.application import Application
    from bokeh.application.handlers.function import FunctionHandler
    from bokeh.server.server import Server
    from tornado.ioloop import IOLoop
    from tornado.web import RequestHandler

    from hsengine.engine.webrtc_bokeh import origin_hosts
    from hsengine.engine.webrtc_viz_apps import SCENES, modify_doc, replace_object

    class HealthHandler(RequestHandler):
        def get(self) -> None:
            self.write({"ok": True, "pid": os.getpid()})

    class KanbanHandler(RequestHandler):
        def get(self) -> None:
            from hsengine.engine.webrtc_kanban import board_html

            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.set_header("Cache-Control", "no-store")
            self.write(board_html())

    class SceneHandler(RequestHandler):
        def post(self) -> None:
            try:
                body = json.loads(self.request.body.decode() or "{}")
            except json.JSONDecodeError:
                self.set_status(400)
                self.write({"ok": False, "error": "bad json"})
                return
            sid = str(body.get("session") or "").strip()
            scene = body.get("scene")
            if not sid or not isinstance(scene, dict):
                self.set_status(400)
                self.write({"ok": False, "error": "session and scene required"})
                return
            SCENES[sid] = scene
            replaced = bool(replace_object(sid, scene))
            self.write({"ok": True, "replaced": replaced, "pid": os.getpid()})

    io = IOLoop()
    io.make_current()
    server = Server(
        {"/hv": Application(FunctionHandler(modify_doc))},
        io_loop=io,
        address="127.0.0.1",
        port=port,
        allow_websocket_origin=origin_hosts(port),
        extra_patterns=[
            (r"/health", HealthHandler),
            (r"/kanban", KanbanHandler),
            (r"/scene", SceneHandler),
        ],
        num_procs=1,
    )
    server.start()
    bound = int(server.port or port)
    log.info("viz server pid=%s http://127.0.0.1:%s/hv", os.getpid(), bound)
    return server, bound


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _die_with_parent()
    from hsengine.engine.webrtc_bokeh import _free_loopback_port

    _server, port = _build(_free_loopback_port())
    ready = (os.environ.get("HSENGINE_VIZ_READY") or "").strip()
    if ready:
        Path(ready).write_text(f"{port}\n")
    _server.io_loop.start()


if __name__ == "__main__":
    main()
