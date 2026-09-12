"""Push Engine/Announce so waffle walkers find this primary UI over S2S.

Launchers stay pull-only. Hermes joins by telling directory engines (Ægir,
later the Signals hub) our lattice ``host:port``. ``UNIMPLEMENTED`` is
honest — try the next seed. The roster is the callee's; we do not invent
a parallel store.
"""
from __future__ import annotations

import logging

import grpc

from hsengine.config import get_int, load_config
from hsengine.engine import federation, surfaces
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

log = logging.getLogger("hsengine.engine.announce")

PROJECT = "hermes"
DEFAULT_TTL_S = 90


def _cfg_str(path: str) -> str:
    try:
        value = load_config().get(path)
    except Exception:
        return ""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "none" else text


def announce_ttl_s() -> int:
    try:
        ttl = int(get_int("hermes.engine.federation.announce_ttl_s"))
    except Exception:
        ttl = DEFAULT_TTL_S
    return ttl if ttl > 0 else DEFAULT_TTL_S


def local_engine_target() -> str:
    """Reachable lattice Engine host:port. Empty if we have no advertise host."""
    host = surfaces.advertise_host()
    if not host:
        return ""
    try:
        port = get_int("hermes.engine.grpc.port")
    except Exception:
        port = 50651
    return f"{host}:{port}"


def _is_self(target: str) -> bool:
    host, sep, port = target.rpartition(":")
    if not sep:
        return False
    try:
        ours = str(get_int("hermes.engine.grpc.port"))
    except Exception:
        ours = "50651"
    if port != ours:
        return False
    return surfaces.is_loopback_host(host) or host == surfaces.advertise_host()


def announce_targets() -> list[str]:
    """Directory seeds: SIGNALS_ENGINE_TARGET then federation.peers. Skip self."""
    seen: set[str] = set()
    out: list[str] = []
    raw_list = [_cfg_str("hermes.engine.federation.directory"), *federation.federation_peers()]
    for raw in raw_list:
        addr = (raw or "").replace("grpc://", "").strip()
        if not addr or addr in seen or _is_self(addr):
            continue
        seen.add(addr)
        out.append(addr)
    return out


def build_announce(*, dashboard_healthy: bool = True) -> zpb.PeerAnnounce | None:
    target = local_engine_target()
    if not target:
        return None
    return zpb.PeerAnnounce(
        project=PROJECT,
        engine_target=target,
        surfaces=surfaces.local_surfaces(dashboard_healthy),
        ttl_seconds=announce_ttl_s(),
    )


def announce_once(target: str, req: zpb.PeerAnnounce, timeout: float = 4.0) -> zpb.AnnounceAck | None:
    addr = target.replace("grpc://", "").strip()
    try:
        with grpc.insecure_channel(addr) as channel:
            stub = zpb_grpc.EngineStub(channel)
            return stub.Announce(req, timeout=timeout)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            log.info("Announce UNIMPLEMENTED at %s — peer is not a directory", addr)
            return None
        log.warning("Announce failed at %s: %s %s", addr, e.code(), e.details())
        return None
    except Exception as e:
        log.warning("Announce failed at %s: %s", addr, e)
        return None


def announce_all(*, dashboard_healthy: bool = True) -> list[tuple[str, zpb.AnnounceAck | None]]:
    req = build_announce(dashboard_healthy=dashboard_healthy)
    if req is None:
        log.info("Announce skipped — no advertise host for engine_target")
        return []
    results: list[tuple[str, zpb.AnnounceAck | None]] = []
    for target in announce_targets():
        ack = announce_once(target, req)
        results.append((target, ack))
        if ack is not None and ack.accepted:
            log.info("Announced hermes at %s to %s (ttl=%ss)", req.engine_target, target, ack.ttl_seconds)
    return results
