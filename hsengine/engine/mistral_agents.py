"""Mistral document analysis and workflows as zndx.agent.v1 agents.

Other projects discover these on Engine/ServerQuery kind=AGENTS and run
them with Agents/Run. They are not model capabilities: Mistral hosts the
model, this engine holds the credential, and a run claims no GPU. An
absent credential means the agents are not advertised.

``mistral-document`` takes a public arXiv, bioRxiv, or medRxiv URL and
returns the OCR plus the structured annotation as JSON. ``mistral-workflow``
starts a named Mistral workflow (``kwargs_json.workflow``, otherwise
``mistral.paper_workflow``) and, by default, waits for its result.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import hsengine
from hsengine.engine.generated.zndx.agent.v1 import agent_pb2 as apb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

PROJECT = "hermes"
DOCUMENT = "mistral-document"
WORKFLOW = "mistral-workflow"
_NAMES = (DOCUMENT, WORKFLOW)


def api_key() -> str:
    """Credential from the process environment, else HERMES_HOME/.env.

    The engine jail binds the profile home but does not export every secret
    into the process environment. The value is for the Authorization header.
    """
    env = os.environ.get("MISTRAL_API_KEY", "").strip()
    if env:
        return env
    home = os.environ.get("HERMES_HOME", "").strip()
    if not home:
        return ""
    path = Path(home).expanduser() / ".env"
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() != "MISTRAL_API_KEY":
            continue
        return value.strip().strip('"').strip("'")
    return ""


def hosted() -> bool:
    return bool(api_key())


def advertised_names() -> list[str]:
    return list(_NAMES) if hosted() else []


def _agent_id(name: str) -> str:
    return f"{PROJECT}/{name}@{hsengine.__version__}"


def agent_ids() -> list[str]:
    if not hosted():
        return []
    return [_agent_id(name) for name in _NAMES]


def owns(agent_id: str) -> bool:
    return any(agent_id == _agent_id(name) or agent_id.endswith(f"/{name}") for name in _NAMES)


def _offer(name: str, *, behaviours: list[str], note: str) -> apb.AgentOffer:
    return apb.AgentOffer(
        agent_id=_agent_id(name),
        project=PROJECT,
        name=name,
        version=hsengine.__version__,
        transport=apb.AGENT_TRANSPORT_SDK,
        billing=apb.BILLING_SUBSCRIPTION,
        behaviours=behaviours,
        note=note,
    )


def _workflow_note() -> str:
    from hsengine.engine.source_drop import paper_workflow_name

    configured = paper_workflow_name()
    default = f" Configured workflow: {configured}." if configured else ""
    return (
        "Run a Mistral workflow. instruction is a public arXiv, bioRxiv, or "
        "medRxiv URL, or a short reason when kwargs_json.input is set. "
        'kwargs_json is {"workflow":"name","input":{...},"wait":true}. '
        "workflow defaults to mistral.paper_workflow. wait true returns the "
        "workflow result; wait false returns execution_id. The credential "
        "stays on this engine. No GPU claim."
        + default
    )


def offers() -> list[apb.AgentOffer]:
    if not hosted():
        return []
    return [
        _offer(
            DOCUMENT,
            behaviours=["ocr", "document_annotation"],
            note=(
                "OCR and structured annotation of one public arXiv, bioRxiv, "
                "or medRxiv URL. instruction is the URL. Optional kwargs_json "
                '{"kind":"arxiv"|"biorxiv"|"medrxiv"}. result_text is JSON '
                "(title, summary, claims, method, limits, text, model). "
                "Mistral hosts the model. This engine holds the credential. "
                "No GPU claim. The result is not written to a wiki."
            ),
        ),
        _offer(
            WORKFLOW,
            behaviours=["workflow"],
            note=_workflow_note(),
        ),
    ]


def hints() -> list[zpb.AgentHint]:
    return [
        zpb.AgentHint(
            agent_id=offer.agent_id,
            project=offer.project,
            name=offer.name,
            version=offer.version,
            transport="sdk",
            billing="subscription",
        )
        for offer in offers()
    ]


def _kwargs(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("kwargs_json must be a JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("kwargs_json must be a JSON object")
    return data


def _paper(instruction: str, kwargs: dict[str, Any]) -> tuple[str, str]:
    from hsengine.engine.source_drop import _CURATED, classify

    url = (instruction or "").strip()
    kind = str(kwargs.get("kind") or "").strip() or classify(url)
    if kind not in _CURATED:
        raise ValueError(
            "Mistral document analysis accepts an arXiv, bioRxiv, or medRxiv URL"
        )
    return url, kind


def fulfil(agent_id: str, *, instruction: str, kwargs_json: str) -> str:
    """Run one Mistral agent. Returns JSON text. Never includes the credential."""
    from hsengine.engine import source_drop as drop

    secret = api_key()
    if not secret:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    kwargs = _kwargs(kwargs_json)
    if agent_id == _agent_id(DOCUMENT) or agent_id.endswith(f"/{DOCUMENT}"):
        url, kind = _paper(instruction, kwargs)
        analysis = drop.mistral_analyze(url, kind=kind, key=secret)
        return json.dumps(analysis, ensure_ascii=False)
    if agent_id == _agent_id(WORKFLOW) or agent_id.endswith(f"/{WORKFLOW}"):
        name = str(kwargs.get("workflow") or "").strip() or drop.paper_workflow_name()
        if not name:
            raise ValueError(
                "no Mistral workflow is configured; set kwargs_json.workflow "
                "or mistral.paper_workflow"
            )
        wait = kwargs.get("wait", True)
        if not isinstance(wait, bool):
            raise ValueError("kwargs_json.wait must be a boolean")
        raw_input = kwargs.get("input")
        if raw_input is None:
            url, kind = _paper(instruction, kwargs)
            raw_input = {"url": drop.pdf_url_for(url, kind), "kind": kind}
        elif not isinstance(raw_input, dict):
            raise ValueError("kwargs_json.input must be an object")
        started = drop.execute_workflow(name, raw_input, wait=wait, key=secret)
        return json.dumps(started, ensure_ascii=False)
    raise ValueError(f"not a Mistral agent: {agent_id}")
