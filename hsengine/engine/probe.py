"""Non-secret health probes for advertised Hermes surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from hsengine.config import get_int, get_str


@dataclass(frozen=True)
class SurfaceProbe:
    healthy: bool
    url: str
    detail: str


def _get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — loopback product probe
        body = resp.read(512).decode("utf-8", errors="replace")
        return int(resp.status), body


def probe_url(url: str, *, timeout: float = 2.0) -> SurfaceProbe:
    if not url:
        return SurfaceProbe(healthy=False, url=url, detail="no url")
    try:
        status, _body = _get(url, timeout=timeout)
        ok = 200 <= status < 300
        return SurfaceProbe(healthy=ok, url=url, detail=f"http {status}")
    except URLError as e:
        return SurfaceProbe(healthy=False, url=url, detail=f"unreachable: {e.reason}")
    except Exception as e:
        return SurfaceProbe(healthy=False, url=url, detail=f"{type(e).__name__}: {e}")


def dashboard_health_url() -> str:
    try:
        base = get_str("hermes.dashboard.http.base_url").rstrip("/")
        path = get_str("hermes.dashboard.http.health_path") or "/api/health"
    except Exception:
        return "http://127.0.0.1:9119/api/health"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def gateway_health_url() -> str:
    try:
        base = get_str("hermes.gateway.http.base_url").rstrip("/")
        path = get_str("hermes.gateway.http.health_path") or "/health"
    except Exception:
        return "http://127.0.0.1:8642/health"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def probe_dashboard() -> SurfaceProbe:
    return probe_url(dashboard_health_url())


def probe_gateway() -> SurfaceProbe:
    return probe_url(gateway_health_url())


def dashboard_bind_port() -> int:
    try:
        return get_int("hermes.dashboard.http.bind_port")
    except Exception:
        return 9119
