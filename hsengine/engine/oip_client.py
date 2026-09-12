"""OIP client proxy — call plain KServe / peer engines via ModelInfer."""
from __future__ import annotations

import logging
import time
from typing import Iterator

import grpc

from hsengine.config import get_int, get_list
from hsengine.engine import oip_tensors as tensors
from hsengine.engine.federation import CompleteResult
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2 as oip_pb
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2_grpc as oip_grpc

log = logging.getLogger("hsengine.engine.oip_client")


def oip_peers() -> list[str]:
    try:
        raw = get_list("hermes.engine.oip.peers")
        peers = [str(p).strip() for p in raw if str(p).strip()]
        if peers:
            return peers
    except Exception:
        pass
    from hsengine.engine import federation

    return federation.federation_peers()


def configured_oip_peers() -> list[str]:
    from hsengine.engine import federation

    try:
        return federation.as_str_list(get_list("hermes.engine.oip.peers"))
    except Exception:
        return []


def model_ready(peer: str, name: str, timeout: float = 3.0) -> bool:
    try:
        with grpc.insecure_channel(peer) as ch:
            stub = oip_grpc.GRPCInferenceServiceStub(ch)
            resp = stub.ModelReady(oip_pb.ModelReadyRequest(name=name), timeout=timeout)
        return bool(resp.ready)
    except Exception as e:
        log.debug("ModelReady %s/%s failed: %s", peer, name, e)
        return False


def _timeout_s() -> float:
    try:
        return float(get_int("hermes.engine.oip.timeout_s"))
    except Exception:
        try:
            return float(get_int("hermes.engine.federation.timeout_s"))
        except Exception:
            return 120.0


def model_infer(
    peer: str,
    *,
    model_name: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    capability: str = "",
    timeout: float | None = None,
) -> CompleteResult:
    timeout = _timeout_s() if timeout is None else timeout
    t0 = time.perf_counter()
    req = tensors.build_infer_request(
        oip_pb,
        model_name=model_name or capability or "agent",
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        capability=capability or model_name,
    )
    with grpc.insecure_channel(peer) as ch:
        stub = oip_grpc.GRPCInferenceServiceStub(ch)
        resp = stub.ModelInfer(req, timeout=timeout)
    text, reasoning = tensors.response_text(resp)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    model = model_name
    if "model" in resp.parameters:
        p = resp.parameters["model"]
        if p.WhichOneof("parameter_choice") == "string_param" and p.string_param:
            model = p.string_param
    finish = "stop"
    if "finish_reason" in resp.parameters:
        p = resp.parameters["finish_reason"]
        if p.WhichOneof("parameter_choice") == "string_param" and p.string_param:
            finish = p.string_param
    return CompleteResult(
        text=text,
        model=model,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=wall_ms,
        reasoning_content=reasoning,
        finish_reason=finish,
        peer=f"oip:{peer}",
        capability=capability or model_name or "agent",
    )


def model_infer_federated(
    *,
    model_name: str = "agent",
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    capability: str = "",
) -> CompleteResult:
    peers = oip_peers()
    if not peers:
        raise RuntimeError(
            "DENY: no OIP peers configured "
            "(hermes.engine.oip.peers / hermes.engine.federation.peers)"
        )
    errors: list[str] = []
    for peer in peers:
        try:
            result = model_infer(
                peer,
                model_name=model_name,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                capability=capability or model_name,
            )
            log.info("OIP ModelInfer ok peer=%s model=%s", peer, result.model)
            return result
        except grpc.RpcError as e:
            err = f"{peer}: {e.code()} {e.details()}"
            log.warning("OIP peer failed: %s", err)
            errors.append(err)
        except Exception as e:
            err = f"{peer}: {e}"
            log.warning("OIP peer failed: %s", err)
            errors.append(err)
    raise RuntimeError("DENY: all OIP peers failed for ModelInfer: " + "; ".join(errors))


def model_stream_infer(
    peer: str,
    *,
    model_name: str,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    capability: str = "",
    timeout: float | None = None,
) -> Iterator[CompleteResult]:
    timeout = _timeout_s() if timeout is None else timeout
    req = tensors.build_infer_request(
        oip_pb,
        model_name=model_name or capability or "agent",
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        capability=capability or model_name,
    )

    def _requests():
        yield req

    t0 = time.perf_counter()
    try:
        with grpc.insecure_channel(peer) as ch:
            stub = oip_grpc.GRPCInferenceServiceStub(ch)
            for resp in stub.ModelStreamInfer(_requests(), timeout=timeout):
                text, reasoning = tensors.response_text(resp)
                wall_ms = (time.perf_counter() - t0) * 1000.0
                delta_text = ""
                delta_reason = ""
                for out in resp.outputs:
                    raw = b""
                    if out.contents.bytes_contents:
                        raw = out.contents.bytes_contents[0]
                    t = raw.decode("utf-8") if raw else ""
                    if out.name == tensors.T_TEXT_DELTA:
                        delta_text += t
                    elif out.name == tensors.T_REASONING_DELTA:
                        delta_reason += t
                yield CompleteResult(
                    text=delta_text or text,
                    model=model_name,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=wall_ms,
                    reasoning_content=delta_reason or reasoning,
                    finish_reason="",
                    peer=f"oip-stream:{peer}",
                    capability=capability or model_name or "agent",
                )
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.UNIMPLEMENTED:
            log.info("peer %s has no ModelStreamInfer — unary fallback", peer)
            yield model_infer(
                peer,
                model_name=model_name,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                capability=capability,
                timeout=timeout,
            )
            return
        raise
