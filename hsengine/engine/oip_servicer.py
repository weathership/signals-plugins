"""KServe OIP server face — mandatory federation face for signals engines."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

import grpc

from hsengine.engine import complete as complete_svc
from hsengine.engine import federation, oip_client
from hsengine.engine import oip_tensors as tensors
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2 as oip_pb
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2_grpc as oip_grpc

log = logging.getLogger("hsengine.engine.oip_servicer")


class OipInferenceServicer(oip_grpc.GRPCInferenceServiceServicer):
    async def ServerLive(self, request: Any, context: Any) -> Any:
        return oip_pb.ServerLiveResponse(live=True)

    async def ServerReady(self, request: Any, context: Any) -> Any:
        ready, _ = await asyncio.to_thread(federation.inference_ready, "agent")
        return oip_pb.ServerReadyResponse(ready=ready or bool(oip_client.oip_peers()))

    async def ModelReady(self, request: Any, context: Any) -> Any:
        name = (request.name or "").strip() or "agent"
        if federation.is_federated_capability(name) or name == "agent":
            route = await asyncio.to_thread(federation.preferred_route, name)
            return oip_pb.ModelReadyResponse(ready=route is not None)
        return oip_pb.ModelReadyResponse(ready=bool(oip_client.oip_peers()))

    async def ServerMetadata(self, request: Any, context: Any) -> Any:
        return oip_pb.ServerMetadataResponse(
            name="hsengine",
            version="0.1.0",
            extensions=[
                "zndx.signals",
                "model_stream_infer",
                "llm_tensor_profile_v1",
            ],
        )

    async def ModelMetadata(self, request: Any, context: Any) -> Any:
        name = (request.name or "").strip() or "agent"
        resp = oip_pb.ModelMetadataResponse(
            name=name,
            versions=["v1"],
            platform="hsengine",
        )
        for tname in (tensors.T_PROMPT, tensors.T_SYSTEM):
            t = resp.inputs.add()
            t.name = tname
            t.datatype = "BYTES"
            t.shape.extend([-1])
        for tname in (
            tensors.T_COMPLETION,
            tensors.T_REASONING,
            tensors.T_TEXT_DELTA,
            tensors.T_REASONING_DELTA,
        ):
            t = resp.outputs.add()
            t.name = tname
            t.datatype = "BYTES"
            t.shape.extend([-1])
        return resp

    async def ModelInfer(self, request: Any, context: Any) -> Any:
        t0 = time.perf_counter()
        try:
            fields = tensors.extract_llm_inputs(request)
        except Exception as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return oip_pb.ModelInferResponse(model_name=request.model_name, id=request.id)
        if not fields["prompt"]:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("No prompt tensor (name=prompt) provided")
            return oip_pb.ModelInferResponse(model_name=request.model_name, id=request.id)
        try:
            result = await asyncio.to_thread(
                complete_svc.complete,
                capability=fields["capability"],
                prompt=fields["prompt"],
                system_prompt=fields["system_prompt"],
                max_tokens=fields["max_tokens"],
                temperature=fields["temperature"],
            )
        except RuntimeError as e:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details(str(e))
            return oip_pb.ModelInferResponse(model_name=request.model_name, id=request.id)
        except Exception as e:
            log.exception("ModelInfer failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return oip_pb.ModelInferResponse(model_name=request.model_name, id=request.id)
        ms = (time.perf_counter() - t0) * 1000.0
        resp = tensors.build_infer_response(
            oip_pb,
            model_name=result.model or fields["model_name"],
            request_id=fields["request_id"],
            completion=result.text,
            reasoning=result.reasoning_content,
            latency_ms=ms,
            finish_reason=result.finish_reason or "stop",
            peer=result.peer,
        )
        resp.parameters["status_note"].string_param = tensors.STATUS_CONSULTING
        return resp

    async def ModelStreamInfer(
        self, request_iterator: AsyncIterator[Any], context: Any
    ) -> AsyncIterator[Any]:
        async for request in request_iterator:
            fields = tensors.extract_llm_inputs(request)
            if not fields["prompt"]:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("No prompt tensor (name=prompt) provided")
                return
            cap = fields["capability"]
            yield tensors.build_infer_response(
                oip_pb,
                model_name="hsengine",
                request_id=fields["request_id"],
                text_delta=tensors.STATUS_CONSULTING,
                peer="local",
            )
            stream_peer = ""
            stream_model = fields["model_name"]
            try:
                explicit = oip_client.configured_oip_peers()
                if explicit:
                    stream_peer = explicit[0]
                else:
                    route = await asyncio.to_thread(federation.preferred_route, cap)
                    if route is not None and await asyncio.to_thread(
                        oip_client.model_ready, route.peer, route.capability
                    ):
                        stream_peer, stream_model = route.peer, route.capability
                if stream_peer:

                    def _sync_stream():
                        return list(
                            oip_client.model_stream_infer(
                                stream_peer,
                                model_name=stream_model,
                                prompt=fields["prompt"],
                                system_prompt=fields["system_prompt"],
                                max_tokens=fields["max_tokens"],
                                temperature=fields["temperature"],
                                capability=cap,
                            )
                        )

                    results = await asyncio.to_thread(_sync_stream)
                    for r in results:
                        yield tensors.build_infer_response(
                            oip_pb,
                            model_name=r.model,
                            request_id=fields["request_id"],
                            completion=r.text,
                            reasoning=r.reasoning_content,
                            latency_ms=r.latency_ms,
                            finish_reason=r.finish_reason or "stop",
                            peer=r.peer,
                        )
                    continue
            except Exception as e:
                log.warning("OIP federated stream failed: %s", e)

            try:
                result = await asyncio.to_thread(
                    complete_svc.complete,
                    capability=cap,
                    prompt=fields["prompt"],
                    system_prompt=fields["system_prompt"],
                    max_tokens=fields["max_tokens"],
                    temperature=fields["temperature"],
                )
                yield tensors.build_infer_response(
                    oip_pb,
                    model_name=result.model or fields["model_name"],
                    request_id=fields["request_id"],
                    completion=result.text,
                    reasoning=result.reasoning_content,
                    latency_ms=result.latency_ms,
                    finish_reason=result.finish_reason or "stop",
                    peer=result.peer,
                )
            except Exception as e:
                log.exception("ModelStreamInfer complete failed")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return
