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


def test_preview_pdf_stops_at_eight_pages_and_full_does_not(monkeypatch):
    seen: dict[str, list[str]] = {}

    def run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        class Proc:
            returncode = 0
            stdout = b"page text"
        return Proc()

    monkeypatch.setattr(drop.subprocess, "run", run)
    monkeypatch.setattr(drop.shutil, "which", lambda name: "/usr/bin/pdftotext")
    assert drop._pdf_to_text(b"%PDF-1.4") == "page text"
    assert seen["cmd"][seen["cmd"].index("-l") + 1] == "8"
    drop._pdf_to_text(b"%PDF-1.4", last_page=None)
    assert "-l" not in seen["cmd"]


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


def _fetch(url, scope="preview"):
    paper = _paper()
    paper["scope"] = scope
    if scope == "full":
        paper["text"] = paper["text"] + " The rest of the paper."
    return paper


def _summary(source):
    assert source["scope"] == "full"
    return "The paper is about the replay unit."


def test_enqueue_files_preview_and_full_cards():
    filed = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        session_id="cafe",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=_fetch,
        summarize=_summary,
    )
    assert filed["created"] is True
    assert filed["gpu_tokens"] == 0
    assert [row["scope"] for row in filed["tasks"]] == ["preview", "full"]
    assert all(row["created"] for row in filed["tasks"])
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, status, result FROM tasks ORDER BY created_at"
        ).fetchall()
    assert len(rows) == 2
    by_title = {row["title"]: row for row in rows}
    assert any(title.startswith("Extract 8 pages:") for title in by_title)
    assert any(title.startswith("Full extract and summary:") for title in by_title)
    assert all(row["status"] == "done" for row in rows)
    from pathlib import Path
    import os

    notes = list(Path(os.environ["WIKI_PATH"]).glob("scratch/*/*.md"))
    assert len(notes) == 2
    bodies = {path.name: path.read_text() for path in notes}
    preview = next(text for name, text in bodies.items() if "full" not in name)
    full = next(text for name, text in bodies.items() if "full" in name)
    assert "first 8 PDF pages" in preview
    assert "## Summary" not in preview
    assert "full text and summary" in full
    assert "replay unit" in full.lower()


def test_second_drop_does_not_start_another_extract():
    calls = {"n": 0}

    def fetch(url, scope="preview"):
        calls["n"] += 1
        return _paper(scope=scope)

    first = drop.enqueue(
        url="https://arxiv.org/pdf/2402.03300.pdf",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=fetch,
        summarize=lambda source: "same paper",
    )
    second = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        performer="hermes",
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("respawned")),
        fetch=fetch,
        summarize=lambda source: "same paper",
    )
    assert first["created"] is True
    assert len(first["tasks"]) == 2
    assert second["created"] is False
    assert {row["id"] for row in second["tasks"]} == {row["id"] for row in first["tasks"]}
    assert calls["n"] == 2


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
        fetch=lambda url, scope="preview": (_ for _ in ()).throw(RuntimeError("origin down")),
        summarize=lambda source: "unused",
    )
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        statuses = [
            row["status"]
            for row in conn.execute("SELECT status FROM tasks").fetchall()
        ]
    assert statuses == ["blocked", "blocked"]


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
