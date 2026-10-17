"""CPU source drop for a live AgentRTC call.

A dropped arXiv, bioRxiv, medRxiv, or web URL is text for the discussion,
not a Docling run. Docling's extract leaf wants a GPU and the old runner
can evict the standing thinking server (GPUs 0–3). This path claims no
GPU token, does not talk to YuniKorn, and does not load a model.

The kanban card is filed before the fetch. Extraction and the scratch
zettel run on a background thread. Hermes writes the Hermes wiki vault.
Gaius writes ``GAIUS_KB_PATH`` scratch. The performer is who extracts,
not the kind of URL.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("hsengine.engine.source_drop")

# Zero on purpose. Do not raise this to borrow extract, light, or heavy.
GPU_TOKENS = 0

_MAX_PER_TURN = 3
_PDF_PAGES = 8
_TEXT_CAP = 48_000
_FETCH_TIMEOUT_S = 30

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
    """Stable card key. A second drop of the same paper is the same card."""
    kind = classify(url)
    if kind == "arxiv":
        match = _ARXIV_RE.search(url)
        return f"arxiv:{(match.group(1) if match else url).lower()}"
    if kind in {"biorxiv", "medrxiv"}:
        match = _RXIV_RE.search(url)
        doi = (match.group("doi") if match else url).rstrip(".").lower()
        if doi.endswith(".full.pdf"):
            doi = doi[: -len(".full.pdf")]
        return f"{kind}:{doi}"
    parsed = urllib.request.urlparse(url)
    clean = parsed._replace(fragment="").geturl()
    return f"web:{clean}"


def file_source_drops(session_id: str, text: str) -> list[dict[str, Any]]:
    """Enqueue every dropped URL on this turn. Failures stay off the call."""
    filed: list[dict[str, Any]] = []
    for url in urls_in(text):
        try:
            filed.append(enqueue(url=url, session_id=session_id, performer="hermes"))
        except Exception:
            log.warning("source drop failed for %s", url, exc_info=True)
    return filed


def enqueue(
    *,
    url: str,
    session_id: str = "",
    performer: str = "hermes",
    spawn: SpawnFn | None = None,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """File the card, then extract off the voice turn.

    Returns as soon as the card exists. ``spawn`` runs the work inline in
    tests. The default spawn is a daemon thread.
    """
    target = (url or "").strip()
    if not target:
        return {"ok": False, "error": "url required", "created": False}
    who = _performer(performer)
    key = drop_key(target)
    kind = classify(target)
    title = _card_title(kind, target)
    with _LOCK:
        existing = _find_card(key)
        if existing and existing["status"] != "blocked":
            return {
                "ok": True,
                "created": False,
                "id": existing["id"],
                "status": existing["status"],
                "title": existing["title"] or title,
                "url": target,
                "kind": kind,
                "performer": who,
                "gpu_tokens": GPU_TOKENS,
            }
        if existing and key in _INFLIGHT:
            return {
                "ok": True,
                "created": False,
                "id": existing["id"],
                "status": existing["status"],
                "title": existing["title"] or title,
                "url": target,
                "kind": kind,
                "performer": who,
                "gpu_tokens": GPU_TOKENS,
            }
        if existing:
            tid = existing["id"]
        else:
            tid = _create_card(
                key=key,
                title=title,
                url=target,
                kind=kind,
                performer=who,
                session_id=session_id,
            )
        _INFLIGHT.add(key)
    worker = lambda: _run(tid, target, who, key, fetch or fetch_source)
    if spawn is None:
        threading.Thread(target=worker, daemon=True, name="source-drop").start()
    else:
        spawn(worker)
    return {
        "ok": True,
        "created": True,
        "id": tid,
        "status": "running",
        "title": title,
        "url": target,
        "kind": kind,
        "performer": who,
        "gpu_tokens": GPU_TOKENS,
    }


def _run(
    task_id: str,
    url: str,
    performer: str,
    key: str,
    fetch: Callable[[str], dict[str, Any]],
) -> None:
    try:
        _comment(task_id, f"Fetching {url} on CPU. gpu_tokens={GPU_TOKENS}. No extract leaf, no vLLM eviction.")
        source = fetch(url)
        written = write_zettel(source, performer=performer)
        rel = str(written.get("relpath") or written.get("path") or "")
        _comment(task_id, f"Wrote {rel} ({written.get('bytes') or 0} bytes).")
        _complete(task_id, rel or "written")
        log.info("source drop %s %s -> %s", performer, key, rel)
    except Exception as exc:
        log.warning("source drop %s failed", key, exc_info=True)
        try:
            _comment(task_id, f"Extract failed: {exc}")
            _block(task_id, str(exc))
        except Exception:
            log.debug("source drop could not block %s", task_id, exc_info=True)
    finally:
        with _LOCK:
            _INFLIGHT.discard(key)
        _refresh()


def fetch_source(url: str, *, get: GetFn | None = None) -> dict[str, Any]:
    """Metadata plus as much prose as a CPU fetch can hold. No model."""
    kind = classify(url)
    getter = get or _http_get
    if kind == "arxiv":
        return _fetch_arxiv(url, getter)
    if kind in {"biorxiv", "medrxiv"}:
        return _fetch_rxiv(url, kind, getter)
    return _fetch_web(url, getter)


def write_zettel(source: dict[str, Any], *, performer: str, now: datetime | None = None) -> dict[str, Any]:
    who = _performer(performer)
    body = zettel_body(source, performer=who)
    if who == "gaius":
        return _write_gaius(body, now=now)
    return _write_hermes(body, now=now)


def zettel_body(source: dict[str, Any], *, performer: str) -> str:
    title = str(source.get("title") or source.get("url") or "source").strip()
    url = str(source.get("url") or "")
    kind = str(source.get("kind") or "web")
    abstract = str(source.get("abstract") or "").strip()
    text = str(source.get("text") or "").strip()
    note = str(source.get("note") or "").strip()
    lines = [
        f"# {title}",
        "",
        f"Source: {url}",
        f"Kind: {kind}",
        f"Performer: {performer}",
        "Extract: CPU text. Not the Docling extract leaf.",
        "",
    ]
    if abstract:
        lines.extend(["## Abstract", "", abstract, ""])
    if text:
        lines.extend(["## Text", "", text, ""])
    if note:
        lines.extend(["## Note", "", note, ""])
    return "\n".join(lines).rstrip() + "\n"


def _fetch_arxiv(url: str, get: GetFn) -> dict[str, Any]:
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
        text = _pdf_to_text(pdf)
    except Exception as exc:
        note = f"PDF text unavailable: {exc}"
    if not text:
        note = note or "Abstract only. pdftotext produced no pages."
    return {
        "url": abs_url,
        "kind": "arxiv",
        "title": title or f"arXiv {paper_id}",
        "authors": authors,
        "abstract": abstract,
        "text": text[:_TEXT_CAP],
        "note": note,
    }


def _fetch_rxiv(url: str, kind: str, get: GetFn) -> dict[str, Any]:
    match = _RXIV_RE.search(url)
    if not match:
        raise RuntimeError(f"not a {kind} url: {url}")
    doi = match.group("doi").rstrip(".")
    if doi.endswith(".full.pdf"):
        doi = doi[: -len(".full.pdf")]
    server = "biorxiv" if kind == "biorxiv" else "medrxiv"
    raw = get(f"https://api.biorxiv.org/details/{server}/{doi}")
    title, abstract = _parse_rxiv(raw)
    text = ""
    note = ""
    try:
        pdf = get(f"https://www.{server}.org/content/{doi}.full.pdf")
        text = _pdf_to_text(pdf)
    except Exception as exc:
        note = f"PDF text unavailable: {exc}"
    if not text:
        note = note or "Abstract only. pdftotext produced no pages."
    return {
        "url": f"https://www.{server}.org/content/{doi}",
        "kind": kind,
        "title": title or doi,
        "abstract": abstract,
        "text": text[:_TEXT_CAP],
        "note": note,
    }


def _fetch_web(url: str, get: GetFn) -> dict[str, Any]:
    raw = get(url)
    if raw[:5] == b"%PDF-":
        text = _pdf_to_text(raw)
        return {
            "url": url,
            "kind": "web",
            "title": _host_title(url),
            "abstract": "",
            "text": text[:_TEXT_CAP],
            "note": "" if text else "PDF had no extractable text.",
        }
    html = raw.decode("utf-8", "replace")
    title = _html_title(html) or _host_title(url)
    text = _html_text(html)
    return {
        "url": url,
        "kind": "web",
        "title": title,
        "abstract": "",
        "text": text[:_TEXT_CAP],
        "note": "" if text else "Page had no extractable text.",
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


def _pdf_to_text(data: bytes) -> str:
    if not data or shutil.which("pdftotext") is None:
        return ""
    with tempfile.TemporaryDirectory() as directory:
        pdf = Path(directory) / "source.pdf"
        pdf.write_bytes(data)
        try:
            proc = subprocess.run(
                [
                    "pdftotext",
                    "-q",
                    "-f",
                    "1",
                    "-l",
                    str(_PDF_PAGES),
                    "-enc",
                    "UTF-8",
                    str(pdf),
                    "-",
                ],
                capture_output=True,
                timeout=_FETCH_TIMEOUT_S,
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


def _write_hermes(body: str, *, now: datetime | None) -> dict[str, Any]:
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "plugins" / "signals-zettel" / "capture.py"
    spec = importlib.util.spec_from_file_location("signals_zettel_capture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"zettel capture missing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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


def _card_title(kind: str, url: str) -> str:
    if kind == "arxiv":
        match = _ARXIV_RE.search(url)
        label = match.group(1) if match else url
    elif kind in {"biorxiv", "medrxiv"}:
        match = _RXIV_RE.search(url)
        label = (match.group("doi") if match else url)[:48]
    else:
        label = _host_title(url)
    return f"Extract {kind}: {label}"[:80]


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


def _find_card(key: str) -> dict[str, str] | None:
    kanban_db, conn = _connect()
    try:
        with closing(conn):
            row = conn.execute(
                "SELECT id, status, title FROM tasks WHERE idempotency_key = ? "
                "AND status != 'archived' ORDER BY created_at DESC LIMIT 1",
                (f"source-drop:{key}",),
            ).fetchone()
        if row is None:
            return None
        return {"id": str(row["id"]), "status": str(row["status"]), "title": str(row["title"] or "")}
    except Exception:
        log.debug("source drop card lookup failed", exc_info=True)
        return None


def _create_card(*, key: str, title: str, url: str, kind: str, performer: str, session_id: str) -> str:
    kanban_db, conn = _connect()
    body = (
        "Source drop from the live call. CPU text extraction into a scratch "
        "zettel. Does not claim the extract GPU and does not evict thinking.\n\n"
        f"URL: {url}\nKind: {kind}\nPerformer: {performer}\n"
        f"gpu_tokens: {GPU_TOKENS}\n"
    )
    with closing(conn):
        return kanban_db.create_task(
            conn,
            title=title,
            body=body,
            created_by="hicks",
            assignee="grok",
            initial_status="running",
            workspace_kind="scratch",
            idempotency_key=f"source-drop:{key}",
            session_id=_session(session_id),
        )


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
