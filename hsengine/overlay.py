"""Cerebras as Hermes' fast-reasoning wire while AgentRTC is in force.

Session-scoped: in-process interactive posture, or a Signals
``interactive_session`` Activity. Not an env var. Registered on the
generic ``hermes_agent.session_runtime`` overlay seam so Hermes core
does not import this package by name.
"""
from __future__ import annotations

from typing import Any


def session_wants_cerebras() -> bool:
    try:
        from hsengine.engine.interactive import is_active

        if is_active():
            return True
    except Exception:
        pass
    try:
        from hsengine.engine import coordination

        rows = coordination.list_activities(
            kind=coordination.KIND_INTERACTIVE, active_only=True
        )
        return bool(rows)
    except Exception:
        return False


def overlay_runtime() -> dict[str, Any] | None:
    """Cerebras OpenAI-compatible kwargs, or None if interactive is not in force."""
    if not session_wants_cerebras():
        return None
    try:
        from hsengine.engine.interactive import _cerebras_key, _cfg
    except Exception:
        return None
    try:
        key = _cerebras_key()
    except RuntimeError:
        return None
    url = _cfg(
        "hermes.engine.webrtc.interactive.cerebras_url",
        "https://api.cerebras.ai/v1",
    ).rstrip("/")
    model = _cfg(
        "hermes.engine.webrtc.interactive.cerebras_model",
        "qwen-3.8-27b",
    )
    return {
        "base_url": url,
        "api_key": key,
        "provider": "cerebras",
        "model": model,
        "api_mode": "chat_completions",
    }
