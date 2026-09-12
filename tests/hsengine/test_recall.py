"""AgentRTC recall ranks recent conversations and local citations first."""
from __future__ import annotations

import os
import time

from hermes_state import SessionDB
from hsengine.engine import recall, session_history


def test_content_tokens_drop_filler_keep_nautilus():
    q = "Do you still have access to the notes we made on Nautilus?"
    assert recall.content_tokens(q) == ["nautilus"]
    assert recall.focus_query(q) == "nautilus"
    assert recall.content_tokens("yeah okay") == []


def test_recency_weight_is_monotonic():
    assert recall.recency_weight(0) > recall.recency_weight(18)
    assert recall.recency_weight(18) > recall.recency_weight(72)
    assert recall.recency_weight(1) > 0.5


def test_recent_session_outranks_older_same_keyword(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        now = time.time()
        old_id = session_history.open_session("oldtalk")
        new_id = session_history.open_session("newtalk")
        session_history.record_turn("oldtalk", user="Nautilus air-gap FSM")
        session_history.record_turn("oldtalk", assistant="got the old brief")
        session_history.record_turn("newtalk", user="Nautilus Brier ledger")
        session_history.record_turn("newtalk", assistant="filed the new note")
        def _stamp(conn):
            conn.execute(
                "UPDATE sessions SET started_at = ? WHERE id = ?",
                (now - 10 * 86400, old_id),
            )
            conn.execute(
                "UPDATE sessions SET started_at = ? WHERE id = ?",
                (now - 2 * 3600, new_id),
            )

        db._execute_write(_stamp)
        pack = recall.recall_pack(
            query="Do you still have the Nautilus notes?",
            webrtc_id="live",
            hermes_home=tmp_path / "empty-home",
            db=db,
            now=now,
        )
        ids = [c["session_id"] for c in pack["conversations"]]
        assert new_id in ids
        assert ids[0] == new_id
        assert "agent-rtc-live" not in ids
    finally:
        session_history.configure(None)
        db.close()


def test_wiki_and_memory_citations_match_query(tmp_path):
    home = tmp_path / ".hermes"
    wiki = home / "wiki" / "entities"
    wiki.mkdir(parents=True)
    (wiki / "nautilus.md").write_text(
        "---\ntitle: Nautilus\nupdated: 2026-09-12\n---\n\n"
        "Air-gap FSM with state-aware probes and a Brier ledger.\n",
        encoding="utf-8",
    )
    (home / "wiki" / "unrelated.md").write_text("# Other\nNo match here.\n", encoding="utf-8")
    (home / "wiki" / "log.md").write_text(
        "## [2026-09-12] ingest | Nautilus\n- Created: entities/nautilus.md\n",
        encoding="utf-8",
    )
    mem = home / "memories"
    mem.mkdir()
    (mem / "MEMORY.md").write_text(
        "Unrelated preamble.\n§\nKey page wiki/entities/nautilus.md — Nautilus air-gap probes.\n",
        encoding="utf-8",
    )
    now = time.time()
    class _NoSessions:
        def search_messages(self, **_k):
            return []

    pack = recall.recall_pack(
        query="Nautilus notes",
        webrtc_id="",
        hermes_home=home,
        db=_NoSessions(),
        now=now,
    )
    paths = [c["path"] for c in pack["citations"]]
    assert paths[0] == "wiki/entities/nautilus.md"
    assert "memories/MEMORY.md" in paths
    assert all("unrelated" not in p.lower() for p in paths)
    text = recall.format_recall(pack)
    assert "Nautilus" in text
    assert "invent" in text.lower()
    assert "wiki/entities/nautilus.md" in text


def test_format_recall_empty_when_no_hits():
    assert recall.format_recall({"conversations": [], "citations": []}) == ""
    assert recall.format_recall(None) == ""


def test_fresh_zettel_within_minutes_not_hours(tmp_path):
    home = tmp_path / ".hermes"
    scratch = home / "wiki" / "scratch" / "2026-09-12"
    scratch.mkdir(parents=True)
    fresh = scratch / "195104_epistemic.md"
    stale = scratch / "080000_old.md"
    fresh.write_text("# Epistemic acquaintance\nJust filed.\n", encoding="utf-8")
    stale.write_text("# Old note\nYesterday.\n", encoding="utf-8")
    now = time.time()
    os.utime(fresh, (now - 180, now - 180))
    os.utime(stale, (now - 3 * 3600, now - 3 * 3600))
    pack = recall.recall_pack(
        query="",
        webrtc_id="",
        hermes_home=home,
        db=type("NoDB", (), {"search_messages": staticmethod(lambda **k: [])})(),
        now=now,
    )
    paths = [c["path"] for c in pack["fresh"]]
    assert "wiki/scratch/2026-09-12/195104_epistemic.md" in paths
    assert all("080000_old" not in p for p in paths)
    text = recall.format_recall(pack)
    assert "Just filed" in text
    assert "epistemic" in text.lower()
    assert "rundown" in text.lower()


def test_fresh_zettel_absent_when_older_than_window(tmp_path):
    home = tmp_path / ".hermes"
    scratch = home / "wiki" / "scratch"
    scratch.mkdir(parents=True)
    note = scratch / "note.md"
    note.write_text("# Something\n", encoding="utf-8")
    now = time.time()
    os.utime(note, (now - 40 * 60, now - 40 * 60))
    pack = recall.recall_pack(query="", hermes_home=home, now=now, db=None)
    assert pack["fresh"] == []
    assert recall.format_recall(pack) == ""


def test_format_recall_puts_lattice_last():
    text = recall.format_recall(
        {
            "conversations": [{"session_id": "s", "source": "agent-rtc", "snippet": "filed nautilus", "age_hours": 2}],
            "citations": [{"path": "wiki/entities/nautilus.md", "title": "Nautilus", "snippet": "FSM"}],
            "lattice": [{"title": "arxiv", "snippet": "federated learning"}],
        }
    )
    assert text.index("Conversations:") < text.index("Citations:")
    assert text.index("Citations:") < text.index("Lattice")
    assert "invent" in text.lower()


def test_session_search_skips_current_question_to_reach_prior(tmp_path, monkeypatch):
    from hsengine.engine import ops

    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.open_session("prior")
        session_history.record_turn(
            "prior",
            user="Write a knowledge base note about Nautilus",
            assistant="Filed entities/nautilus.md",
        )
        session_history.open_session("now")
        session_history.record_turn(
            "now",
            user="Do you still have access to the notes we made on Nautilus?",
        )
        monkeypatch.setattr(session_history, "live_webrtc_id", lambda: "now")
        monkeypatch.setattr(
            "tools.session_search_tool.session_search",
            lambda **kw: __import__("json").dumps(
                {
                    "success": True,
                    "mode": "discover",
                    "count": 1,
                    "hits": [{"session_id": "agent-rtc-prior", "snippet": "Filed entities/nautilus.md"}],
                    "sort": kw.get("sort"),
                    "query": kw.get("query"),
                }
            ),
        )
        data = __import__("json").loads(ops.dispatch("session_search", {"query": "Nautilus"}))
        assert data.get("mode") != "this_call"
        assert data.get("sort") == "newest" or (data.get("hits") or [{}])[0]["session_id"] == "agent-rtc-prior"
        assert data.get("query") in (None, "nautilus", "Nautilus") or data.get("hits")
    finally:
        session_history.configure(None)
        db.close()
