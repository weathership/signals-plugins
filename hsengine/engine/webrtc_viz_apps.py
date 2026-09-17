"""Standalone HoloViews/Bokeh documents for AgentRTC.

Aegir is an optional data source, not a runtime. One Bokeh document per
Chromium tab; the viewer never speaks Bokeh protocol.
"""
from __future__ import annotations

import json
import logging
import re
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
# Live Panel panes — in-place object replace, no Chromium navigate.
PANES: dict[str, Any] = {}


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
        "data": (data or "").strip(),
    }
    SCENES[session_id] = scene
    return scene


def replace_object(session_id: str, scene: dict[str, Any]) -> bool:
    """Swap the HoloViews object on the live pane. False if no pane yet."""
    pane = PANES.get(session_id)
    if pane is None:
        return False
    pane.object = _hv_obj(scene)
    log.info("holoviews pane updated session=%s kind=%s", session_id, scene.get("kind"))
    return True


def drop_session(session_id: str) -> None:
    PANES.pop(session_id, None)
    SCENES.pop(session_id, None)


def _default_title(kind: str, origin: str) -> str:
    if kind == "chord" and origin == "aegir":
        return "Aperture — SKOS constituent lattice"
    if kind == "chord":
        return "Ontology chord"
    if kind in ("density", "filings_density"):
        return "Filings density"
    if kind in ("timeline", "filings"):
        return "Filings timeline"
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
        return _curves(scene, title)
    if kind == "heatmap":
        data = [(i, j, ((i + j) % 7) / 7.0) for i in range(8) for j in range(8)]
        return hv.HeatMap(data, ["x", "y"], "v").opts(
            title=title, width=720, height=720, cmap="Viridis"
        )
    if kind in ("density", "filings_density"):
        return _density(scene, title)
    if kind in ("timeline", "filings"):
        return _timeline(scene, title)
    if kind == "scatter":
        return _curves(scene, title, scatter=True)
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
            width=1100,
            height=640,
            title=title,
            bgcolor="#0b0b12",
            label_text_color="#e8ecf4",
        )
    )


_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_FORM_RE = re.compile(
    r"(Form\s*\d+[A-Z]?|8-K|10-K|10-Q|13G/?A?|S-\d+|4\b)", re.IGNORECASE
)


def _payload(scene: dict[str, Any]) -> dict[str, Any]:
    raw = (scene.get("data") or "").strip()
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _events_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in payload.get("events") or []:
        if not isinstance(row, dict):
            continue
        at = str(row.get("at") or row.get("date") or "").strip()
        lane = str(
            row.get("lane") or row.get("name") or row.get("symbol") or ""
        ).strip()
        if at and lane:
            events.append(
                {"at": at, "lane": lane, "label": str(row.get("label") or "")}
            )
    return events


def _tickers_from_scene(scene: dict[str, Any]) -> list[str]:
    payload = _payload(scene)
    raw = payload.get("tickers") or payload.get("symbols")
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    if isinstance(raw, list) and raw:
        return [str(t).strip().upper() for t in raw if str(t).strip()]
    nodes = [str(n).strip().upper() for n in (scene.get("nodes") or []) if str(n).strip()]
    if nodes and all(2 <= len(n) <= 5 and n.replace(".", "").isalnum() for n in nodes):
        return nodes
    return []


def _parse_fmp_hit(title: str, ticker: str) -> tuple[str, str] | None:
    found = _DATE_RE.search(title or "")
    if not found:
        return None
    form = _FORM_RE.search(title or "")
    label = form.group(1).replace(" ", "") if form else "filing"
    return found.group(1), label


def events_from_fmp(tickers: list[str]) -> list[dict[str, Any]]:
    """Gaius FMP filings / 8-K / insider → {at, lane, label}. Empty if Gaius is quiet."""
    from hsengine.engine import ops

    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ticker in tickers:
        for stream in ("filings", "eight_k", "insider"):
            try:
                out = ops.fmp(query=ticker, stream=stream, limit=16)
            except Exception:
                log.debug("fmp %s %s failed", ticker, stream, exc_info=True)
                continue
            for hit in out.get("hits") or []:
                if not isinstance(hit, dict):
                    continue
                parsed = _parse_fmp_hit(str(hit.get("title") or ""), ticker)
                if parsed is None:
                    continue
                at, label = parsed
                key = (at, ticker, label)
                if key in seen:
                    continue
                seen.add(key)
                events.append({"at": at, "lane": ticker, "label": label})
    events.sort(key=lambda e: (e["at"], e["lane"]))
    return events


def _scene_events(scene: dict[str, Any]) -> list[dict[str, Any]]:
    events = _events_from_payload(_payload(scene))
    if events:
        return events
    tickers = _tickers_from_scene(scene)
    if tickers:
        pulled = events_from_fmp(tickers)
        if pulled:
            return pulled
    return [
        {"at": "2026-08-06", "lane": "NOV", "label": "13G/A"},
        {"at": "2026-08-27", "lane": "SLB", "label": "Form 4"},
        {"at": "2026-08-31", "lane": "SLB", "label": "8-K"},
        {"at": "2026-08-31", "lane": "SLB", "label": "Form 4"},
        {"at": "2026-09-01", "lane": "SLB", "label": "Form 4"},
    ]


def _empty_plot(title: str, message: str) -> Any:
    import holoviews as hv

    return hv.Text(0.5, 0.5, message).opts(
        title=title or "",
        text_color="#e8ecf4",
        fontsize=16,
        bgcolor="#0b0b12",
        width=1100,
        height=620,
    )


def _curves(scene: dict[str, Any], title: str, *, scatter: bool = False) -> Any:
    """Real series only. Never invent index-vs-value from ticker names."""
    import holoviews as hv

    payload = _payload(scene)
    series = payload.get("series")
    traces: list[Any] = []
    if isinstance(series, list):
        for row in series:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("symbol") or "")
            xs = row.get("x") or []
            ys = row.get("y") or []
            pts = row.get("points")
            if pts:
                data = [(p[0], p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
            elif xs and ys and len(xs) == len(ys):
                data = list(zip(xs, ys))
            else:
                continue
            if len(data) < 2:
                continue
            if scatter:
                traces.append(hv.Scatter(data, "x", "y", label=name))
            else:
                traces.append(hv.Curve(data, "x", "y", label=name))
    if traces:
        opts = dict(
            title=title or "",
            width=1100,
            height=620,
            bgcolor="#0b0b12",
        )
        if len(traces) == 1:
            return traces[0].opts(**opts)
        return hv.Overlay(traces).opts(**opts, legend_position="top_left")
    return _empty_plot(
        title,
        "No numeric series in the payload\nFMP quote is name/exchange only",
    )


def _timeline(scene: dict[str, Any], title: str) -> Any:
    import holoviews as hv
    import pandas as pd

    events = _scene_events(scene)
    df = pd.DataFrame(events)
    df["at"] = pd.to_datetime(df["at"], errors="coerce")
    df = df.dropna(subset=["at"])
    if df.empty:
        return hv.Scatter([(0, 0)], "t", "lane").opts(title=title, width=1100, height=640, bgcolor="#0b0b12")
    return hv.Scatter(df, kdims=["at"], vdims=["lane"]).opts(
        title=title or "Filings timeline",
        width=1100,
        height=640,
        size=14,
        color="lane",
        cmap="Category20",
        bgcolor="#0b0b12",
        xlabel="",
        ylabel="",
    )


def _density(scene: dict[str, Any], title: str) -> Any:
    """Week × ticker heatmap of filing counts — density, not a 4-point scatter."""
    import holoviews as hv
    import pandas as pd

    events = _scene_events(scene)
    df = pd.DataFrame(events)
    df["at"] = pd.to_datetime(df["at"], errors="coerce")
    df = df.dropna(subset=["at"])
    if df.empty:
        return hv.HeatMap([(0, "—", 0)], ["week", "lane"], "n").opts(
            title=title, width=1100, height=420, cmap="Magma", bgcolor="#0b0b12"
        )
    df["week"] = df["at"].dt.to_period("W").dt.start_time
    counts = df.groupby(["week", "lane"], as_index=False).size()
    counts = counts.rename(columns={"size": "n"})
    return hv.HeatMap(counts, kdims=["week", "lane"], vdims=["n"]).opts(
        title=title or "Filings density",
        width=1100,
        height=420,
        cmap="Magma",
        colorbar=True,
        bgcolor="#0b0b12",
        xlabel="",
        ylabel="",
        tools=["hover"],
    )


_ACTIVE_INSPECT_PATCHED = False


def _patch_bokeh_active_inspect() -> None:
    """Bokeh 3.9: toolbar.active_inspect is 'auto' (str); HoloViews does .append."""
    global _ACTIVE_INSPECT_PATCHED
    if _ACTIVE_INSPECT_PATCHED:
        return
    from holoviews.plotting.bokeh.element import ElementPlot

    orig = ElementPlot._set_active_tools

    def _safe(self, plot):  # type: ignore[no-untyped-def]
        tb = getattr(plot, "toolbar", None)
        ai = getattr(tb, "active_inspect", None)
        if isinstance(ai, str):
            plot.toolbar.active_inspect = []
        return orig(self, plot)

    ElementPlot._set_active_tools = _safe  # type: ignore[method-assign]
    _ACTIVE_INSPECT_PATCHED = True


def modify_doc(doc: Any) -> None:
    """Bokeh FunctionHandler: attach a real HoloViews plot to the server document.

    ``hv.render`` + ``column`` left an empty ``bk-Column`` (no canvas) in
    headless Chromium. Panel ``HoloViews.server_doc`` is the supported
    Bokeh-server attach path. WebGL is off — GraphRenderer/WebGL paints
    black under ``--headless=new``.
    """
    import holoviews as hv
    import panel as pn

    args = {}
    ctx = getattr(doc, "session_context", None)
    req = getattr(ctx, "request", None) if ctx is not None else None
    if req is not None:
        args = getattr(req, "arguments", None) or {}
    sid = _arg(args, "session")
    scene = SCENES.get(sid) or put_scene(sid or "anon", kind="chord")
    title = str(scene.get("title") or "AgentRTC viz")
    _patch_bokeh_active_inspect()
    hv.extension("bokeh", logo=False)
    hv.renderer("bokeh").webgl = False
    css = (
        "html, body, .bk-root, .bk-Row, .bk-Column, .bk-GridBox "
        "{ background: #0b0b12 !important; color: #e8ecf4 !important; }"
    )
    if css not in (pn.config.raw_css or []):
        pn.config.raw_css.append(css)
    pn.extension()
    obj = _hv_obj(scene)
    pane = pn.pane.HoloViews(
        obj,
        backend="bokeh",
        width=1280,
        height=720,
        linked_axes=False,
    )
    if sid:
        PANES[sid] = pane
    pane.server_doc(doc)
    doc.title = title
    log.info(
        "holoviews document session=%s kind=%s roots=%s",
        sid or "-",
        scene.get("kind"),
        [type(r).__name__ for r in doc.roots],
    )
