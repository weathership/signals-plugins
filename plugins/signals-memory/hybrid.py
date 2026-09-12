"""Hybrid lexical + semantic recall for the signals-memory provider.

Tiers (highest first): recent Hermes conversations (FTS, recency-weighted),
local wiki/MEMORY.md citations, JSONL turns, then Gaius lattice SEARCH.
Invent from the pack; do not dump it as speech.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("hsengine.plugins.signals_memory")

_LATTICE_LIMIT = 2


def webrtc_id_from_session(session_id: str) -> str:
    sid = (session_id or "").strip()
    prefix = "agent-rtc-"
    if sid.startswith(prefix):
        return sid[len(prefix) :]
    return ""


def lattice_hits(query: str, *, limit: int = _LATTICE_LIMIT) -> list[dict[str, Any]]:
    """Semantic-ish lattice hits via Gaius ServerQuery SEARCH. Empty on failure."""
    q = " ".join((query or "").split())
    if not q:
        return []
    try:
        from hsengine.engine.ops import search
        from hsengine.engine.recall import focus_query

        focused = focus_query(q) or q
        data = search(query=focused, stream="kb", limit=max(1, limit))
    except Exception:
        log.debug("signals-memory lattice search failed", exc_info=True)
        return []
    hits: list[dict[str, Any]] = []
    for raw in data.get("hits") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "")
        snippet = str(raw.get("snippet") or "")
        if not title and not snippet:
            continue
        hits.append(
            {
                "kind": "lattice",
                "title": title,
                "snippet": snippet,
                "source": str(raw.get("source") or "gaius"),
                "project": str(raw.get("project") or "gaius"),
                "score": float(raw.get("score") or 0.0),
            }
        )
        if len(hits) >= max(1, limit):
            break
    return hits


def prefetch_block(
    query: str,
    *,
    session_id: str = "",
    hermes_home: Path | None = None,
    jsonl_hits: list[dict[str, Any]] | None = None,
    include_lattice: bool = True,
) -> str:
    """Format the hybrid pack for MemoryProvider.prefetch. Empty if nothing matched."""
    from hsengine.engine.recall import format_recall, recall_pack

    pack = recall_pack(
        query=query,
        webrtc_id=webrtc_id_from_session(session_id),
        hermes_home=hermes_home,
    )
    turns = list(jsonl_hits or [])
    if turns:
        pack["turns"] = turns[:3]
    if include_lattice:
        pack["lattice"] = lattice_hits(query, limit=_LATTICE_LIMIT)
    return format_recall(pack)
