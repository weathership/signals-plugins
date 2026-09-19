"""Grok-review the last AgentRTC session into a scratch zettel.

Chat slash ``/rtc-review`` (optional focus / ``--about`` / ``--session``).
The zettel lands under ``wiki/scratch/`` so the next Connect picks it up
as USER-PROVIDED entropy for about 12 minutes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .capture import capture

SOURCE = "agent-rtc"
_MAX_MESSAGES = 80
_TURN_CLIP = 800
_TRANSCRIPT_CHARS = 24_000
_FLAG = re.compile(r"--(about|session)(?:=|\s+)(\S+)", re.I)

REVIEW_SYSTEM = (
    "You are reviewing an AgentRTC voice session (Ripley spoken, Bishop invent, "
    "Vasquez viz; the spoken model is Qwen). Write a scratch zettel for the NEXT "
    "Connect. Start with a markdown H1 title. Name the stuck distinction, what "
    "was circling, and one next move. Write as a note the operator just filed, "
    "not interior monologue. Do not greet. Do not dump the transcript. Banned "
    "frames: sitting-with, turning-over, returning-to-a-thread, keeps-surfacing, "
    "good-to-be-back. This zettel is USER-PROVIDED opening entropy within ~12 minutes."
)


def parse_review_args(raw: str) -> dict[str, str]:
    about = session = ""
    rest = raw or ""
    for m in list(_FLAG.finditer(rest)):
        key = m.group(1).lower()
        val = m.group(2).strip().strip("\"'")
        if key == "about":
            about = val
        else:
            session = val
    rest = _FLAG.sub(" ", rest)
    return {"focus": " ".join(rest.split()), "about": about, "session": session}


def last_agent_rtc_session(
    *,
    db: Any | None = None,
    session_id: str = "",
) -> dict[str, Any] | None:
    owned = False
    if db is None:
        from hermes_state import SessionDB

        db = SessionDB()
        owned = True
    try:
        sid = (session_id or "").strip()
        if sid:
            row = db.get_session(sid)
            if isinstance(row, dict) and str(row.get("source") or "") == SOURCE:
                return row
            return None
        rows = db.list_sessions_rich(
            source=SOURCE,
            limit=1,
            order_by_last_active=True,
            compact_rows=True,
            include_archived=False,
        )
        if rows and isinstance(rows[0], dict):
            return rows[0]
        return None
    finally:
        if owned:
            try:
                db.close()
            except Exception:
                pass


def format_transcript(messages: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    total = 0
    rows = list(messages or [])
    if len(rows) > _MAX_MESSAGES:
        rows = rows[-_MAX_MESSAGES:]
    for m in rows:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        text = " ".join(str(m.get("content") or "").split())
        if not text:
            continue
        if len(text) > _TURN_CLIP:
            text = text[: _TURN_CLIP - 1].rstrip() + "…"
        line = f"{role}: {text}"
        if total + len(line) + 1 > _TRANSCRIPT_CHARS:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _consult(*, question: str, context: str, system: str) -> dict[str, Any]:
    try:
        from hsengine.engine.grok_consult import consult
    except ImportError:
        return {"ok": False, "error": "signals-hsengine is not installed"}
    return consult(question=question, context=context, system=system)


def review_session(
    *,
    focus: str = "",
    session_id: str = "",
    about: str = "",
    db: Any | None = None,
    hermes_home: Path | None = None,
    consult_fn: Any | None = None,
) -> dict[str, Any]:
    """Review the last (or named) agent-rtc session; write a scratch zettel."""
    owned = False
    if db is None:
        from hermes_state import SessionDB

        db = SessionDB()
        owned = True
    try:
        row = last_agent_rtc_session(db=db, session_id=session_id)
        if not row:
            return {
                "ok": False,
                "error": "no agent-rtc session to review (Connect first, or pass --session)",
            }
        sid = str(row.get("id") or "")
        messages = db.get_messages(sid) if sid else []
        transcript = format_transcript(messages)
        if not transcript:
            return {"ok": False, "error": f"session {sid} has no user/assistant turns"}
        question = "Review this AgentRTC transcript into a scratch zettel."
        if focus.strip():
            question += f" Focus: {focus.strip()}"
        fn = consult_fn or _consult
        grok = fn(question=question, context=transcript, system=REVIEW_SYSTEM)
        if not grok.get("ok"):
            return {
                "ok": False,
                "error": str(grok.get("error") or "Grok review failed"),
                "session_id": sid,
            }
        body = str(grok.get("text") or "").strip()
        if not body.startswith("#"):
            body = f"# Grok lift\n\n{body}"
        home = Path(hermes_home) if hermes_home is not None else None
        if home is None:
            from hermes_constants import get_hermes_home

            home = get_hermes_home()
        vault = home / "wiki"
        out = capture(body=body, vault=vault, about=about)
        out["session_id"] = sid
        out["turns"] = transcript.count("\n") + 1 if transcript else 0
        out["model"] = grok.get("model") or ""
        out["provider"] = grok.get("provider") or ""
        return out
    finally:
        if owned:
            try:
                db.close()
            except Exception:
                pass


def format_slash_result(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        err = str(data.get("error") or "unknown error")
        return f"  /rtc-review failed: {err}"
    sid = data.get("session_id") or ""
    rel = data.get("relpath") or ""
    model = data.get("model") or "grok"
    turns = data.get("turns") or 0
    return (
        f"  Grok reviewed {sid} ({turns} turns, {model})\n"
        f"  Zettel {rel}\n"
        f"  {data.get('resource')}\n"
        f"  Next Connect within ~12 minutes picks this up as USER-PROVIDED."
    )


def slash(raw_args: str) -> str:
    args = parse_review_args(raw_args or "")
    return format_slash_result(
        review_session(
            focus=args["focus"],
            session_id=args["session"],
            about=args["about"],
        )
    )


def tool_result(args: dict[str, Any] | None = None) -> str:
    import json

    args = args or {}
    data = review_session(
        focus=str(args.get("focus") or ""),
        session_id=str(args.get("session_id") or args.get("session") or ""),
        about=str(args.get("about") or ""),
    )
    payload = dict(data)
    payload["success"] = bool(data.get("ok"))
    return json.dumps(payload, ensure_ascii=False)
