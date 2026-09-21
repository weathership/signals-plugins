"""AgentRTC kanban view: HTML board on the compositor, same SQLite as the dashboard.

The gated dashboard /kanban tab needs a login cookie. Chromium on the
AgentRTC video talks to a loopback page that reads hermes_cli.kanban_db
directly. Mutations go through the same DB; the page is reloaded when
the live kind is kanban.
"""
from __future__ import annotations

import html
import json
import logging
import time
from contextlib import closing
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.kanban")

COLUMNS = (
    "triage",
    "todo",
    "ready",
    "running",
    "blocked",
    "review",
    "done",
)
_MOVEABLE = frozenset(c for c in COLUMNS if c != "running")
_AUTHOR = "ripley"


def _conn():
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    return kbc.connect()


def _task_row(t: Any) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title or "",
        "status": t.status,
        "assignee": t.assignee or "",
        "priority": int(t.priority or 0),
        "body": (t.body or "")[:400],
    }


def list_tasks(*, status: str = "", limit: int = 80) -> dict[str, Any]:
    from hermes_cli import kanban_db

    st = (status or "").strip() or None
    with closing(_conn()) as conn:
        rows = kanban_db.list_tasks(
            conn,
            status=st,
            limit=max(1, min(int(limit or 80), 200)),
        )
        return {
            "ok": True,
            "count": len(rows),
            "tasks": [_task_row(t) for t in rows],
        }


def show_task(task_id: str) -> dict[str, Any]:
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id required"}
    with closing(_conn()) as conn:
        t = kanban_db.get_task(conn, tid)
        if t is None:
            return {"ok": False, "error": f"task {tid!r} not found"}
        comments = [
            {"author": c.author, "body": c.body, "created_at": c.created_at}
            for c in kanban_db.list_comments(conn, tid)[-12:]
        ]
        return {"ok": True, "task": _task_row(t), "comments": comments}


def create_task(*, title: str, body: str = "", assignee: str = "") -> dict[str, Any]:
    from hermes_cli import kanban_db

    heading = (title or "").strip()
    if not heading:
        return {"ok": False, "error": "title required"}
    with closing(_conn()) as conn:
        tid = kanban_db.create_task(
            conn,
            title=heading,
            body=(body or "").strip() or None,
            assignee=(assignee or "").strip() or None,
            created_by=_AUTHOR,
            triage=True,
        )
    refresh_view()
    return {"ok": True, "id": tid, "title": heading, "status": "triage"}


def comment_task(task_id: str, body: str) -> dict[str, Any]:
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    text = (body or "").strip()
    if not tid or not text:
        return {"ok": False, "error": "task_id and body required"}
    with closing(_conn()) as conn:
        cid = kanban_db.add_comment(conn, tid, _AUTHOR, text)
    refresh_view()
    return {"ok": True, "comment_id": cid, "task_id": tid}


def complete_task(task_id: str, *, result: str = "") -> dict[str, Any]:
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id required"}
    with closing(_conn()) as conn:
        t = kanban_db.get_task(conn, tid)
        if t is None:
            return {"ok": False, "error": f"task {tid!r} not found"}
        if not _land_ready(conn, tid):
            return {"ok": False, "error": f"could not complete {tid}"}
        ok = kanban_db.complete_task(
            conn, tid, result=(result or "").strip() or None, fire_lifecycle_hook=False
        )
    if not ok:
        return {"ok": False, "error": f"could not complete {tid}"}
    refresh_view()
    return {"ok": True, "id": tid, "status": "done"}


def block_task(task_id: str, *, reason: str = "") -> dict[str, Any]:
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id required"}
    with closing(_conn()) as conn:
        t = kanban_db.get_task(conn, tid)
        if t is None:
            return {"ok": False, "error": f"task {tid!r} not found"}
        if t.status == "blocked":
            return {"ok": True, "id": tid, "status": "blocked"}
        note = (reason or "").strip() or None
        if t.status in ("running", "ready"):
            ok = kanban_db.block_task(conn, tid, reason=note)
        elif _land_ready(conn, tid):
            t = kanban_db.get_task(conn, tid)
            if t is not None and t.status in ("running", "ready"):
                ok = kanban_db.block_task(conn, tid, reason=note)
            else:
                ok = _set_status(conn, tid, "blocked")
        else:
            ok = _set_status(conn, tid, "blocked")
        if ok and note:
            try:
                kanban_db.add_comment(conn, tid, _AUTHOR, f"blocked: {note}")
            except Exception:
                log.debug("kanban block comment skipped", exc_info=True)
    if not ok:
        return {"ok": False, "error": f"could not block {tid}"}
    refresh_view()
    return {"ok": True, "id": tid, "status": "blocked"}


def unblock_task(task_id: str) -> dict[str, Any]:
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id required"}
    with closing(_conn()) as conn:
        ok = kanban_db.unblock_task(conn, tid)
    if not ok:
        return {"ok": False, "error": f"could not unblock {tid}"}
    refresh_view()
    return {"ok": True, "id": tid}


def link_tasks(parent_id: str, child_id: str) -> dict[str, Any]:
    from hermes_cli import kanban_db

    parent, child = (parent_id or "").strip(), (child_id or "").strip()
    if not parent or not child:
        return {"ok": False, "error": "parent_id and child_id required"}
    with closing(_conn()) as conn:
        kanban_db.link_tasks(conn, parent, child)
    refresh_view()
    return {"ok": True, "parent": parent, "child": child}


def move_task(task_id: str, status: str) -> dict[str, Any]:
    """Drag-drop analog: move a card to a compositor column (not running)."""
    from hermes_cli import kanban_db

    tid = (task_id or "").strip()
    st = (status or "").strip().lower()
    if not tid:
        return {"ok": False, "error": "task_id required"}
    if st not in _MOVEABLE:
        return {"ok": False, "error": f"status must be one of {sorted(_MOVEABLE)}"}
    with closing(_conn()) as conn:
        t = kanban_db.get_task(conn, tid)
        if t is None:
            return {"ok": False, "error": f"task {tid!r} not found"}
        if t.status == st:
            return {"ok": True, "id": tid, "status": st}
        if st == "done":
            if not _land_ready(conn, tid):
                return {"ok": False, "error": f"could not move {tid} to done"}
            ok = kanban_db.complete_task(conn, tid, fire_lifecycle_hook=False)
        elif st == "blocked":
            if not _land_ready(conn, tid):
                return {"ok": False, "error": f"could not move {tid} to blocked"}
            ok = kanban_db.block_task(conn, tid)
        elif st == "todo" and t.status == "triage":
            ok = kanban_db.specify_triage_task(conn, tid, author=_AUTHOR)
        elif st == "ready" and t.status in ("blocked", "scheduled"):
            ok = kanban_db.unblock_task(conn, tid)
        else:
            ok = _set_status(conn, tid, st)
    if not ok:
        return {"ok": False, "error": f"could not move {tid} to {st}"}
    refresh_view()
    landed = st
    with closing(_conn()) as conn:
        t = kanban_db.get_task(conn, tid)
        if t is not None:
            landed = t.status
    return {"ok": True, "id": tid, "status": landed}


def _land_ready(conn: Any, tid: str) -> bool:
    """complete/block only accept running|ready|blocked|review. Promote inbox cards."""
    from hermes_cli import kanban_db

    t = kanban_db.get_task(conn, tid)
    if t is None:
        return False
    if t.status in ("ready", "running", "blocked", "review"):
        return True
    if t.status == "triage":
        if not kanban_db.specify_triage_task(conn, tid, author=_AUTHOR):
            return False
        t = kanban_db.get_task(conn, tid)
        if t is None:
            return False
    if t.status == "todo":
        if not _set_status(conn, tid, "ready"):
            return False
        t = kanban_db.get_task(conn, tid)
    return t is not None and t.status in ("ready", "running", "blocked", "review")


def _set_status(conn: Any, tid: str, new_status: str) -> bool:
    """Direct column write for AgentRTC drag (same event as dashboard)."""
    from hermes_cli import kanban_db

    if new_status not in _MOVEABLE:
        return False
    if new_status == "ready" and not kanban_db._parents_satisfied(conn, tid):
        return False
    with kanban_db.write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET status = ?, claim_lock = NULL, "
            "claim_expires = NULL, worker_pid = NULL WHERE id = ?",
            (new_status, tid),
        )
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) "
            "VALUES (?, 'status', ?, ?)",
            (
                tid,
                json.dumps({"status": new_status, "source": "agentrtc"}),
                int(time.time()),
            ),
        )
    if new_status in {"done", "ready", "review"}:
        kanban_db.recompute_ready(conn)
    return True


def board_html() -> str:
    from hermes_cli import kanban_db

    grouped: dict[str, list[Any]] = {c: [] for c in COLUMNS}
    try:
        with closing(_conn()) as conn:
            for t in kanban_db.list_tasks(conn, limit=200):
                if t.status in grouped:
                    grouped[t.status].append(t)
    except Exception as e:
        log.warning("kanban board read failed: %s", e)
        err = html.escape(str(e)[:240])
        return (
            "<!doctype html><meta charset=utf-8>"
            f"<body data-kanban-board=1 style='background:#111;color:#eee;font:16px sans-serif;padding:24px'>"
            f"<p>Kanban unavailable: {err}</p></body>"
        )
    cols = []
    for status in COLUMNS:
        cards = []
        for t in grouped[status][:18]:
            who = html.escape(t.assignee or "")
            title = html.escape(t.title or t.id)
            tid = html.escape(t.id)
            cards.append(
                f"<article style='background:#1c1c24;border:1px solid #333;border-radius:6px;"
                f"padding:8px 10px;margin:0 0 8px;font-size:13px;line-height:1.35'>"
                f"<div style='font-weight:600'>{title}</div>"
                f"<div style='opacity:.65;font-size:11px;margin-top:4px'>{tid}"
                f"{(' · ' + who) if who else ''}</div></article>"
            )
        body = "".join(cards) or "<div style='opacity:.4;font-size:12px'>empty</div>"
        cols.append(
            f"<section style='min-width:160px;flex:1;background:#16161c;padding:10px;"
            f"border-radius:8px'><h2 style='margin:0 0 10px;font-size:12px;letter-spacing:.08em;"
            f"text-transform:uppercase;opacity:.8'>{status}</h2>{body}</section>"
        )
    inner = "".join(cols)
    return (
        "<!doctype html><meta charset=utf-8>"
        "<title>Kanban</title>"
        "<body data-kanban-board=1 style='margin:0;background:#0e0e12;color:#e8ecf4;"
        "font-family:ui-sans-serif,system-ui,sans-serif'>"
        "<header style='padding:10px 16px;font-size:14px;font-weight:600;"
        "background:#111118;border-bottom:1px solid #2a2a33'>Kanban</header>"
        f"<div style='display:flex;gap:10px;padding:12px;overflow:hidden;height:668px'>{inner}</div>"
        "</body>"
    )


def blocked_for_session(hermes_session_id: str) -> list[dict[str, Any]]:
    """Cards this AgentRTC session created that the dispatcher parked."""
    sid = (hermes_session_id or "").strip()
    if not sid:
        return []
    from hermes_cli import kanban_db

    out: list[dict[str, Any]] = []
    with closing(_conn()) as conn:
        for t in kanban_db.list_tasks(conn, status="blocked", session_id=sid, limit=40):
            err = str(getattr(t, "last_failure_error", None) or "").strip()
            if not err:
                row = conn.execute(
                    "SELECT payload FROM task_events WHERE task_id = ? "
                    "ORDER BY created_at DESC LIMIT 8",
                    (t.id,),
                ).fetchall()
                for (payload,) in row:
                    try:
                        data = json.loads(payload) if isinstance(payload, str) else payload
                    except Exception:
                        data = None
                    if isinstance(data, dict):
                        err = str(
                            data.get("error") or data.get("reason") or data.get("summary") or ""
                        ).strip()
                        if err:
                            break
            out.append(
                {
                    "id": t.id,
                    "title": t.title or t.id,
                    "assignee": t.assignee or "",
                    "error": err,
                }
            )
    return out


_BLOCKED_SIG: dict[str, str] = {}


def blocked_glance(webrtc_id: str, *, force: bool = False) -> str:
    """Spoken-loop glance: blocked lanes need dialog, not a silent park.

    The same blocked set is offered once until the signature changes.
    """
    from hsengine.engine import session_history

    wid = (webrtc_id or "").strip() or session_history.live_webrtc_id()
    if not wid:
        return ""
    cards = blocked_for_session(session_history.hermes_session_id(wid))
    if not cards:
        _BLOCKED_SIG.pop(wid, None)
        return ""
    sig = "|".join(f"{c['id']}:{c['error'][:80]}" for c in cards)
    if not force and _BLOCKED_SIG.get(wid) == sig:
        return ""
    _BLOCKED_SIG[wid] = sig
    lines = [
        "Kanban blocked — Hermes could not keep pursuing these lanes. "
        "Investigate with the person on the call (retry, reassign, or fix spawn):"
    ]
    for c in cards[:6]:
        err = c["error"].split(". On a system")[0].strip() or "blocked"
        who = c["assignee"] or "unassigned"
        lines.append(f"- {c['title']} ({who}): {err}")
    return "\n".join(lines)


def surface_blocked_to_call(*, webrtc_id: str = "") -> dict[str, Any]:
    """STEER Ripley when this call's cards were auto-blocked."""
    from hsengine.engine import session_history
    from hsengine.engine.primary_hermes import offer_steer

    glance = blocked_glance(webrtc_id)
    if not glance:
        return {"ok": True, "steered": 0}
    # First line is the steer; details stay in glance for Bishop.
    offer_steer(
        "The research lanes are blocked — workers could not start. "
        "Ask what they want: retry, reassign, or look at the spawn error."
    )
    return {"ok": True, "steered": 1, "glance": glance}


def refresh_view() -> None:
    try:
        from hsengine.engine import webrtc_program

        st = webrtc_program.PROGRAM.status()
        if st.get("kind") != "kanban" or not st.get("live"):
            return
        webrtc_program.show(kind="kanban", title=str(st.get("title") or "Kanban"), fade_s=0.2)
    except Exception:
        log.debug("kanban view refresh skipped", exc_info=True)
