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


def signals_preprints_fetch(url: str, kind: str) -> dict:
    """OCR one public preprint. Same shape as the engine's ``mistral_analyze``."""
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
        "document_annotation_prompt": (
            "Read the paper. short_title is at most eight words. "
            "summary is for a discussion. claims are stated results. "
            "method is how they were produced. limits are what is not shown."
        ),
        "document_annotation_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "preprint_analysis",
                "strict": True,
                "schema": {
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
                },
            },
        },
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
    raw = body.get("document_annotation")
    annotation = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
    if not isinstance(annotation, dict):
        annotation = {}
    short = str(annotation.get("short_title") or "").strip() or url
    return {
        "url": url,
        "kind": kind,
        "scope": "full",
        "title": short,
        "short_title": short,
        "summary": str(annotation.get("summary") or "").strip(),
        "claims": [str(item).strip() for item in (annotation.get("claims") or []) if str(item).strip()],
        "method": str(annotation.get("method") or "").strip(),
        "limits": str(annotation.get("limits") or "").strip(),
        "text": text,
        "model": str(body.get("model") or _MODEL),
    }


import mistralai.workflows as workflows
from pydantic import BaseModel


class SignalsPreprintsInput(BaseModel):
    url: str
    kind: str


@workflows.activity()
async def signals_preprints_analyze(url: str, kind: str) -> dict:
    return signals_preprints_fetch(url, kind)


@workflows.workflow.define(
    name=WORKFLOW_NAME,
    workflow_display_name="Signals preprint analysis",
    workflow_description="OCR and structured summary of an arXiv, bioRxiv, or medRxiv PDF.",
    search_keys=["url", "kind"],
)
class SignalsPreprints:
    @workflows.workflow.entrypoint
    async def run(self, paper: SignalsPreprintsInput) -> dict:
        return await signals_preprints_analyze(paper.url, paper.kind)


def main() -> None:
    import asyncio

    asyncio.run(workflows.run_worker([SignalsPreprints]))


if __name__ == "__main__":
    main()
