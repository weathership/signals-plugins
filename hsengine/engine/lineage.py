"""RecordLineage → Signals Atlas OpenLineage. No private catalog."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from hsengine.config import get_str
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

GURU_NOATLAS = "#LN.00000001.NOATLAS"


def atlas_url() -> str:
    try:
        url = (get_str("hermes.engine.lineage.atlas_url") or "").strip()
    except Exception:
        url = ""
    url = url or "http://127.0.0.1:21010/api/v1/lineage"
    url = url.rstrip("/")
    if not url.endswith("/lineage"):
        url = url + "/lineage"
    return url


def record(event_json: str, event_type: str = "") -> zpb.LineageResponse:
    raw = (event_json or "").strip()
    if not raw:
        return zpb.LineageResponse(
            accepted=False, error=f"{GURU_NOATLAS} LineageRequest.event_json is empty."
        )
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        return zpb.LineageResponse(
            accepted=False, error=f"{GURU_NOATLAS} event_json is not JSON: {e}"
        )
    want = (event_type or "").strip().upper()
    got = str(body.get("eventType") or "").upper()
    if want and got and want != got:
        return zpb.LineageResponse(
            accepted=False,
            error=f"{GURU_NOATLAS} event_type={want!r} != event_json.eventType={got!r}",
        )
    url = atlas_url()
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — lattice Atlas
            if resp.status >= 400:
                snippet = resp.read()[:300].decode("utf-8", errors="replace")
                return zpb.LineageResponse(
                    accepted=False,
                    error=f"{GURU_NOATLAS} Atlas HTTP {resp.status}: {snippet}",
                )
    except urllib.error.HTTPError as e:
        snippet = e.read()[:300].decode("utf-8", errors="replace")
        return zpb.LineageResponse(
            accepted=False, error=f"{GURU_NOATLAS} Atlas HTTP {e.code}: {snippet}"
        )
    except Exception as e:
        return zpb.LineageResponse(
            accepted=False, error=f"{GURU_NOATLAS} Atlas POST {url} failed: {e}"
        )
    return zpb.LineageResponse(accepted=True, error="")
