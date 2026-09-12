"""Capability router for Complete — lives only in the engine.

DEPRECATED(federation sole path): long-term portable inference is KServe OIP
(server face + client proxy + ModelStreamInfer); Complete is the transitional hop.

Hermes does not host GPU models. ``agent`` / ``instruct`` route to lattice peers
(gaius ``thinking``, aegir ``instruct``) via OIP when ready, else Engine/Complete.
"""
from __future__ import annotations

import logging

import grpc

from hsengine.engine import federation, oip_client
from hsengine.engine.federation import CompleteResult

log = logging.getLogger("hsengine.engine.complete")


def complete(
    *,
    capability: str = "agent",
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    json_schema: str = "",
) -> CompleteResult:
    cap = (capability or "agent").strip() or "agent"

    from hsengine.engine import interactive

    # Dialog / Hermes-agent fast reasoning is Cerebras while AgentRTC is on.
    # Thinking stays on Gaius (GPUs 0–3).
    if interactive.is_active() and cap in ("agent", "instruct"):
        return interactive.complete_cerebras(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if oip_client.configured_oip_peers():
        try:
            return oip_client.model_infer_federated(
                model_name=cap,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                capability=cap,
            )
        except Exception as e:
            log.warning("configured OIP peers failed, planning federation routes: %s", e)

    return complete_routes(
        cap,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        json_schema=json_schema,
    )


def complete_routes(
    capability: str,
    *,
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    json_schema: str = "",
) -> CompleteResult:
    cap = federation.normalize_capability(capability)
    if not federation.federation_peers():
        raise RuntimeError(
            "DENY: no federation peers configured "
            "(hermes.engine.federation.peers) — cannot Complete"
        )
    routes = federation.plan_routes(cap)
    if not routes:
        raise RuntimeError("DENY: " + federation.no_route_reason(cap))
    errors: list[str] = []
    for route in routes:
        if oip_client.model_ready(route.peer, route.capability):
            try:
                result = oip_client.model_infer(
                    route.peer,
                    model_name=route.capability,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    capability=route.capability,
                )
                log.info("Complete via OIP route=%s served=%s", route.label, result.model)
                return result
            except Exception as e:
                err = f"{route.label} oip: {e}"
                log.warning("OIP route failed: %s", err)
                errors.append(err)
        try:
            result = federation.complete_on_peer(
                route.peer,
                capability=cap,
                peer_capability=route.capability,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_schema=json_schema,
            )
            log.info(
                "Complete ok route=%s served=%s tokens=%s",
                route.label,
                result.model,
                result.completion_tokens,
            )
            return result
        except grpc.RpcError as e:
            err = f"{route.label}: {e.code().name} {e.details()}"
            log.warning("Complete route failed: %s", err)
            errors.append(err)
        except Exception as e:
            err = f"{route.label}: {type(e).__name__}: {e}"
            log.warning("Complete route failed: %s", err)
            errors.append(err)
    raise RuntimeError(
        "DENY: all federation routes failed for Complete: " + "; ".join(errors)
    )
