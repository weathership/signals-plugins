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
