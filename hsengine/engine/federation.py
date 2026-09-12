"""Federated capability client — plan routes from peer Status, then Complete.

DEPRECATED(federation sole path): portable federation MUST use KServe OIP
(ModelInfer / ModelStreamInfer). Unary ``Engine/Complete`` remains the
transitional adapter here.

Law: never expose peer-private model HTTP ports (vLLM). Peers own GPU leases.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import grpc

from hsengine.config import get_int, load_config
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

log = logging.getLogger("hsengine.engine.federation")

DEFAULT_CAPABILITY = "agent"
LOCAL_CAPABILITIES = frozenset({"agent"})
_DEFAULT_ACCEPTED: dict[str, list[str]] = {
    "agent": ["thinking", "instruct"],
    "instruct": ["thinking", "instruct"],
}


@dataclass(frozen=True)
class CompleteResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    reasoning_content: str
    finish_reason: str
    peer: str
    capability: str


@dataclass(frozen=True)
class Route:
    """One candidate fulfilment; ``capability`` is the name the PEER advertises."""

    peer: str
    capability: str
    model: str = ""
    healthy: bool | None = None
    project: str = ""

    @property
    def label(self) -> str:
        who = self.project or self.peer
        text = f"{who} capability={self.capability}"
        return f"{text} model={self.model}" if self.model else text


def _cfg(path: str, default: Any = None) -> Any:
    try:
        value = load_config().get(path)
    except Exception:
        return default
    return default if value is None else value


def as_str_list(value: Any) -> list[str]:
    """HOCON list, or a comma-separated env override string, as clean strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    try:
        return [str(v).strip() for v in value if str(v).strip()]
    except TypeError:
        text = str(value).strip()
        return [text] if text else []


def federation_peers() -> list[str]:
    """Configured peer targets (host:port) in preference order. Empty ⇒ no route."""
    return as_str_list(_cfg("hermes.engine.federation.peers"))


def normalize_capability(capability: str | None) -> str:
    return (capability or "").strip() or DEFAULT_CAPABILITY


def accepted_capabilities(capability: str | None) -> list[str]:
    """Peer capabilities acceptable for a product capability, best first."""
    cap = normalize_capability(capability)
    configured = as_str_list(_cfg(f"hermes.engine.federation.capability_map.{cap}"))
    if configured:
        return configured
    return list(_DEFAULT_ACCEPTED.get(cap, [cap]))


def map_capability(capability: str | None) -> str:
    return accepted_capabilities(capability)[0]


def federated_capability_names() -> frozenset[str]:
    cmap = _cfg("hermes.engine.federation.capability_map")
    keys = set(cmap.keys()) if hasattr(cmap, "keys") else set()
    keys.update(_DEFAULT_ACCEPTED)
    names: set[str] = set()
    for key in keys:
        names.add(key)
        names.update(accepted_capabilities(key))
    return frozenset(names)


def is_federated_capability(capability: str | None) -> bool:
    cap = (capability or "").strip()
    if not cap:
        return False
    return cap in federated_capability_names()


def complete_timeout_s() -> float:
    try:
        return float(get_int("hermes.engine.federation.timeout_s"))
    except Exception:
        return 1200.0


def status_ttl_s() -> float:
    try:
        return float(_cfg("hermes.engine.federation.status_ttl_s", 5))
    except (TypeError, ValueError):
        return 5.0


_status_lock = threading.Lock()
_status_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _fetch_status(peer: str, timeout: float) -> dict[str, Any] | None:
    try:
        with grpc.insecure_channel(peer) as ch:
            stub = zpb_grpc.EngineStub(ch)
            st = stub.Status(zpb.StatusRequest(), timeout=timeout)
    except Exception as e:
        log.debug("peer Status failed %s: %s", peer, e)
        return None
    return {
        "project": st.project,
        "total_gpus": st.total_gpus,
        "endpoints": [
            {
                "capability": ep.capability,
                "model": ep.model,
                "healthy": ep.healthy,
                "gpu_ids": list(ep.gpu_ids),
            }
            for ep in st.endpoints
        ],
        "surfaces": [
            {"kind": s.kind, "url": s.url, "healthy": s.healthy} for s in st.surfaces
        ],
    }


def peer_status(
    peer: str, timeout: float = 5.0, *, use_cache: bool = True
) -> dict[str, Any] | None:
    ttl = status_ttl_s()
    now = time.monotonic()
    if use_cache and ttl > 0:
        with _status_lock:
            hit = _status_cache.get(peer)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    snapshot = _fetch_status(peer, timeout)
    with _status_lock:
        _status_cache[peer] = (now, snapshot)
    return snapshot


def reset_status_cache() -> None:
    with _status_lock:
        _status_cache.clear()


def query_peer(
    peer: str,
    kind: int,
    *,
    limit: int = 0,
    since_ms: int = 0,
    stream: str = "",
    note_id: str = "",
    query: str = "",
    timeout: float = 8.0,
):
    """One ``Engine/ServerQuery`` at a peer engine (two hops: the voice loop asks
    THIS engine, this engine asks the peer). Returns the response or None when
    the peer is unreachable / does not serve the kind — the caller says so."""
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    target = str(peer or "").replace("grpc://", "").strip()
    if not target:
        return None
    kwargs = dict(
        kind=kind, origin_project="hermes", limit=int(limit or 0),
        since_ms=int(since_ms or 0), stream=str(stream or ""), note_id=str(note_id or ""),
    )
    if query:
        kwargs["query"] = query
    req = zpb.ServerQueryRequest(**kwargs)
    try:
        with grpc.insecure_channel(target) as ch:
            return zpb_grpc.EngineStub(ch).ServerQuery(req, timeout=timeout)
    except grpc.RpcError as e:
        log.info("ServerQuery kind=%s at %s failed: %s", kind, target, e.code().name)
        return None


def peer_gpu_occupancy() -> tuple[frozenset[int], int]:
    """Union of peer ``Status.gpu_ids`` and the max advertised ``total_gpus``.

    YK queue state is token counts, not devices. Physical pins are what
    each engine reports on ``Endpoint.gpu_ids``. Empty Status is honest:
    packing still uses ``total_gpus`` (or 0 if no peer answered).
    """
    held: set[int] = set()
    total = 0
    for peer in federation_peers():
        st = peer_status(peer)
        if not st:
            continue
        try:
            total = max(total, int(st.get("total_gpus") or 0))
        except (TypeError, ValueError):
            pass
        for ep in st.get("endpoints") or []:
            if not isinstance(ep, dict):
                continue
            for raw in ep.get("gpu_ids") or []:
                try:
                    held.add(int(raw))
                except (TypeError, ValueError):
                    continue
    return frozenset(held), total


def plan_routes(capability: str | None, peers: list[str] | None = None) -> list[Route]:
    cap = normalize_capability(capability)
    accepted = accepted_capabilities(cap)
    peers = federation_peers() if peers is None else list(peers)
    routes: list[Route] = []
    answered: list[tuple[str, dict[str, Any]]] = []
    for peer in peers:
        st = peer_status(peer)
        if not st:
            continue
        answered.append((peer, st))
        for ep in st.get("endpoints") or []:
            if ep.get("capability") in accepted:
                routes.append(
                    Route(
                        peer=peer,
                        capability=str(ep["capability"]),
                        model=str(ep.get("model") or ""),
                        healthy=bool(ep.get("healthy")),
                        project=str(st.get("project") or ""),
                    )
                )
    if not routes:
        routes = [
            Route(peer=peer, capability=accepted[0], project=str(st.get("project") or ""))
            for peer, st in answered
        ]
    peer_index = {p: i for i, p in enumerate(peers)}

    def _key(r: Route) -> tuple[int, int, int]:
        rank = accepted.index(r.capability) if r.capability in accepted else len(accepted)
        return (0 if r.healthy else 1, rank, peer_index.get(r.peer, len(peers)))

    routes.sort(key=_key)
    return routes


def preferred_route(capability: str | None = DEFAULT_CAPABILITY) -> Route | None:
    routes = plan_routes(capability)
    return routes[0] if routes else None


def no_route_reason(capability: str | None) -> str:
    peers = federation_peers()
    if not peers:
        return "no federation peers configured (hermes.engine.federation.peers)"
    return (
        f"no federation peer answered Status for {','.join(accepted_capabilities(capability))} "
        f"(peers={','.join(peers)})"
    )


def peer_hints() -> list[tuple[str, str]]:
    """(project, target) per configured peer for ServerQuery PEERS; project '' if silent."""
    hints: list[tuple[str, str]] = []
    for peer in federation_peers():
        st = peer_status(peer)
        hints.append((str((st or {}).get("project") or ""), peer))
    return hints


def complete_on_peer(
    peer: str,
    *,
    capability: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    json_schema: str = "",
    timeout: float | None = None,
    peer_capability: str | None = None,
) -> CompleteResult:
    """DEPRECATED(federation): prefer OIP ModelInfer."""
    peer_cap = (peer_capability or "").strip() or map_capability(capability)
    timeout = complete_timeout_s() if timeout is None else timeout
    t0 = time.perf_counter()
    req = zpb.CompleteRequest(
        capability=peer_cap,
        prompt=prompt or "",
        system_prompt=system_prompt or "",
        max_tokens=int(max_tokens or 4096),
        temperature=float(temperature if temperature is not None else 0.7),
        json_schema=json_schema or "",
    )
    with grpc.insecure_channel(peer) as ch:
        stub = zpb_grpc.EngineStub(ch)
        resp = stub.Complete(req, timeout=timeout)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    return CompleteResult(
        text=resp.text or "",
        model=resp.model or "",
        prompt_tokens=int(resp.prompt_tokens or 0),
        completion_tokens=int(resp.completion_tokens or 0),
        latency_ms=float(resp.latency_ms or wall_ms),
        reasoning_content=resp.reasoning_content or "",
        finish_reason=resp.finish_reason or "",
        peer=peer,
        capability=peer_cap,
    )


def inference_ready(capability: str | None = DEFAULT_CAPABILITY) -> tuple[bool, str]:
    if not federation_peers():
        return False, "no peers configured"
    route = preferred_route(capability)
    if route is None:
        return False, no_route_reason(capability)
    detail = f"{route.peer} {route.label}"
    if route.healthy is None:
        detail += " (not advertised yet; lazy Complete may load)"
    elif not route.healthy:
        detail += " (advertised; health unreported)"
    return True, detail
