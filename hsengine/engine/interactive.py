"""WebRTC interactive posture: agent-rtc + Cerebras dialog.

Enter on the first RTC session, leave on the last hangup. No silent
fallback to local Qwen for the spoken turn.

The posture is DECLARED to the federation as a coordination Activity
(kind ``interactive_session``) through this engine → Signals → Airflow.
Claims on that Activity ARE the YuniKorn configuration; Signals applies
them. This process never talks to Kubernetes. Dialog is Cerebras
(token-metered); moshi takes the agent-rtc GPU; CPU search sits on
compute. Gaius thinking on heavy is not ceded. A session that cannot be
declared is denied. Leaving releases the activity.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import httpx

from hsengine.engine import coordination
from hsengine.engine.federation import CompleteResult
from hsengine.engine.yk_sentinel import QUEUE as AGENT_RTC_QUEUE, moshi_serving

log = logging.getLogger("hsengine.engine.interactive")

_mu = threading.Lock()
_refcount = 0
_active = False
_lease: coordination.ActivityLease | None = None


def is_active() -> bool:
    with _mu:
        return _active


def current_activity() -> dict | None:
    with _mu:
        return dict(_lease.activity) if _lease is not None else None


def _cfg(path: str, default: str) -> str:
    try:
        from hsengine.config import get_str

        value = get_str(path)
        return value if value else default
    except Exception:
        return default


def _cerebras_key() -> str:
    """Cerebras key from HOCON (${?CEREBRAS_API_KEY}) then the process env.

    Secrets enter through secretspec dotenv (gitignored ``.env``), sourced by
    ``hermes-engine.sh`` the same way the dashboard wrapper loads auth.
    """
    key = _cfg("hermes.engine.webrtc.interactive.cerebras_key", "").strip()
    if not key:
        key = (os.environ.get("CEREBRAS_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "DENY: CEREBRAS_API_KEY required to enter agent-rtc interactive posture "
            "(secretspec set --provider dotenv CEREBRAS_API_KEY)"
        )
    return key


def _control_url() -> str:
    return _cfg("hermes.engine.webrtc.interactive.control", "http://127.0.0.1:5081")


_TOOL_ROUNDS = 4
_RECALL_CLIP = 800


def _spoken_context(
    *,
    prompt: str,
    system_prompt: str,
    session_id: str,
    history: list[dict] | None,
) -> tuple[str, list[dict]]:
    """System text plus prior user/assistant turns for a spoken Cerebras call.

    ``history`` wins when the caller already assembled turns. Otherwise the
    AgentRTC SessionDB window is loaded. Overflow is a recall note, not silence.
    """
    from hsengine.engine import session_history

    parts = [system_prompt.strip()] if system_prompt and system_prompt.strip() else []
    prior: list[dict] = []
    meta: dict = {}
    if history is not None:
        prior = [
            {"role": str(m.get("role") or ""), "content": str(m.get("content") or "")}
            for m in history
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
        ]
    elif session_id:
        prior, meta = session_history.prompt_history(session_id, current_user=prompt)
    if prior and prior[-1]["role"] == "user":
        prior = prior[:-1]
    if session_id and int(meta.get("older_count") or 0) > 0:
        parts.append(
            "Earlier turns on this Hermes session are stored "
            f"(older_count={meta['older_count']}, session_id={meta.get('hermes_session_id') or session_history.hermes_session_id(session_id)}). "
            "Call session_search to recall them. Do not invent earlier turns."
        )
    if session_id:
        recalled = session_history.recalled_memory(session_id, prompt)
        if recalled:
            parts.append(
                "Recalled Hermes memory (do not read aloud unless they ask):\n"
                + recalled[:_RECALL_CLIP]
            )
    return "\n\n".join(parts), prior


def _tool_calls_from(msg: dict) -> list[dict]:
    calls = msg.get("tool_calls")
    if isinstance(calls, list) and calls:
        return [c for c in calls if isinstance(c, dict)]
    fn = msg.get("function_call")
    if isinstance(fn, dict) and fn.get("name"):
        return [{"id": "call_0", "type": "function", "function": fn}]
    return []


def _run_tool_calls(calls: list[dict]) -> list[dict]:
    from hsengine.engine import ops

    out: list[dict] = []
    for tc in calls:
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or "")
        raw = fn.get("arguments") or "{}"
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        log.info("cerebras tool %s", name)
        out.append(
            {
                "role": "tool",
                "tool_call_id": str(tc.get("id") or name or "call"),
                "content": ops.dispatch(name, args),
            }
        )
    return out


def complete_cerebras(
    *,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,
    tools: bool = True,
    speak: bool = True,
    session_id: str = "",
    history: list[dict] | None = None,
) -> CompleteResult:
    key = _cerebras_key()
    model = _cfg("hermes.engine.webrtc.interactive.cerebras_model", "qwen-3.8-27b")
    base = _cfg("hermes.engine.webrtc.interactive.cerebras_url", "https://api.cerebras.ai/v1").rstrip("/")
    effort = reasoning_effort or _cfg("hermes.engine.webrtc.interactive.reasoning_effort", "low")
    sys_text, prior = _spoken_context(
        prompt=prompt,
        system_prompt=system_prompt,
        session_id=session_id,
        history=history,
    )
    messages: list[dict] = []
    if sys_text:
        messages.append({"role": "system", "content": sys_text})
    messages.extend(prior)
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    prompt_tokens = 0
    completion_tokens = 0
    text = ""
    finish = "stop"
    reasoning = ""
    data: dict = {}
    with httpx.Client(timeout=120.0) as client:
        for _round in range(_TOOL_ROUNDS if tools else 1):
            body: dict = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "reasoning_effort": effort,
            }
            if tools:
                from hsengine.engine.ops import CEREBRAS_TOOLS

                body["tools"] = CEREBRAS_TOOLS
                body["tool_choice"] = "auto"
            r = client.post(f"{base}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            usage = data.get("usage") or {}
            prompt_tokens += int(usage.get("prompt_tokens") or 0)
            completion_tokens += int(usage.get("completion_tokens") or 0)
            finish = choice.get("finish_reason") or "stop"
            reasoning = (msg.get("reasoning") or reasoning or "").strip()
            calls = _tool_calls_from(msg) if tools else []
            if calls:
                messages.append(msg)
                messages.extend(_run_tool_calls(calls))
                continue
            text = (msg.get("content") or "").strip()
            break
    result = CompleteResult(
        text=text,
        model=data.get("model") or model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=0.0,
        reasoning_content=reasoning,
        finish_reason=finish,
        peer="cerebras",
        capability="thinking",
    )
    spoken = spoken_text(text) if speak else ""
    if spoken:
        threading.Thread(
            target=_speak_cerebras,
            args=(spoken,),
            daemon=True,
            name="cerebras-tts",
        ).start()
    return result


def spoken_text(text: str) -> str:
    """Plain words for Kyutai TTS — no markdown or URLs."""
    import re

    t = " ".join((text or "").split())
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`+", "", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[#*_\[\]]+", " ", t)
    return " ".join(t.split())


def _speak_cerebras(text: str) -> None:
    try:
        from hsengine.engine.webrtc_tts import speak_on_session_boards

        log.info("speaking %r", text[:200])
        speak_on_session_boards(text, source="cerebras")
    except Exception:
        log.exception("Kyutai TTS failed for Cerebras text")


def _moshi_on() -> None:
    url = _control_url().rstrip("/")
    with httpx.Client(timeout=180.0) as client:
        r = client.post(f"{url}/interactive/on")
        if r.status_code >= 400:
            detail = r.text
            raise RuntimeError(f"moshi supervisor {r.status_code}: {detail}")
        body = r.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("error") or "moshi supervisor refused activate")
    if not moshi_serving():
        raise RuntimeError("moshi-server not listening after activate")


def _moshi_off() -> None:
    url = _control_url().rstrip("/")
    try:
        with httpx.Client(timeout=30.0) as client:
            client.post(f"{url}/interactive/off")
    except Exception:
        log.warning("moshi supervisor deactivate failed", exc_info=True)


def _require_declared_workload(activity: dict) -> None:
    """Signals must echo the agent-rtc GPU claim and leave the Activity in force.

    Those claims are the YuniKorn configuration; Signals applies them.
    Cerebras dialog and CPU search are gpu=0 leaves (token-metered / compute)
    and must not appear as a local GPU floor. Missing agent-rtc or a
    non-in-force state means Connect is denied.
    """
    claims = {
        (str(c.get("leaf") or ""), int(c.get("gpu") or 0))
        for c in (activity.get("claims") or [])
        if isinstance(c, dict)
    }
    needed = {(AGENT_RTC_QUEUE, 1)}
    if not needed <= claims:
        raise RuntimeError(
            "DENY: Signals did not echo the agent-rtc workload claims on the "
            f"declared activity (got {sorted(claims)!r})"
        )
    for leaf, gpu in claims:
        if str(leaf).startswith("root.external.") and gpu:
            raise RuntimeError(
                f"DENY: {leaf} is external (Cerebras/token-metered) and must not "
                f"claim local GPUs (gpu={gpu})"
            )
    state = str(activity.get("state") or "")
    if state not in coordination.IN_FORCE:
        raise RuntimeError(
            f"DENY: declared activity is not in force (state={state!r})"
        )


def enter(owner: str = "webrtc") -> None:
    """Enter the interactive posture. Order: declare the Activity to the
    federation (via this engine → Signals; Signals applies the YK claims),
    then start moshi. Any failure releases what was declared and re-raises."""
    global _refcount, _active, _lease
    with _mu:
        _refcount += 1
        if _refcount > 1 and _active:
            return
    _cerebras_key()
    lease: coordination.ActivityLease | None = None
    try:
        lease = coordination.declare_interactive(owner)
        _require_declared_workload(lease.activity)
        _moshi_on()
    except Exception as e:
        with _mu:
            _refcount = max(0, _refcount - 1)
            _active = False
            _lease = None
        _moshi_off()
        if lease is not None:
            lease.release(f"aborted: {str(e)[:120]}")
        raise
    lease.start_renewing()
    with _mu:
        _active = True
        _lease = lease
    try:
        from hsengine.engine.named_bots import ensure_bots

        ensure_bots()
    except Exception:
        log.warning("named bots ensure failed", exc_info=True)
    log.info(
        "agent-rtc interactive posture on (activity %s declared; YK claims asserted while RUNNING)",
        lease.activity_id,
    )


def leave(outcome: str = "hangup") -> None:
    global _refcount, _active, _lease
    with _mu:
        _refcount = max(0, _refcount - 1)
        if _refcount > 0:
            return
        _active = False
        lease, _lease = _lease, None
    _moshi_off()
    if lease is not None:
        lease.release(outcome)
    log.info("agent-rtc interactive posture off; activity released — peers restore their desired sets")


async def enter_async(owner: str = "webrtc") -> None:
    await asyncio.to_thread(enter, owner)


async def leave_async(outcome: str = "hangup") -> None:
    await asyncio.to_thread(leave, outcome)
