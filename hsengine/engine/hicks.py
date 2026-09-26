"""Hicks files implied call work into kanban triage without stopping the voice.

Ripley keeps the foreground. The gateway dispatcher (orchestrator profile
``hicks``, leaf assignee ``grok``) pulls cards across the board. Bishop and
Vasquez stay on the live call: a suggestion is ``bishop_suggest``, a figure
is Vasquez, and a figure keeps the video.
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from typing import Any

_SUGGESTING: ContextVar[bool] = ContextVar("hicks_bishop_suggest", default=False)

log = logging.getLogger("hsengine.engine.hicks")

ACTIVE = frozenset(
    {"triage", "todo", "scheduled", "ready", "running", "blocked", "review"}
)

_ASK = re.compile(
    r"\b("
    r"look into|look up|pull up|pull the|follow up|follow-up|"
    r"dig into|research|draft|write up|compare|design|"
    r"check on|find out|on the board|add (?:a |the )?card|"
    r"we should|keep an eye|circle back"
    r")\b",
    re.I,
)
_COMMIT = re.compile(
    r"\b(i'll|i will|i'm going to|im going to|let me|i'm gonna)\b",
    re.I,
)
_EMPTY_COMMIT = re.compile(
    r"\b(let me know|i'll be here|i'll wait|i'm here)\b",
    re.I,
)
_RESIDUAL = re.compile(
    r"\b(i'll also|then i'll|next i'll|still need to|after that|in the background)\b",
    re.I,
)
_LEAD = re.compile(
    r"^(?:i'll|i will|i'm going to|im going to|let me|i'm gonna)\s+",
    re.I,
)
_SMALLTALK = re.compile(
    r"(?:hi|hey|hello|thanks|thank you|ok|okay|yes|yeah|yep|no|nope|"
    r"good morning|good afternoon|good evening|how are you|how's it going)"
    r"[.!]?",
    re.I,
)
# A lookup that already happened in the foreground is not a second card.
_DONE_TOOLS = frozenset(
    {
        "fmp",
        "web_search",
        "kb_search",
        "hermes",
        "agenda",
        "sitrep",
        "recent_thoughts",
        "session_search",
        "grok_consult",
        "viz_show",
        "viz_select",
        "viz_hover",
        "conversation",
        "agenda_create",
    }
)
_ORCH_LINE = re.compile(r"(?m)^(\s*orchestrator_profile:\s*)([^\s#]+)")

_FILED_STEER = (
    "Work just landed on the board and continues in the background. "
    "You may change the subject. One sentence is enough if you mention it. "
    "Do not say it is finished. Do not name the machinery."
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _is_smalltalk(text: str) -> bool:
    return bool(_SMALLTALK.fullmatch((text or "").strip()))


def _imperative(text: str) -> str:
    raw = " ".join((text or "").split())
    raw = _LEAD.sub("", raw).strip(" .?!;:")
    raw = re.sub(
        r"^(?:hey|ok|okay|so|well|please|can you|could you|would you|let's|lets)\b[:,\s]*",
        "",
        raw,
        flags=re.I,
    ).strip(" .?!;:")
    if len(raw) < 8:
        return ""
    title = raw[0].upper() + raw[1:]
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0].rstrip() + "…"
    return title


def tool_names_of(result: Any) -> frozenset[str]:
    """Names a Cerebras result actually called. Mocks and missing fields are empty."""
    raw = getattr(result, "tool_names", None)
    if type(raw) not in (list, tuple, set, frozenset):
        return frozenset()
    return frozenset(str(name) for name in raw if str(name).strip())


def implied_title(user: str, assistant: str, *, tools_used: Any = ()) -> str | None:
    """Triage title for suggested or promised work the turn did not finish.

    A lookup that already ran (``fmp``, ``web_search``, ``hermes``, …) is the
    work. A future-tense sentence with no tool, or a request that outlives
    the reply, is a card.
    """
    said = " ".join((user or "").split())
    spoken = " ".join((assistant or "").split())
    if not said and not spoken:
        return None
    if _is_smalltalk(said) and not _COMMIT.search(spoken):
        return None
    if _EMPTY_COMMIT.search(spoken) and not _ASK.search(said):
        return None
    if type(tools_used) in (list, tuple, set, frozenset):
        used = frozenset(str(n) for n in tools_used if str(n).strip())
    else:
        used = frozenset()
    did = bool(used & _DONE_TOOLS)
    residual = bool(_RESIDUAL.search(spoken))
    commit = bool(_COMMIT.search(spoken))
    ask = bool(_ASK.search(said))
    if did and not residual:
        return None
    if not commit and not ask and not residual:
        return None
    if ask and said:
        source = said
    else:
        source = spoken or said
    title = _imperative(source)
    return title or None


def kanban_would_cover_figure(*, live: bool, current_kind: str, requested: str) -> bool:
    """A live HoloViews page keeps the video. Kanban stays on the dashboard."""
    req = (requested or "").strip().lower()
    cur = (current_kind or "").strip().lower()
    return req == "kanban" and bool(live) and bool(cur) and cur != "kanban"


def pin_orchestrator_text(text: str) -> str:
    """Point ``orchestrator_profile`` at Hicks when it is still the old default.

    A hand-set orchestrator other than ``grok`` is left alone.
    """

    def repl(match: re.Match[str]) -> str:
        raw = match.group(2).strip().strip("'\"")
        if raw in {"", "grok", "hicks"}:
            return f"{match.group(1)}hicks"
        return match.group(0)

    return _ORCH_LINE.sub(repl, text, count=1)


def _active(rows: list[Any]) -> list[Any]:
    out = []
    for task in rows:
        status = str(getattr(task, "status", "") or "")
        if status in ACTIVE:
            out.append(task)
    return out


def _load_active() -> list[Any]:
    from contextlib import closing

    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with closing(kbc.connect()) as conn:
        return _active(list(kanban_db.list_tasks(conn, limit=80)))


def board_aside() -> str:
    """Per-turn note for Ripley. Empty when nothing is in flight.

    Not part of the cached Hermes prefix — the voice loop rebuilds its
    system text every turn, the same way a steer does.
    """
    try:
        active = _load_active()
    except Exception:
        log.debug("hicks board read failed", exc_info=True)
        return ""
    if not active:
        return ""
    lines = [
        "Board (background, still moving; do not read this list aloud "
        "unless they ask; do not say these are finished):"
    ]
    for task in active[:6]:
        title = " ".join(str(getattr(task, "title", "") or "").split())[:80]
        status = str(getattr(task, "status", "") or "")
        lines.append(f"- {status} · {title}")
    lines.append(
        "You may change topic. The work continues in the background. "
        "A HoloViews figure takes the video over the kanban view; the "
        "dashboard board still shows every lane."
    )
    if len(active) >= 2:
        lines.append(
            "Several lanes are in flight. You may call bishop_suggest once "
            "for a suggestion, then stay with the topic. recent_thoughts or "
            "web_search may inform an aside about the work or how it should end."
        )
    return "\n".join(lines)


def _find_open(conn: Any, title: str) -> str | None:
    from hermes_cli import kanban_db

    want = _norm(title)
    if not want:
        return None
    for task in kanban_db.list_tasks(conn, limit=200):
        if str(getattr(task, "status", "") or "") not in ACTIVE:
            continue
        if _norm(str(getattr(task, "title", "") or "")) == want:
            return str(task.id)
    return None


def file_implied(
    *,
    session_id: str,
    title: str,
    user: str,
    assistant: str,
) -> dict[str, Any]:
    """Create one triage card, or return the open card with the same title."""
    from contextlib import closing

    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    heading = (title or "").strip()
    if not heading:
        return {"ok": False, "error": "title required", "created": False}
    try:
        from hsengine.engine.session_history import hermes_session_id

        sid = hermes_session_id(session_id) if (session_id or "").strip() else None
    except Exception:
        sid = None
    body = (
        "From the live call. Hicks filed this because it was suggested or "
        "promised and not finished on the turn.\n\n"
        f"Room: {' '.join((user or '').split())[:500]}\n"
        f"Spoken: {' '.join((assistant or '').split())[:500]}\n\n"
        "Move it across the board. Put blockers on the card. Leaf work "
        "defaults to grok. Bishop and Vasquez stay on the live call."
    )
    kanban_db.init_db()
    with closing(kbc.connect()) as conn:
        existing = _find_open(conn, heading)
        if existing:
            return {
                "ok": True,
                "id": existing,
                "title": heading,
                "status": "triage",
                "created": False,
            }
        tid = kanban_db.create_task(
            conn,
            title=heading,
            body=body,
            created_by="hicks",
            triage=True,
            session_id=sid,
        )
    try:
        from hsengine.engine.webrtc_kanban import refresh_view

        refresh_view()
    except Exception:
        log.debug("hicks board refresh skipped", exc_info=True)
    log.info("hicks filed %s %r", tid, heading[:80])
    return {"ok": True, "id": tid, "title": heading, "status": "triage", "created": True}


def note_turn(
    *,
    session_id: str,
    user: str,
    assistant: str,
    tools_used: Any = (),
) -> dict[str, Any]:
    """File this turn's implied work, if any, and steer the next spoken turn once."""
    title = implied_title(user, assistant, tools_used=tools_used)
    if not title:
        return {"ok": True, "created": False}
    try:
        filed = file_implied(
            session_id=session_id, title=title, user=user, assistant=assistant
        )
    except Exception:
        log.warning("hicks ingress failed", exc_info=True)
        return {"ok": False, "created": False, "error": "ingress failed"}
    if filed.get("created"):
        try:
            from hsengine.engine.primary_hermes import offer_steer

            offer_steer(_FILED_STEER)
        except Exception:
            log.debug("hicks steer skipped", exc_info=True)
    return filed


def suggestion_busy() -> bool:
    return bool(_SUGGESTING.get())


def suggestion_enter() -> Token[bool]:
    return _SUGGESTING.set(True)


def suggestion_exit(token: Token[bool]) -> None:
    _SUGGESTING.reset(token)


def pin_orchestrator_file(path: Any) -> bool:
    """Rewrite one config line. Returns True when the text changed."""
    from pathlib import Path

    file = Path(path)
    if not file.is_file():
        return False
    text = file.read_text(encoding="utf-8")
    updated = pin_orchestrator_text(text)
    if updated == text:
        return False
    tmp = file.with_suffix(file.suffix + ".hicks-tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(file)
    return True
