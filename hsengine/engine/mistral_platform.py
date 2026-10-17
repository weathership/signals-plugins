"""Mistral as a zndx.platform.v1 platform held by this engine.

Hermes and every other lattice peer call this process over gRPC. This
module is the only place that turns a platform verb into a Mistral HTTP
call. The credential never leaves the engine.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

import grpc

from hsengine.engine.generated.zndx.platform.v1 import platform_pb2 as ppb
from hsengine.engine.generated.zndx.platform.v1 import platform_pb2_grpc as ppb_grpc
from hsengine.engine.mistral_agents import api_key

VENDOR = "mistral"
PROJECT = "hermes"
ACCOUNT = "hermes"
_PRODUCTS = ("document", "workflow")


def hosted() -> bool:
    return bool(api_key())


def platform_id() -> str:
    return f"{PROJECT}/{VENDOR}@{ACCOUNT}"


def offer() -> ppb.PlatformOffer:
    return ppb.PlatformOffer(
        platform_id=platform_id(),
        project=PROJECT,
        vendor=VENDOR,
        account=ACCOUNT,
        # An API key bills per call. Callers may refuse token-metered.
        billing=ppb.BILLING_TOKEN_METERED,
        products=list(_PRODUCTS),
        note=(
            "Document OCR and workflow execution. instruction is not used; "
            "Call.input_json carries the verb payload. The credential stays "
            "on this engine. A call claims no GPU."
        ),
    )


def hint() -> ppb.PlatformHint:
    o = offer()
    return ppb.PlatformHint(
        platform_id=o.platform_id,
        project=o.project,
        vendor=o.vendor,
        account=o.account,
        billing="token-metered",
        products=list(o.products),
    )


def verbs() -> list[str]:
    return [
        "document.analyze",
        "workflow.execute",
        "workflow.get",
        "workflow.list",
    ]


def _input(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("input_json must be a JSON object") from exc
    if not isinstance(data, dict):
        raise ValueError("input_json must be a JSON object")
    if len(text.encode("utf-8")) > 1_048_576:
        raise ValueError("input_json exceeds 1 MiB")
    return data


def _now_ms() -> int:
    return int(time.time() * 1000)


def _event(call_id: str, seq: int, **fields: Any) -> ppb.PlatformEvent:
    ev = ppb.PlatformEvent(call_id=call_id, seq=seq, at_unix_ms=_now_ms())
    for key, value in fields.items():
        getattr(ev, key).CopyFrom(value)
    return ev


def _dispatch(product: str, verb: str, foreign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from hsengine.engine import source_drop as drop

    secret = api_key()
    if not secret:
        raise RuntimeError("MISTRAL_API_KEY is unset")
    if product == "document" and verb == "analyze":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("document.analyze requires input_json.url")
        kind = str(payload.get("kind") or "").strip() or drop.classify(url)
        if kind not in drop._CURATED:
            raise ValueError(
                "document.analyze accepts an arXiv, bioRxiv, or medRxiv URL"
            )
        # The execution is what Studio lists under Executions. Inline OCR
        # never creates one.
        name = str(payload.get("name") or "").strip() or drop.signals_preprints_name() or "signals-preprint-analysis"
        started = drop.execute_workflow(
            name,
            {"url": drop.pdf_url_for(url, kind), "kind": kind},
            wait=True,
            key=secret,
        )
        analysis = started.get("result")
        if not isinstance(analysis, dict):
            raise RuntimeError("workflow completed without an analysis object")
        written = drop.write_kb(analysis)
        return {
            **analysis,
            "execution_id": started.get("execution_id") or "",
            "workflow": name,
            "wiki": written.get("relpath") or "",
        }
    if product == "workflow" and verb == "execute":
        name = str(payload.get("name") or "").strip() or drop.signals_preprints_name()
        if not name:
            raise ValueError("workflow.execute requires input_json.name")
        wait = payload.get("wait", True)
        if not isinstance(wait, bool):
            raise ValueError("input_json.wait must be a boolean")
        raw_input = payload.get("input")
        if raw_input is None:
            url = str(payload.get("url") or "").strip()
            kind = str(payload.get("kind") or "").strip() or drop.classify(url)
            if kind not in drop._CURATED:
                raise ValueError(
                    "workflow.execute without input requires an arXiv, bioRxiv, or medRxiv url"
                )
            raw_input = {"url": drop.pdf_url_for(url, kind), "kind": kind}
        elif not isinstance(raw_input, dict):
            raise ValueError("input_json.input must be an object")
        return drop.execute_workflow(name, raw_input, wait=wait, key=secret)
    if product == "workflow" and verb == "get":
        execution_id = (foreign_id or str(payload.get("execution_id") or "")).strip()
        if not execution_id:
            raise ValueError("workflow.get requires foreign_id")
        result = drop.await_signals_preprints(execution_id, key=secret)
        return {"execution_id": execution_id, "status": "COMPLETED", "result": result}
    if product == "workflow" and verb == "list":
        name = drop.signals_preprints_name()
        names = [name] if name else []
        return {"workflows": names}
    raise ValueError(f"this engine does not serve {product}.{verb}")


def iter_call(request: ppb.PlatformCall) -> Iterator[ppb.PlatformEvent]:
    """One platform call. Yields accepted, deliverable, done. No credential."""
    if not hosted():
        raise RuntimeError("MISTRAL_API_KEY is unset")
    product = (request.product or "").strip()
    verb = (request.verb or "").strip()
    if not product or not verb:
        raise ValueError("product and verb are required")
    call_id = (request.call_id or "").strip() or f"call-{_now_ms()}"
    payload = _input(request.input_json)
    seq = 0
    seq += 1
    yield _event(
        call_id,
        seq,
        accepted=ppb.CallAccepted(
            call_id=call_id,
            platform_id=platform_id(),
            product=product,
            verb=verb,
            foreign_id=request.foreign_id or "",
            billing="token-metered",
        ),
    )
    try:
        result = _dispatch(product, verb, request.foreign_id or "", payload)
        body = json.dumps(result, ensure_ascii=False)
        if api_key() and api_key() in body:
            raise RuntimeError("refusing to return a payload that contains the credential")
        seq += 1
        yield _event(
            call_id,
            seq,
            deliverable=ppb.Deliverable(json=body, trajectory_format="json"),
        )
        seq += 1
        yield _event(
            call_id,
            seq,
            done=ppb.CallDone(
                state=ppb.CALL_COMPLETED,
                foreign_id=str(result.get("execution_id") or request.foreign_id or ""),
            ),
        )
    except Exception as exc:
        seq += 1
        message = str(exc)
        secret = api_key()
        if secret:
            message = message.replace(secret, "***")
        yield _event(
            call_id,
            seq,
            done=ppb.CallDone(state=ppb.CALL_FAILED, error=message, stop_reason=type(exc).__name__),
        )


class PlatformsServicer(ppb_grpc.PlatformsServicer):
    """Lattice and local gRPC face. The HTTP client stays in source_drop."""

    async def ListPlatforms(self, request, context):
        if not hosted():
            return ppb.ListPlatformsResponse(project=PROJECT, platforms=[])
        return ppb.ListPlatformsResponse(project=PROJECT, platforms=[offer()])

    async def Describe(self, request, context):
        if not hosted():
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("mistral platform is not configured")
            return ppb.DescribeResponse()
        want = (request.platform_id or request.vendor or VENDOR).strip()
        if want not in {platform_id(), VENDOR, ""}:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"this engine holds {platform_id()}")
            return ppb.DescribeResponse()
        return ppb.DescribeResponse(platform=offer(), verbs=verbs())

    async def Call(self, request, context):
        try:
            events = list(iter_call(request))
        except ValueError as exc:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return
        except RuntimeError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return
        for ev in events:
            yield ev

    async def Cancel(self, request, context):
        return ppb.CancelResponse(accepted=False, state=ppb.CALL_STATE_UNSPECIFIED, error="no durable call")

    async def GetCall(self, request, context):
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details("call records are the Call stream")
        return ppb.CallRecord()
