# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""Match Aegir's qualified offsets back onto the AgentRTC text we already hold.

The stream itself is Aegir's AdmitSession. This module does not cut windows
and does not import Aegir. A transport failure leaves the transcript in place.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("hsengine.engine.sdg_aperture")

DISPLAY_KIND = "sdg"


def links_in_message(message_start: int, message_text: str, admissions: list[dict]) -> list[dict]:
    """Character ranges inside one message. Offsets on the wire are into the session concatenation."""

    message = message_text or ""
    message_end = message_start + len(message)
    links = []
    for admission in admissions:
        start = max(int(admission.get("start") or 0), message_start)
        end = min(int(admission.get("end") or 0), message_end)
        if end <= start:
            continue
        iri = str(admission.get("genus_iri") or "")
        if not iri:
            continue
        links.append(
            {
                "start": start - message_start,
                "end": end - message_start,
                "genus_iri": iri,
                "genus_code": str(admission.get("genus_code") or ""),
                "genus_label": str(admission.get("genus_label") or ""),
                "rel_margin_h": admission.get("rel_margin_h"),
                "tau": admission.get("tau"),
            }
        )
    return links


def slice_for_mistral(message_text: str, link: dict) -> str:
    return (message_text or "")[int(link["start"]) : int(link["end"])]


def attach(message_text: str, links: list[dict], *, workflow_name: str = "", deliverable: dict | None = None) -> dict:
    """Metadata for the assistant row. An empty workflow name does not invent an IRI."""

    stamped = []
    for link in links:
        row = dict(link)
        if workflow_name and deliverable:
            iri = str(deliverable.get("sdg_iri") or "")
            offered = {str(item) for item in (deliverable.get("offered") or [])}
            if iri and (not offered or iri in offered):
                row["sdg.iri"] = iri
                if deliverable.get("confidence") is not None:
                    row["semantica.confidence"] = deliverable.get("confidence")
        stamped.append(row)
    return {"links": stamped, "text_len": len(message_text or "")}


def stamp_message(db: Any, session_id: str, content: str, metadata: dict, *, role: str = "assistant") -> bool:
    """Write the links onto the row that holds this text. A missing writer returns false."""

    writer = getattr(db, "set_latest_matching_message_display_kind", None)
    if writer is None:
        return False
    try:
        return bool(writer(session_id, role=role, content=content, display_kind=DISPLAY_KIND, display_metadata=metadata))
    except Exception:
        log.warning("sdg link stamp failed", exc_info=True)
        return False


def metadata_json(metadata: dict) -> str:
    return json.dumps(metadata, sort_keys=True)
