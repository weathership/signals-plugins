"""Nautilus follow-only: the Hermes instance exists and names project=hermes."""
from __future__ import annotations

from pathlib import Path

from hsengine.engine.supervision_spec import instance_exists, instance_path, load_spec


def test_instance_is_checked_in():
    path = instance_path()
    assert instance_exists()
    text = Path(path).read_text()
    assert 'project: "hermes"' in text
    assert "127.0.0.1:50651" in text
    assert "127.0.0.1:50661" in text
    assert "RESTART_STRATEGY_NONE" in text
    spec = load_spec()
    assert spec is not None
    assert spec.spec_version
    assert len(spec.sha256) == 64
    assert "PROCESS_KIND_ENGINE" not in text or "engine" in text
