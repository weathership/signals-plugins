"""The engine is the only Mistral speaker. Peers call Platforms over gRPC."""
from __future__ import annotations

import json

from hsengine.engine import mistral_platform as plat
from hsengine.engine import s2s
from hsengine.engine import source_drop as drop
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.platform.v1 import platform_pb2 as ppb

_URL = "https://arxiv.org/abs/2402.03300"


def _silence(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))


def test_absent_key_is_not_a_platform(monkeypatch, tmp_path):
    _silence(monkeypatch, tmp_path)
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_PLATFORMS)
    assert list(resp.platforms) == []


def test_server_query_lists_mistral_for_every_peer(monkeypatch, tmp_path):
    _silence(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_PLATFORMS)
    assert len(resp.platforms) == 1
    hint = resp.platforms[0]
    assert hint.vendor == "mistral"
    assert hint.project == "hermes"
    assert hint.billing == "token-metered"
    assert list(hint.products) == ["document", "workflow"]
    assert "super-secret" not in str(resp)


def test_document_analyze_returns_json_without_the_credential(monkeypatch, tmp_path):
    _silence(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    seen = {}

    def analyze(url, *, kind, key=None):
        seen["url"] = url
        seen["kind"] = kind
        seen["key"] = key
        return {
            "url": "https://arxiv.org/pdf/2402.03300.pdf",
            "kind": kind,
            "title": "Replay",
            "summary": "A summary.",
            "claims": ["one"],
            "method": "a method",
            "limits": "a limit",
            "text": "The paper.",
            "model": "mistral-ocr-latest",
        }

    monkeypatch.setattr(drop, "mistral_analyze", analyze)
    events = list(
        plat.iter_call(
            ppb.PlatformCall(
                vendor="mistral",
                product="document",
                verb="analyze",
                input_json=json.dumps({"url": _URL}),
            )
        )
    )
    assert [ev.WhichOneof("event") for ev in events] == ["accepted", "deliverable", "done"]
    assert events[0].accepted.billing == "token-metered"
    assert seen == {"url": _URL, "kind": "arxiv", "key": "super-secret"}
    body = json.loads(events[1].deliverable.json)
    assert body["summary"] == "A summary."
    assert "super-secret" not in events[1].deliverable.json
    assert events[2].done.state == ppb.CALL_COMPLETED


def test_other_pdf_fails_the_call(monkeypatch, tmp_path):
    _silence(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    events = list(
        plat.iter_call(
            ppb.PlatformCall(
                product="document",
                verb="analyze",
                input_json=json.dumps({"url": "https://example.com/note.pdf"}),
            )
        )
    )
    assert events[-1].done.state == ppb.CALL_FAILED
    assert "arXiv" in events[-1].done.error
    assert "super-secret" not in events[-1].done.error


def test_workflow_execute_sends_the_public_pdf(monkeypatch, tmp_path):
    _silence(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    seen = {}

    def execute(name, inputs, *, wait=True, key=None, sleep=None):
        seen["name"] = name
        seen["inputs"] = inputs
        seen["key"] = key
        return {"execution_id": "exec-1", "workflow": name, "status": "COMPLETED", "result": {"summary": "ok"}}

    monkeypatch.setattr(drop, "execute_workflow", execute)
    events = list(
        plat.iter_call(
            ppb.PlatformCall(
                product="workflow",
                verb="execute",
                input_json=json.dumps({"name": "hermes-paper-analysis", "url": _URL, "wait": False}),
            )
        )
    )
    assert seen["inputs"]["url"] == "https://arxiv.org/pdf/2402.03300.pdf"
    assert seen["key"] == "super-secret"
    body = json.loads(events[1].deliverable.json)
    assert body["execution_id"] == "exec-1"
    assert "super-secret" not in events[1].deliverable.json
