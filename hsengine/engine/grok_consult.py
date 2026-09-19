"""Occasional Grok consult via the Hermes xAI subscription (xai-oauth).

Spoken Ripley stays on Cerebras. This is a second opinion when the
thread is looping or the undertaking is too complex for one Qwen turn.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("hsengine.engine.grok_consult")

DEFAULT_MODEL = "grok-4.6"
DEFAULT_BASE = "https://api.x.ai/v1"
MAX_TOKENS = 2048
DEFAULT_SYSTEM = (
    "You are a consult for an AgentRTC conversation "
    "(Ripley/Bishop/Vasquez). Be specific. Do not greet. "
    "Name the stuck distinction, then one next move."
)


def grok_available() -> bool:
    try:
        from tools.xai_http import has_xai_credentials

        return bool(has_xai_credentials())
    except Exception:
        return False


def configured_model() -> str:
    try:
        from hermes_cli.config import load_config

        block = load_config().get("model") or {}
        if isinstance(block, dict):
            name = str(block.get("default") or "").strip()
            if name:
                return name
    except Exception:
        pass
    try:
        from hsengine.config import get_str

        name = get_str("hermes.engine.webrtc.interactive.grok_model")
        if name:
            return name
    except Exception:
        pass
    return DEFAULT_MODEL


def consult(
    *,
    question: str,
    context: str = "",
    system: str = "",
    max_tokens: int = 0,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "question required"}
    try:
        from tools.xai_http import resolve_xai_http_credentials

        creds = resolve_xai_http_credentials(prefer_api_key=False)
    except Exception as e:
        return {"ok": False, "error": f"xAI credentials unavailable: {e}"}
    token = str(creds.get("api_key") or "").strip()
    base = str(creds.get("base_url") or DEFAULT_BASE).rstrip("/")
    if not token:
        return {"ok": False, "error": "no xAI bearer (hermes auth add xai-oauth)"}
    model = configured_model()
    user = q
    if context.strip():
        user = f"{q}\n\nContext from this call:\n{context.strip()[:8000]}"
    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        from tools.xai_http import hermes_xai_user_agent

        headers["User-Agent"] = hermes_xai_user_agent()
    except Exception:
        pass
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (system or "").strip() or DEFAULT_SYSTEM,
            },
            {"role": "user", "content": user},
        ],
        "max_tokens": int(max_tokens) if max_tokens else MAX_TOKENS,
        "temperature": 0.4,
    }
    try:
        with httpx.Client(timeout=90.0) as client:
            r = client.post(f"{base}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.debug("grok consult failed", exc_info=True)
        return {"ok": False, "error": str(e), "model": model}
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    text = str(msg.get("content") or "").strip()
    if not text:
        text = str(msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    usage = data.get("usage") or {}
    return {
        "ok": bool(text),
        "text": text,
        "model": data.get("model") or model,
        "provider": creds.get("provider") or "xai-oauth",
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }
