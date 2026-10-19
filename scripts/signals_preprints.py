"""signals-preprints worker for the signals-preprint-analysis workflow.

The orchestrator is Mistral's. This process registers the workflow on the
``signals-preprints`` deployment and runs its activities. The engine starts
each execution and writes the wiki note when the result returns.

The class is defined at module scope because Temporal's sandbox imports it
by name. The SDK is not in the Hermes lock.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

WORKFLOW_NAME = "signals-preprint-analysis"
_OCR_URL = "https://api.mistral.ai/v1/ocr"
_MODEL = "mistral-ocr-latest"


def signals_preprints_ocr(url: str, kind: str) -> dict:
    """Read the public PDF into markdown. The summary is a later activity."""
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        token = os.environ.get("MISTRAL_SA_TOKEN", "").strip()
        path = os.environ.get("MISTRAL_SA_TOKEN_PATH", "").strip()
        if not token and path:
            token = open(path, encoding="utf-8").read().strip()
        key = token
    if not key:
        raise RuntimeError("no Mistral credential for signals-preprints")
    payload = {
        "model": _MODEL,
        "document": {"type": "document_url", "document_url": url},
        "table_format": "markdown",
        "extract_header": True,
        "extract_footer": True,
        "include_image_base64": False,
    }
    request = urllib.request.Request(
        _OCR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Mistral OCR HTTP {exc.code}: {detail}") from exc
    pages = body.get("pages") or []
    text = "\n\n".join(
        str(page.get("markdown") or "").strip()
        for page in pages
        if str(page.get("markdown") or "").strip()
    )
    return {
        "url": url,
        "kind": kind,
        "text": text,
        "model": str(body.get("model") or _MODEL),
    }


_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "short_title": {"type": "string"},
        "summary": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "string"}},
        "method": {"type": "string"},
        "limits": {"type": "string"},
    },
    "required": ["short_title", "summary", "claims", "method", "limits"],
}


def signals_preprints_summarize(paper: dict) -> dict:
    """Turn the OCR markdown into the structured note fields."""
    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no Mistral credential for signals-preprints")
    excerpt = str(paper.get("text") or "")[:14000]
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Read this preprint markdown. short_title is at most eight words. "
                    "summary is for a discussion. claims are stated results. "
                    "method is how they were produced. limits are what is not shown.\n\n"
                    + excerpt
                ),
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "preprint_analysis", "strict": True, "schema": _SUMMARY_SCHEMA},
        },
    }
    request = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Mistral summary HTTP {exc.code}: {detail}") from exc
    content = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    try:
        parsed = json.loads(content) if content.strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    short = str(parsed.get("short_title") or "").strip() or str(paper.get("url") or "paper")
    return {
        "url": paper.get("url") or "",
        "kind": paper.get("kind") or "",
        "scope": "full",
        "title": short,
        "short_title": short,
        "summary": str(parsed.get("summary") or "").strip(),
        "claims": [str(item).strip() for item in (parsed.get("claims") or []) if str(item).strip()],
        "method": str(parsed.get("method") or "").strip(),
        "limits": str(parsed.get("limits") or "").strip(),
        "text": str(paper.get("text") or ""),
        "model": str(paper.get("model") or _MODEL),
    }


import mistralai.workflows as workflows
from pydantic import BaseModel


class SignalsPreprintsInput(BaseModel):
    url: str
    kind: str


@workflows.activity()
async def signals_preprints_read(url: str, kind: str) -> dict:
    return signals_preprints_ocr(url, kind)


@workflows.activity()
async def signals_preprints_note(paper: dict) -> dict:
    return signals_preprints_summarize(paper)


@workflows.workflow.define(
    name=WORKFLOW_NAME,
    workflow_display_name="Signals preprint analysis",
    workflow_description="OCR a preprint, then write the structured note.",
    search_keys=["url", "kind"],
)
class SignalsPreprints:
    def __init__(self) -> None:
        self.stage = "queued"

    @workflows.workflow.query(name="progress")
    def progress(self) -> dict:
        return {"stage": self.stage, "workflow": WORKFLOW_NAME}

    @workflows.workflow.entrypoint
    async def run(self, paper: SignalsPreprintsInput) -> dict:
        self.stage = "ocr"
        fetched = await signals_preprints_read(paper.url, paper.kind)
        self.stage = "summary"
        return await signals_preprints_note(fetched)


SYSTEM_ONE_NAME = "signals-system-one"
_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
_SYSTEM_ONE_MODEL = "mistral-small-latest"


def _offered_lines(offered: list[dict], genus_iri: str, genus_code: str, genus_label: str) -> str:
    rows = list(offered or [])
    if not rows and genus_iri:
        rows = [{"iri": genus_iri, "code": genus_code, "label": genus_label}]
    lines = []
    for point in rows:
        iri = str(point.get("iri") or "")
        if not iri:
            continue
        lines.append(f"- {iri} | {point.get('code') or ''} | {point.get('label') or ''}")
    return "\n".join(lines)


def signals_system_one_read(
    text: str,
    genus_iri: str,
    genus_code: str,
    genus_label: str,
    offered: list[dict] | None = None,
) -> dict:
    """Pick one aperture IRI for the span. An IRI outside that list is dropped."""
    from hsengine.engine.sdg_iris import resolve_sdg_iri

    key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no Mistral credential for signals-system-one")
    catalog = _offered_lines(offered or [], genus_iri, genus_code, genus_label)
    payload = {
        "model": _SYSTEM_ONE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Assign this span to one SDG ontology IRI from the list. "
                    "sdg_iri must be copied exactly from the list. "
                    "If none of the IRIs is warranted, sdg_iri is empty and confidence is 0. "
                    "Do not invent an IRI. note is one sentence.\n\n"
                    f"admitted: {genus_iri} | {genus_code} | {genus_label}\n"
                    f"iris:\n{catalog}\n\n"
                    f"span:\n{text}"
                ),
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "system_one",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "sdg_iri": {"type": "string"},
                        "confidence": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["sdg_iri", "confidence", "note"],
                },
            },
        },
    }
    request = urllib.request.Request(
        _CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Mistral chat HTTP {exc.code}: {detail}") from exc
    content = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    try:
        parsed = json.loads(content) if content.strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    pool = list(offered or [])
    if not pool and genus_iri:
        pool = [{"iri": genus_iri, "code": genus_code, "label": genus_label}]
    iri = resolve_sdg_iri(str(parsed.get("sdg_iri") or ""), pool)
    return {
        "sdg_iri": iri,
        "confidence": parsed.get("confidence") if iri else 0,
        "note": str(parsed.get("note") or ""),
        "offered": [str(point.get("iri") or "") for point in pool if point.get("iri")],
    }


class OfferedIri(BaseModel):
    iri: str
    code: str = ""
    label: str = ""


class SignalsSystemOneInput(BaseModel):
    text: str
    genus_iri: str
    genus_code: str = ""
    genus_label: str = ""
    offered: list[OfferedIri] = []


@workflows.activity()
async def signals_system_one_analyze(
    text: str,
    genus_iri: str,
    genus_code: str,
    genus_label: str,
    offered: list[OfferedIri] | None = None,
) -> dict:
    rows = []
    for item in offered or []:
        if hasattr(item, "model_dump"):
            rows.append(item.model_dump())
        else:
            rows.append(item.dict())
    return signals_system_one_read(text, genus_iri, genus_code, genus_label, rows)


@workflows.workflow.define(
    name=SYSTEM_ONE_NAME,
    workflow_display_name="Signals system one",
    workflow_description="Assign an SDG IRI under the genus Aegir admitted.",
    search_keys=["genus_iri", "genus_code"],
)
class SignalsSystemOne:
    @workflows.workflow.entrypoint
    async def run(self, item: SignalsSystemOneInput) -> dict:
        return await signals_system_one_analyze(
            item.text, item.genus_iri, item.genus_code, item.genus_label, item.offered,
        )


def main() -> None:
    import asyncio

    asyncio.run(workflows.run_worker([SignalsPreprints, SignalsSystemOne]))


if __name__ == "__main__":
    main()
