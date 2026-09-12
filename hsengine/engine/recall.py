"""Tiered, temporal recall for AgentRTC spoken turns.

Recent Hermes conversations and local citations (wiki + MEMORY.md under
HERMES_HOME) rank above older matches. Gaius lattice KB is not in this
pack — that stays ``kb_search``.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("hsengine.engine.recall")

# Half-weight around this many hours; yesterday still beats last week.
_TAU_HOURS = 18.0
_SESSION_LIMIT = 3
_CITATION_LIMIT = 3
_FRESH_MINUTES = 12
_FRESH_LIMIT = 2
_FRESH_DIRS = ("scratch", "inbox")
_SNIPPET = 280
_BUDGET = 1600
_MAX_WIKI_BYTES = 120_000
_HIDDEN_SOURCES = frozenset({"kanban", "subagent", "tool"})
_STOP = frozenset(
    """
    a an the to of on in for with from at as is are was were be been being
    do does did have has had having you we i they it this that those these
    our your their my still access notes note made about what where when how
    who why which whom whose there here then than too very just also not
    and or but if so because while after before into over under again
    please yeah yes no okay ok know think like something anything everything
    session call talk talking talked conversation conversations
    """.split()
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_UPDATED = re.compile(r"^updated:\s*(\d{4}-\d{2}-\d{2})\s*$", re.M | re.I)
_TITLE = re.compile(r"^title:\s*(.+)$", re.M | re.I)


def content_tokens(query: str) -> list[str]:
    """Keywords worth searching — drops STT filler so FTS AND does not go empty."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _TOKEN.findall(query or ""):
        w = raw.lower()
        if w in _STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def focus_query(query: str) -> str:
    """FTS string from *query* (space-AND of content tokens)."""
    return " ".join(content_tokens(query))


def recency_weight(age_hours: float, *, tau: float = _TAU_HOURS) -> float:
    if age_hours < 0:
        age_hours = 0.0
    if tau <= 0:
        tau = _TAU_HOURS
    return 1.0 / (1.0 + float(age_hours) / tau)


def _age_hours(ts: float | None, now: float) -> float:
    if ts is None:
        return 1e6
    try:
        age = (now - float(ts)) / 3600.0
    except (TypeError, ValueError):
        return 1e6
    return max(0.0, age)


def _clip(text: str, n: int = _SNIPPET) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _body_snippet(text: str) -> str:
    body = text or ""
    if body.lstrip().startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    return _clip(body)


def _frontmatter_title(text: str, fallback: str) -> str:
    m = _TITLE.search(text or "")
    if not m:
        return fallback
    return m.group(1).strip().strip("\"'") or fallback


def _file_ts(path: Path, text: str) -> float:
    m = _UPDATED.search(text or "")
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _matches(text: str, tokens: Iterable[str]) -> int:
    blob = (text or "").lower()
    return sum(blob.count(t) for t in tokens)


def _fresh_hits(
    *,
    hermes_home: Path,
    now: float,
    max_age_minutes: float = _FRESH_MINUTES,
    limit: int = _FRESH_LIMIT,
) -> list[dict[str, Any]]:
    """Zettels created in the last few minutes. Empty when nothing is that new."""
    wiki = hermes_home / "wiki"
    if not wiki.is_dir() or max_age_minutes <= 0:
        return []
    max_age_s = float(max_age_minutes) * 60.0
    hits: list[dict[str, Any]] = []
    for folder in _FRESH_DIRS:
        root = wiki / folder
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            try:
                if not path.is_file() or path.stat().st_size > _MAX_WIKI_BYTES:
                    continue
                mtime = path.stat().st_mtime
                age_s = now - mtime
                if age_s < 0 or age_s > max_age_s:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(hermes_home).as_posix()
            hits.append(
                {
                    "kind": "fresh",
                    "path": rel,
                    "title": _frontmatter_title(text, path.stem),
                    "snippet": _body_snippet(text),
                    "age_minutes": age_s / 60.0,
                    "mtime": mtime,
                }
            )
    hits.sort(key=lambda h: -float(h.get("mtime") or 0))
    return hits[: max(1, limit)]


def _wiki_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def _citation_hits(
    *,
    tokens: list[str],
    hermes_home: Path,
    now: float,
    limit: int,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    wiki = hermes_home / "wiki"
    for path in _wiki_files(wiki):
        try:
            if path.stat().st_size > _MAX_WIKI_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n = _matches(f"{path.name}\n{text}", tokens)
        if not n:
            continue
        rel = path.relative_to(hermes_home).as_posix()
        age = _age_hours(_file_ts(path, text), now)
        name_bonus = 1.5 if any(t in path.stem.lower() for t in tokens) else 1.0
        parts = {p.lower() for p in path.parts}
        if path.stem.lower() in {"log", "index", "schema"}:
            loc_w = 0.35
        elif "entities" in parts or "concepts" in parts:
            loc_w = 1.8
        elif "raw" in parts:
            loc_w = 0.7
        else:
            loc_w = 1.0
        hits.append(
            {
                "kind": "wiki",
                "path": rel,
                "title": _frontmatter_title(text, path.stem),
                "snippet": _body_snippet(text),
                "age_hours": age,
                "score": recency_weight(age) * n * name_bonus * loc_w,
            }
        )
    memory = hermes_home / "memories" / "MEMORY.md"
    if memory.is_file():
        try:
            body = memory.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        for part in re.split(r"\n§\n|\n{2,}", body):
            n = _matches(part, tokens)
            if not n:
                continue
            age = _age_hours(_file_ts(memory, part), now)
            hits.append(
                {
                    "kind": "memory",
                    "path": "memories/MEMORY.md",
                    "title": "MEMORY.md",
                    "snippet": _clip(part),
                    "age_hours": age,
                    "score": recency_weight(age) * n * 1.2,
                }
            )
    hits.sort(key=lambda h: (-float(h["score"]), float(h["age_hours"])))
    return hits[: max(1, limit)]


def _session_hits(
    *,
    tokens: list[str],
    db: Any,
    exclude_session_id: str,
    now: float,
    limit: int,
) -> list[dict[str, Any]]:
    q = " ".join(tokens)
    if db is None or not q:
        return []
    try:
        rows = db.search_messages(
            query=q,
            role_filter=["user", "assistant"],
            exclude_sources=list(_HIDDEN_SOURCES),
            limit=80,
            sort="newest",
            fields=("id", "session_id", "role", "snippet", "source", "model", "session_started"),
        )
    except Exception:
        log.debug("agent-rtc recall session search failed", exc_info=True)
        return []
    by_sid: dict[str, dict[str, Any]] = {}
    exclude = (exclude_session_id or "").strip()
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("session_id") or "")
        if not sid or sid == exclude:
            continue
        source = str(r.get("source") or "")
        if source in _HIDDEN_SOURCES:
            continue
        started = r.get("session_started")
        try:
            started_f = float(started) if started is not None else None
        except (TypeError, ValueError):
            started_f = None
        age = _age_hours(started_f, now)
        src_w = 1.8 if source == "agent-rtc" else (0.25 if source == "cron" else 1.0)
        snippet = str(r.get("snippet") or "")
        n = max(1, _matches(snippet, tokens))
        score = recency_weight(age) * src_w * n
        prev = by_sid.get(sid)
        if prev is None or score > float(prev["score"]):
            by_sid[sid] = {
                "session_id": sid,
                "source": source or "unknown",
                "snippet": _clip(snippet),
                "age_hours": age,
                "score": score,
                "when": started_f,
            }
    ranked = sorted(by_sid.values(), key=lambda h: (-float(h["score"]), float(h["age_hours"])))
    return ranked[: max(1, limit)]


def recall_pack(
    *,
    query: str,
    webrtc_id: str = "",
    hermes_home: Path | None = None,
    db: Any = None,
    now: float | None = None,
    session_limit: int = _SESSION_LIMIT,
    citation_limit: int = _CITATION_LIMIT,
) -> dict[str, Any]:
    """Ranked conversations + local citations. Empty lists when nothing matches."""
    import time as time_mod

    from hermes_constants import get_hermes_home
    from hsengine.engine import session_history

    tokens = content_tokens(query)
    pack: dict[str, Any] = {
        "query": " ".join(tokens),
        "tokens": tokens,
        "conversations": [],
        "citations": [],
        "fresh": [],
    }
    clock = float(now if now is not None else time_mod.time())
    home = Path(hermes_home) if hermes_home is not None else get_hermes_home()
    pack["fresh"] = _fresh_hits(hermes_home=home, now=clock)
    if not tokens:
        return pack
    store = db if db is not None else session_history._store()
    exclude = session_history.hermes_session_id(webrtc_id) if webrtc_id else ""
    pack["conversations"] = _session_hits(
        tokens=tokens,
        db=store,
        exclude_session_id=exclude,
        now=clock,
        limit=session_limit,
    )
    pack["citations"] = _citation_hits(
        tokens=tokens,
        hermes_home=home,
        now=clock,
        limit=citation_limit,
    )
    return pack


def format_recall(pack: dict[str, Any] | None, *, budget: int = _BUDGET) -> str:
    """Spoken-context block. Empty if the pack has no hits.

    Agent-mediated: invent from the tiers; do not read the block as a briefing.
    Lexical talks/wiki outrank lattice/Gaius semantics.
    """
    if not pack:
        return ""
    conv = list(pack.get("conversations") or [])
    cites = list(pack.get("citations") or [])
    turns = list(pack.get("turns") or [])
    lattice = list(pack.get("lattice") or [])
    fresh = list(pack.get("fresh") or [])
    if not conv and not cites and not turns and not lattice and not fresh:
        return ""
    lines = [
        "Memory (hybrid, recent first). Invent from this; do not read it as a briefing. "
        "Our talks and wiki outrank the lattice (Gaius)."
    ]
    if fresh:
        lines.append(
            "Just filed (last few minutes). May color the opening; do not rundown:"
        )
        for h in fresh:
            age_m = float(h.get("age_minutes") or 0)
            when = "just now" if age_m < 1 else f"{age_m:.0f}m ago"
            path = str(h.get("path") or "")
            title = str(h.get("title") or "")
            snippet = str(h.get("snippet") or "")
            lines.append(f"- {when} {path} ({title}): {snippet}")
    if conv:
        lines.append("Conversations:")
        for h in conv:
            age = float(h.get("age_hours") or 0)
            when = f"{age:.0f}h ago" if age >= 1 else "just now"
            sid = str(h.get("session_id") or "")
            src = str(h.get("source") or "")
            snippet = str(h.get("snippet") or "")
            lines.append(f"- {when} [{src}] {sid}: {snippet}")
    if cites:
        lines.append("Citations:")
        for h in cites:
            title = str(h.get("title") or h.get("path") or "")
            path = str(h.get("path") or "")
            snippet = str(h.get("snippet") or "")
            lines.append(f"- {path} ({title}): {snippet}")
    if turns:
        lines.append("Recent turns:")
        for h in turns:
            role = str(h.get("role") or "turn")
            snippet = str(h.get("text") or h.get("snippet") or "")
            lines.append(f"- {role}: {snippet}")
    if lattice:
        lines.append("Lattice (Gaius, lower priority):")
        for h in lattice:
            title = str(h.get("title") or "")
            snippet = str(h.get("snippet") or "")
            lines.append(f"- {title}: {snippet}".rstrip(": "))
    text = "\n".join(lines)
    if len(text) <= budget:
        return text
    return text[: budget - 1].rstrip() + "…"
