"""Run the configured primary Hermes agent from an AgentRTC voice tool.

Spoken Ripley stays on Cerebras. This hop is the CLI agent: Grok via
xai-oauth (or whatever ``config.yaml`` model.provider is), CLI tools
including kanban, skills, and cron. Same SessionDB as the call.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("hsengine.engine.primary_hermes")


def _headless_clarify(question: str, choices=None, multi_select=False) -> str:
    """No TTY on the nested hop — do not block the voice loop."""
    prefix = f"[AgentRTC hermes hop: no user at a prompt for {question!r}. "
    if choices:
        what = "subset" if multi_select else "option"
        return f"{prefix}Pick the best {what} from {choices} and continue.]"
    return f"{prefix}Make the most reasonable assumption and continue.]"


@contextmanager
def _primary_surface() -> Iterator[None]:
    """Session-scoped CLI surface: kanban check_fn, cron (HERMES_INTERACTIVE).

    ``get_tool_definitions(quiet_mode=True)`` memoizes the filtered schema, so
    flipping gates without clearing that cache leaves kanban/cron stripped.
    """
    from model_tools import _clear_tool_defs_cache
    from tools import kanban_tools
    from tools.registry import invalidate_check_fn_cache

    orig = kanban_tools._profile_has_kanban_toolset
    kanban_tools._profile_has_kanban_toolset = lambda: True
    prev = os.environ.get("HERMES_INTERACTIVE")
    os.environ["HERMES_INTERACTIVE"] = "1"
    invalidate_check_fn_cache()
    _clear_tool_defs_cache()
    try:
        yield
    finally:
        kanban_tools._profile_has_kanban_toolset = orig
        if prev is None:
            os.environ.pop("HERMES_INTERACTIVE", None)
        else:
            os.environ["HERMES_INTERACTIVE"] = prev
        invalidate_check_fn_cache()
        _clear_tool_defs_cache()


def _cli_toolsets() -> list[str]:
    try:
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools

        names = set(_get_platform_tools(load_config(), "cli"))
    except Exception:
        names = {"hermes-cli"}
    names.add("kanban")
    return sorted(names)


PARTNER_RAILS = (
    "You are a silent Hermes partner on a live AgentRTC call. "
    "Ripley speaks; you are not heard. Do the work with tools "
    "(kanban, skills, cron, files, terminal, browser). "
    "Never mention Grok, Hermes, Bishop, Cerebras, tools, or the machinery. "
    "When you are done, output exactly:\n"
    "STEER: <one or two sentences Ripley can follow on the next spoken turn, or NONE>\n"
    "MONOLOGUE: <first-person in her voice she can speak now, or NONE>"
)


def parse_partner_reply(text: str):
    """Bishop-shaped STEER/MONOLOGUE. Do not dump unstructured operational prose."""
    from hsengine.engine.named_bots import BishopOutcome, parse_bishop_reply, _STEER_LINE, _MONO_LINE

    raw = (text or "").strip()
    if not raw:
        return BishopOutcome()
    if raw.startswith("{") or _STEER_LINE.search(raw) or _MONO_LINE.search(raw):
        return parse_bishop_reply(raw)
    return BishopOutcome()


def offer_steer(steer: str) -> None:
    """Same affordance as Bishop: color the next spoken Ripley turn."""
    text = " ".join((steer or "").split())
    if not text:
        return
    try:
        from hsengine.engine.webrtc_session import HUB

        turns = getattr(HUB, "_turns", None) or {}
        for taker in list(turns.values()):
            if hasattr(taker, "pending_steer"):
                taker.pending_steer = text
                return
    except Exception:
        log.debug("hermes partner steer not offered", exc_info=True)


def _partner_prompt(prompt: str) -> str:
    body = (prompt or "").strip()
    return body + "\n\nWhen you are done with tools, output STEER and MONOLOGUE as specified."


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
    with primary_runtime(), _primary_surface():
        agent = AIAgent(
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            requested_provider=runtime.get("requested_provider"),
            api_mode=runtime.get("api_mode"),
            model=model,
            credential_pool=runtime.get("credential_pool"),
            enabled_toolsets=_cli_toolsets(),
            ephemeral_system_prompt=PARTNER_RAILS,
            quiet_mode=True,
            skip_background_review=True,
            session_id=session_id,
            session_db=session_db,
            platform="agent-rtc",
            clarify_callback=_headless_clarify,
        )
        agent._end_session_on_close = False
        try:
            result = agent.run_conversation(
                _partner_prompt(prompt), conversation_history=history
            )
            raw = str((result or {}).get("final_response") or "")
        finally:
            try:
                agent.close()
            except Exception:
                log.warning("primary hermes agent close failed", exc_info=True)
    try:
        from hsengine.engine.webrtc_kanban import refresh_view, surface_blocked_to_call

        refresh_view()
        surface_blocked_to_call()
    except Exception:
        log.debug("kanban view refresh skipped", exc_info=True)
    outcome = parse_partner_reply(raw)
    offer_steer(outcome.steer)
    speak = outcome.monologue or outcome.steer
    return {
        "ok": True,
        "steer": outcome.steer,
        "monologue": outcome.monologue,
        "text": speak,
        "model": model or runtime.get("model") or "",
        "provider": runtime.get("provider") or "",
        "session_id": session_id or "",
    }
