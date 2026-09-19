"""Fortnight-old scratch zettels move to archive/YYYYQN/MM-DD with link rewrite."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "plugins" / "signals-wiki" / "archive_scratch.py"
    spec = importlib.util.spec_from_file_location("archive_scratch_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_archive_rel_uses_quarter_and_mm_dd():
    assert (
        mod.archive_rel("scratch/2026-09-05/153022_article.md")
        == "archive/2026Q3/09-05/153022_article.md"
    )
    assert mod.archive_rel("scratch/2026-01-02/010101_x.md") == (
        "archive/2026Q1/01-02/010101_x.md"
    )


def test_due_is_fortnight_by_filename_date(tmp_path):
    vault = tmp_path / "wiki"
    old = vault / "scratch" / "2026-09-01"
    old.mkdir(parents=True)
    (old / "120000_old.md").write_text("old\n")
    fresh = vault / "scratch" / "2026-09-18"
    fresh.mkdir(parents=True)
    (fresh / "120000_new.md").write_text("new\n")
    due = mod.due_zettels(vault, now=date(2026, 9, 19), days=14)
    assert due == ["scratch/2026-09-01/120000_old.md"]


def test_migrate_rewrites_prev_next_and_wikilinks(tmp_path):
    vault = tmp_path / "wiki"
    d1 = vault / "scratch" / "2026-09-01"
    d1.mkdir(parents=True)
    older = "scratch/2026-09-01/100000_one.md"
    newer = "scratch/2026-09-01/110000_two.md"
    (vault / older).write_text(
        "---\nprev: \"\"\nnext: scratch/2026-09-01/110000_two.md\n---\n# one\n"
    )
    (vault / newer).write_text(
        "---\nprev: scratch/2026-09-01/100000_one.md\nnext: \"\"\n---\n"
        "See [[scratch/2026-09-01/100000_one]]\n"
    )
    current = vault / "current" / "notes"
    current.mkdir(parents=True)
    (current / "article.md").write_text(
        "Trail: scratch/2026-09-01/110000_two.md\n"
    )
    out = mod.migrate(vault, now=date(2026, 9, 19), days=14, dry_run=False)
    assert out["ok"]
    assert not (vault / older).exists()
    dest_one = vault / "archive/2026Q3/09-01/100000_one.md"
    dest_two = vault / "archive/2026Q3/09-01/110000_two.md"
    assert dest_one.is_file() and dest_two.is_file()
    one = dest_one.read_text(encoding="utf-8")
    two = dest_two.read_text(encoding="utf-8")
    article = (current / "article.md").read_text(encoding="utf-8")
    assert "archive/2026Q3/09-01/110000_two.md" in one
    assert "archive/2026Q3/09-01/100000_one.md" in two
    assert "[[archive/2026Q3/09-01/100000_one]]" in two
    assert "scratch/2026-09-01/" not in one
    assert "scratch/2026-09-01/" not in two
    assert "archive/2026Q3/09-01/110000_two.md" in article
