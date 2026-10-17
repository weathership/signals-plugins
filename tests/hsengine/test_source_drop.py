"""A dropped URL is a CPU zettel, tracked on the board, with no GPU claim."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from hsengine.engine import ops
from hsengine.engine import source_drop as drop


@pytest.fixture(autouse=True)
def _isolate_board(tmp_path, monkeypatch):
    root = tmp_path / "kanban-home"
    root.mkdir()
    hermes = tmp_path / ".hermes"
    (hermes / "wiki").mkdir(parents=True)
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    monkeypatch.setenv("WIKI_PATH", str(hermes / "wiki"))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("GAIUS_KB_PATH", raising=False)
    monkeypatch.delenv("GAIUS_ROOT", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    import hsengine.engine.webrtc_kanban as kb

    monkeypatch.setattr(kb, "refresh_view", lambda: None)
    return hermes


def _paper(**overrides):
    base = {
        "url": "https://arxiv.org/abs/2402.03300",
        "kind": "arxiv",
        "title": "A small paper",
        "abstract": "The abstract says the unit is the replay.",
        "text": "Page one of the paper.",
        "note": "",
    }
    base.update(overrides)
    return base


def test_gpu_tokens_stay_zero():
    assert drop.GPU_TOKENS == 0


def test_urls_in_keeps_papers_and_skips_localhost():
    text = (
        "look at https://arxiv.org/abs/2402.03300 and "
        "https://www.biorxiv.org/content/10.1101/2024.01.01.123456 and "
        "http://127.0.0.1:52021/kanban"
    )
    found = drop.urls_in(text)
    assert found == [
        "https://arxiv.org/abs/2402.03300",
        "https://www.biorxiv.org/content/10.1101/2024.01.01.123456",
    ]
    assert drop.classify(found[0]) == "arxiv"
    assert drop.classify(found[1]) == "biorxiv"
    assert drop.drop_key("https://arxiv.org/pdf/2402.03300.pdf") == "arxiv:2402.03300"


def test_fetch_arxiv_uses_the_api_and_stops_at_abstract_without_pdf(monkeypatch):
    def get(url: str) -> bytes:
        assert "export.arxiv.org" in url
        return b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Replay units</title>
            <summary>The missing noun.</summary>
            <author><name>Ada</name></author>
          </entry>
        </feed>"""

    monkeypatch.setattr(drop, "_pdf_to_text", lambda data: "")
    # PDF fetch raises; the abstract still lands.
    def get_fail_pdf(url: str) -> bytes:
        if url.endswith(".pdf"):
            raise RuntimeError("no pdf")
        return get(url)

    source = drop.fetch_source("https://arxiv.org/abs/2402.03300", get=get_fail_pdf)
    assert source["title"] == "Replay units"
    assert "missing noun" in source["abstract"]
    assert source["text"] == ""
    assert "PDF" in source["note"]


def test_enqueue_writes_hermes_zettel_and_closes_the_card():
    filed = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        session_id="cafe",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=lambda url: _paper(),
    )
    assert filed["created"] is True
    assert filed["status"] == "running"
    assert filed["gpu_tokens"] == 0
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        row = conn.execute(
            "SELECT status, result FROM tasks WHERE id = ?", (filed["id"],)
        ).fetchone()
        comments = conn.execute(
            "SELECT body FROM task_comments WHERE task_id = ? ORDER BY id",
            (filed["id"],),
        ).fetchall()
    assert row["status"] == "done"
    assert "scratch/" in (row["result"] or "")
    assert any("gpu_tokens=0" in c["body"] for c in comments)
    from pathlib import Path
    import os

    wiki = Path(os.environ["WIKI_PATH"])
    notes = list(wiki.glob("scratch/*/*.md"))
    assert len(notes) == 1
    body = notes[0].read_text()
    assert "Replay" in body or "small paper" in body
    assert "Not the Docling extract leaf" in body


def test_second_drop_does_not_start_another_extract():
    calls = {"n": 0}

    def fetch(url: str):
        calls["n"] += 1
        return _paper()

    first = drop.enqueue(
        url="https://arxiv.org/pdf/2402.03300.pdf",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=fetch,
    )
    second = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        performer="hermes",
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("respawned")),
        fetch=fetch,
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["id"] == first["id"]
    assert calls["n"] == 1


def test_gaius_performer_writes_kb_scratch(tmp_path, monkeypatch):
    scratch = tmp_path / "gaius-scratch"
    monkeypatch.setenv("GAIUS_KB_PATH", str(scratch))
    when = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    written = drop.write_zettel(_paper(title="Lattice note"), performer="gaius", now=when)
    assert written["resource"].startswith("gaius-scratch:")
    text = (scratch / written["relpath"]).read_text()
    assert "Performer: gaius" in text
    assert "Lattice note" in text
    with pytest.raises(RuntimeError):
        monkeypatch.delenv("GAIUS_KB_PATH")
        drop.write_zettel(_paper(), performer="gaius")


def test_failed_fetch_blocks_the_card():
    filed = drop.enqueue(
        url="https://example.com/paper",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=lambda url: (_ for _ in ()).throw(RuntimeError("origin down")),
    )
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        status = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (filed["id"],)
        ).fetchone()["status"]
    assert status == "blocked"


def test_dispatch_source_drop_returns_the_card(monkeypatch):
    monkeypatch.setattr(
        drop,
        "enqueue",
        lambda **kwargs: {"ok": True, "created": True, "id": "t_test", "gpu_tokens": 0, **kwargs},
    )
    monkeypatch.setattr(
        "hsengine.engine.source_drop.enqueue",
        lambda **kwargs: {"ok": True, "created": True, "id": "t_test", "gpu_tokens": 0},
    )
    data = json.loads(ops.dispatch("source_drop", {"url": "https://arxiv.org/abs/2402.03300"}))
    assert data["ok"] is True
    assert data["gpu_tokens"] == 0
