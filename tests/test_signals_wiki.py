"""Wiki dashboard plugin lists the vault and refuses path escape."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException


def _load():
    root = Path(__file__).resolve().parents[1] / "plugins" / "signals-wiki" / "dashboard"
    spec = importlib.util.spec_from_file_location("signals_wiki_api_test", root / "plugin_api.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_pages_from_vault(tmp_path, monkeypatch):
    vault = tmp_path / "wiki"
    (vault / "design").mkdir(parents=True)
    (vault / "design" / "note.md").write_text("# hi\n")
    monkeypatch.setenv("WIKI_PATH", str(vault))
    mod = _load()
    pages = mod.list_pages()
    assert pages[0]["path"] == "design/note.md"


def test_safe_rejects_dotdot(tmp_path, monkeypatch):
    vault = tmp_path / "wiki"
    vault.mkdir()
    monkeypatch.setenv("WIKI_PATH", str(vault))
    mod = _load()
    with pytest.raises(HTTPException):
        mod._safe("../etc/passwd")


def test_object_key_is_hermes_wiki_prefix():
    mod = _load()
    assert mod._object_key("design/note.md") == "wiki/design/note.md"


def test_rail_is_archive_current_scratch_and_current_hides_scratch(
    tmp_path, monkeypatch
):
    vault = tmp_path / "wiki"
    (vault / "design").mkdir(parents=True)
    (vault / "design" / "note.md").write_text("# n\n")
    (vault / "scratch" / "2026-09-19").mkdir(parents=True)
    (vault / "scratch" / "2026-09-19" / "a.md").write_text("s\n")
    monkeypatch.setenv("WIKI_PATH", str(vault))
    mod = _load()
    rail = mod.rail()
    assert [s["id"] for s in rail["sections"]] == ["archive", "current", "scratch"]
    current = rail["sections"][1]
    names = {e["name"] for e in current["recent"]}
    assert "scratch" not in names
    assert "archive" not in names
    assert "design" in names
    scratch = rail["sections"][2]
    assert scratch["recent"][0]["name"] == "2026-09-19"
    archive = rail["sections"][0]
    assert archive["recent"] == []
    assert archive["total"] == 0


def test_listing_paginates_and_more_opens_next_offset(tmp_path, monkeypatch):
    vault = tmp_path / "wiki" / "scratch"
    vault.mkdir(parents=True)
    for i in range(6):
        p = vault / f"2026-09-{i+10:02d}"
        p.mkdir()
        (p / "n.md").write_text("x\n")
        os_utime = __import__("os").utime
        os_utime(p, (1_000_000 + i, 1_000_000 + i))
    monkeypatch.setenv("WIKI_PATH", str(vault.parent))
    mod = _load()
    first = mod.list_level("scratch", "", offset=0, limit=4)
    assert first["more"] is True
    assert first["next_offset"] == 4
    assert len(first["entries"]) == 4
    second = mod.list_level("scratch", "", offset=4, limit=4)
    assert second["more"] is False
    seen = {e["path"] for e in first["entries"] + second["entries"]}
    assert len(seen) == 6


def test_extract_and_resolve_wikilinks(tmp_path, monkeypatch):
    vault = tmp_path / "wiki"
    (vault / "design").mkdir(parents=True)
    (vault / "design" / "canonical-state-schema.md").write_text(
        "See [[canonical-state-schema]] and [[notes/article-draft]].\n"
    )
    (vault / "notes").mkdir()
    (vault / "notes" / "article-draft.md").write_text("hub\n")
    monkeypatch.setenv("WIKI_PATH", str(vault))
    mod = _load()
    pages = mod.list_pages()
    links = mod.extract_wikilinks(
        "See [[canonical-state-schema]] and [[notes/article-draft|the article]]."
    )
    assert [x["target"] for x in links] == [
        "canonical-state-schema",
        "notes/article-draft",
    ]
    assert mod.resolve_wikilink(pages, "canonical-state-schema") == (
        "design/canonical-state-schema.md"
    )
    assert mod.resolve_wikilink(pages, "notes/article-draft") == (
        "notes/article-draft.md"
    )
