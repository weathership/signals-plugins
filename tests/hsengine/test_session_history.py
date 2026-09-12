"""AgentRTC turns land in Hermes SessionDB under source=agent-rtc."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

from hermes_state import SessionDB
from hsengine.engine import session_history
from hsengine.engine.webrtc_moshi import TurnTaker


def test_open_record_close_roundtrip(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        sid = session_history.open_session("deadbeefcafe", model="qwen-3.8-27b")
        assert sid == "agent-rtc-deadbeefcafe"
        session_history.record_turn("deadbeefcafe", user="how's it going")
        session_history.record_turn("deadbeefcafe", assistant="Discover is the conversation today.")
        session_history.close_session("deadbeefcafe")
        row = db.get_session(sid)
        assert row["source"] == "agent-rtc"
        assert row["display_name"] == "AgentRTC"
        assert row["ended_at"]
        msgs = db.get_messages(sid)
        roles = [m["role"] for m in msgs]
        texts = [m["content"] for m in msgs]
        assert roles == ["user", "assistant"]
        assert texts[0] == "how's it going"
        assert "Discover" in texts[1]
        recent = session_history.recent_turns("deadbeefcafe", limit=8)
        assert [t["role"] for t in recent] == ["user", "assistant"]
        assert recent[0]["text"] == "how's it going"
    finally:
        session_history.configure(None)
        db.close()


def test_record_turn_does_not_raise_when_store_fails():
    session_history.configure(MagicMock())
    try:
        session_history._db.append_message.side_effect = RuntimeError("locked")
        session_history.record_turn("x", user="hello")
    finally:
        session_history.configure(None)


def test_turn_taker_writes_user_then_assistant():
    recorded: list[tuple] = []
    remembered: list[tuple] = []
    complete_kw: list[dict] = []

    def _record(webrtc_id, **kwargs):
        recorded.append((webrtc_id, kwargs))

    def _remember(webrtc_id, **kwargs):
        remembered.append((webrtc_id, kwargs))

    result = MagicMock()
    result.text = "hello back"
    result.model = "qwen-3.8-27b"

    def _complete(**kwargs):
        complete_kw.append(kwargs)
        return result

    async def _run():
        taker = TurnTaker(asyncio.get_running_loop(), quiet_s=0.02, session_id="abc123")
        with patch("hsengine.engine.session_history.record_turn", _record):
            with patch("hsengine.engine.session_history.remember_turn", _remember):
                with patch("hsengine.engine.interactive.complete_cerebras", _complete):
                    taker.on_word("hello")
                    taker.on_word("there")
                    await asyncio.sleep(0.08)

    asyncio.run(_run())
    assert recorded[0] == ("abc123", {"user": "hello there"})
    assert recorded[1][0] == "abc123"
    assert recorded[1][1]["assistant"] == "hello back"
    assert complete_kw[0]["session_id"] == "abc123"
    assert remembered == [("abc123", {"user": "hello there", "assistant": "hello back"})]


def test_turn_taker_drains_pending_steer_into_the_spoken_system():
    complete_kw: list[dict] = []
    result = MagicMock()
    result.text = "hello back"
    result.model = "qwen-3.8-27b"

    async def _run():
        taker = TurnTaker(asyncio.get_running_loop(), quiet_s=0.02, session_id="abc123")
        taker.pending_steer = "float the Lilly gap, don't clock the call"
        with patch("hsengine.engine.session_history.record_turn", lambda *a, **k: None):
            with patch("hsengine.engine.session_history.remember_turn", lambda *a, **k: None):
                with patch(
                    "hsengine.engine.interactive.complete_cerebras",
                    lambda **k: complete_kw.append(k) or result,
                ):
                    taker.on_word("hello")
                    taker.on_word("there")
                    await asyncio.sleep(0.08)

    asyncio.run(_run())
    assert complete_kw
    system = complete_kw[0]["system_prompt"]
    assert "float the Lilly gap" in system
    assert "do not mention this note" in system.lower()


def test_prompt_history_drops_current_user_and_reports_overflow(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.open_session("call1")
        for i in range(20):
            session_history.record_turn("call1", user=f"topic-{i} unique-{i}")
            session_history.record_turn("call1", assistant=f"ack-{i}")
        session_history.record_turn("call1", user="later question")
        window, meta = session_history.prompt_history(
            "call1", current_user="later question", limit=8
        )
        assert meta["older_count"] > 0
        assert meta["hermes_session_id"] == "agent-rtc-call1"
        assert len(window) <= 8
        joined = " ".join(m["content"] for m in window)
        assert "unique-0" not in joined
        assert "later question" not in joined
        assert window[-1]["role"] == "assistant"
        stored = db.get_messages("agent-rtc-call1")
        assert any("unique-0" in (m.get("content") or "") for m in stored)
        assert any("later question" in (m.get("content") or "") for m in stored)
    finally:
        session_history.configure(None)
        db.close()


def test_remember_turn_syncs_memory_manager(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    mgr = MagicMock()
    session_history.configure_memory(mgr)
    try:
        session_history.open_session("mem1")
        session_history.record_turn("mem1", user="remember the lattice")
        session_history.record_turn("mem1", assistant="the lattice is the hub")
        session_history.remember_turn(
            "mem1", user="remember the lattice", assistant="the lattice is the hub"
        )
        mgr.sync_all.assert_called_once()
        args, kwargs = mgr.sync_all.call_args
        assert args[0] == "remember the lattice"
        assert args[1] == "the lattice is the hub"
        assert kwargs["session_id"] == "agent-rtc-mem1"
        mgr.queue_prefetch_all.assert_called_once()
    finally:
        session_history.configure_memory(None)
        session_history.configure(None)
        db.close()


def test_overflow_turns_are_searchable_in_this_session(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.open_session("search1")
        for i in range(24):
            session_history.record_turn("search1", user=f"alpha-{i} needle-{i}")
            session_history.record_turn("search1", assistant=f"ack-{i}")
        window, meta = session_history.prompt_history("search1", limit=8)
        assert meta["older_count"] > 0
        assert "needle-0" not in " ".join(m["content"] for m in window)
        hits = session_history.search_this_call("search1", "needle-0")
        assert hits
        assert hits[0]["role"] == "user"
        assert "needle-0" in hits[0]["text"]
        from tools.session_search_tool import session_search

        raw_read = session_search(session_id="agent-rtc-search1", db=db)
        data = json.loads(raw_read)
        texts = [m.get("content") or "" for m in data.get("messages") or []]
        assert any("needle-0" in t for t in texts)
    finally:
        session_history.configure(None)
        db.close()
