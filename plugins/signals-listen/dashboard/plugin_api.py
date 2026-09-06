"""signals-listen dashboard API, mounted at /api/plugins/signals-listen/.

Signaling JSON in, HermesEngine.WebRtcOffer out. Media never crosses this
HTTP path — UDP is engine-local. User plugins must be in plugins.enabled
or this module is not imported.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import grpc
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

log = logging.getLogger("signals_listen")

router = APIRouter()

_POSTER = Path(__file__).resolve().parent / "poster.jpg"


def _engine_target() -> str:
    return os.environ.get("HERMES_ENGINE_TARGET") or "127.0.0.1:50651"


def _stubs():
    from hsengine.engine.generated import hermes_engine_pb2 as pb
    from hsengine.engine.generated import hermes_engine_pb2_grpc as pb_grpc

    return pb, pb_grpc


def poster_path() -> Path | None:
    return _POSTER if _POSTER.is_file() else None


class OfferBody(BaseModel):
    sdp: str = Field(min_length=1)
    type: str = "offer"


def _http_for_rpc(err: grpc.RpcError) -> HTTPException:
    code = err.code()
    detail = err.details() or str(err)
    mapping = {
        grpc.StatusCode.FAILED_PRECONDITION: 412,
        grpc.StatusCode.UNIMPLEMENTED: 501,
        grpc.StatusCode.UNAVAILABLE: 503,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    }
    return HTTPException(status_code=mapping.get(code, 502), detail=detail)


async def engine_status() -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        reply = await stub.EngineStatus(pb.EngineStatusRequest(), timeout=3)
    caps = list(reply.capabilities)
    return {
        "ok": True,
        "engine": target,
        "project": reply.project,
        "version": reply.version,
        "capabilities": caps,
        "webrtc": "webrtc" in caps,
        "poster": "/dashboard-plugins/signals-listen/poster.jpg",
    }


async def webrtc_offer(sdp: str, typ: str = "offer") -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        reply = await stub.WebRtcOffer(
            pb.WebRtcOfferRequest(sdp=sdp, type=typ or "offer"),
            timeout=20,
        )
    return {
        "sdp": reply.sdp,
        "type": reply.type,
        "session_id": reply.session_id,
        "source": reply.source,
    }


@router.get("/status")
async def status():
    try:
        return await engine_status()
    except grpc.RpcError as e:
        log.warning("listen status rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/offer")
async def offer(body: OfferBody):
    try:
        return await webrtc_offer(body.sdp, body.type)
    except grpc.RpcError as e:
        log.warning("listen offer rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@router.get("/poster")
async def poster():
    path = poster_path()
    if path is None:
        raise HTTPException(status_code=404, detail="no Gaius card still")
    return FileResponse(path, media_type="image/jpeg")
