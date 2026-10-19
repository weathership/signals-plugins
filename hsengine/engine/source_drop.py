"""Source drop for a live AgentRTC call.

A dropped URL is text for the discussion, not a Docling run. Docling's
extract leaf wants a GPU and the old runner can evict the standing
thinking server (GPUs 0–3). This path claims no GPU token, does not talk
to YuniKorn, and does not load a local model.

Two kanban cards are filed before either fetch. The preview is the first
eight PDF pages, on CPU, as a scratch zettel. The full card for an arXiv
or bioRxiv PDF is one Mistral Document AI call (OCR plus a structured
summary) and lands in the Hermes wiki at
``current/kb/arXiv``, ``current/kb/bioRxiv``, or ``current/kb/medRxiv``.
Gaius syncs that tree on its own schedule. URL variants of one preprint
(abs, pdf, html, ``.full.pdf``, a trailing version) share one card, so
the analysis does not run again. A different server is a different
paper. Any other PDF is filed blocked until the user approves it;
approval runs the CPU path, not Mistral.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.source_drop")

# Zero on purpose. Do not raise this to borrow extract, light, or heavy.
GPU_TOKENS = 0

# A drop is two cards: the pages the room can read now, and the whole source.
SCOPES = ("preview", "full")

_MAX_PER_TURN = 3
_PDF_PAGES = 8
_PREVIEW_CAP = 48_000
_FULL_CAP = 200_000
_SUMMARY_INPUT = 24_000
_FETCH_TIMEOUT_S = 30
_FULL_FETCH_TIMEOUT_S = 120
_MISTRAL_TIMEOUT_S = 180
_MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
_WORKFLOW_EXECUTE = "https://api.mistral.ai/v1/workflows/{name}/execute"
_WORKFLOW_EXECUTION = "https://api.mistral.ai/v1/workflows/executions/{execution_id}"
_WORKFLOW_POLL_S = 5
_WORKFLOW_WAIT_S = 900
_MISTRAL_MODEL = "mistral-ocr-latest"
_CURATED = frozenset({"arxiv", "biorxiv", "medrxiv"})
_APPROVAL_REASON = (
    "Mistral document analysis is limited to arXiv, bioRxiv, and medRxiv PDFs. "
    "This PDF stays blocked until you explicitly approve it."
)
_ANNOTATION_PROMPT = (
    "Read the paper. short_title is at most eight words in plain language. "
    "summary is for someone who will discuss the paper before reading it. "
    "claims are results the paper states. method is how those results were "
    "produced. limits are what the paper does not show. Do not invent citations."
)

_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+")
_ARXIV_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?",
    re.I,
)
_RXIV_RE = re.compile(
    r"(?P<server>bio|med)rxiv\.org/(?:content|cgi/content)/+(?P<doi>10\.\d{4,9}/[^\s?#]+)",
    re.I,
)
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()

GetFn = Callable[[str], bytes]
SpawnFn = Callable[[Callable[[], None]], None]


def urls_in(text: str) -> list[str]:
    """Paper and page URLs in an utterance. Local and empty hosts are skipped."""
    found: list[str] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:")
        if _skip_url(url):
            continue
        key = drop_key(url)
        if key in seen:
            continue
        seen.add(key)
        found.append(url)
        if len(found) >= _MAX_PER_TURN:
            break
    return found


def _skip_url(url: str) -> bool:
    host = urllib.request.urlparse(url).hostname or ""
    host = host.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0"} or host.endswith(".local"):
        return True
    return False


def classify(url: str) -> str:
    if _ARXIV_RE.search(url or ""):
        return "arxiv"
    match = _RXIV_RE.search(url or "")
    if match:
        return "biorxiv" if match.group("server").lower() == "bio" else "medrxiv"
    return "web"


def drop_key(url: str) -> str:
    """Stable card key for one preprint on one server.

    abs, pdf, html, and a trailing version are the same arXiv paper.
    A bioRxiv or medRxiv content page, ``.full.pdf``, and a ``vN`` suffix
    are the same DOI on that server. The key does not cross servers:
    an arXiv id and a 10.1101 DOI are not the same paper, and a PDF on
    any other host does not inherit either key.
    """
    kind = classify(url)
    if kind == "arxiv":
        match = _ARXIV_RE.search(url)
        return f"arxiv:{(match.group(1) if match else url).lower()}"
    if kind in {"biorxiv", "medrxiv"}:
        return f"{kind}:{_rxiv_doi(url)}"
    parsed = urllib.request.urlparse(url)
    clean = parsed._replace(fragment="").geturl()
    return f"web:{clean}"


def _rxiv_doi(url: str, *, keep_version: bool = False) -> str:
    """DOI for a card key, or with its ``vN`` kept for the PDF fetch.

    bioRxiv and medRxiv serve the file at ``.../<doi>vN.full.pdf``. The
    unversioned URL redirects, and Mistral will not follow that redirect.
    The card key still drops the version so v1 and v2 are one preprint.
    """
    match = _RXIV_RE.search(url or "")
    doi = (match.group("doi") if match else url).rstrip(".").lower()
    doi = re.sub(r"(?:\.full)?(?:[-_]text)?(?:\.pdf)?$", "", doi)
    if not keep_version:
        doi = re.sub(r"v\d+$", "", doi)
    return doi


def file_source_drops(session_id: str, text: str) -> list[dict[str, Any]]:
    """Enqueue every dropped URL on this turn. Failures stay off the call."""
    filed: list[dict[str, Any]] = []
    for url in urls_in(text):
        try:
            filed.append(enqueue(url=url, session_id=session_id, performer="hermes"))
        except Exception:
            log.warning("source drop failed for %s", url, exc_info=True)
    return filed


def needs_pdf_approval(url: str, kind: str) -> bool:
    """True for a PDF that is not an arXiv, bioRxiv, or medRxiv paper."""
    if kind in _CURATED:
        return False
    path = urllib.request.urlparse(url or "").path.lower()
    return path.endswith(".pdf")


def enqueue(
    *,
    url: str,
    session_id: str = "",
    performer: str = "hermes",
    approve: bool = False,
    spawn: SpawnFn | None = None,
    fetch: Callable[..., dict[str, Any]] | None = None,
    summarize: Callable[[dict[str, Any]], str] | None = None,
    analyze: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """File two cards, then extract off the voice turn.

    ``preview`` is the first eight PDF pages. ``full`` for arXiv, bioRxiv,
    and medRxiv is Mistral and lands in ``current/kb``. Any other PDF is
    blocked until ``approve`` is true, and that approval stays on the CPU path.
    ``spawn`` runs the work inline in tests.
    """
    target = (url or "").strip()
    if not target:
        return {
            "ok": False,
            "error": "url required",
            "created": False,
            "tasks": [],
            "awaiting_approval": False,
        }
    who = _performer(performer)
    key = drop_key(target)
    kind = classify(target)
    gated = needs_pdf_approval(target, kind) and not approve
    jobs: list[tuple[str, str, str]] = []
    tasks: list[dict[str, Any]] = []
    comments: list[str] = []
    created_any = False
    with _LOCK:
        for scope in SCOPES:
            ikey = f"{key}:{scope}"
            title = _card_title(kind, target, scope)
            existing = _find_card(key, scope)
            if gated:
                if existing:
                    tasks.append(_task_row(existing, scope, title, created=False))
                    continue
                tid = _create_card(
                    key=key,
                    title=title,
                    url=target,
                    kind=kind,
                    performer=who,
                    session_id=session_id,
                    scope=scope,
                    initial_status="blocked",
                )
                created_any = True
                comments.append(tid)
                tasks.append(
                    {
                        "id": tid,
                        "scope": scope,
                        "status": "blocked",
                        "title": title,
                        "created": True,
                    }
                )
                continue
            if existing and existing["status"] != "blocked":
                tasks.append(_task_row(existing, scope, title, created=False))
                continue
            if existing and ikey in _INFLIGHT:
                tasks.append(_task_row(existing, scope, title, created=False))
                continue
            if existing:
                _unblock(existing["id"])
                tid = existing["id"]
            else:
                tid = _create_card(
                    key=key,
                    title=title,
                    url=target,
                    kind=kind,
                    performer=who,
                    session_id=session_id,
                    scope=scope,
                )
                created_any = True
            _INFLIGHT.add(ikey)
            jobs.append((tid, scope, ikey))
            tasks.append(
                {
                    "id": tid,
                    "scope": scope,
                    "status": "running",
                    "title": title,
                    "created": not existing,
                }
            )
    for tid in comments:
        _comment(tid, _APPROVAL_REASON)
    fetcher = fetch or fetch_source
    summarizer = summarize if summarize is not None else summarize_source
    analyzer = analyze or mistral_analyze
    for tid, scope, ikey in jobs:
        worker = lambda tid=tid, scope=scope, ikey=ikey: _run(
            tid, target, who, key, scope, kind, fetcher, summarizer, analyzer, now
        )
        if spawn is None:
            threading.Thread(target=worker, daemon=True, name=f"source-drop-{scope}").start()
        else:
            spawn(worker)
    preview = next(row for row in tasks if row["scope"] == "preview")
    return {
        "ok": True,
        "created": created_any,
        "id": preview["id"],
        "status": preview["status"],
        "title": preview["title"],
        "url": target,
        "kind": kind,
        "performer": who,
        "gpu_tokens": GPU_TOKENS,
        "awaiting_approval": gated,
        "tasks": tasks,
    }


def _task_row(existing: dict[str, str], scope: str, title: str, *, created: bool) -> dict[str, Any]:
    return {
        "id": existing["id"],
        "scope": scope,
        "status": existing["status"],
        "title": existing["title"] or title,
        "created": created,
    }


def _run(
    task_id: str,
    url: str,
    performer: str,
    key: str,
    scope: str,
    kind: str,
    fetch: Callable[..., dict[str, Any]],
    summarize: Callable[[dict[str, Any]], str],
    analyze: Callable[..., dict[str, Any]],
    now: datetime | None,
) -> None:
    ikey = f"{key}:{scope}"
    try:
        curated = scope == "full" and kind in _CURATED
        if curated and mistral_preprint_urgent():
            note = f"Mistral document analysis of {url}. The note lands in current/kb."
        elif curated:
            note = f"Gaius docling of {url} on local GPUs. No Mistral call."
        elif scope == "preview":
            note = f"Fetching the first {_PDF_PAGES} PDF pages of {url} on CPU."
        else:
            note = f"Fetching the full text of {url} on CPU, then writing a summary."
        _comment(
            task_id,
            f"{note} gpu_tokens={GPU_TOKENS}. No extract leaf, no vLLM eviction.",
        )
        if curated:
            source = _curated_source(url, kind, analyze, task_id)
            if source.get("provider") == "gaius":
                rel = str(source.get("resource") or "")
                _comment(task_id, f"Gaius owns {rel}.")
                _complete(task_id, rel or "gaius")
                log.info("source drop %s %s %s -> %s", performer, scope, key, rel)
                return
            source["scope"] = "full"
            written = write_kb(source, now=now)
        else:
            source = dict(fetch(url, scope=scope))
            source["scope"] = scope
            if scope == "full":
                source["summary"] = summarize(source)
            written = write_zettel(source, performer=performer, now=now)
        rel = str(written.get("relpath") or written.get("path") or "")
        _comment(task_id, f"Wrote {rel} ({written.get('bytes') or 0} bytes).")
        _complete(task_id, rel or "written")
        log.info("source drop %s %s %s -> %s", performer, scope, key, rel)
    except Exception as exc:
        log.warning("source drop %s %s failed", scope, key, exc_info=True)
        try:
            _comment(task_id, f"Extract failed: {exc}")
            _block(task_id, str(exc))
        except Exception:
            log.debug("source drop could not block %s", task_id, exc_info=True)
    finally:
        with _LOCK:
            _INFLIGHT.discard(ikey)
        _refresh()


def fetch_source(url: str, *, get: GetFn | None = None, scope: str = "preview") -> dict[str, Any]:
    """Metadata plus PDF or page text. ``preview`` stops at eight pages."""
    kind = classify(url)
    getter = get or _http_get
    window = _scope(scope)
    if kind == "arxiv":
        return _fetch_arxiv(url, getter, window)
    if kind in {"biorxiv", "medrxiv"}:
        return _fetch_rxiv(url, kind, getter, window)
    return _fetch_web(url, getter, window)


def summarize_source(source: dict[str, Any]) -> str:
    """Discussion summary. Cerebras while a call is up; no extract GPU."""
    body = str(source.get("text") or source.get("abstract") or "").strip()
    if not body:
        raise RuntimeError("nothing to summarize")
    title = str(source.get("title") or source.get("url") or "source")
    abstract = str(source.get("abstract") or "").strip()
    prompt = f"Title: {title}\n\nAbstract:\n{abstract}\n\nText:\n{body[:_SUMMARY_INPUT]}"
    from hsengine.engine.complete import complete

    result = complete(
        capability="agent",
        system_prompt=(
            "Write a discussion summary of this source in a few paragraphs "
            "of plain prose. Do not invent citations. This is not a GPU extract."
        ),
        prompt=prompt,
        max_tokens=900,
        temperature=0.2,
    )
    text = (result.text or "").strip()
    if not text:
        raise RuntimeError("summary came back empty")
    return text


def pdf_url_for(url: str, kind: str) -> str:
    """Public PDF URL Mistral can fetch. arXiv, bioRxiv, and medRxiv only."""
    if kind == "arxiv":
        match = _ARXIV_RE.search(url or "")
        if not match:
            raise RuntimeError(f"not an arXiv url: {url}")
        return f"https://arxiv.org/pdf/{match.group(1)}.pdf"
    if kind in {"biorxiv", "medrxiv"}:
        server = "biorxiv" if kind == "biorxiv" else "medrxiv"
        return f"https://www.{server}.org/content/{_rxiv_doi(url, keep_version=True)}.full.pdf"
    raise RuntimeError(
        f"Mistral document analysis is limited to arXiv, bioRxiv, and medRxiv, got {kind}"
    )


SYSTEM_ONE_WORKFLOW = "signals-system-one"


def system_one_name(home: Path | None = None) -> str:
    """Mistral workflow that confirms an aperture genus. Empty disables the call."""
    explicit = os.environ.get("SIGNALS_SYSTEM_ONE_WORKFLOW", "").strip()
    if explicit:
        return explicit
    root = home
    if root is None:
        raw = os.environ.get("HERMES_HOME", "").strip()
        root = Path(raw).expanduser() if raw else None
    if root is None:
        return SYSTEM_ONE_WORKFLOW
    path = root / "config.yaml"
    if not path.is_file():
        return SYSTEM_ONE_WORKFLOW
    found = _yaml_scalar(path.read_text(encoding="utf-8", errors="replace"), ("mistral", "system_one_workflow"))
    return found or SYSTEM_ONE_WORKFLOW


def _workflow_payload(result: dict) -> dict:
    """The entrypoint return. Mistral stores it under ``result.result``."""

    inner = result.get("result")
    if not isinstance(inner, dict):
        return result
    if "kind" not in result and "kind" in inner:
        return inner
    if "sdg_iri" not in result and "sdg_iri" in inner:
        return inner
    return result


def run_system_one(text: str, link: dict[str, Any]) -> dict[str, Any] | None:
    """Assign subtree IRIs to word sequences. Development calls TypeSafe, not Mistral."""
    from hsengine.engine.sdg_iris import genus_of, subtree
    from hsengine.engine.system_one import assign_word_sequences

    if not mistral_preprint_urgent():
        return None
    admitted = str(link.get("genus_iri") or "")
    if not text or not admitted:
        return None
    genus = genus_of(admitted)
    if genus is None:
        return None
    offered = subtree(str(genus["iri"]))
    try:
        found = assign_word_sequences(text, offered)
    except Exception:
        log.warning("system-one assignment failed", exc_info=True)
        return None
    best = max(found, key=lambda row: float(row.get("confidence") or 0.0)) if found else None
    return {
        "sdg_iri": "" if best is None else str(best["iri"]),
        "confidence": None if best is None else best.get("confidence"),
        "offered": [point["iri"] for point in offered],
        "assignments": found,
    }


def signals_preprints_name(home: Path | None = None) -> str:
    """Name of the deployed Mistral workflow, or empty when unset.

    Empty means the full card calls OCR directly. A managed deployment
    runs the worker on Mistral Cloud; this process only starts the
    execution and writes the wiki note when it completes.
    """
    explicit = (
        os.environ.get("SIGNALS_PREPRINTS_WORKFLOW", "").strip()
        or os.environ.get("MISTRAL_PAPER_WORKFLOW", "").strip()
    )
    if explicit:
        return explicit
    root = home
    if root is None:
        raw = os.environ.get("HERMES_HOME", "").strip()
        root = Path(raw).expanduser() if raw else None
    if root is None:
        return ""
    path = root / "config.yaml"
    if not path.is_file():
        return ""
    return _yaml_scalar(path.read_text(encoding="utf-8", errors="replace"), ("mistral", "paper_workflow"))


def mistral_preprint_urgent() -> bool:
    """True only while an AgentRTC session is up. That is the Mistral window."""
    from hsengine.engine.signals_preprints_session import urgent

    return urgent()


def gaius_preprint(url: str, kind: str) -> dict[str, Any]:
    """Hand the preprint to Gaius docling on local GPUs. No Mistral call."""
    root = Path(os.environ.get("GAIUS_ROOT", "")).expanduser()
    if not str(root):
        raise RuntimeError("GAIUS_ROOT is unset; Gaius preprint extract has nowhere to run")
    python = next(
        (root / rel for rel in (".venv/bin/python", "venv/bin/python") if (root / rel).is_file()),
        None,
    )
    if python is None:
        raise RuntimeError(f"no Gaius interpreter under {root}")
    pdf = pdf_url_for(url, kind) if kind != "arxiv" else url
    flag = "--arxiv_url" if kind == "arxiv" else "--source_url"
    cmd = [
        str(python),
        "-m",
        "gaius.flows.docling.flow",
        "run",
        flag,
        pdf,
        "--enable_topics",
        "False",
        "--enable_scoring",
        "False",
    ]
    log.info("gaius preprint %s %s", kind, pdf)
    completed = subprocess.run(cmd, cwd=str(root), check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-400:]
        raise RuntimeError(f"Gaius docling exited {completed.returncode}: {tail}")
    return {
        "provider": "gaius",
        "url": pdf,
        "kind": kind,
        "resource": f"gaius-docling:{pdf}",
    }


def _curated_source(
    url: str,
    kind: str,
    analyze: Callable[..., dict[str, Any]],
    task_id: str,
) -> dict[str, Any]:
    if not mistral_preprint_urgent():
        _comment(
            task_id,
            "No AgentRTC session. Gaius extracts this preprint on local GPUs. "
            "Mistral runs only while a call is up.",
        )
        return gaius_preprint(url, kind)
    name = signals_preprints_name()
    if not name:
        return dict(analyze(url, kind=kind))
    try:
        execution_id = start_signals_preprints(name, url, kind)
    except RuntimeError as exc:
        if "404" in str(exc):
            log.warning("paper workflow %s is not registered; OCR runs here", name)
            _comment(task_id, f"Workflow {name} is not registered. OCR runs in this process.")
            return dict(analyze(url, kind=kind))
        raise
    _comment(task_id, f"Mistral workflow {name} execution {execution_id}.")
    return await_signals_preprints(execution_id)


_WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def execute_workflow(
    name: str,
    inputs: dict[str, Any],
    *,
    wait: bool = True,
    key: str | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Start a Mistral workflow. ``wait`` polls until the execution finishes.

    The credential is the Authorization header only. It is not copied into
    ``inputs`` or the returned object.
    """
    workflow = (name or "").strip()
    if not _WORKFLOW_NAME.fullmatch(workflow):
        raise RuntimeError("workflow name is empty or not a single token")
    if not isinstance(inputs, dict):
        raise RuntimeError("workflow input must be an object")
    secret = _mistral_key(key)
    if not secret:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    status, body = _mistral_json(
        "POST",
        _WORKFLOW_EXECUTE.format(name=workflow),
        {"input": inputs, "wait_for_result": False},
        secret,
    )
    if status == 404:
        raise RuntimeError(f"workflow {workflow} HTTP 404")
    if status >= 300 or not isinstance(body, dict) or not body.get("execution_id"):
        raise RuntimeError(f"workflow execute HTTP {status}")
    execution_id = str(body["execution_id"])
    if not wait:
        return {"execution_id": execution_id, "workflow": workflow, "status": "started"}
    result = await_signals_preprints(execution_id, sleep=sleep, key=secret)
    return {
        "execution_id": execution_id,
        "workflow": workflow,
        "status": "COMPLETED",
        "result": result,
    }


def start_signals_preprints(name: str, url: str, kind: str) -> str:
    started = execute_workflow(
        name,
        {"url": pdf_url_for(url, kind), "kind": kind},
        wait=False,
    )
    return str(started["execution_id"])


def await_signals_preprints(
    execution_id: str,
    *,
    sleep: Callable[[float], None] | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    key = _mistral_key(key)
    if not key:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    pause = sleep or time.sleep
    deadline = time.monotonic() + _WORKFLOW_WAIT_S
    while True:
        status, body = _mistral_json(
            "GET",
            _WORKFLOW_EXECUTION.format(execution_id=execution_id),
            None,
            key,
        )
        if status >= 300 or not isinstance(body, dict):
            raise RuntimeError(f"workflow status HTTP {status}")
        state = str(body.get("status") or "")
        if state == "COMPLETED":
            result = body.get("result")
            if isinstance(result, str):
                result = json.loads(result)
            if not isinstance(result, dict):
                raise RuntimeError("workflow completed without an analysis object")
            return _workflow_payload(result)
        if state in {"FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"}:
            raise RuntimeError(f"workflow {execution_id} {state}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"workflow {execution_id} still {state or 'running'}")
        pause(_WORKFLOW_POLL_S)


def _mistral_json(method: str, url: str, payload: dict[str, Any] | None, key: str) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"detail": raw.decode("utf-8", "replace")[:300]}


def _mistral_key(explicit: str | None) -> str:
    """Process environment, else HERMES_HOME/.env.

    Kanban workers and other children have MISTRAL_API_KEY scrubbed. ACP
    loads the dotenv. The engine process does neither, so the file is the
    shared source for every path.
    """
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    from hsengine.engine.mistral_agents import api_key

    return api_key()


def _yaml_scalar(text: str, path: tuple[str, ...]) -> str:
    want = list(path)
    depth = 0
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        name, _, value = raw.strip().partition(":")
        value = value.strip().strip('"').strip("'")
        if indent == 0:
            depth = 0
        if depth < len(want) and name == want[depth] and indent == depth * 2:
            if depth == len(want) - 1:
                return value
            depth += 1
    return ""


def mistral_analyze(url: str, *, kind: str, key: str | None = None) -> dict[str, Any]:
    """OCR the public PDF and return the structured paper analysis.

    One Document AI call. No local PDF read and no local model.
    """
    key = _mistral_key(key)
    if not key:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    pdf_url = pdf_url_for(url, kind)
    payload = {
        "model": _MISTRAL_MODEL,
        "document": {"type": "document_url", "document_url": pdf_url},
        "table_format": "markdown",
        "extract_header": True,
        "extract_footer": True,
        "include_image_base64": False,
        "document_annotation_prompt": _ANNOTATION_PROMPT,
        "document_annotation_format": _annotation_format(),
    }
    body = _mistral_post(payload, key)
    pages = body.get("pages") or []
    text = "\n\n".join(
        str(page.get("markdown") or "").strip()
        for page in pages
        if str(page.get("markdown") or "").strip()
    )
    annotation = _annotation_dict(body.get("document_annotation"))
    short = str(annotation.get("short_title") or "").strip()
    title = short or pdf_url
    return {
        "url": pdf_url,
        "kind": kind,
        "scope": "full",
        "title": title,
        "short_title": short or title,
        "summary": str(annotation.get("summary") or "").strip(),
        "claims": [str(item).strip() for item in (annotation.get("claims") or []) if str(item).strip()],
        "method": str(annotation.get("method") or "").strip(),
        "limits": str(annotation.get("limits") or "").strip(),
        "text": text,
        "model": str(body.get("model") or _MISTRAL_MODEL),
    }


def write_kb(source: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Curated paper note under ``current/kb/{arXiv,bioRxiv,medRxiv}``."""
    kind = str(source.get("kind") or "")
    collection = _kb_collection(kind)
    module = _zettel_module()
    root = module.vault_root()
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    stamp = clock.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    short = str(source.get("short_title") or source.get("title") or "paper")
    rel = f"current/kb/{collection}/{stamp}_{module.slugify(short)}.md"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"already exists: {rel}")
    content = kb_body(source, relpath=rel, created=stamp)
    path.write_text(content, encoding="utf-8")
    _append_kb_log(root, str(source.get("title") or short), rel, stamp[:10])
    return {
        "ok": True,
        "path": str(path),
        "relpath": rel,
        "resource": f"wiki:{rel}",
        "bytes": len(content.encode("utf-8")),
    }


def kb_body(source: dict[str, Any], *, relpath: str, created: str) -> str:
    title = str(source.get("title") or "paper").strip()
    claims = source.get("claims") or []
    claim_lines = "\n".join(f"- {item}" for item in claims) or "- (none stated)"
    lines = [
        "---",
        f"title: {json.dumps(title)}",
        f"created: {created}",
        "type: kb",
        f"source: {source.get('url') or ''}",
        f"source_kind: {source.get('kind') or ''}",
        "provider: mistral",
        f"model: {source.get('model') or _MISTRAL_MODEL}",
        f"about_path: {relpath}",
        "---",
        "",
        f"# {title}",
        "",
        "## Summary",
        "",
        str(source.get("summary") or "").strip(),
        "",
        "## Claims",
        "",
        claim_lines,
        "",
        "## Method",
        "",
        str(source.get("method") or "").strip(),
        "",
        "## Limits",
        "",
        str(source.get("limits") or "").strip(),
        "",
        "## Text",
        "",
        str(source.get("text") or "").strip(),
        "",
    ]
    return "\n".join(lines)


def _kb_collection(kind: str) -> str:
    if kind == "arxiv":
        return "arXiv"
    if kind == "biorxiv":
        return "bioRxiv"
    if kind == "medrxiv":
        return "medRxiv"
    raise RuntimeError(f"no curated collection for {kind}")


def _annotation_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "paper_analysis",
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
    }


def _annotation_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("Mistral document annotation was empty")


def _mistral_post(payload: dict[str, Any], key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _MISTRAL_OCR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_MISTRAL_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Mistral OCR HTTP {exc.code}: {detail}") from exc
    if not isinstance(body, dict):
        raise RuntimeError("Mistral OCR returned a non-object")
    return body


def _append_kb_log(root: Path, title: str, rel: str, day: str) -> None:
    log_path = root / "log.md"
    if not log_path.is_file():
        return
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{day}] kb | {title}\n- Created: {rel} (wiki:{rel})\n")
    except OSError:
        return


def write_zettel(source: dict[str, Any], *, performer: str, now: datetime | None = None) -> dict[str, Any]:
    who = _performer(performer)
    body = zettel_body(source, performer=who)
    if who == "gaius":
        return _write_gaius(body, now=now)
    return _write_hermes(body, now=now)


def zettel_body(source: dict[str, Any], *, performer: str) -> str:
    title = str(source.get("title") or source.get("url") or "source").strip()
    scope = _scope(str(source.get("scope") or "preview"))
    heading = title if scope == "preview" else f"{title} (full)"
    url = str(source.get("url") or "")
    kind = str(source.get("kind") or "web")
    abstract = str(source.get("abstract") or "").strip()
    text = str(source.get("text") or "").strip()
    summary = str(source.get("summary") or "").strip()
    note = str(source.get("note") or "").strip()
    scope_line = (
        f"Scope: first {_PDF_PAGES} PDF pages."
        if scope == "preview"
        else "Scope: full text and summary."
    )
    lines = [
        f"# {heading}",
        "",
        f"Source: {url}",
        f"Kind: {kind}",
        f"Performer: {performer}",
        scope_line,
        "Extract: CPU text. Not the Docling extract leaf.",
        "",
    ]
    if summary:
        lines.extend(["## Summary", "", summary, ""])
    if abstract:
        lines.extend(["## Abstract", "", abstract, ""])
    if text:
        lines.extend(["## Text", "", text, ""])
    if note:
        lines.extend(["## Note", "", note, ""])
    return "\n".join(lines).rstrip() + "\n"


def _scope(scope: str) -> str:
    name = (scope or "preview").strip().lower()
    if name not in SCOPES:
        raise RuntimeError(f"scope must be preview or full, got {scope!r}")
    return name


def _text_cap(scope: str) -> int:
    return _PREVIEW_CAP if scope == "preview" else _FULL_CAP


def _fetch_arxiv(url: str, get: GetFn, scope: str) -> dict[str, Any]:
    match = _ARXIV_RE.search(url)
    if not match:
        raise RuntimeError(f"not an arXiv url: {url}")
    paper_id = match.group(1)
    abs_url = f"https://arxiv.org/abs/{paper_id}"
    raw = get(f"https://export.arxiv.org/api/query?id_list={paper_id}")
    title, abstract, authors = _parse_arxiv(raw)
    text = ""
    note = ""
    try:
        pdf = get(f"https://arxiv.org/pdf/{paper_id}.pdf")
        text = _pdf_to_text(pdf, last_page=_PDF_PAGES if scope == "preview" else None)
    except Exception as exc:
        note = f"PDF text unavailable: {exc}"
    if not text:
        note = note or "Abstract only. pdftotext produced no pages."
    return {
        "url": abs_url,
        "kind": "arxiv",
        "scope": scope,
        "title": title or f"arXiv {paper_id}",
        "authors": authors,
        "abstract": abstract,
        "text": text[: _text_cap(scope)],
        "note": note,
    }


def _fetch_rxiv(url: str, kind: str, get: GetFn, scope: str) -> dict[str, Any]:
    if not _RXIV_RE.search(url or ""):
        raise RuntimeError(f"not a {kind} url: {url}")
    doi = _rxiv_doi(url, keep_version=True)
    server = "biorxiv" if kind == "biorxiv" else "medrxiv"
    raw = get(f"https://api.biorxiv.org/details/{server}/{doi}")
    title, abstract = _parse_rxiv(raw)
    text = ""
    note = ""
    try:
        pdf = get(f"https://www.{server}.org/content/{doi}.full.pdf")
        text = _pdf_to_text(pdf, last_page=_PDF_PAGES if scope == "preview" else None)
    except Exception as exc:
        note = f"PDF text unavailable: {exc}"
    if not text:
        note = note or "Abstract only. pdftotext produced no pages."
    return {
        "url": f"https://www.{server}.org/content/{doi}",
        "kind": kind,
        "scope": scope,
        "title": title or doi,
        "abstract": abstract,
        "text": text[: _text_cap(scope)],
        "note": note,
    }


def _fetch_web(url: str, get: GetFn, scope: str) -> dict[str, Any]:
    raw = get(url)
    if raw[:5] == b"%PDF-":
        text = _pdf_to_text(raw, last_page=_PDF_PAGES if scope == "preview" else None)
        return {
            "url": url,
            "kind": "web",
            "scope": scope,
            "title": _host_title(url),
            "abstract": "",
            "text": text[: _text_cap(scope)],
            "note": "" if text else "PDF had no extractable text.",
        }
    html = raw.decode("utf-8", "replace")
    title = _html_title(html) or _host_title(url)
    text = _html_text(html)
    note = ""
    if scope == "preview":
        note = "Not a PDF. The short card is the opening of the page, not eight pages."
    if not text:
        note = "Page had no extractable text."
    return {
        "url": url,
        "kind": "web",
        "scope": scope,
        "title": title,
        "abstract": "",
        "text": text[: _text_cap(scope)],
        "note": note,
    }


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "HermesAgentRTC/source-drop"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc


def _parse_arxiv(raw: bytes) -> tuple[str, str, str]:
    root = ET.fromstring(raw)
    entry = root.find("a:entry", _ATOM)
    if entry is None:
        return "", "", ""
    title = " ".join((entry.findtext("a:title", default="", namespaces=_ATOM) or "").split())
    abstract = " ".join((entry.findtext("a:summary", default="", namespaces=_ATOM) or "").split())
    authors = []
    for node in entry.findall("a:author", _ATOM):
        name = (node.findtext("a:name", default="", namespaces=_ATOM) or "").strip()
        if name:
            authors.append(name)
    return title, abstract, ", ".join(authors)


def _parse_rxiv(raw: bytes) -> tuple[str, str]:
    import json

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return "", ""
    collection = payload.get("collection") or []
    if not collection or not isinstance(collection[0], dict):
        return "", ""
    row = collection[0]
    title = " ".join(str(row.get("title") or "").split())
    abstract = " ".join(str(row.get("abstract") or "").split())
    return title, abstract


def _pdf_to_text(data: bytes, *, last_page: int | None = _PDF_PAGES) -> str:
    if not data or shutil.which("pdftotext") is None:
        return ""
    command = ["pdftotext", "-q", "-f", "1"]
    if last_page is not None:
        command.extend(["-l", str(last_page)])
    timeout = _FETCH_TIMEOUT_S if last_page is not None else _FULL_FETCH_TIMEOUT_S
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "source.pdf"
        pdf.write_bytes(data)
        command.extend(["-enc", "UTF-8", str(pdf), "-"])
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def _html_title(html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    if not match:
        return ""
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())[:180]


def _html_text(html: str) -> str:
    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    stripped = re.sub(r"(?is)<[^>]+>", " ", stripped)
    return " ".join(stripped.split())


def _host_title(url: str) -> str:
    host = urllib.request.urlparse(url).hostname or "web"
    return host


def _zettel_module() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "plugins" / "signals-zettel" / "capture.py"
    spec = importlib.util.spec_from_file_location("signals_zettel_capture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"zettel capture missing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_hermes(body: str, *, now: datetime | None) -> dict[str, Any]:
    module = _zettel_module()
    written = module.capture(body=body, now=now)
    if not written.get("ok"):
        raise RuntimeError(str(written.get("error") or "zettel capture failed"))
    return written


def _write_gaius(body: str, *, now: datetime | None) -> dict[str, Any]:
    import importlib.util

    root = _gaius_scratch_root()
    path = Path(__file__).resolve().parents[2] / "plugins" / "signals-zettel" / "capture.py"
    spec = importlib.util.spec_from_file_location("signals_zettel_capture_gaius", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"zettel capture missing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = now or datetime.now()
    title = module.title_from_body(body)
    rel = f"{clock.strftime('%Y-%m-%d')}/{clock.strftime('%H%M%S')}_{module.slugify(title)}.md"
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise RuntimeError(f"already exists: {rel}")
    dest.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    return {
        "ok": True,
        "path": str(dest),
        "relpath": rel,
        "resource": f"gaius-scratch:{rel}",
        "bytes": dest.stat().st_size,
    }


def _gaius_scratch_root() -> Path:
    raw = os.environ.get("GAIUS_KB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    home = os.environ.get("GAIUS_ROOT", "").strip()
    if home:
        return Path(home).expanduser() / "build" / "dev" / "scratch"
    raise RuntimeError("GAIUS_KB_PATH is unset; Gaius scratch zettel has nowhere to land")


def _performer(name: str) -> str:
    who = (name or "hermes").strip().lower()
    if who not in {"hermes", "gaius"}:
        raise RuntimeError(f"performer must be hermes or gaius, got {name!r}")
    return who


def _card_title(kind: str, url: str, scope: str) -> str:
    if kind == "arxiv":
        match = _ARXIV_RE.search(url)
        label = match.group(1) if match else url
    elif kind in {"biorxiv", "medrxiv"}:
        label = _rxiv_doi(url)[:48]
    else:
        label = _host_title(url)
    prefix = "Extract 8 pages" if scope == "preview" else "Full extract and summary"
    return f"{prefix}: {label}"[:80]


def _session(session_id: str) -> str | None:
    if not (session_id or "").strip():
        return None
    try:
        from hsengine.engine.session_history import hermes_session_id

        return hermes_session_id(session_id)
    except Exception:
        return None


def _connect():
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    return kanban_db, kbc.connect()


def _find_card(key: str, scope: str) -> dict[str, str] | None:
    kanban_db, conn = _connect()
    try:
        with closing(conn):
            row = conn.execute(
                "SELECT id, status, title FROM tasks WHERE idempotency_key = ? "
                "AND status != 'archived' ORDER BY created_at DESC LIMIT 1",
                (f"source-drop:{key}:{scope}",),
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row["id"]), "status": str(row["status"]), "title": str(row["title"] or "")}
    except Exception:
        log.debug("source drop card lookup failed", exc_info=True)
        return None


def _create_card(
    *,
    key: str,
    title: str,
    url: str,
    kind: str,
    performer: str,
    session_id: str,
    scope: str,
    initial_status: str = "running",
) -> str:
    kanban_db, conn = _connect()
    if scope == "preview":
        job = f"First {_PDF_PAGES} PDF pages into a scratch zettel."
    else:
        job = "Full text extraction and a discussion summary into a scratch zettel."
    body = (
        "Source drop from the live call. "
        f"{job} Does not claim the extract GPU and does not evict thinking.\n\n"
        f"URL: {url}\nKind: {kind}\nScope: {scope}\nPerformer: {performer}\n"
        f"gpu_tokens: {GPU_TOKENS}\n\n"
        "The hsengine source-drop thread performs a Mistral extract. "
        "A kanban or ACP worker does not get MISTRAL_API_KEY in its environment. "
        "Re-run from that path with scripts/mistral_board.py, which reads "
        "HERMES_HOME/.env.\n"
    )
    with closing(conn):
        return kanban_db.create_task(
            conn,
            title=title,
            body=body,
            created_by="hicks",
            assignee="grok",
            initial_status=initial_status,
            workspace_kind="scratch",
            idempotency_key=f"source-drop:{key}:{scope}",
            session_id=_session(session_id),
        )


def _unblock(task_id: str) -> None:
    kanban_db, conn = _connect()
    with closing(conn):
        kanban_db.unblock_task(conn, task_id)


def _comment(task_id: str, body: str) -> None:
    kanban_db, conn = _connect()
    with closing(conn):
        kanban_db.add_comment(conn, task_id, "hicks", body)
    _refresh()


def _complete(task_id: str, result: str) -> None:
    kanban_db, conn = _connect()
    with closing(conn):
        kanban_db.complete_task(
            conn,
            task_id,
            result=result,
            summary=result,
            fire_lifecycle_hook=False,
        )


def _block(task_id: str, reason: str) -> None:
    kanban_db, conn = _connect()
    with closing(conn):
        kanban_db.block_task(conn, task_id, reason=reason[:500], kind="transient")


def _refresh() -> None:
    try:
        from hsengine.engine.webrtc_kanban import refresh_view

        refresh_view()
    except Exception:
        log.debug("source drop board refresh skipped", exc_info=True)
