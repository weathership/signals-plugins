"""Grok-review of the last AgentRTC session files a fresh scratch zettel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hermes_state import SessionDB
from hsengine.engine.recall import fresh_zettel_glance


def _load_review():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "plugins" / "signals-zettel" / "review.py"
    spec = importlib.util.spec_from_file_location("signals_zettel_review", path)
    assert spec is not None and spec.loader is not None
    # capture.py is a sibling; load the package-ish module by executing with
    # a fake parent so `from .capture import capture` works.
    pkg = Path(__file__).resolve().parents[1] / "plugins" / "signals-zettel"
    parent_name = "signals_zettel_review_pkg"
    import sys
    import types

    parent = types.ModuleType(parent_name)
    parent.__path__ = [str(pkg)]
    sys.modules[parent_name] = parent
    cap_spec = importlib.util.spec_from_file_location(
        f"{parent_name}.capture", pkg / "capture.py"
    )
    assert cap_spec is not None and cap_spec.loader is not None
    cap = importlib.util.module_from_spec(cap_spec)
    sys.modules[f"{parent_name}.capture"] = cap
    cap_spec.loader.exec_module(cap)
    spec = importlib.util.spec_from_file_location(
        f"{parent_name}.review", pkg / "review.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{parent_name}.review"] = mod
    spec.loader.exec_module(mod)
    return mod


rev = _load_review()


def test_parse_review_args_focus_about_session():
    out = rev.parse_review_args(
        "kasten vs archive --about current/design/canonical-state-schema.md "
        "--session agent-rtc-cafe"
    )
    assert out["focus"] == "kasten vs archive"
    assert out["about"] == "current/design/canonical-state-schema.md"
    assert out["session"] == "agent-rtc-cafe"
    assert rev.parse_review_args("")["focus"] == ""


def test_format_transcript_clips_and_keeps_order():
    msgs = [
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "there"},
        {"role": "user", "content": "x" * 2000},
    ]
    text = rev.format_transcript(msgs)
    assert "user: hello" in text
    assert "assistant: there" in text
    assert "ignore" not in text
    assert "…" in text
    assert len(text) < 4000


def test_last_agent_rtc_session_is_the_newest(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("cli-1", "cli")
        db.append_message("cli-1", "user", "chat grok")
        db.create_session("agent-rtc-old", "agent-rtc")
        db.append_message("agent-rtc-old", "user", "old call")
        db.create_session("agent-rtc-new", "agent-rtc")
        db.append_message("agent-rtc-new", "user", "kasten")
        db.append_message("agent-rtc-new", "assistant", "archive is the move")
        row = rev.last_agent_rtc_session(db=db)
        assert row is not None
        assert row["id"] == "agent-rtc-new"
        named = rev.last_agent_rtc_session(db=db, session_id="agent-rtc-old")
        assert named is not None and named["id"] == "agent-rtc-old"
        assert rev.last_agent_rtc_session(db=db, session_id="cli-1") is None
    finally:
        db.close()


def test_review_writes_a_zettel_fresh_glance_can_see(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    db = SessionDB(db_path=home / "state.db")
    seen: dict = {}

    def _consult(*, question, context, system=""):
        seen["question"] = question
        seen["context"] = context
        seen["system"] = system
        return {
            "ok": True,
            "text": "# Grok lift: kasten vs archive\n\nFile the current doc; stop circling.",
            "model": "grok-4.6",
            "provider": "xai-oauth",
        }

    try:
        db.create_session("agent-rtc-cafe", "agent-rtc")
        db.append_message("agent-rtc-cafe", "user", "is it kasten or archive")
        db.append_message("agent-rtc-cafe", "assistant", "we keep restating the same split")
        out = rev.review_session(
            focus="the looping split",
            db=db,
            hermes_home=home,
            consult_fn=_consult,
        )
        assert out["ok"] is True
        assert out["session_id"] == "agent-rtc-cafe"
        assert out["relpath"].startswith("scratch/")
        assert "kasten" in Path(out["path"]).read_text(encoding="utf-8").lower()
        assert "looping split" in seen["question"]
        assert "kasten or archive" in seen["context"]
        assert "USER-PROVIDED" in seen["system"]
        glance = fresh_zettel_glance(hermes_home=home, now=datetime.now().timestamp(), limit=1)
        assert "Grok lift" in glance or "kasten" in glance.lower()
        assert "wiki/scratch" in glance
        text = rev.format_slash_result(out)
        assert "/rtc-review failed" not in text
        assert "agent-rtc-cafe" in text
        assert "12 minutes" in text
    finally:
        db.close()


def test_review_without_a_session_is_an_error(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("cli-only", "cli")
        db.append_message("cli-only", "user", "hello")
        out = rev.review_session(db=db, hermes_home=tmp_path / ".hermes")
        assert out["ok"] is False
        assert "no agent-rtc" in out["error"]
    finally:
        db.close()


def test_review_reports_grok_failure(tmp_path):
    home = tmp_path / ".hermes"
    home.mkdir()
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("agent-rtc-x", "agent-rtc")
        db.append_message("agent-rtc-x", "user", "hello")
        db.append_message("agent-rtc-x", "assistant", "hi")
        out = rev.review_session(
            db=db,
            hermes_home=home,
            consult_fn=lambda **k: {"ok": False, "error": "no bearer"},
        )
        assert out["ok"] is False
        assert "bearer" in out["error"]
        assert (home / "wiki").exists() is False or not list((home / "wiki").rglob("*.md"))
    finally:
        db.close()
