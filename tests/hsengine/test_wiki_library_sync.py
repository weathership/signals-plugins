"""Wiki markdown syncs into a Mistral library without repeating unchanged files."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_wiki_mistral_library.py"
_spec = importlib.util.spec_from_file_location("wiki_library_sync", _SCRIPT)
assert _spec and _spec.loader
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def test_plan_skips_unchanged_replaces_edits_and_deletes_departed():
    local = {"current/kb/arXiv/a.md": "aaa", "current/notes/b.md": "bbb"}
    remote = {
        "current/kb/arXiv/a.md": {"id": "doc-a", "hash": "aaa"},
        "current/notes/b.md": {"id": "doc-b", "hash": "old"},
        "current/notes/gone.md": {"id": "doc-g", "hash": "zzz"},
        "hand-uploaded.pdf": {"id": "doc-h", "hash": "qqq"},
    }
    state = {
        "current/kb/arXiv/a.md": {"sha256": "aaa", "document_id": "doc-a"},
        "current/notes/b.md": {"sha256": "old", "document_id": "doc-b"},
        "current/notes/gone.md": {"sha256": "zzz", "document_id": "doc-g"},
    }
    actions = sync.plan_sync(local, remote, state)
    assert actions["skip"] == ["current/kb/arXiv/a.md"]
    assert actions["replace"] == ["current/notes/b.md"]
    assert actions["upload"] == []
    assert actions["delete"] == ["current/notes/gone.md"]
    assert "hand-uploaded.pdf" not in actions["delete"]


def test_same_bytes_are_not_uploaded_twice_when_the_library_has_no_hash():
    local = {"current/kb/arXiv/a.md": "aaa"}
    remote = {"current/kb/arXiv/a.md": {"id": "doc-a", "hash": ""}}
    state = {"current/kb/arXiv/a.md": {"sha256": "aaa", "document_id": "doc-a"}}
    actions = sync.plan_sync(local, remote, state)
    assert actions["skip"] == ["current/kb/arXiv/a.md"]
    assert actions["upload"] == []
    assert actions["replace"] == []


def test_sync_uploads_once_and_skips_on_the_next_pass(tmp_path: Path):
    vault = tmp_path / "wiki"
    note = vault / "current" / "kb" / "arXiv"
    note.mkdir(parents=True)
    (note / "paper.md").write_text("# Paper\n\nThe body.\n", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "hidden.md").write_text("nope", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    stored: dict[str, bytes] = {}

    def transport(method, url, body, headers):
        calls.append((method, url.split("?")[0]))
        assert "Bearer test-key" in headers["Authorization"]
        if method == "GET":
            data = [
                {"id": doc_id, "name": name, "hash": ""}
                for name, doc_id in ((n, f"id-{i}") for i, n in enumerate(stored))
            ]
            # After upload, list is only used at the start of a pass.
            return 200, {"data": [], "pagination": None}
        if method == "POST":
            assert body and b"paper.md" in body
            stored["current/kb/arXiv/paper.md"] = body
            return 200, {"id": "doc-1", "name": "current/kb/arXiv/paper.md"}
        if method == "DELETE":
            return 200, None
        raise AssertionError(method)

    state = tmp_path / "state.json"
    first = sync.sync_wiki(
        root=vault,
        library="01a14b46-d2d4-7425-bb37-47d095e13f22",
        key="test-key",
        state_path=state,
        transport=transport,
    )
    assert first["uploaded"] == 1
    assert first["errors"] == []
    posts = [item for item in calls if item[0] == "POST"]
    assert len(posts) == 1

    def transport_again(method, url, body, headers):
        calls.append((method, url))
        if method == "GET":
            return 200, {
                "data": [{"id": "doc-1", "name": "current/kb/arXiv/paper.md", "hash": ""}],
                "pagination": None,
            }
        raise AssertionError(f"unexpected {method}")

    second = sync.sync_wiki(
        root=vault,
        library="01a14b46-d2d4-7425-bb37-47d095e13f22",
        key="test-key",
        state_path=state,
        transport=transport_again,
    )
    assert second["skipped"] == 1
    assert second["uploaded"] == 0
    assert second["replaced"] == 0


def test_library_id_comes_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISTRAL_LIBRARY_ID", raising=False)
    (tmp_path / "config.yaml").write_text(
        "mistral:\n  library_id: 01a14b46-d2d4-7425-bb37-47d095e13f22\n",
        encoding="utf-8",
    )
    assert sync.library_id(tmp_path) == "01a14b46-d2d4-7425-bb37-47d095e13f22"


def test_api_key_is_read_from_dotenv_without_being_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    (tmp_path / ".env").write_text('MISTRAL_API_KEY="secret-value"\n', encoding="utf-8")
    assert sync.load_api_key(tmp_path) == "secret-value"
