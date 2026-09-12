"""Clipboard zettel capture under the Hermes wiki vault."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

def _load_capture():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "plugins" / "signals-zettel" / "capture.py"
    spec = importlib.util.spec_from_file_location("signals_zettel_capture", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cap = _load_capture()


def test_vault_prefers_obsidian_then_wiki(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    obs = tmp_path / "obsidian"
    env = {"WIKI_PATH": str(wiki)}
    assert cap.vault_root(env=env, hermes_home=tmp_path) == wiki
    env["OBSIDIAN_VAULT_PATH"] = str(obs)
    assert cap.vault_root(env=env, hermes_home=tmp_path) == obs
    assert cap.vault_root(env={}, hermes_home=tmp_path) == tmp_path / "wiki"


def test_zettel_relpath_gaius_shape():
    now = datetime(2026, 9, 12, 17, 30, 42)
    rel = cap.zettel_relpath("Nautilus air-gap", now=now)
    assert rel == "scratch/2026-09-12/173042_nautilus-air-gap.md"


def test_slugify_strips_noise():
    assert cap.slugify("  Foo / Bar!!  ") == "foo-bar"
    assert cap.slugify("") == "note"


def test_capture_writes_body_and_resource(tmp_path):
    vault = tmp_path / "wiki"
    vault.mkdir()
    now = datetime(2026, 9, 12, 8, 1, 2)
    out = cap.capture(
        body="Nautilus air-gap\n\nFSM with a Brier ledger.",
        vault=vault,
        now=now,
    )
    assert out["ok"] is True
    assert out["relpath"] == "scratch/2026-09-12/080102_nautilus-air-gap.md"
    assert out["resource"] == "wiki:scratch/2026-09-12/080102_nautilus-air-gap.md"
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert text.startswith("# Nautilus air-gap\n")
    assert "Brier ledger" in text


def test_capture_keeps_existing_heading(tmp_path):
    vault = tmp_path / "wiki"
    vault.mkdir()
    out = cap.capture(
        body="# Already titled\n\nBody.\n",
        vault=vault,
        now=datetime(2026, 9, 12, 9, 0, 0),
    )
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert text.startswith("# Already titled\n")
    assert text.count("# ") == 1
    assert out["relpath"].endswith("_already-titled.md")


def test_capture_empty_body_fails(tmp_path):
    out = cap.capture(vault=tmp_path / "wiki", body="  \n")
    assert out["ok"] is False
    assert out["error"] == "usage: /zettel <pasted text>"


def test_capture_appends_wiki_log(tmp_path):
    vault = tmp_path / "wiki"
    vault.mkdir()
    (vault / "log.md").write_text("# Log\n", encoding="utf-8")
    out = cap.capture(
        body="Probe\nhello",
        vault=vault,
        now=datetime(2026, 9, 12, 10, 0, 0),
    )
    log = (vault / "log.md").read_text(encoding="utf-8")
    assert out["relpath"] in log
    assert "wiki:" in log
