"""AgentRTC kanban board: same SQLite as the dashboard, loopback HTML view."""
from __future__ import annotations

import json

import pytest

from hsengine.engine import ops
from hsengine.engine import webrtc_kanban as kb

_REAL_REFRESH = kb.refresh_view


@pytest.fixture(autouse=True)
def _isolate_board(tmp_path, monkeypatch):
    root = tmp_path / "kanban-home"
    root.mkdir()
    hermes = tmp_path / ".hermes"
    hermes.mkdir()
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.setattr(kb, "refresh_view", lambda: None)
    return root


def test_create_list_show_comment_and_complete_from_triage():
    created = kb.create_task(title="Expose the board", body="loopback HTML")
    assert created["ok"] is True
    assert created["status"] == "triage"
    tid = created["id"]
    listed = kb.list_tasks()
    assert listed["ok"] is True
    assert any(t["id"] == tid and t["title"] == "Expose the board" for t in listed["tasks"])
    shown = kb.show_task(tid)
    assert shown["ok"] is True
    assert shown["task"]["body"] == "loopback HTML"
    note = kb.comment_task(tid, "Ripley is driving this from AgentRTC")
    assert note["ok"] is True
    shown = kb.show_task(tid)
    assert any("AgentRTC" in (c.get("body") or "") for c in shown["comments"])
    done = kb.complete_task(tid, result="on the compositor")
    assert done["ok"] is True
    assert done["status"] == "done"
    after = kb.show_task(tid)
    assert after["task"]["status"] == "done"


def test_block_unblock_move_and_link():
    parent = kb.create_task(title="Theta W38")
    child = kb.create_task(title="W37 backfill")
    assert kb.link_tasks(parent["id"], child["id"])["ok"] is True
    blocked = kb.block_task(child["id"], reason="waiting on W38")
    assert blocked["ok"] is True
    assert blocked["status"] == "blocked"
    assert kb.show_task(child["id"])["task"]["status"] == "blocked"
    opened = kb.unblock_task(child["id"])
    assert opened["ok"] is True
    moved = kb.move_task(parent["id"], "todo")
    assert moved["ok"] is True
    assert moved["status"] in ("todo", "ready")
    review = kb.move_task(parent["id"], "review")
    assert review["ok"] is True
    assert review["status"] == "review"


def test_board_html_marks_the_compositor_page():
    kb.create_task(title="Lattice W38")
    page = kb.board_html()
    assert "data-kanban-board" in page
    assert "Lattice W38" in page
    assert "<section" in page
    for col in kb.COLUMNS:
        assert col in page


def test_create_and_show_require_ids():
    assert kb.create_task(title="  ")["ok"] is False
    assert kb.show_task("")["ok"] is False
    assert kb.show_task("t_missing")["ok"] is False
    assert kb.move_task("t_x", "running")["ok"] is False


def test_dispatch_kanban_tools_round_trip():
    created = json.loads(ops.dispatch("kanban_create", {"title": "Track Theta"}))
    assert created["ok"] is True
    listed = json.loads(ops.dispatch("kanban_list", {}))
    assert listed["count"] >= 1
    tid = created["id"]
    shown = json.loads(ops.dispatch("kanban_show", {"task_id": tid}))
    assert shown["task"]["title"] == "Track Theta"
    moved = json.loads(ops.dispatch("kanban_move", {"task_id": tid, "status": "todo"}))
    assert moved["ok"] is True
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    for name in (
        "kanban_list",
        "kanban_show",
        "kanban_create",
        "kanban_comment",
        "kanban_complete",
        "kanban_block",
        "kanban_unblock",
        "kanban_link",
        "kanban_move",
    ):
        assert name in names
        assert name in ops._DISPATCH


def test_refresh_view_reloads_only_when_kanban_is_live(monkeypatch):
    from hsengine.engine import webrtc_program as wp

    seen: list[dict] = []
    monkeypatch.setattr(wp, "show", lambda **k: seen.append(k) or {"ok": True})
    monkeypatch.setattr(
        wp.PROGRAM,
        "status",
        lambda: {"kind": "chord", "live": True, "title": "x"},
    )
    _REAL_REFRESH()
    assert seen == []
    monkeypatch.setattr(
        wp.PROGRAM,
        "status",
        lambda: {"kind": "kanban", "live": True, "title": "Kanban"},
    )
    _REAL_REFRESH()
    assert seen and seen[0]["kind"] == "kanban"
