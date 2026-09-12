"""Federation surfaces — advertise the Hermes dashboard to the signals lattice.

signals-protocol ``specification/protocol/surfaces.md``: a peer launcher lists
only engines that answer ``Engine/Status`` and fill ``StatusResponse.surfaces``
with a ``kind=primary`` browser-reachable URL. Never loopback. Never secrets.
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse, urlunparse

from hsengine.config import get_int, load_config
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

SURFACE_PRIMARY = "primary"
SURFACE_HEALTH = "health"
SURFACE_GATEWAY = "gateway"
DEFAULT_BIND_PORT = 9119
DEFAULT_HEALTH_PATH = "/api/health"

_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"})


def _cfg_str(path: str) -> str:
    """Config string with pyhocon's None / 'None' for unset ``${?VAR}`` folded to ''."""
    try:
        value = load_config().get(path)
    except Exception:
        return ""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "none" else text


def is_loopback_host(host: str | None) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if not h:
        return True
    return h in _LOOPBACK or h.startswith("127.")


def _host_only(raw: str) -> str:
    """Accept ``host``, ``host:port`` or ``scheme://host:port/…``; return the bare host."""
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" in text:
        return (urlparse(text).hostname or "").strip("[]")
    text = text.split("/", 1)[0]
    if text.count(":") == 1:
        text = text.rsplit(":", 1)[0]
    return text.strip("[]")


def advertise_host() -> str:
    """Lattice hostname peers should use for our URLs. Never loopback; '' is honest."""
    configured = _host_only(_cfg_str("hermes.dashboard.http.advertise_host"))
    if configured and not is_loopback_host(configured):
        return configured
    try:
        fqdn = (socket.getfqdn() or "").strip()
        if fqdn and "." in fqdn and not is_loopback_host(fqdn):
            return fqdn
        short = (socket.gethostname() or "").strip()
        if short and not is_loopback_host(short):
            return short
    except OSError:
        pass
    return ""


def rewrite_public_url(url: str) -> str:
    """Swap a loopback host in ``url`` for the advertise host, keeping the port."""
    host = advertise_host()
    if not url or not host:
        return url
    parsed = urlparse(url)
    if not parsed.hostname or not is_loopback_host(parsed.hostname):
        return url
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse(
        (parsed.scheme or "http", netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _bind_port() -> int:
    try:
        return get_int("hermes.dashboard.http.bind_port")
    except Exception:
        return DEFAULT_BIND_PORT


def _health_path() -> str:
    path = _cfg_str("hermes.dashboard.http.health_path") or DEFAULT_HEALTH_PATH
    return path if path.startswith("/") else f"/{path}"


def primary_ui_url() -> str:
    """Browser-reachable Hermes dashboard URL, or '' when no non-loopback host is known."""
    override = _cfg_str("hermes.dashboard.http.primary_ui")
    if override:
        candidate = rewrite_public_url(override)
        if not is_loopback_host(urlparse(candidate).hostname):
            return candidate.rstrip("/")
    host = advertise_host()
    if not host:
        return ""
    return f"http://{host}:{_bind_port()}"


def gateway_url() -> str:
    """Browser/API-reachable gateway URL under the advertise host, or ''."""
    host = advertise_host()
    if not host:
        return ""
    try:
        port = get_int("hermes.gateway.http.bind_port")
    except Exception:
        port = 8642
    return f"http://{host}:{port}"


def local_surfaces(healthy: bool, *, gateway_healthy: bool | None = None) -> list[zpb.Surface]:
    """``StatusResponse.surfaces`` for this engine; empty when no public host is known."""
    url = primary_ui_url()
    if not url:
        return []
    gw_ok = healthy if gateway_healthy is None else bool(gateway_healthy)
    surfaces = [
        zpb.Surface(kind=SURFACE_PRIMARY, url=url, healthy=bool(healthy)),
        zpb.Surface(kind=SURFACE_HEALTH, url=f"{url}{_health_path()}", healthy=bool(healthy)),
    ]
    gw = gateway_url()
    if gw:
        surfaces.append(zpb.Surface(kind=SURFACE_GATEWAY, url=gw, healthy=gw_ok))
    return surfaces


def canonical_target(addr: str) -> str:
    """Loopback peer targets are same-box; present them under the advertise host."""
    host = advertise_host()
    if not host or not addr:
        return addr
    tgt_host, sep, port = addr.rpartition(":")
    if sep and is_loopback_host(tgt_host):
        return f"{host}:{port}"
    return addr
