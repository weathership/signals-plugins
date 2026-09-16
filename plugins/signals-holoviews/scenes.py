"""Scene data for AgentRTC program stills.

First pass is plain HoloViews (when installed) or matplotlib. No Datashader.
Aegir aperture chords load if the federated workspace package is importable.
"""
from __future__ import annotations

import json
from typing import Any

# Tiny SKOS-shaped aperture so the chord is real without Aegir on PATH.
DEMO_NODES = [
    "Material",
    "Process",
    "Quantity",
    "Specimen",
    "Instrument",
    "Observation",
]
DEMO_EDGES = [
    (0, 1, 2),
    (0, 2, 3),
    (1, 3, 2),
    (2, 5, 2),
    (3, 4, 1),
    (4, 5, 2),
    (1, 5, 1),
]


def parse_data(raw: str) -> tuple[list[str], list[tuple[int, int, float]]]:
    text = (raw or "").strip()
    if not text:
        return list(DEMO_NODES), list(DEMO_EDGES)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return list(DEMO_NODES), list(DEMO_EDGES)
    nodes = [str(n) for n in (payload.get("nodes") or []) if str(n).strip()]
    edges: list[tuple[int, int, float]] = []
    for row in payload.get("edges") or []:
        if isinstance(row, dict):
            s, t, w = row.get("source"), row.get("target"), row.get("value", 1)
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            s, t = row[0], row[1]
            w = row[2] if len(row) > 2 else 1
        else:
            continue
        try:
            edges.append((int(s), int(t), float(w)))
        except (TypeError, ValueError):
            continue
    if not nodes:
        return list(DEMO_NODES), list(DEMO_EDGES)
    return nodes, edges or list(DEMO_EDGES)


def aperture_nodes_edges(source: str = "") -> tuple[list[str], list[tuple[int, int, float]], str]:
    """Prefer a live Aegir aperture substrate; else the demo chord."""
    src = (source or "").strip().lower()
    if src in ("", "demo", "fixture"):
        return list(DEMO_NODES), list(DEMO_EDGES), "demo"
    try:
        from aegir.viz.lineup_app import _aperture_substrate
    except Exception:
        return list(DEMO_NODES), list(DEMO_EDGES), "demo"
    try:
        anchors = _aperture_substrate("scratch", "")
    except Exception:
        return list(DEMO_NODES), list(DEMO_EDGES), "demo"
    return _anchors_to_chord(anchors)


def _anchors_to_chord(anchors: dict[str, Any]) -> tuple[list[str], list[tuple[int, int, float]], str]:
    from itertools import combinations

    rows: list[dict[str, Any]] = []
    df: dict[str, int] = {}
    for lbl, entry in (anchors or {}).items():
        if not isinstance(entry, dict):
            continue
        frag = str(entry.get("iri") or lbl).rsplit("#", 1)[-1]
        cons = {
            x.get("iri")
            for x in (entry.get("constituents") or [])
            if isinstance(x, dict) and x.get("kind") == "concept" and x.get("iri")
        }
        rows.append({"frag": frag, "cons": cons})
        for c in cons:
            df[c] = df.get(c, 0) + 1
    rows.sort(key=lambda r: r["frag"])
    if len(rows) < 2:
        return list(DEMO_NODES), list(DEMO_EDGES), "demo"
    idx = {r["frag"]: i for i, r in enumerate(rows)}
    edges: list[tuple[int, int, float]] = []
    for a, b in combinations(rows, 2):
        n = sum(1 for c in a["cons"] & b["cons"] if df.get(c, 9) <= 3)
        if n:
            edges.append((idx[a["frag"]], idx[b["frag"]], float(n)))
    nodes = [r["frag"][:28] for r in rows]
    if not edges:
        return list(DEMO_NODES), list(DEMO_EDGES), "demo"
    return nodes, edges, "aegir"
