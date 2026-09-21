"""In-process Bokeh server on loopback for AgentRTC Chromium.

Not Aegir's /viz reverse proxy. One server per engine process; each
Connect's Chromium holds its own Bokeh websocket document.
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.bokeh")

_mu = threading.Lock()
_server: Any = None
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


def ensure_server() -> int:
    """Start the loopback Bokeh server if needed. Returns the bound port."""
    global _server, _port
    with _mu:
        if _server is not None and _port:
            return _port
        port = _free_loopback_port()
        from bokeh.application import Application
        from bokeh.application.handlers.function import FunctionHandler
        from bokeh.server.server import Server

        from hsengine.engine.webrtc_viz_apps import modify_doc

        from tornado.web import RequestHandler

        class KanbanHandler(RequestHandler):
            def get(self) -> None:
                from hsengine.engine.webrtc_kanban import board_html

                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.set_header("Cache-Control", "no-store")
                self.write(board_html())

        apps = {"/hv": Application(FunctionHandler(modify_doc))}
        server = Server(
            apps,
            address="127.0.0.1",
            port=port,
            allow_websocket_origin=origin_hosts(port),
            extra_patterns=[(r"/kanban", KanbanHandler)],
            num_procs=1,
        )
        server.start()
        _server = server
        _port = port
        log.info("bokeh loopback server http://127.0.0.1:%s/hv", port)
        return _port


def stop_server() -> None:
    global _server, _port
    with _mu:
        server, _server = _server, None
        _port = 0
    if server is None:
        return
    try:
        server.stop()
    except Exception:
        log.debug("bokeh stop", exc_info=True)
