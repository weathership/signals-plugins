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
    agenda: str = ""
    timezone: str = ""


class HangupBody(BaseModel):
    session_id: str = Field(min_length=1)


class SayBody(BaseModel):
    session_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class StopBody(BaseModel):
    session_id: str = Field(min_length=1)


def _http_for_rpc(err: grpc.RpcError) -> HTTPException:
    code = err.code()
    detail = err.details() or str(err)
    mapping = {
        grpc.StatusCode.FAILED_PRECONDITION: 412,
        grpc.StatusCode.UNIMPLEMENTED: 501,
        grpc.StatusCode.UNAVAILABLE: 503,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.INVALID_ARGUMENT: 400,
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
        "stt": "stt" in caps,
        "poster": "/dashboard-plugins/signals-listen/poster.jpg",
    }


async def webrtc_offer(
    sdp: str, typ: str = "offer", agenda: str = "", timezone: str = ""
) -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        kwargs = {"sdp": sdp, "type": typ or "offer"}
        if agenda:
            kwargs["agenda_id"] = agenda
        if timezone:
            kwargs["timezone"] = timezone
        log.info("listen offer agenda=%s tz=%s", agenda or "-", timezone or "-")
        reply = await stub.WebRtcOffer(
            pb.WebRtcOfferRequest(**kwargs),
            timeout=300,
        )
    return {
        "sdp": reply.sdp,
        "type": reply.type,
        "session_id": reply.session_id,
        "source": reply.source,
    }


async def webrtc_hangup(session_id: str) -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        reply = await stub.WebRtcHangup(
            pb.WebRtcHangupRequest(session_id=session_id),
            timeout=5,
        )
    return {"dropped": bool(reply.dropped), "session_id": session_id}


async def webrtc_say(session_id: str, text: str) -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        reply = await stub.WebRtcUserText(
            pb.WebRtcUserTextRequest(session_id=session_id, text=text),
            timeout=10,
        )
    return {"accepted": bool(reply.accepted), "session_id": session_id}


async def webrtc_stop(session_id: str) -> dict:
    pb, pb_grpc = _stubs()
    target = _engine_target()
    async with grpc.aio.insecure_channel(target) as ch:
        stub = pb_grpc.HermesEngineStub(ch)
        reply = await stub.WebRtcInterrupt(
            pb.WebRtcInterruptRequest(session_id=session_id),
            timeout=5,
        )
    return {
        "ok": bool(reply.ok),
        "speaking": bool(reply.speaking),
        "dropped_samples": int(reply.dropped_samples or 0),
        "session_id": session_id,
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
        return await webrtc_offer(body.sdp, body.type, body.agenda, body.timezone)
    except grpc.RpcError as e:
        log.warning("listen offer rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@router.post("/hangup")
async def hangup(body: HangupBody):
    try:
        return await webrtc_hangup(body.session_id)
    except grpc.RpcError as e:
        log.warning("listen hangup rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@router.post("/say")
async def say(body: SayBody):
    try:
        return await webrtc_say(body.session_id, body.text)
    except grpc.RpcError as e:
        log.warning("listen say rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@router.post("/stop")
async def stop(body: StopBody):
    try:
        return await webrtc_stop(body.session_id)
    except grpc.RpcError as e:
        log.warning("listen stop rpc: %s", e)
        raise _http_for_rpc(e) from e
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@router.get("/poster")
async def poster():
    path = poster_path()
    if path is None:
        raise HTTPException(status_code=404, detail="no Gaius card still")
    return FileResponse(path, media_type="image/jpeg")
