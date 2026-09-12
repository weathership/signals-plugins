"""zndx.agent.v1 — Hermes hosts the ``hermes`` agent (AIAgent loop).

Complete/OIP ``capability=agent`` is still an inference *route* to a peer's
``thinking``. The agent itself is this offer. Metabot (and any lattice
caller) discovers it via ServerQuery AGENTS / ListAgents and Runs it over
gRPC — including across hosts. The ACP/SDK transport never leaves this
process.

A Run is a Hermes session: transcript in SessionDB, memories via
MemoryManager, full tools. That is the hermes-only toolchain. Callers do
not reimplement those tools; they delegate.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Iterator

import grpc
import hsengine
from hsengine.engine.generated.zndx.agent.v1 import agent_pb2 as apb
from hsengine.engine.generated.zndx.agent.v1 import agent_pb2_grpc as apb_grpc
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

log = logging.getLogger("hsengine.engine.agents")

AGENT_NAME = "hermes"
PROJECT = "hermes"

_mu = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}


def agent_id() -> str:
    return f"{PROJECT}/{AGENT_NAME}@{hsengine.__version__}"


def _billing() -> "apb.Billing":
    try:
        from hsengine.engine.interactive import is_active

        if is_active():
            return apb.BILLING_TOKEN_METERED
    except Exception:
        pass
    return apb.BILLING_LOCAL


def offer() -> apb.AgentOffer:
    return apb.AgentOffer(
        agent_id=agent_id(),
        project=PROJECT,
        name=AGENT_NAME,
        version=hsengine.__version__,
        transport=apb.AGENT_TRANSPORT_SDK,
        model_capabilities=["thinking", "instruct"],
        mcp=[apb.MCP_TRANSPORT_HTTP],
        workspace=True,
        behaviours=[
            "skills",
            "memory",
            "session_search",
            "terminal",
            "browser",
            "delegate_task",
        ],
        billing=_billing(),
        note=(
            "Hermes agent loop. Delegate with 'have Hermes …' or call this "
            "for skills, memory, files, browser, and lattice tools. Those "
            "tools are not Complete capabilities — they live inside this run."
        ),
    )


def hint() -> zpb.AgentHint:
    o = offer()
    billing = "token-metered" if o.billing == apb.BILLING_TOKEN_METERED else "local"
    if o.billing == apb.BILLING_SUBSCRIPTION:
        billing = "subscription"
    return zpb.AgentHint(
        agent_id=o.agent_id,
        project=o.project,
        name=o.name,
        version=o.version,
        transport="sdk",
        model_capabilities=list(o.model_capabilities),
        billing=billing,
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _event(run_id: str, seq: int, **fields: Any) -> apb.AgentEvent:
    ev = apb.AgentEvent(run_id=run_id, seq=seq, at_unix_ms=_now_ms())
    for key, value in fields.items():
        getattr(ev, key).CopyFrom(value)
    return ev


def _resolve_agent(name: str) -> str:
    wanted = (name or "").strip()
    if not wanted:
        raise ValueError("agent is required")
    aid = agent_id()
    if wanted in (AGENT_NAME, aid, f"{PROJECT}/{AGENT_NAME}"):
        return aid
    raise ValueError(f"this engine hosts {aid}, not {wanted}")


def _run_agent(instruction: str, *, run_id: str, system_prompt: str = "") -> str:
    """One Hermes AIAgent turn. Session id is the run — memories land there."""
    from agent.interactive_cerebras import overlay_runtime
    from run_agent import AIAgent

    ov = overlay_runtime() or {}
    kwargs: dict[str, Any] = {
        "session_id": f"agent-run-{run_id}",
        "quiet_mode": True,
        "skip_background_review": True,
        "platform": "agent-run",
    }
    if ov:
        kwargs.update(
            {
                "base_url": ov["base_url"],
                "api_key": ov["api_key"],
                "provider": ov["provider"],
                "model": ov["model"],
                "api_mode": ov.get("api_mode") or "chat_completions",
            }
        )
    agent = AIAgent(**kwargs)
    agent._end_session_on_close = False
    prompt = instruction
    if system_prompt:
        prompt = f"{system_prompt.strip()}\n\n{instruction}"
    try:
        return str(agent.chat(prompt) or "")
    finally:
        try:
            agent.close()
        except Exception:
            log.warning("hermes agent close failed", exc_info=True)


def iter_run(request: apb.RunRequest) -> Iterator[apb.AgentEvent]:
    """Drive one Run as a sequence of AgentEvents (tests call this directly)."""
    from hsengine.engine.coordination import uuid7

    aid = _resolve_agent(request.agent)
    run_id = (request.run_id or "").strip() or uuid7()
    instruction = (request.instruction or "").strip()
    if not instruction:
        raise ValueError("instruction is required")
    seq = 0
    with _mu:
        _runs[run_id] = {
            "agent_id": aid,
            "state": apb.RUN_RUNNING,
            "started_unix_ms": _now_ms(),
            "ended_unix_ms": 0,
            "error": "",
            "result_text": "",
        }
    seq += 1
    yield _event(
        run_id,
        seq,
        accepted=apb.RunAccepted(
            run_id=run_id,
            agent_id=aid,
            model=request.model_capability or "thinking",
            model_peer="cerebras" if _billing() == apb.BILLING_TOKEN_METERED else "gaius",
            activity_id="",
            workspace_uri=request.workspace_uri or "",
        ),
    )
    try:
        text = _run_agent(
            instruction,
            run_id=run_id,
            system_prompt=request.system_prompt or "",
        )
        seq += 1
        yield _event(
            run_id,
            seq,
            message=apb.Message(turn=1, role="assistant", text=text),
        )
        seq += 1
        done = apb.RunDone(
            state=apb.RUN_COMPLETED,
            stop_reason="end_turn",
            result_text=text,
            usage=apb.Usage(turns=1, wall_ms=0),
        )
        yield _event(run_id, seq, done=done)
        with _mu:
            rec = _runs.get(run_id) or {}
            rec["state"] = apb.RUN_COMPLETED
            rec["ended_unix_ms"] = _now_ms()
            rec["result_text"] = text
            _runs[run_id] = rec
    except Exception as e:
        log.exception("hermes agent run failed")
        seq += 1
        yield _event(
            run_id,
            seq,
            done=apb.RunDone(
                state=apb.RUN_FAILED,
                stop_reason="error",
                error=str(e),
            ),
        )
        with _mu:
            rec = _runs.get(run_id) or {}
            rec["state"] = apb.RUN_FAILED
            rec["ended_unix_ms"] = _now_ms()
            rec["error"] = str(e)
            _runs[run_id] = rec


class AgentsServicer(apb_grpc.AgentsServicer):
    async def ListAgents(self, request, context):
        return apb.ListAgentsResponse(project=PROJECT, agents=[offer()])

    async def Run(self, request, context):
        try:
            events = await asyncio.to_thread(lambda: list(iter_run(request)))
        except ValueError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return
        for ev in events:
            yield ev

    async def Cancel(self, request, context):
        rid = (request.run_id or "").strip()
        with _mu:
            rec = _runs.get(rid)
            if rec is None:
                return apb.CancelResponse(
                    accepted=False, state=apb.RUN_STATE_UNSPECIFIED, error="unknown run"
                )
            rec["state"] = apb.RUN_CANCELLED
            rec["ended_unix_ms"] = _now_ms()
        return apb.CancelResponse(accepted=True, state=apb.RUN_CANCELLED)

    async def GetRun(self, request, context):
        rid = (request.run_id or "").strip()
        with _mu:
            rec = dict(_runs.get(rid) or {})
        if not rec:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"unknown run {rid}")
            return apb.RunRecord()
        return apb.RunRecord(
            run_id=rid,
            agent_id=str(rec.get("agent_id") or ""),
            state=int(rec.get("state") or 0),
            started_unix_ms=int(rec.get("started_unix_ms") or 0),
            ended_unix_ms=int(rec.get("ended_unix_ms") or 0),
            error=str(rec.get("error") or ""),
        )
