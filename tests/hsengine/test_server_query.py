"""Federation face: Status carries surfaces; ServerQuery answers SURFACES / PEERS."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from hsengine.config import reset_config
from hsengine.engine import federation, probe, server
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

GAIUS = "127.0.0.1:50051"
AEGIR = "127.0.0.1:50151"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    monkeypatch.delenv("HERMES_PRIMARY_UI", raising=False)
    reset_config()
    federation.reset_status_cache()
    yield
    reset_config()
    federation.reset_status_cache()


def _dash(healthy: bool = True) -> probe.SurfaceProbe:
    return probe.SurfaceProbe(
        healthy=healthy,
        url="http://127.0.0.1:9119/api/health",
        detail="ok" if healthy else "unreachable",
    )


def _gw(healthy: bool = False) -> probe.SurfaceProbe:
    return probe.SurfaceProbe(
        healthy=healthy, url="http://127.0.0.1:8642/health", detail="down"
    )


def _gaius_status() -> dict:
    return {
        "project": "gaius",
        "total_gpus": 6,
        "endpoints": [
            {"capability": "cognition", "model": "gaius-engine", "healthy": True, "gpu_ids": []},
            {"capability": "thinking", "model": "Qwen/Qwen3.8-27B", "healthy": False, "gpu_ids": [0, 1, 2, 3]},
        ],
        "surfaces": [{"kind": "primary", "url": "http://lattice.example.org:9890", "healthy": True}],
    }


def _quiet():
    statuses = {GAIUS: _gaius_status(), AEGIR: None}
    return (
        patch.object(server.probe, "probe_dashboard", return_value=_dash()),
        patch.object(server.probe, "probe_gateway", return_value=_gw()),
        patch.object(federation, "federation_peers", return_value=[GAIUS, AEGIR]),
        patch.object(federation, "peer_status", side_effect=lambda p, *a, **k: statuses.get(p)),
        patch.object(server.yk, "our_gpu_ids", return_value=[]),
    )


def _run(coro):
    return asyncio.run(coro)


def test_status_advertises_hermes_agent_and_route_model():
    p1, p2, p3, p4, p5 = _quiet()
    with p1, p2, p3, p4, p5:
        resp = _run(server.ZndxEngineServicer().Status(zpb.StatusRequest(), None))
    assert resp.project == "hermes"
    primary = [s for s in resp.surfaces if s.kind == "primary"]
    assert [(s.url, s.healthy) for s in primary] == [("http://lattice.example.org:9119", True)]
    by_cap = {e.capability: e for e in resp.endpoints}
    assert "agent" in by_cap
    assert by_cap["agent"].healthy is True
    assert by_cap["instruct"].model == "Qwen/Qwen3.8-27B"
    assert resp.total_gpus == 6
    assert list(by_cap["agent"].gpu_ids) == []
    detail = json.loads(by_cap["instruct"].detail)
    assert detail["federation"]["accepted"] == ["thinking", "instruct"]
    assert detail["federation"]["route"]["capability"] == "thinking"
    assert detail["federation"]["route"]["project"] == "gaius"
    blob = by_cap["instruct"].detail.lower() + by_cap["agent"].detail.lower()
    for forbidden in ("password", "api_key", "secret", "token"):
        assert forbidden not in blob


def test_peer_gpu_occupancy_unions_status_gpu_ids():
    with (
        patch.object(federation, "federation_peers", return_value=[GAIUS, AEGIR]),
        patch.object(
            federation,
            "peer_status",
            side_effect=lambda p, *a, **k: _gaius_status() if p == GAIUS else None,
        ),
    ):
        held, n = federation.peer_gpu_occupancy()
    assert held == frozenset({0, 1, 2, 3})
    assert n == 6


def test_server_query_surfaces():
    p1, p2, p3, p4, p5 = _quiet()
    with p1, p2, p3, p4, p5:
        resp = _run(
            server.ZndxEngineServicer().ServerQuery(
                zpb.ServerQueryRequest(kind=zpb.SERVER_QUERY_KIND_SURFACES, origin_project="gaius"),
                None,
            )
        )
    assert resp.project == "hermes"
    assert [s.kind for s in resp.surfaces][0] == "primary"
    assert resp.surfaces[0].url == "http://lattice.example.org:9119"


def test_server_query_peers_canonicalizes_loopback_targets():
    p1, p2, p3, p4, p5 = _quiet()
    with p1, p2, p3, p4, p5:
        resp = _run(
            server.ZndxEngineServicer().ServerQuery(
                zpb.ServerQueryRequest(kind=zpb.SERVER_QUERY_KIND_PEERS), None
            )
        )
    assert [(p.project, p.target) for p in resp.peers] == [
        ("gaius", "lattice.example.org:50051"),
        ("", "lattice.example.org:50151"),
    ]


def test_server_query_unknown_kind_is_honest_empty():
    # QUEUES is a kind this engine does not serve: an honest empty answer.
    p1, p2, p3, p4, p5 = _quiet()
    with p1, p2, p3, p4, p5:
        resp = _run(
            server.ZndxEngineServicer().ServerQuery(
                zpb.ServerQueryRequest(kind=zpb.SERVER_QUERY_KIND_QUEUES), None
            )
        )
    assert resp.project == "hermes"
    assert not resp.remotes and not resp.surfaces and not resp.peers and not resp.schedules


def test_server_query_schedules_is_the_workload_catalogue():
    # (2026-09-07) SCHEDULES is no longer empty: it is this engine's workload
    # catalogue — the interactive agent-rtc workflow, source=engine.
    p1, p2, p3, p4, p5 = _quiet()
    with p1, p2, p3, p4, p5:
        resp = _run(
            server.ZndxEngineServicer().ServerQuery(
                zpb.ServerQueryRequest(kind=zpb.SERVER_QUERY_KIND_SCHEDULES), None
            )
        )
    assert [(s.id, s.kind, s.source) for s in resp.schedules] == [
        ("interactive.agent_rtc", "interactive_session", "engine")
    ]
    assert not resp.remotes and not resp.surfaces and not resp.peers


def test_yield_unknown_workload_is_idempotent_ok():
    resp = _run(
        server.ZndxEngineServicer().Yield(zpb.YieldRequest(workload_id="missing"), None)
    )
    assert resp.ok is True
    assert resp.process_ended is False
