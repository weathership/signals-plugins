"""OpenAI-shaped client that talks lattice OIP (llm_tools_v1) or Complete."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import grpc

from hsengine.engine import oip_tensors as tensors
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2 as oip_pb
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2_grpc as oip_grpc
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

log = logging.getLogger("hsengine.plugins.signals_oip")

HERMES_SKIP_TRANSPORT_WRAP = True
HERMES_SKIP_ASYNC_WRAP = True


def _target(raw: str) -> str:
    return (raw or "").replace("grpc://", "").replace("oip://", "").strip()


def _openai_tool_calls(raw: list[dict[str, Any]] | None) -> list[Any]:
    out: list[Any] = []
    for item in raw or []:
        name = str(item.get("name") or "")
        args = item.get("arguments_json")
        if args is None:
            args = item.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args)
        out.append(
            SimpleNamespace(
                id=str(item.get("id") or ""),
                type="function",
                function=SimpleNamespace(name=name, arguments=args),
            )
        )
    return out


def _message(content: str, tool_calls: list[Any], reasoning: str = "") -> Any:
    msg = SimpleNamespace(
        role="assistant",
        content=content or None,
        tool_calls=tool_calls or None,
    )
    if reasoning:
        msg.reasoning = reasoning
    return msg


class _Completions:
    def __init__(self, outer: "SignalsOipClient"):
        self._outer = outer

    def create(self, **kwargs: Any) -> Any:
        return self._outer._create(**kwargs)


class _Chat:
    def __init__(self, outer: "SignalsOipClient"):
        self.completions = _Completions(outer)


class SignalsOipClient:
    """Minimal OpenAI client surface for AIAgent (create_client seam)."""

    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, **client_kwargs: Any):
        self.api_key = client_kwargs.get("api_key") or "signals"
        self.base_url = str(client_kwargs.get("base_url") or "")
        self.timeout = client_kwargs.get("timeout") or 1200
        self.chat = _Chat(self)
        self._tools_ext: bool | None = None

    def _peer(self) -> str:
        target = _target(self.base_url)
        if target:
            return target
        from hsengine.config import get_str

        try:
            hub = get_str("hermes.engine.federation.directory")
        except Exception:
            hub = ""
        if not hub:
            import os

            hub = (os.environ.get("SIGNALS_ENGINE_TARGET") or "").strip()
        return _target(hub) or "127.0.0.1:50051"

    def _peer_has_llm_tools(self, peer: str) -> bool:
        if self._tools_ext is not None:
            return self._tools_ext
        try:
            with grpc.insecure_channel(peer) as ch:
                stub = oip_grpc.GRPCInferenceServiceStub(ch)
                meta = stub.ServerMetadata(oip_pb.ServerMetadataRequest(), timeout=4)
            self._tools_ext = tensors.EXT_LLM_TOOLS in list(meta.extensions)
        except Exception:
            self._tools_ext = False
        return self._tools_ext

    def _create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            raise NotImplementedError("signals OIP client is unary in v1; disable streaming")
        messages = list(kwargs.get("messages") or [])
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice") or ""
        if not isinstance(tool_choice, str):
            tool_choice = json.dumps(tool_choice)
        model = str(kwargs.get("model") or "thinking")
        prompt = ""
        system_prompt = ""
        for msg in messages:
            role = (msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")) or ""
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "") or ""
            if role == "system" and not system_prompt:
                system_prompt = content if isinstance(content, str) else json.dumps(content)
            elif role == "user":
                prompt = content if isinstance(content, str) else json.dumps(content)
        tools_json = json.dumps(tools) if tools else ""
        messages_json = json.dumps(messages) if messages else ""
        peer = self._peer()
        timeout = float(kwargs.get("timeout") or self.timeout or 1200)
        if tools_json and self._peer_has_llm_tools(peer):
            text, reasoning, calls, finish, model_out = self._via_oip(
                peer,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                tools_json=tools_json,
                messages_json=messages_json,
                tool_choice=tool_choice,
                timeout=timeout,
            )
        else:
            text, reasoning, calls, finish, model_out = self._via_complete(
                peer,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                tools_json=tools_json,
                messages_json=messages_json,
                tool_choice=tool_choice,
                timeout=timeout,
            )
        choice = SimpleNamespace(
            index=0,
            finish_reason=finish or ("tool_calls" if calls else "stop"),
            message=_message(text, _openai_tool_calls(calls), reasoning),
        )
        return SimpleNamespace(
            id="signals-oip",
            model=model_out or model,
            choices=[choice],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )

    def _via_oip(
        self,
        peer: str,
        *,
        model: str,
        prompt: str,
        system_prompt: str,
        tools_json: str,
        messages_json: str,
        tool_choice: str,
        timeout: float,
    ) -> tuple[str, str, list[dict[str, Any]], str, str]:
        req = tensors.build_infer_request(
            oip_pb,
            model_name=model,
            prompt=prompt,
            system_prompt=system_prompt,
            tools_json=tools_json,
            messages_json=messages_json,
            tool_choice=tool_choice,
            capability=model,
        )
        with grpc.insecure_channel(peer) as ch:
            stub = oip_grpc.GRPCInferenceServiceStub(ch)
            resp = stub.ModelInfer(req, timeout=timeout)
        text, reasoning = tensors.response_text(resp)
        raw = tensors.response_tool_calls_json(resp)
        calls: list[dict[str, Any]] = []
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                calls = [c for c in parsed if isinstance(c, dict)]
        finish = "stop"
        if "finish_reason" in resp.parameters:
            p = resp.parameters["finish_reason"]
            if p.WhichOneof("parameter_choice") == "string_param":
                finish = p.string_param or finish
        model_out = model
        if "model" in resp.parameters:
            p = resp.parameters["model"]
            if p.WhichOneof("parameter_choice") == "string_param" and p.string_param:
                model_out = p.string_param
        return text, reasoning, calls, finish, model_out

    def _via_complete(
        self,
        peer: str,
        *,
        model: str,
        prompt: str,
        system_prompt: str,
        tools_json: str,
        messages_json: str,
        tool_choice: str,
        timeout: float,
    ) -> tuple[str, str, list[dict[str, Any]], str, str]:
        req = zpb.CompleteRequest(
            capability=model if model in ("thinking", "instruct", "agent") else "thinking",
            prompt=prompt or "",
            system_prompt=system_prompt or "",
            tools_json=tools_json or "",
            messages_json=messages_json or "",
            tool_choice=tool_choice or "",
        )
        with grpc.insecure_channel(peer) as ch:
            stub = zpb_grpc.EngineStub(ch)
            resp = stub.Complete(req, timeout=timeout)
        calls = [
            {
                "id": tc.id,
                "name": tc.name,
                "arguments_json": tc.arguments_json,
            }
            for tc in resp.tool_calls
        ]
        return (
            resp.text or "",
            resp.reasoning_content or "",
            calls,
            resp.finish_reason or "",
            resp.model or model,
        )
