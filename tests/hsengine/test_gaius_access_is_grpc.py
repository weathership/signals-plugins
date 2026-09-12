"""Hermes reaches Gaius capabilities over gRPC, never peer-private HTTP."""
from __future__ import annotations

from types import SimpleNamespace

from hsengine.engine import federation
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb


def test_complete_on_peer_calls_engine_complete(monkeypatch):
    seen: list[str] = []

    class _Stub:
        def Complete(self, req, timeout=None):
            seen.append(req.capability)
            return SimpleNamespace(
                text="ok",
                model="Qwen",
                prompt_tokens=1,
                completion_tokens=1,
                latency_ms=1.0,
                reasoning_content="",
                finish_reason="stop",
            )

    class _Ch:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(federation.grpc, "insecure_channel", lambda peer: _Ch())
    monkeypatch.setattr(
        federation.zpb_grpc, "EngineStub", lambda ch: _Stub()
    )
    out = federation.complete_on_peer(
        "127.0.0.1:50051",
        capability="thinking",
        prompt="hi",
    )
    assert seen == ["thinking"]
    assert out.peer == "127.0.0.1:50051"
    assert out.text == "ok"


def test_query_peer_is_engine_server_query(monkeypatch):
    class _Stub:
        def ServerQuery(self, req, timeout=None):
            assert req.kind == zpb.SERVER_QUERY_KIND_FMP
            return SimpleNamespace(project="gaius", fmp_hint=None)

    class _Ch:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(federation.grpc, "insecure_channel", lambda peer: _Ch())
    monkeypatch.setattr(
        "hsengine.engine.generated.zndx.engine.v1.engine_pb2_grpc.EngineStub",
        lambda ch: _Stub(),
    )
    resp = federation.query_peer(
        "127.0.0.1:50051", zpb.SERVER_QUERY_KIND_FMP, query="SLB", stream="quote"
    )
    assert resp.project == "gaius"
