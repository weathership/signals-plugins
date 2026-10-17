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


def test_preprint_url_variants_share_one_key_and_servers_stay_apart():
    """abs/pdf/html/version on one server are one paper. Servers are not."""
    arxiv = [
        "https://arxiv.org/abs/2402.03300",
        "https://arxiv.org/pdf/2402.03300",
        "https://arxiv.org/pdf/2402.03300.pdf",
        "https://arxiv.org/pdf/2402.03300v2.pdf",
        "https://arxiv.org/html/2402.03300v3",
    ]
    bio = [
        "https://www.biorxiv.org/content/10.1101/2024.01.01.123456",
        "https://www.biorxiv.org/content/10.1101/2024.01.01.123456.full.pdf",
        "https://www.biorxiv.org/content/10.1101/2024.01.01.123456v2.full.pdf",
    ]
    med = [
        "https://www.medrxiv.org/content/10.1101/2024.02.02.654321",
        "https://www.medrxiv.org/content/10.1101/2024.02.02.654321.full.pdf",
        "https://www.medrxiv.org/content/10.1101/2024.02.02.654321v1",
    ]
    assert len({drop.drop_key(url) for url in arxiv}) == 1
    assert len({drop.drop_key(url) for url in bio}) == 1
    assert len({drop.drop_key(url) for url in med}) == 1
    assert drop.drop_key(arxiv[0]) != drop.drop_key(bio[0])
    assert drop.drop_key(bio[0]) != drop.drop_key(med[0])
    assert drop.drop_key("https://example.com/2402.03300.pdf").startswith("web:")
    assert not drop.needs_pdf_approval(med[0], "medrxiv")
    assert drop.needs_pdf_approval("https://example.com/2402.03300.pdf", "web")
    assert drop.pdf_url_for(med[2], "medrxiv") == (
        "https://www.medrxiv.org/content/10.1101/2024.02.02.654321v1.full.pdf"
    )
    assert drop.drop_key(med[2]) == drop.drop_key(med[0])


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


def _analysis(url, kind="arxiv"):
    return {
        "url": "https://arxiv.org/pdf/2402.03300.pdf",
        "kind": kind,
        "title": "Replay units",
        "short_title": "Replay units",
        "summary": "The paper is about the replay unit.",
        "claims": ["The replay unit is the noun."],
        "method": "Read the paper.",
        "limits": "One week.",
        "text": "Full OCR markdown.",
        "model": "mistral-ocr-latest",
    }


def test_enqueue_files_preview_and_full_cards():
    when = datetime(2026, 10, 17, 18, 4, 5, tzinfo=timezone.utc)
    filed = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        session_id="cafe",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=_fetch,
        summarize=_summary,
        analyze=_analysis,
        now=when,
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

    wiki = Path(os.environ["WIKI_PATH"])
    notes = list(wiki.glob("scratch/*/*.md"))
    assert len(notes) == 1
    preview = notes[0].read_text()
    assert "first 8 PDF pages" in preview
    assert "## Summary" not in preview
    curated = list(wiki.glob("current/kb/arXiv/*.md"))
    assert len(curated) == 1
    assert curated[0].name == "2026-10-17T180405Z_replay-units.md"
    full = curated[0].read_text()
    assert "type: kb" in full
    assert "provider: mistral" in full
    assert "replay unit" in full.lower()
    assert "Full OCR markdown." in full


def test_second_drop_does_not_start_another_extract():
    calls = {"fetch": 0, "analyze": 0}

    def fetch(url, scope="preview"):
        calls["fetch"] += 1
        return _paper(scope=scope)

    def analyze(url, kind="arxiv"):
        calls["analyze"] += 1
        return _analysis(url, kind)

    first = drop.enqueue(
        url="https://arxiv.org/pdf/2402.03300.pdf",
        performer="hermes",
        spawn=lambda fn: fn(),
        fetch=fetch,
        analyze=analyze,
        summarize=lambda source: "same paper",
    )
    second = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        performer="hermes",
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("respawned")),
        fetch=fetch,
        analyze=analyze,
        summarize=lambda source: "same paper",
    )
    assert first["created"] is True
    assert len(first["tasks"]) == 2
    assert second["created"] is False
    assert {row["id"] for row in second["tasks"]} == {row["id"] for row in first["tasks"]}
    assert calls["fetch"] == 1
    assert calls["analyze"] == 1


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


def test_other_pdf_stays_blocked_until_approved():
    calls = {"fetch": 0, "analyze": 0}

    def fetch(url, scope="preview"):
        calls["fetch"] += 1
        return _paper()

    def analyze(url, kind="arxiv"):
        calls["analyze"] += 1
        return _analysis(url, kind)

    filed = drop.enqueue(
        url="https://example.com/papers/note.pdf",
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("ran")),
        fetch=fetch,
        analyze=analyze,
    )
    assert filed["awaiting_approval"] is True
    assert [row["status"] for row in filed["tasks"]] == ["blocked", "blocked"]
    assert calls == {"fetch": 0, "analyze": 0}
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        comments = conn.execute("SELECT body FROM task_comments").fetchall()
    assert comments
    assert "explicitly approve" in comments[0]["body"]


def test_approved_other_pdf_stays_off_mistral_and_off_the_curated_kb(tmp_path):
    filed = drop.enqueue(
        url="https://example.com/papers/note.pdf",
        approve=True,
        spawn=lambda fn: fn(),
        fetch=_fetch,
        summarize=_summary,
        analyze=lambda url, kind: (_ for _ in ()).throw(AssertionError("mistral")),
    )
    assert filed["awaiting_approval"] is False
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc
    from pathlib import Path
    import os

    kanban_db.init_db()
    with kbc.connect() as conn:
        statuses = [row["status"] for row in conn.execute("SELECT status FROM tasks")]
    assert statuses == ["done", "done"]
    wiki = Path(os.environ["WIKI_PATH"])
    assert list(wiki.glob("current/kb/*/*.md")) == []
    assert list(wiki.glob("scratch/*/*.md"))


def test_a_second_drop_with_approval_runs_the_blocked_pdf():
    url = "https://example.com/papers/note.pdf"
    held = drop.enqueue(
        url=url,
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("ran")),
    )
    assert held["awaiting_approval"] is True
    released = drop.enqueue(
        url=url,
        approve=True,
        spawn=lambda fn: fn(),
        fetch=_fetch,
        summarize=_summary,
        analyze=lambda url, kind: (_ for _ in ()).throw(AssertionError("mistral")),
    )
    assert released["awaiting_approval"] is False
    assert {row["id"] for row in released["tasks"]} == {row["id"] for row in held["tasks"]}
    from hermes_cli import kanban_db
    from hermes_cli import kanban_db_connect as kbc

    kanban_db.init_db()
    with kbc.connect() as conn:
        statuses = [row["status"] for row in conn.execute("SELECT status FROM tasks")]
    assert statuses == ["done", "done"]


def test_medrxiv_variants_share_one_curated_note():
    when = datetime(2026, 10, 17, 19, 1, 2, tzinfo=timezone.utc)
    calls = {"n": 0}
    page = "https://www.medrxiv.org/content/10.1101/2024.02.02.654321"
    pdf = page + "v1.full.pdf"

    def analyze(url, kind="medrxiv"):
        calls["n"] += 1
        assert kind == "medrxiv"
        note = _analysis(url, kind)
        note["short_title"] = "Trial endpoint"
        return note

    first = drop.enqueue(
        url=page,
        spawn=lambda fn: fn(),
        fetch=_fetch,
        analyze=analyze,
        now=when,
    )
    second = drop.enqueue(
        url=pdf,
        spawn=lambda fn: (_ for _ in ()).throw(AssertionError("respawned")),
        fetch=_fetch,
        analyze=analyze,
    )
    assert first["awaiting_approval"] is False
    assert second["created"] is False
    assert {row["id"] for row in second["tasks"]} == {row["id"] for row in first["tasks"]}
    assert calls["n"] == 1
    from pathlib import Path
    import os

    notes = list(Path(os.environ["WIKI_PATH"]).glob("current/kb/medRxiv/*.md"))
    assert len(notes) == 1
    assert notes[0].name.startswith("2026-10-17T190102Z_trial-endpoint")


def test_mistral_request_is_the_public_pdf_and_keeps_the_key_out_of_the_body(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    seen: dict = {}

    def post(payload, key):
        seen["payload"] = payload
        seen["key"] = key
        return {
            "model": "mistral-ocr-latest",
            "pages": [{"index": 0, "markdown": "# Body\n\nThe paper."}],
            "document_annotation": (
                '{"short_title":"Replay units","summary":"A summary.",'
                '"claims":["One claim."],"method":"A method.","limits":"A limit."}'
            ),
        }

    monkeypatch.setattr(drop, "_mistral_post", post)
    source = drop.mistral_analyze("https://arxiv.org/abs/2402.03300", kind="arxiv")
    payload = seen["payload"]
    assert seen["key"] == "test-key"
    assert "test-key" not in json.dumps(payload)
    assert payload["document"]["document_url"] == "https://arxiv.org/pdf/2402.03300.pdf"
    assert payload["document_annotation_format"]["type"] == "json_schema"
    assert payload["include_image_base64"] is False
    assert source["summary"] == "A summary."
    assert "The paper." in source["text"]
    with pytest.raises(RuntimeError):
        drop.mistral_analyze("https://example.com/note.pdf", kind="web")


def test_named_workflow_writes_the_kb_note_from_the_execution(monkeypatch):
    monkeypatch.setenv("MISTRAL_PAPER_WORKFLOW", "signals-preprint-analysis")
    seen = {}

    def start(name, url, kind):
        seen["start"] = (name, url, kind)
        return "exec-1"

    def wait(execution_id, sleep=None):
        assert execution_id == "exec-1"
        return _analysis("https://arxiv.org/abs/2402.03300", kind="arxiv")

    monkeypatch.setattr(drop, "start_paper_workflow", start)
    monkeypatch.setattr(drop, "await_paper_workflow", wait)
    filed = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        spawn=lambda fn: fn(),
        fetch=_fetch,
        analyze=lambda url, kind="arxiv": (_ for _ in ()).throw(AssertionError("inline ocr")),
    )
    assert seen["start"] == (
        "signals-preprint-analysis",
        "https://arxiv.org/abs/2402.03300",
        "arxiv",
    )
    assert filed["tasks"][1]["scope"] == "full"
    from pathlib import Path
    import os

    notes = list(Path(os.environ["WIKI_PATH"]).glob("current/kb/arXiv/*.md"))
    assert len(notes) == 1
    assert "replay unit" in notes[0].read_text().lower()


def test_workflow_execute_sends_the_public_pdf(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    seen = {}

    def send(method, url, payload, key):
        seen["payload"] = payload
        seen["url"] = url
        assert key == "test-key"
        return 200, {"execution_id": "exec-9", "status": "RUNNING"}

    monkeypatch.setattr(drop, "_mistral_json", send)
    assert drop.start_paper_workflow("signals-preprint-analysis", "https://arxiv.org/abs/2402.03300", "arxiv") == "exec-9"
    assert seen["payload"]["input"]["url"] == "https://arxiv.org/pdf/2402.03300.pdf"
    assert seen["payload"]["wait_for_result"] is False
    assert "test-key" not in str(seen["payload"])


def test_missing_workflow_falls_back_to_inline_ocr(monkeypatch):
    monkeypatch.setenv("MISTRAL_PAPER_WORKFLOW", "signals-preprint-analysis")

    def start(name, url, kind):
        raise RuntimeError(f"workflow {name} HTTP 404")

    monkeypatch.setattr(drop, "start_paper_workflow", start)
    filed = drop.enqueue(
        url="https://arxiv.org/abs/2402.03300",
        spawn=lambda fn: fn(),
        fetch=_fetch,
        analyze=_analysis,
    )
    assert filed["created"] is True
    from pathlib import Path
    import os

    assert list(Path(os.environ["WIKI_PATH"]).glob("current/kb/arXiv/*.md"))


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
