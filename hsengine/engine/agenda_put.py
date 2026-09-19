"""Put one Agenda item onto Gaius over Engine/PutAgendaItem.

Gaius holds the calendar row. Session materials go to rustfs under
``s3://hermes/resources/<item-id>/`` and are fetched at Connect from Hermes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("hsengine.engine.agenda_put")

_AGENTS = frozenset({"ripley", "grok", "hermes", "bishop", "vasquez", "metabot"})


def _clean_agent(name: str) -> str:
    raw = (name or "").strip().lower().replace(" ", "")
    if raw in _AGENTS:
        return raw
    if raw in {"chat", "cli"}:
        return "grok"
    return "hermes"


def put_agenda_item(
    *,
    title: str,
    body: str = "",
    kind: str = "event",
    intent: str = "session",
    starts_ms: int = 0,
    ends_ms: int = 0,
    tags: list[str] | None = None,
    with_whom: str = "",
    session_prompt: str = "",
    session_materials: str = "",
    origin_agent: str = "ripley",
    origin_project: str = "hermes",
) -> dict[str, Any]:
    """Create an Agenda item on Gaius. Returns the stored item or an error dict."""
    from hsengine.engine import federation
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    heading = (title or "").strip()
    if not heading:
        return {"ok": False, "error": "title required"}
    target = federation.peer_target_for_project("gaius")
    if not target:
        peers = federation.federation_peers()
        target = next((p for p in peers if p.endswith(":50051")), "") or (
            peers[0] if peers else ""
        )
    if not target:
        return {"ok": False, "error": "no Gaius engine target (federation.peers)"}
    if intent == "session" and not starts_ms:
        starts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    item = zpb.AgendaHintItem(
        title=heading,
        body=body or "",
        kind=kind or "event",
        intent=intent or "session",
        starts_ms=int(starts_ms or 0),
        ends_ms=int(ends_ms or 0),
        with_whom=with_whom or "",
    )
    if tags:
        item.tags.extend(str(t) for t in tags)
    req = zpb.PutAgendaItemRequest(
        origin_project=origin_project or "hermes",
        origin_agent=_clean_agent(origin_agent),
        item=item,
    )
    try:
        import grpc

        with grpc.insecure_channel(target) as ch:
            resp = zpb_grpc.EngineStub(ch).PutAgendaItem(req, timeout=15.0)
    except Exception as e:
        log.info("PutAgendaItem at %s failed: %s", target, e)
        return {"ok": False, "error": str(e), "target": target}
    out = {
        "ok": bool(resp.ok),
        "id": resp.item.id if resp.item else "",
        "title": resp.item.title if resp.item else heading,
        "origin_agent": req.origin_agent,
        "target": target,
        "note": resp.note or "",
    }
    if resp.item and resp.item.id:
        out["path"] = resp.item.id
        if (session_prompt or "").strip() or (session_materials or "").strip():
            try:
                from hsengine.engine.resources_store import put_session_materials

                stored = put_session_materials(
                    resp.item.id,
                    prompt=session_prompt,
                    materials=session_materials,
                )
                out["resources"] = stored
            except Exception as e:
                log.warning("rustfs session materials put failed: %s", e)
                out["resources_error"] = str(e)
    if not resp.ok:
        out["error"] = resp.note or "Gaius refused PutAgendaItem"
    return out
