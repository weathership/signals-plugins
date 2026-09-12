"""Live interactive posture: Cerebras complete + Connect via signals-protocol.

Skipped unless CEREBRAS_API_KEY and (for enter) the Signals scheduler plus
moshi supervisor are up. Does not print secrets. Does not talk to Kubernetes.
"""
from __future__ import annotations

import os
import socket

import pytest

from hsengine.engine import coordination, interactive
from hsengine.engine.yk_sentinel import QUEUE, moshi_serving

# conftest strips *_API_KEY before each test. Snapshot at import.
_KEY_SNAP = os.environ.get("CEREBRAS_API_KEY") or ""


def _ensure_key() -> bool:
    if _KEY_SNAP:
        os.environ["CEREBRAS_API_KEY"] = _KEY_SNAP
        return True
    try:
        interactive._cerebras_key()
        return True
    except RuntimeError:
        return False


def _port_up(host: str, port: int) -> bool:
    try:
        s = socket.create_connection((host, port), 1)
        s.close()
        return True
    except OSError:
        return False


def _supervisor_up() -> bool:
    return _port_up("127.0.0.1", 5081)


def _signals_up() -> bool:
    raw = coordination.target()
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit():
        return False
    return _port_up(host, int(port))


@pytest.mark.integration
def test_cerebras_qwen38_complete_without_kubernetes():
    if not _ensure_key():
        pytest.skip("CEREBRAS_API_KEY not configured")

    result = interactive.complete_cerebras(
        prompt="Reply with the single word: pong",
        max_tokens=32,
        temperature=0,
        reasoning_effort="none",
        tools=False,
    )
    assert result.peer == "cerebras"
    assert result.model == "qwen-3.8-27b"
    assert "pong" in result.text.lower()


@pytest.mark.integration
def test_interactive_enter_declares_then_starts_moshi():
    if not _ensure_key():
        pytest.skip("CEREBRAS_API_KEY not configured")
    if not _signals_up():
        pytest.skip("Signals scheduler not listening")
    if not _supervisor_up():
        pytest.skip("moshi supervisor :5081 not up")

    with interactive._mu:
        interactive._refcount = 0
        interactive._active = False
        interactive._lease = None

    interactive.enter()
    try:
        assert interactive.is_active()
        activity = interactive.current_activity()
        assert activity is not None
        claims = {(c["leaf"], int(c["gpu"])) for c in activity["claims"]}
        assert (QUEUE, 1) in claims
        assert not any(leaf.startswith("root.external.") and gpu for leaf, gpu in claims)
        assert moshi_serving() or _port_up("127.0.0.1", 5080)
        result = interactive.complete_cerebras(
            prompt="Reply with the single word: pong",
            max_tokens=16,
            temperature=0,
            reasoning_effort="none",
            tools=False,
        )
        assert result.peer == "cerebras"
        assert "qwen" in result.model.lower() or result.model == "qwen-3.8-27b"
        assert result.text
        assert "pong" in result.text.lower()
    finally:
        interactive.leave()

    assert interactive.is_active() is False
