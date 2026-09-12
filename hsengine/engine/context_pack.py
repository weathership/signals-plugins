"""Agent-mediated AgentRTC: named agents sit between workflow products and the human.

Connect loads agenda + thoughts briefs over ServerQuery. Bishop (silent,
tools and up to two delegate_task children) invents; Ripley speaks. Freshness
is a property of those workflows — a stale or empty opening is the first-turn
signal that the workspace is failing, not a cue to invent today's news.
"""
from __future__ import annotations

import logging

log = logging.getLogger("hsengine.engine.context_pack")

_SPOKEN_CAP = 800
# Match the 6h auditor: thoughts older than 2× 4h cadence are stale.
THOUGHTS_STALE_MIN = 8 * 60
AGENDA_STALE_MIN = 36 * 60
_UNUSABLE = (
    "unreachable",
    "cannot reach",
    "can't reach",
    "no brief",
    "nopool",
)


def _clip(text: str, n: int = _SPOKEN_CAP) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    cut = t[: n - 1].rsplit(" ", 1)[0]
    return cut + "…"


def usable_spoken(text: str | None) -> str:
    """Keep real spoken briefs; drop fetch/idle/error notes so they never go on the call."""
    t = _clip(text or "")
    if len(t) < 24:
        return ""
    low = t.lower()
    if any(tok in low for tok in _UNUSABLE):
        return ""
    if t.startswith("#") or low.startswith(("error", "failed", "idle", "empty")):
        return ""
    return t


def _age_min(brief: dict) -> int | None:
    raw = brief.get("age_min")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _age_label(minutes: int | None) -> str:
    if minutes is None:
        return "unknown age"
    if minutes < 90:
        return f"{minutes} min"
    hours = minutes / 60
    if hours < 40:
        return f"{hours:.0f}h"
    return f"{hours / 24:.1f}d"


def workspace_freshness(
    *,
    thoughts_age_min: int | None,
    agenda_age_min: int | None,
    has_spoken: bool,
) -> str:
    """fresh | stale | empty — first-turn signal, not a health check."""
    if not has_spoken:
        return "empty"
    if thoughts_age_min is None or thoughts_age_min > THOUGHTS_STALE_MIN:
        return "stale"
    if agenda_age_min is not None and agenda_age_min > AGENDA_STALE_MIN:
        return "stale"
    return "fresh"


def conversational_context(*, agenda_id: str = "") -> dict[str, str]:
    """Spoken agenda + thoughts briefs (and the named item, if any)."""
    from hsengine.engine import ops

    out: dict[str, str] = {}
    agenda_age: int | None = None
    thoughts_age: int | None = None
    try:
        agenda = ops.agenda(item_id=agenda_id or "")
    except Exception:
        log.warning("agenda brief fetch failed", exc_info=True)
        agenda = {}
    briefs = agenda.get("briefs") if isinstance(agenda, dict) else None
    if isinstance(briefs, list) and briefs:
        spoken = usable_spoken(
            str(briefs[0].get("spoken") or briefs[0].get("written") or "")
        )
        if spoken:
            out["agenda_spoken"] = spoken
        agenda_age = _age_min(briefs[0] if isinstance(briefs[0], dict) else {})
        if agenda_age is not None:
            out["agenda_age"] = _age_label(agenda_age)
    if agenda_id and isinstance(agenda, dict):
        item = agenda.get("item") if isinstance(agenda.get("item"), dict) else None
        if item:
            body = str(item.get("body") or item.get("summary") or "")
            title = str(item.get("title") or "")
            if title:
                out["agenda_title"] = title
            if body:
                out["agenda_item"] = _clip(body, 1200)
    try:
        thoughts = ops.recent_thoughts(limit=4, since_hours=24)
    except Exception:
        log.warning("thoughts brief fetch failed", exc_info=True)
        thoughts = {}
    tbriefs = thoughts.get("briefs") if isinstance(thoughts, dict) else None
    if isinstance(tbriefs, list) and tbriefs:
        spoken = usable_spoken(
            str(tbriefs[0].get("spoken") or tbriefs[0].get("written") or "")
        )
        if spoken:
            out["thoughts_spoken"] = spoken
        thoughts_age = _age_min(tbriefs[0] if isinstance(tbriefs[0], dict) else {})
        if thoughts_age is None:
            # Fall back to newest thought in the window.
            rows = thoughts.get("thoughts") if isinstance(thoughts, dict) else None
            if isinstance(rows, list) and rows:
                when = str(rows[0].get("when") or "")
                out["thoughts_when"] = when
        if thoughts_age is not None:
            out["thoughts_age"] = _age_label(thoughts_age)
    has_spoken = bool(out.get("agenda_spoken") or out.get("thoughts_spoken"))
    state = workspace_freshness(
        thoughts_age_min=thoughts_age,
        agenda_age_min=agenda_age,
        has_spoken=has_spoken,
    )
    out["workspace"] = state
    if state == "stale":
        bits = []
        if out.get("thoughts_age"):
            bits.append("thoughts " + out["thoughts_age"])
        if out.get("agenda_age"):
            bits.append("agenda " + out["agenda_age"])
        out["workspace_note"] = "stale (" + (", ".join(bits) or "ages unknown") + ")"
    elif state == "empty":
        out["workspace_note"] = "empty — no live agenda or thoughts brief"
    else:
        out["workspace_note"] = "fresh"
    return out


def pipeline_block(pack: dict[str, str] | None) -> str:
    """Plain-text block to splice into the opening prompt."""
    if not pack:
        return ""
    parts: list[str] = []
    state = pack.get("workspace") or ""
    note = pack.get("workspace_note") or ""
    if state in ("stale", "empty"):
        parts.append("Workspace freshness: " + (note or state) + ".")
    agenda = usable_spoken(pack.get("agenda_spoken") or "")
    if agenda:
        parts.append("Today's agenda brief:\n" + agenda)
    thoughts = usable_spoken(pack.get("thoughts_spoken") or "")
    if thoughts:
        parts.append("Latest thoughts brief:\n" + thoughts)
    return "\n\n".join(parts)
