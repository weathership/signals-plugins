"""Mistral document and workflow agents on zndx.agent.v1."""
from __future__ import annotations

import json

from hsengine.engine import agents, mistral_agents, s2s, source_drop as drop
from hsengine.engine.generated.zndx.agent.v1 import agent_pb2 as apb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

_URL = "https://arxiv.org/abs/2402.03300"


def _silence_key(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))


def test_absent_credential_is_not_advertised(monkeypatch, tmp_path):
    _silence_key(monkeypatch, tmp_path)
    assert mistral_agents.offers() == []
    assert mistral_agents.advertised_names() == []
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_AGENTS)
    assert [agent.name for agent in resp.agents] == ["hermes"]


def test_profile_dotenv_does_not_put_mistral_on_the_agent_yellow_pages(monkeypatch, tmp_path):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text('MISTRAL_API_KEY="from-file"\n', encoding="utf-8")
    assert mistral_agents.offers() == []
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_AGENTS)
    assert [agent.name for agent in resp.agents] == ["hermes"]
    assert "from-file" not in str(resp)


def test_document_run_returns_analysis_without_the_credential(monkeypatch, tmp_path):
    _silence_key(monkeypatch, tmp_path)
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
    events = list(agents.iter_run(apb.RunRequest(agent="mistral-document", instruction=_URL)))
    assert [ev.WhichOneof("event") for ev in events] == ["accepted", "message", "done"]
    assert events[0].accepted.model_peer == "mistral"
    assert seen == {"url": _URL, "kind": "arxiv", "key": "super-secret"}
    body = json.loads(events[2].done.result_text)
    assert body["summary"] == "A summary."
    assert "super-secret" not in events[2].done.result_text


def test_other_pdf_is_a_failed_run(monkeypatch, tmp_path):
    _silence_key(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    events = list(
        agents.iter_run(
            apb.RunRequest(agent="mistral-document", instruction="https://example.com/note.pdf")
        )
    )
    assert events[-1].done.state == apb.RUN_FAILED
    assert "arXiv" in events[-1].done.error
    assert "super-secret" not in events[-1].done.error


def test_workflow_run_sends_the_public_pdf_and_hides_the_credential(monkeypatch, tmp_path):
    _silence_key(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    seen = {}

    def execute(name, inputs, *, wait=True, key=None, sleep=None):
        seen["name"] = name
        seen["inputs"] = inputs
        seen["wait"] = wait
        seen["key"] = key
        return {
            "execution_id": "exec-1",
            "workflow": name,
            "status": "COMPLETED",
            "result": {"summary": "from the workflow"},
        }

    monkeypatch.setattr(drop, "execute_workflow", execute)
    events = list(
        agents.iter_run(
            apb.RunRequest(
                agent="hermes/mistral-workflow",
                instruction=_URL,
                kwargs_json='{"workflow":"hermes-paper-analysis"}',
            )
        )
    )
    assert seen["name"] == "hermes-paper-analysis"
    assert seen["inputs"]["url"] == "https://arxiv.org/pdf/2402.03300.pdf"
    assert seen["inputs"]["kind"] == "arxiv"
    assert seen["key"] == "super-secret"
    assert seen["wait"] is True
    body = json.loads(events[-1].done.result_text)
    assert body["result"]["summary"] == "from the workflow"
    assert "super-secret" not in events[-1].done.result_text


def test_workflow_without_a_name_fails(monkeypatch, tmp_path):
    _silence_key(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("MISTRAL_API_KEY=super-secret\n", encoding="utf-8")
    monkeypatch.setattr(drop, "paper_workflow_name", lambda home=None: "")
    events = list(
        agents.iter_run(apb.RunRequest(agent="mistral-workflow", instruction="analyse this"))
    )
    assert events[-1].done.state == apb.RUN_FAILED
    assert "workflow" in events[-1].done.error
