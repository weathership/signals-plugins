"""signals-memory is the hybrid MemoryProvider AgentRTC should load."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "signals-memory" / "__init__.py"


def _load_provider():
    spec = importlib.util.spec_from_file_location("signals_memory_plugin", PLUGIN)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SignalsMemoryProvider()


def test_prefetch_skips_trivial_prompts(tmp_path):
    p = _load_provider()
    p.initialize("agent-rtc-x", hermes_home=str(tmp_path), platform="agent-rtc")
    assert p.prefetch("ok") == ""
    assert p.prefetch("thanks") == ""


def test_sync_and_jsonl_search(tmp_path):
    p = _load_provider()
    p.initialize("s1", hermes_home=str(tmp_path), platform="agent-rtc")
    p.sync_turn("Write a Nautilus note", "Filed entities/nautilus.md", session_id="s1")
    hits = p._search("Nautilus", limit=4)
    assert hits
    assert any("Nautilus" in h.get("text", "") for h in hits)


def test_prefetch_includes_wiki_citation(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from hsengine.engine import session_history

    home = tmp_path / ".hermes"
    wiki = home / "wiki" / "entities"
    wiki.mkdir(parents=True)
    (wiki / "nautilus.md").write_text(
        "---\ntitle: Nautilus\nupdated: 2026-09-12\n---\n\nAir-gap FSM probes.\n",
        encoding="utf-8",
    )
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    p = _load_provider()
    p.initialize("agent-rtc-live", hermes_home=str(home), platform="agent-rtc")
    monkeypatch.setattr(
        "hsengine.engine.ops.search",
        lambda **k: {"ok": True, "hits": [{"title": "arxiv nautilus", "snippet": "federated learning"}]},
    )
    try:
        block = p.prefetch("Do you still have the Nautilus notes?", session_id="agent-rtc-live")
        assert "wiki/entities/nautilus.md" in block
        assert "invent" in block.lower()
        assert "Lattice" in block
        assert "arxiv nautilus" in block
    finally:
        session_history.configure(None)
        db.close()


def test_agentrtc_loads_signals_memory_when_provider_unset(tmp_path, monkeypatch):
    from hsengine.engine import session_history

    session_history.reset_memory()
    loaded: list[str] = []

    class _Prov:
        name = "signals-memory"

        def is_available(self):
            return True

    def _load(name):
        loaded.append(name)
        return _Prov() if name == "signals-memory" else None

    monkeypatch.setattr(
        "hermes_cli.config.cfg_get", lambda *_a, **_k: ""
    )
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {})
    monkeypatch.setattr("plugins.memory.load_memory_provider", _load)
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: tmp_path)

    class _Mgr:
        def __init__(self):
            self.added = []

        def add_provider(self, p):
            self.added.append(p)

        def initialize_all(self, **k):
            self.kwargs = k

        def prefetch_all(self, q, *, session_id=""):
            return f"pack:{q}:{session_id}"

        def on_session_switch(self, *a, **k):
            return None

    monkeypatch.setattr("agent.memory_manager.MemoryManager", _Mgr)
    try:
        mgr = session_history._memory_manager("agent-rtc-x")
        assert mgr is not None
        assert loaded == ["signals-memory"]
        assert session_history.recalled_memory("x", "Nautilus notes") == "pack:Nautilus notes:agent-rtc-x"
    finally:
        session_history.reset_memory()


def test_configured_provider_is_not_overridden(monkeypatch, tmp_path):
    from hsengine.engine import session_history

    session_history.reset_memory()

    class _Honcho:
        name = "honcho"

        def is_available(self):
            return True

    monkeypatch.setattr("hermes_cli.config.cfg_get", lambda *_a, **_k: "honcho")
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"memory": {"provider": "honcho"}})
    monkeypatch.setattr(
        "plugins.memory.load_memory_provider",
        lambda name: _Honcho() if name == "honcho" else None,
    )
    monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: tmp_path)

    class _Mgr:
        def add_provider(self, p):
            self.p = p

        def initialize_all(self, **k):
            pass

        def on_session_switch(self, *a, **k):
            return None

    monkeypatch.setattr("agent.memory_manager.MemoryManager", _Mgr)
    try:
        mgr = session_history._memory_manager("s")
        assert mgr is not None
        assert mgr.p.name == "honcho"
    finally:
        session_history.reset_memory()
