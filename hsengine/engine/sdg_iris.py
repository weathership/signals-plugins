# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""Aperture-point IRIs from the SDG ontology.

System-one may assign only one of these. A label, a notation, or a
fragment is resolved back to the IRI. Anything else is not an assignment.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_CATALOG = Path(__file__).resolve().parent / "data" / "sdg_aperture_iris.json"


@lru_cache(maxsize=1)
def aperture_points() -> tuple[dict, ...]:
    raw = json.loads(_CATALOG.read_text(encoding="utf-8"))
    return tuple(raw)


def subtree(genus_iri: str) -> list[dict]:
    """The admitted genus and the aperture points narrower than it.

    Siblings and the broader concept are not offered. System-one assigns
    inside the match Aegir already made.
    """

    points = list(aperture_points())
    by_iri = {str(point["iri"]): point for point in points}
    hit = by_iri.get(genus_iri or "")
    if hit is None:
        fragment = (genus_iri or "").rsplit("#", 1)[-1]
        hit = next((point for point in points if point["iri"].rsplit("#", 1)[-1] == fragment), None)
    if hit is None:
        return [{"iri": genus_iri, "code": "", "label": "", "broader": ""}] if genus_iri else []
    wanted = {hit["iri"]}
    growing = True
    while growing:
        growing = False
        for point in points:
            if point["iri"] in wanted:
                continue
            if str(point.get("broader") or "") in wanted:
                wanted.add(point["iri"])
                growing = True
    return [point for point in points if point["iri"] in wanted]


def resolve_sdg_iri(raw: str, offered: list[dict] | None = None) -> str:
    """Map a model string onto one offered aperture IRI, or empty."""

    text = (raw or "").strip().strip("<>").strip()
    if not text:
        return ""
    pool = list(offered) if offered else list(aperture_points())
    if text in {str(point.get("iri") or "") for point in pool}:
        return text
    fragment = text.rsplit("#", 1)[-1]
    lowered = text.lower()
    for point in pool:
        iri = str(point.get("iri") or "")
        if iri.rsplit("#", 1)[-1] == fragment:
            return iri
        if str(point.get("code") or "") == text:
            return iri
        if str(point.get("label") or "").lower() == lowered:
            return iri
    return ""
