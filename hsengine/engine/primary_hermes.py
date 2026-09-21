"""Run the configured primary Hermes agent from an AgentRTC voice tool.

Spoken Ripley stays on Cerebras. This hop is the CLI agent: Grok via
xai-oauth (or whatever ``config.yaml`` model.provider is), hermes-cli
tools plus kanban. Same SessionDB as the call.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("hsengine.engine.primary_hermes")


@contextmanager
def _kanban_visible() -> Iterator[None]:
    """Kanban tools are check_fn-gated on ``kanban`` in config toolsets."""
    from tools import kanban_tools
    from tools.registry import invalidate_check_fn_cache

    orig = kanban_tools._profile_has_kanban_toolset
    kanban_tools._profile_has_kanban_toolset = lambda: True
    invalidate_check_fn_cache()
    try:
        yield
    finally:
        kanban_tools._profile_has_kanban_toolset = orig
        invalidate_check_fn_cache()


def _cli_toolsets() -> list[str]:
    try:
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools

        names = set(_get_platform_tools(load_config(), "cli"))
    except Exception:
        names = {"hermes-cli"}
    names.add("kanban")
    return sorted(names)


def _primary_runtime() -> tuple[str, dict[str, Any]]:
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider

    cfg = load_config()
    block = cfg.get("model") if isinstance(cfg.get("model"), dict) else {}
    model = str(block.get("default") or "").strip()
    provider = str(block.get("provider") or "").strip()
    runtime = resolve_runtime_provider(
        requested=provider or None,
        target_model=model or None,
        explicit_base_url=str(block.get("base_url") or "").strip() or None,
        explicit_api_key=str(block.get("api_key") or "").strip() or None,
    )
    if not isinstance(runtime, dict) or not runtime:
        raise RuntimeError("primary Hermes runtime did not resolve")
    return model, runtime


def run(
    *,
    prompt: str,
    session_id: str | None,
    session_db: Any,
    history: list | None,
) -> dict[str, Any]:
    from hsengine.overlay import primary_runtime
    from run_agent import AIAgent

    model, runtime = _primary_runtime()
    with primary_runtime(), _kanban_visible():
        agent = AIAgent(
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            requested_provider=runtime.get("requested_provider"),
            api_mode=runtime.get("api_mode"),
            model=model,
            credential_pool=runtime.get("credential_pool"),
            enabled_toolsets=_cli_toolsets(),
            quiet_mode=True,
            skip_background_review=True,
            session_id=session_id,
            session_db=session_db,
            platform="agent-rtc",
        )
        agent._end_session_on_close = False
        try:
            result = agent.run_conversation(prompt, conversation_history=history)
            text = str((result or {}).get("final_response") or "")
        finally:
            try:
                agent.close()
            except Exception:
                log.warning("primary hermes agent close failed", exc_info=True)
    try:
        from hsengine.engine.webrtc_kanban import refresh_view

        refresh_view()
    except Exception:
        log.debug("kanban view refresh skipped", exc_info=True)
    return {
        "ok": True,
        "text": text,
        "model": model or runtime.get("model") or "",
        "provider": runtime.get("provider") or "",
        "session_id": session_id or "",
    }
