"""Standalone HoloViews/Bokeh documents for AgentRTC.

Aegir is an optional data source, not a runtime. One Bokeh document per
Chromium tab; the viewer never speaks Bokeh protocol.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

log = logging.getLogger("hsengine.engine.webrtc.viz.apps")

# SKOS-shaped demo so a Connect has a real chord with no federated workspace.
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

# Per Connect scene. The Bokeh handler reads this; query string is only a nonce.
SCENES: dict[str, dict[str, Any]] = {}


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


def put_scene(
    session_id: str,
    *,
    kind: str = "chord",
    title: str = "",
    highlight: str = "",
    source: str = "",
    data: str = "",
) -> dict[str, Any]:
    name = (kind or "chord").strip().lower()
    origin = "demo"
    if name in ("aperture", "aegir", "skos") or (source or "").strip().lower() in (
        "aegir",
        "aperture",
    ):
        nodes, edges, origin = aperture_nodes_edges(source or "aegir")
        name = "chord"
    else:
        nodes, edges = parse_data(data)
        if (data or "").strip():
            origin = "data"
    scene = {
        "kind": name,
        "title": (title or "").strip() or _default_title(name, origin),
        "highlight": (highlight or "").strip(),
        "source": origin,
        "nodes": nodes,
        "edges": edges,
    }
    SCENES[session_id] = scene
    return scene


def _default_title(kind: str, origin: str) -> str:
    if kind == "chord" and origin == "aegir":
        return "Aperture — SKOS constituent lattice"
    if kind == "chord":
        return "Ontology chord"
    return kind.replace("_", " ").title()


def _arg(args: dict, key: str, default: str = "") -> str:
    raw = args.get(key)
    if not raw:
        return default
    item = raw[0] if isinstance(raw, (list, tuple)) else raw
    if isinstance(item, (bytes, bytearray)):
        return item.decode("utf-8", "replace")
    return str(item)


def _hv_obj(scene: dict[str, Any]) -> Any:
    import holoviews as hv
    import pandas as pd

    hv.extension("bokeh", logo=False)
    kind = scene.get("kind") or "chord"
    title = scene.get("title") or ""
    highlight = (scene.get("highlight") or "").strip().lower()
    nodes: list[str] = list(scene.get("nodes") or DEMO_NODES)
    edges: list[tuple[int, int, float]] = list(scene.get("edges") or DEMO_EDGES)
    if kind == "curve":
        xs = list(range(max(2, len(nodes))))
        ys = [1.0 + (i % 5) * 0.3 for i in xs]
        return hv.Curve(list(zip(xs, ys)), "index", "value").opts(
            title=title, width=1100, height=620, bgcolor="#0b0b12"
        )
    if kind == "heatmap":
        data = [(i, j, ((i + j) % 7) / 7.0) for i in range(8) for j in range(8)]
        return hv.HeatMap(data, ["x", "y"], "v").opts(
            title=title, width=720, height=720, cmap="Viridis"
        )
    if kind == "scatter":
        xs = list(range(max(2, len(nodes))))
        ys = [1.0 + (i % 5) * 0.3 for i in xs]
        return hv.Scatter(list(zip(xs, ys)), "index", "value").opts(
            title=title, width=1100, height=620, size=10, bgcolor="#0b0b12"
        )
    node_df = pd.DataFrame({"index": list(range(len(nodes))), "name": nodes})
    if highlight:
        node_df["active"] = [int(highlight in n.lower()) for n in nodes]
    edge_df = pd.DataFrame(edges, columns=["source", "target", "value"])
    return hv.Chord((edge_df, hv.Dataset(node_df, "index"))).opts(
        hv.opts.Chord(
            labels="name",
            node_color="index",
            edge_color="source",
            cmap="Category20",
            width=720,
            height=720,
            title=title,
        )
    )


def modify_doc(doc: Any) -> None:
    """Bokeh FunctionHandler entry: one HoloViews plot as a live document."""
    from bokeh.layouts import column
    from bokeh.models import Div

    args = {}
    ctx = getattr(doc, "session_context", None)
    req = getattr(ctx, "request", None) if ctx is not None else None
    if req is not None:
        args = getattr(req, "arguments", None) or {}
    sid = _arg(args, "session")
    scene = SCENES.get(sid) or put_scene(sid or "anon", kind="chord")
    title = html.escape(str(scene.get("title") or "AgentRTC viz"))
    banner = Div(
        text=(
            f'<div style="color:#e8ecf4;font:16px/1.4 sans-serif;padding:8px 12px;'
            f'background:#0b0b12">{title} · live</div>'
        ),
        width=1280,
    )
    try:
        plot = __import__("holoviews").render(_hv_obj(scene), backend="bokeh")
        doc.add_root(column(banner, plot, sizing_mode="stretch_width"))
    except Exception:
        log.exception("holoviews document failed; banner only")
        doc.add_root(banner)
    doc.title = str(scene.get("title") or "AgentRTC viz")
