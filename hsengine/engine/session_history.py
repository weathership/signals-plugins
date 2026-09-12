"""AgentRTC turns in Hermes session history (the same SessionDB the dashboard lists).

One Hermes session per WebRTC Connect, source ``agent-rtc``. Persistence must
never deny a call: a store failure is logged and the voice path continues.

The live Cerebras prompt only holds a window of recent turns. The full
transcript stays in SessionDB (session_search) and is synced into Hermes
memory providers as each pair completes, so overflow is recall — not loss.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger("hsengine.engine.session_history")

SOURCE = "agent-rtc"
DISPLAY_NAME = "AgentRTC"

# Messages kept in the spoken Cerebras prompt. The rest remain in SessionDB.
VOICE_WINDOW = 64
# Tool payload clip; the prompt window may keep a bit more of each turn.
_TURN_CLIP = 800
_PROMPT_CLIP = 1500

_mu = threading.Lock()
_db: Any = None

_mem_mu = threading.Lock()
_mem_mgr: Any = None
_mem_tried = False
_mem_sid = ""


def hermes_session_id(webrtc_id: str) -> str:
    return f"agent-rtc-{webrtc_id}"


def live_webrtc_id() -> str:
    """The in-process AgentRTC Connect id, or empty when no peer is up."""
    try:
        from hsengine.engine.webrtc_session import HUB

        pcs = getattr(HUB, "_pcs", None) or {}
        return str(next(iter(pcs), "") or "")
    except Exception:
        return ""


def configure(db: Any | None) -> None:
    """Tests inject a SessionDB; production leaves this None (lazy default store)."""
    global _db
    with _mu:
        _db = db


def configure_memory(mgr: Any | None) -> None:
    """Tests inject a MemoryManager; ``None`` disables provider load for this process."""
    global _mem_mgr, _mem_tried, _mem_sid
    with _mem_mu:
        _mem_mgr = mgr
        _mem_tried = True
        _mem_sid = ""


def reset_memory() -> None:
    """Tests: allow the next ``_memory_manager`` call to load providers again."""
    global _mem_mgr, _mem_tried, _mem_sid
    with _mem_mu:
        _mem_mgr = None
        _mem_tried = False
        _mem_sid = ""


def _store() -> Any | None:
    global _db
    with _mu:
        if _db is not None:
            return _db
        try:
            from hermes_state import SessionDB

            _db = SessionDB()
            return _db
        except Exception:
            log.warning("agent-rtc session store unavailable", exc_info=True)
            return None


def _model() -> str:
    try:
        from hsengine.config import get_str

        return get_str("hermes.engine.webrtc.interactive.cerebras_model") or "qwen-3.8-27b"
    except Exception:
        return "qwen-3.8-27b"


def open_session(webrtc_id: str, *, model: str = "") -> str | None:
    """Create the Hermes session row for this Connect. Returns the Hermes id."""
    if not webrtc_id:
        return None
    sid = hermes_session_id(webrtc_id)
    db = _store()
    if db is None:
        return None
    try:
        db.create_session(
            sid,
            SOURCE,
            model=model or _model(),
            display_name=DISPLAY_NAME,
            session_key=webrtc_id,
        )
        log.info("agent-rtc history session %s", sid)
        return sid
    except Exception:
        log.warning("agent-rtc history open failed", exc_info=True)
        return None


def record_turn(
    webrtc_id: str,
    *,
    user: str = "",
    assistant: str = "",
    model: str = "",
) -> None:
    if not webrtc_id:
        return
    sid = hermes_session_id(webrtc_id)
    user_text = (user or "").strip()
    asst_text = (assistant or "").strip()
    if not user_text and not asst_text:
        return
    db = _store()
    if db is None:
        return
    try:
        db.ensure_session(sid, SOURCE, model=model or _model(), display_name=DISPLAY_NAME)
        if user_text:
            db.append_message(sid, "user", user_text)
        if asst_text:
            db.append_message(sid, "assistant", asst_text, finish_reason="stop")
    except Exception:
        log.warning("agent-rtc history record failed", exc_info=True)


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    if len(t) > n:
        return t[: n - 1].rstrip() + "…"
    return t


def _turns_from_rows(rows: Any, *, clip: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in rows or []:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        text = _clip(str(m.get("content") or ""), clip)
        if not text:
            continue
        out.append({"role": role, "text": text})
    return out


def recent_turns(webrtc_id: str, *, limit: int = 32) -> list[dict[str, str]]:
    """Last turns on this Connect, chronological, clipped for a tool payload."""
    if not webrtc_id:
        return []
    db = _store()
    if db is None:
        return []
    try:
        n = max(1, min(int(limit or 32), VOICE_WINDOW))
        rows = db.get_messages(hermes_session_id(webrtc_id), latest=True, limit=n)
    except Exception:
        log.warning("agent-rtc history read failed", exc_info=True)
        return []
    return _turns_from_rows(rows, clip=_TURN_CLIP)


def message_count(webrtc_id: str) -> int:
    if not webrtc_id:
        return 0
    db = _store()
    if db is None:
        return 0
    try:
        return int(db.message_count(hermes_session_id(webrtc_id)) or 0)
    except Exception:
        log.warning("agent-rtc history count failed", exc_info=True)
        return 0


def window_meta(webrtc_id: str, *, shown: int) -> dict[str, Any]:
    total = message_count(webrtc_id)
    shown_n = max(0, int(shown or 0))
    return {
        "hermes_session_id": hermes_session_id(webrtc_id) if webrtc_id else "",
        "older_count": max(0, total - shown_n),
        "total": total,
        "shown": shown_n,
    }


def prompt_history(
    webrtc_id: str,
    *,
    current_user: str = "",
    limit: int = VOICE_WINDOW,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """OpenAI-style prior turns for the spoken prompt, plus overflow stats.

    The current user utterance is excluded when it was already ``record_turn``'d
    so it is not duplicated as the last history message plus the new user turn.
    """
    if not webrtc_id:
        return [], window_meta("", shown=0)
    db = _store()
    if db is None:
        return [], window_meta(webrtc_id, shown=0)
    try:
        n = max(1, min(int(limit or VOICE_WINDOW), VOICE_WINDOW))
        rows = db.get_messages(hermes_session_id(webrtc_id), latest=True, limit=n + 4)
    except Exception:
        log.warning("agent-rtc prompt history read failed", exc_info=True)
        return [], window_meta(webrtc_id, shown=0)
    turns = _turns_from_rows(rows, clip=_PROMPT_CLIP)
    dropped_current = False
    cur = (current_user or "").strip()
    if cur and turns and turns[-1]["role"] == "user" and turns[-1]["text"] == _clip(cur, _PROMPT_CLIP):
        turns = turns[:-1]
        dropped_current = True
    if len(turns) > n:
        turns = turns[-n:]
    messages = [{"role": t["role"], "content": t["text"]} for t in turns]
    meta = window_meta(webrtc_id, shown=len(messages) + (1 if dropped_current else 0))
    if dropped_current:
        # current user is the new prompt, not "shown" history
        meta["older_count"] = max(0, meta["total"] - len(messages) - 1)
        meta["shown"] = len(messages)
    return messages, meta


def search_this_call(webrtc_id: str, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Substring search over this Connect's full transcript (including overflow)."""
    q = (query or "").strip().lower()
    if not webrtc_id or not q:
        return []
    db = _store()
    if db is None:
        return []
    try:
        n = max(1, min(int(limit or 8), 16))
        rows = db.get_messages(hermes_session_id(webrtc_id))
    except Exception:
        log.warning("agent-rtc this-call search failed", exc_info=True)
        return []
    hits: list[dict[str, Any]] = []
    for m in rows or []:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()
        if not text or q not in text.lower():
            continue
        hits.append({"id": m.get("id"), "role": role, "text": _clip(text, 400)})
        if len(hits) >= n:
            break
    return hits


def transcript_messages(webrtc_id: str) -> list[dict[str, str]]:
    """Full user/assistant transcript for Hermes proper (no voice-window cap)."""
    if not webrtc_id:
        return []
    db = _store()
    if db is None:
        return []
    try:
        rows = db.get_messages_as_conversation(
            hermes_session_id(webrtc_id), repair_alternation=True
        )
    except Exception:
        log.warning("agent-rtc transcript read failed", exc_info=True)
        return []
    out: list[dict[str, str]] = []
    for m in rows or []:
        role = str(m.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()
        if text:
            out.append({"role": role, "content": text})
    return out


def _memory_manager(session_id: str) -> Any | None:
    """Process-wide MemoryManager: configured provider, else signals-memory when installed."""
    global _mem_mgr, _mem_tried, _mem_sid
    with _mem_mu:
        if not _mem_tried:
            _mem_tried = True
            try:
                from agent.memory_manager import MemoryManager
                from hermes_cli.config import cfg_get, load_config
                from hermes_constants import get_hermes_home
                from plugins.memory import load_memory_provider

                name = str(cfg_get(load_config(), "memory", "provider") or "").strip()
                provider = load_memory_provider(name) if name else None
                if not name:
                    fallback = load_memory_provider("signals-memory")
                    if fallback is not None and fallback.is_available():
                        provider = fallback
                if provider is not None and provider.is_available():
                    mgr = MemoryManager()
                    mgr.add_provider(provider)
                    mgr.initialize_all(
                        session_id=session_id,
                        platform="agent-rtc",
                        hermes_home=str(get_hermes_home()),
                        agent_context="primary",
                    )
                    _mem_mgr = mgr
                    _mem_sid = session_id
            except Exception:
                log.warning("agent-rtc memory manager unavailable", exc_info=True)
                _mem_mgr = None
        mgr = _mem_mgr
        sid = _mem_sid
    if mgr is None or not session_id:
        return mgr
    if sid and sid != session_id:
        try:
            mgr.on_session_switch(
                session_id, parent_session_id=sid, reset=True, reason="agent-rtc"
            )
        except Exception:
            log.warning("agent-rtc memory session switch failed", exc_info=True)
    if sid != session_id:
        with _mem_mu:
            _mem_sid = session_id
    return mgr


def remember_turn(webrtc_id: str, *, user: str, assistant: str) -> None:
    """Mirror a completed voice pair into Hermes memory providers. Never raises."""
    user_text = (user or "").strip()
    asst_text = (assistant or "").strip()
    if not webrtc_id or not user_text or not asst_text:
        return
    sid = hermes_session_id(webrtc_id)
    try:
        mgr = _memory_manager(sid)
        if mgr is None:
            return
        mgr.sync_all(user_text, asst_text, session_id=sid)
        mgr.queue_prefetch_all(user_text, session_id=sid)
    except Exception:
        log.warning("agent-rtc memory sync failed", exc_info=True)


def recalled_memory(webrtc_id: str, query: str) -> str:
    """Prefetch through the memory subsystem (signals-memory hybrid when installed).

    Empty or trivial *query* still returns zettels filed in the last few minutes
    so the Connect invent pass can see them.
    """
    q = (query or "").strip()
    trivial = not q
    try:
        from agent.memory_provider import is_trivial_prompt

        trivial = trivial or is_trivial_prompt(q)
    except Exception:
        pass
    if trivial:
        try:
            from hsengine.engine.recall import format_recall, recall_pack

            return format_recall(recall_pack(query="", webrtc_id=webrtc_id))
        except Exception:
            log.warning("agent-rtc fresh-zettel recall failed", exc_info=True)
            return ""
    sid = hermes_session_id(webrtc_id) if webrtc_id else ""
    try:
        mgr = _memory_manager(sid or "agent-rtc")
        if mgr is not None:
            extra = (mgr.prefetch_all(q, session_id=sid) or "").strip()
            if extra:
                return extra
    except Exception:
        log.warning("agent-rtc memory prefetch failed", exc_info=True)
    try:
        from hsengine.engine.recall import format_recall, recall_pack

        return format_recall(recall_pack(query=q, webrtc_id=webrtc_id))
    except Exception:
        log.warning("agent-rtc temporal recall failed", exc_info=True)
        return ""


def close_session(webrtc_id: str, reason: str = "hangup") -> None:
    if not webrtc_id:
        return
    db = _store()
    if db is None:
        return
    try:
        db.end_session(hermes_session_id(webrtc_id), reason)
    except Exception:
        log.warning("agent-rtc history close failed", exc_info=True)
