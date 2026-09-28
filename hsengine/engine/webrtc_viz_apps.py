"""Standalone HoloViews/Bokeh documents for AgentRTC.

Aegir is an optional data source, not a runtime. One Bokeh document per
Chromium tab; the viewer never speaks Bokeh protocol.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from hsengine.engine.webrtc_cdp import PLOT_H, PLOT_W

log = logging.getLogger("hsengine.engine.webrtc.viz.apps")

# Not drawn. FMP's documented surface used here has no executable options chain.
_OPTIONS_NOTE = (
    "Options quotes are not a verified FMP adapter. "
    "Hypothetical premiums are not shown as observations."
)
_OPTIONS_KINDS = frozenset(
    {
        "chain_liquidity",
        "iv_smile",
        "vol_surface",
        "term_structure",
        "implied_versus_realized",
        "greeks_grid",
        "physical_versus_risk_neutral",
        "pricing_residuals",
        "option_pnl_attribution",
        "open_interest_profile",
        "payoff_comparison",
        "covered_call",
        "strike_expiry_map",
        "roll_surface",
    }
)

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
    if kind in _OPTIONS_KINDS:
        return _empty_plot(title, _OPTIONS_NOTE)
    if kind in ("curve", "line", "relative", "relative_performance"):
        return _curves(scene, title, force_index=kind in ("relative", "relative_performance"))
    if kind in ("return_board", "cross_asset_return_board"):
        return _return_board(scene, title)
    if kind in ("price_structure",):
        return _price_structure(scene, title)
    if kind in ("cash_conversion", "cash_bridge"):
        return _cash_bridge(scene, title)
    if kind in ("roic", "roic_wacc"):
        return _roic(scene, title)
    if kind in ("consensus", "consensus_revisions"):
        return _consensus(scene, title)
    if kind in ("reverse_dcf",):
        return _reverse_dcf(scene, title)
    if kind in ("candle", "ohlc"):
        return _candles(scene, title)
    if kind == "volume":
        return _volume(scene, title)
    if kind == "range":
        return _range(scene, title)
    if kind == "returns":
        return _returns(scene, title)
    if kind == "heatmap":
        return _return_heatmap(scene, title)
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
            width=PLOT_W,
            height=PLOT_H,
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
        width=PLOT_W,
        height=620,
    )


def daily_returns(points: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
    """Close-to-close percent. The first point has no prior close, so it is dropped."""
    out: list[tuple[Any, float]] = []
    prev: float | None = None
    for at, price in points:
        y = float(price)
        if prev not in (None, 0.0):
            out.append((at, 100.0 * (y - float(prev)) / float(prev)))
        prev = y
    return out


def _bars_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("bars") or payload.get("ohlc") or []
    bars: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return bars
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            bar = {
                "at": str(row.get("at") or row.get("date") or ""),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if not bar["at"]:
            continue
        if row.get("volume") not in (None, ""):
            try:
                bar["volume"] = float(row["volume"])
            except (TypeError, ValueError):
                pass
        bars.append(bar)
    bars.sort(key=lambda b: b["at"])
    return bars


def eod_bars_from_hits(hits: list[Any]) -> list[dict[str, Any]]:
    """OHLC bars from FMP eod hits. Skips a hit that is only a close."""
    from hsengine.engine.ops import enrich_fmp_hit

    payload_hits = []
    for hit in hits or []:
        if isinstance(hit, dict):
            payload_hits.append(enrich_fmp_hit(dict(hit)))
    bars: list[dict[str, Any]] = []
    for hit in payload_hits:
        try:
            bar = {
                "at": str(hit.get("as_of") or hit.get("title") or ""),
                "open": float(hit["open"]),
                "high": float(hit["high"]),
                "low": float(hit["low"]),
                "close": float(hit["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if not bar["at"]:
            continue
        if hit.get("volume") not in (None, ""):
            try:
                bar["volume"] = float(hit["volume"])
            except (TypeError, ValueError):
                pass
        bars.append(bar)
    bars.sort(key=lambda b: b["at"])
    return bars


def _price_frame(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Bars for one name. Payload bars win; otherwise the first ticker's eod."""
    bars = _bars_from_payload(_payload(scene))
    if bars:
        return bars
    from hsengine.engine import ops

    tickers = _tickers_from_scene(scene)
    if not tickers:
        return []
    try:
        out = ops.fmp(query=tickers[0], stream="eod", limit=90)
    except Exception:
        log.debug("fmp eod bars failed", exc_info=True)
        return []
    return eod_bars_from_hits(out.get("hits") or [])


def _style(title: str, **extra: Any) -> dict[str, Any]:
    opts = dict(title=title or "", width=PLOT_W, height=PLOT_H, bgcolor="#0b0b12")
    opts.update(extra)
    return opts


def _time_or_label(value: Any) -> Any:
    """An ISO day is a time axis. A name or an index stays a category.

    Ninety date strings on a category axis are one tick per session, which
    packs the row. A time axis spaces them.
    """
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            from datetime import date

            year, month, day = (int(part) for part in text[:10].split("-"))
            return date(year, month, day)
        except ValueError:
            return value
    return value


def axis_label_opts(
    n_x: int, labels: list[str] | None = None, *, width: int = PLOT_W
) -> dict[str, Any]:
    """Keep x labels readable in the frame. Too many categories rotate, then thin.

    A horizontal tick needs about 80 px. A rotated one needs about 28.
    """
    n = max(0, int(n_x))
    wide = max(4, int(width) // 80)
    turned = max(8, int(width) // 28)
    font = {"title": 16, "labels": 13, "yticks": 14, "xticks": 12}
    if n <= wide:
        return {"xrotation": 0, "fontsize": font}
    font = {**font, "xticks": 11}
    if n <= turned:
        return {"xrotation": 55, "fontsize": font}
    font = {**font, "xticks": 9}
    opts: dict[str, Any] = {"xrotation": 70, "fontsize": font}
    if labels:
        step = max(2, (n + turned - 1) // turned)
        shown = list(labels)[::step]
        last = labels[-1]
        if shown and shown[-1] != last:
            shown.append(last)
        opts["xticks"] = shown
    return opts


def _curves(scene: dict[str, Any], title: str, *, scatter: bool = False, force_index: bool = False) -> Any:
    """Real series only. Never invent index-vs-value from ticker names."""
    import holoviews as hv

    payload = _payload(scene)
    series = payload.get("series")
    prepared: list[tuple[str, list]] = []
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
            prepared.append((name, data))
    if not prepared:
        prepared = _eod_series(scene)
    prepared = [
        (name, [(_time_or_label(x), y) for x, y in data]) for name, data in prepared
    ]
    # Two price levels on one axis hide the move (XOM near 110, SPY near 500).
    if force_index or len(prepared) >= 2:
        prepared = [(name, rebase_to_100(data)) for name, data in prepared]
    traces: list[Any] = []
    for name, data in prepared:
        if scatter:
            traces.append(hv.Scatter(data, "x", "y", label=name))
        else:
            traces.append(hv.Curve(data, "x", "y", label=name))
    if traces:
        indexed = force_index or len(prepared) >= 2
        xs = [x for _name, data in prepared for x, _y in data]
        time_axis = bool(xs) and all(hasattr(x, "year") for x in xs)
        opts = _style(
            title or "",
            ylabel="indexed to 100" if indexed else "close",
        )
        if not time_axis:
            labels = list(dict.fromkeys(str(x) for x in xs))
            opts.update(axis_label_opts(len(labels), labels))
        if len(traces) == 1:
            return traces[0].opts(**opts)
        return hv.Overlay(traces).opts(**opts, legend_position="top_left")
    return _empty_plot(
        title,
        "No numeric series — pass payload.series or tickers for FMP eod",
    )


def rebase_to_100(points: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
    """Index a price path to 100 at its first point. Relative move, not the level."""
    if len(points) < 2:
        return list(points)
    base = float(points[0][1])
    if base == 0:
        return list(points)
    return [(t, 100.0 * float(y) / base) for t, y in points]


def eod_points_from_hits(hits: list[Any]) -> list[tuple[str, float]]:
    from hsengine.engine.ops import enrich_fmp_hit

    pts: list[tuple[str, float]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        hit = enrich_fmp_hit(dict(hit))
        at = str(hit.get("as_of") or hit.get("title") or "").strip()
        raw = hit.get("close", hit.get("price"))
        if not at or raw in (None, ""):
            continue
        try:
            pts.append((at, float(raw)))
        except (TypeError, ValueError):
            continue
    return pts


def _eod_series(scene: dict[str, Any]) -> list[tuple[str, list]]:
    """Daily closes when viz_show got tickers but no series. Not filings."""
    from hsengine.engine import ops

    series: list[tuple[str, list]] = []
    for ticker in _tickers_from_scene(scene)[:6]:
        try:
            out = ops.fmp(query=ticker, stream="eod", limit=90)
        except Exception:
            log.debug("fmp eod %s failed", ticker, exc_info=True)
            continue
        pts = eod_points_from_hits(out.get("hits") or [])
        if len(pts) < 2:
            continue
        series.append((ticker, pts))
    return series


def _series_for_scene(scene: dict[str, Any]) -> list[tuple[str, list]]:
    """Named close paths from payload.series, else FMP eod for the tickers."""
    payload = _payload(scene)
    prepared: list[tuple[str, list]] = []
    series = payload.get("series")
    if isinstance(series, list):
        for row in series:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("symbol") or "")
            pts = row.get("points")
            xs, ys = row.get("x") or [], row.get("y") or []
            if pts:
                data = [(p[0], p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
            elif xs and ys and len(xs) == len(ys):
                data = list(zip(xs, ys))
            else:
                data = []
            if len(data) >= 2:
                prepared.append((name, data))
    if prepared:
        return prepared
    return _eod_series(scene)


def _candles(scene: dict[str, Any], title: str) -> Any:
    """One name, daily OHLC. Wick is high–low; the body is open–close."""
    import holoviews as hv

    bars = _price_frame(scene)
    if len(bars) < 2:
        return _empty_plot(title, "No OHLC bars — pass bars or one ticker for FMP eod")
    wick = [(i, b["low"], i, b["high"]) for i, b in enumerate(bars)]
    up, down = [], []
    for i, b in enumerate(bars):
        body = (i - 0.3, b["open"], i + 0.3, b["close"])
        (up if b["close"] >= b["open"] else down).append(body)
    layers = [hv.Segments(wick, kdims=["x0", "y0", "x1", "y1"]).opts(color="#c5cdd8")]
    if up:
        layers.append(hv.Rectangles(up).opts(color="#3dd68c", line_color="#3dd68c"))
    if down:
        layers.append(hv.Rectangles(down).opts(color="#ff5d73", line_color="#ff5d73"))
    plot = hv.Overlay(layers).opts(**_style(title or "OHLC", ylabel="price", xlabel="session"))
    return plot


def _volume(scene: dict[str, Any], title: str) -> Any:
    """Close above volume. A layout, not one axis trying to hold both units."""
    import holoviews as hv

    bars = _price_frame(scene)
    if len(bars) < 2 or not any("volume" in b for b in bars):
        return _empty_plot(title, "No volume — pass bars with volume or one ticker")
    close = hv.Curve([(i, b["close"]) for i, b in enumerate(bars)], "session", "close")
    vol = hv.Bars([(i, b.get("volume") or 0) for i, b in enumerate(bars)], "session", "volume")
    return (close + vol).cols(1).opts(title=title or "Close and volume")


def _range(scene: dict[str, Any], title: str) -> Any:
    """High–low band with the close through it."""
    import holoviews as hv

    bars = _price_frame(scene)
    if len(bars) < 2:
        return _empty_plot(title, "No high-low bars")
    band = hv.Area(
        [(i, b["low"], b["high"]) for i, b in enumerate(bars)],
        kdims=["session"],
        vdims=["low", "high"],
    ).opts(alpha=0.35, color="#7aa2ff")
    close = hv.Curve([(i, b["close"]) for i, b in enumerate(bars)], "session", "close").opts(
        color="#e8ecf4"
    )
    return (band * close).opts(**_style(title or "High-low range", ylabel="price"))


def _returns(scene: dict[str, Any], title: str) -> Any:
    """Day-to-day percent change. One name is bars; several names are lines."""
    import holoviews as hv

    prepared = _series_for_scene(scene)
    if not prepared:
        return _empty_plot(title, "No closes to difference")
    traces = []
    for name, pts in prepared:
        rets = daily_returns([(a, float(y)) for a, y in pts])
        if len(rets) < 2:
            continue
        if len(prepared) == 1:
            traces.append(hv.Bars(rets, "session", "return %", label=name))
        else:
            traces.append(hv.Curve(rets, "session", "return %", label=name))
    if not traces:
        return _empty_plot(title, "Not enough closes for a return")
    if len(traces) == 1:
        return traces[0].opts(**_style(title or "Daily returns", ylabel="return %"))
    return hv.Overlay(traces).opts(**_style(title or "Daily returns", ylabel="return %"))


def _return_heatmap(scene: dict[str, Any], title: str) -> Any:
    """Names × dates of daily percent change. Not a filing count, not a demo grid."""
    import holoviews as hv

    prepared = _series_for_scene(scene)
    cells = []
    for name, pts in prepared:
        for at, ret in daily_returns([(a, float(y)) for a, y in pts]):
            cells.append((str(at), name or "series", ret))
    if len({c[1] for c in cells}) < 2:
        return _empty_plot(title, "A return heatmap needs at least two names")
    sessions = list(dict.fromkeys(c[0] for c in cells))
    return hv.HeatMap(cells, ["session", "name"], "return %").opts(
        **_style(
            title or "Daily returns",
            cmap="RdBu_r",
            colorbar=True,
            symmetric=True,
            **axis_label_opts(len(sessions), sessions),
        )
    )


def return_horizons(points: list[tuple[Any, float]]) -> dict[str, float]:
    """Percent change over 1, 5, and 21 sessions, plus the fetched window.

    The window is not calendar year-to-date. Ninety daily bars do not
    reconstruct YTD.
    """
    if len(points) < 2:
        return {}
    last = float(points[-1][1])

    def pct(back: int) -> float | None:
        if len(points) <= back:
            return None
        prev = float(points[-1 - back][1])
        if prev == 0:
            return None
        return round(100.0 * (last - prev) / prev, 2)

    out: dict[str, float] = {}
    for key, back in (("d", 1), ("w", 5), ("m", 21)):
        value = pct(back)
        if value is not None:
            out[key] = value
    first = float(points[0][1])
    if first != 0:
        out["span"] = round(100.0 * (last - first) / first, 2)
    return out


def _return_board(scene: dict[str, Any], title: str) -> Any:
    """Named assets × horizons. Caller rows win; tickers pull FMP closes."""
    import holoviews as hv

    assets = list(_payload(scene).get("assets") or [])
    if not assets:
        for name, pts in _eod_series(scene):
            horizons = return_horizons([(a, float(y)) for a, y in pts])
            if horizons:
                assets.append({"name": name, **horizons})
    cells = []
    for row in assets:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        for horizon in ("d", "w", "m", "span", "ytd"):
            if row.get(horizon) in (None, ""):
                continue
            cells.append((horizon, str(row["name"]), float(row[horizon])))
    if not cells:
        return _empty_plot(title, "No return board — pass assets or tickers")
    return hv.HeatMap(cells, ["horizon", "name"], "return %").opts(
        **_style(title or "Return board", cmap="RdBu_r", colorbar=True, symmetric=True)
    )


def _price_structure(scene: dict[str, Any], title: str) -> Any:
    """Candle, a 20-session average when there are enough bars, and volume if present."""
    import holoviews as hv

    bars = _price_frame(scene)
    if len(bars) < 2:
        return _empty_plot(title, "No OHLC bars for a price structure")
    candle = _candles(scene, "")
    layers = [candle]
    if len(bars) >= 5:
        closes = [(b["at"], b["close"]) for b in bars]
        avg = _moving_average(closes, min(20, len(closes)))
        if len(avg) >= 2:
            layers.append(
                hv.Curve([(i + len(bars) - len(avg), y) for i, (_t, y) in enumerate(avg)], "session", "ma").opts(
                    color="#f0c14a"
                )
            )
    plot = hv.Overlay(layers) if len(layers) > 1 else candle
    if not any("volume" in b for b in bars):
        return plot.opts(**_style(title or "Price structure"))
    vol = hv.Bars([(i, b.get("volume") or 0) for i, b in enumerate(bars)], "session", "volume")
    return (plot + vol).cols(1).opts(title=title or "Price structure")


def _moving_average(points: list[tuple[Any, float]], window: int) -> list[tuple[Any, float]]:
    out: list[tuple[Any, float]] = []
    buf: list[float] = []
    for at, price in points:
        buf.append(float(price))
        if len(buf) > window:
            buf.pop(0)
        if len(buf) == window:
            out.append((at, sum(buf) / float(window)))
    return out


def _cash_bridge(scene: dict[str, Any], title: str) -> Any:
    """Signed steps from net income toward free cash flow. Amounts are the caller's."""
    import holoviews as hv

    steps = _payload(scene).get("steps") or []
    clean = []
    for row in steps:
        if not isinstance(row, dict) or row.get("value") in (None, ""):
            continue
        clean.append((str(row.get("label") or "step"), float(row["value"])))
    if len(clean) < 2:
        return _empty_plot(title, "No cash bridge — pass steps with label and value")
    level = 0.0
    boxes = []
    for i, (label, value) in enumerate(clean):
        boxes.append((i - 0.35, level, i + 0.35, level + value, label))
        level += value
    rects = [(b[0], b[1], b[2], b[3]) for b in boxes]
    return hv.Rectangles(rects).opts(**_style(title or "Cash conversion", ylabel="amount", xlabel="step"))


def _roic(scene: dict[str, Any], title: str) -> Any:
    import holoviews as hv

    rows = _payload(scene).get("points") or []
    roic, wacc = [], []
    for row in rows:
        if not isinstance(row, dict) or not row.get("at"):
            continue
        if row.get("roic") not in (None, ""):
            roic.append((str(row["at"]), float(row["roic"])))
        if row.get("wacc") not in (None, ""):
            wacc.append((str(row["at"]), float(row["wacc"])))
    if len(roic) < 2:
        return _empty_plot(title, "No ROIC path — pass points with at and roic")
    layers = [hv.Curve(roic, "period", "rate", label="ROIC")]
    if len(wacc) >= 2:
        layers.append(hv.Curve(wacc, "period", "rate", label="WACC"))
    return hv.Overlay(layers).opts(**_style(title or "ROIC and WACC", ylabel="rate"))


def _consensus(scene: dict[str, Any], title: str) -> Any:
    """A single as-of is a snapshot. Revision history needs more than one stored vintage."""
    import holoviews as hv

    rows = _payload(scene).get("estimates") or []
    vintages = {str(r.get("as_of") or "") for r in rows if isinstance(r, dict) and r.get("as_of")}
    if len(vintages) < 2:
        return _empty_plot(
            title,
            "Estimate snapshot only — a live pull is not a revision history",
        )
    pts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("mean") in (None, "") or not row.get("as_of"):
            continue
        pts.append((str(row["as_of"]), float(row["mean"])))
    if len(pts) < 2:
        return _empty_plot(title, "Estimate snapshot only — a live pull is not a revision history")
    pts.sort()
    return hv.Curve(pts, "as of", "mean estimate").opts(**_style(title or "Consensus vintages", ylabel="estimate"))


def _reverse_dcf(scene: dict[str, Any], title: str) -> Any:
    """Cells the caller already valued. Masked cells are omitted, not drawn as zero."""
    import holoviews as hv

    rows = _payload(scene).get("cells") or []
    cells = []
    for row in rows:
        if not isinstance(row, dict) or row.get("value") in (None, ""):
            continue
        cells.append((float(row["growth"]), float(row["roic"]), float(row["value"])))
    if not cells:
        return _empty_plot(title, "No admissible reverse-DCF cells")
    return hv.HeatMap(cells, ["growth", "ROIC"], "enterprise value").opts(
        **_style(title or "Reverse DCF (model)", cmap="Viridis", colorbar=True)
    )


def _timeline(scene: dict[str, Any], title: str) -> Any:
    import holoviews as hv
    import pandas as pd

    events = _scene_events(scene)
    df = pd.DataFrame(events)
    df["at"] = pd.to_datetime(df["at"], errors="coerce")
    df = df.dropna(subset=["at"])
    if df.empty:
        return hv.Scatter([(0, 0)], "t", "lane").opts(title=title, width=PLOT_W, height=PLOT_H, bgcolor="#0b0b12")
    return hv.Scatter(df, kdims=["at"], vdims=["lane"]).opts(
        title=title or "Filings timeline",
        width=PLOT_W,
        height=PLOT_H,
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
            **_style(title, cmap="Magma", colorbar=True)
        )
    df["week"] = df["at"].dt.to_period("W").dt.start_time
    counts = df.groupby(["week", "lane"], as_index=False).size()
    counts = counts.rename(columns={"size": "n"})
    week_labels = list(dict.fromkeys(counts["week"].tolist()))
    return hv.HeatMap(counts, kdims=["week", "lane"], vdims=["n"]).opts(
        **_style(
            title or "Filings density",
            cmap="Magma",
            colorbar=True,
            xlabel="",
            ylabel="",
            tools=["hover"],
            **axis_label_opts(len(week_labels), week_labels),
        )
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
        "html, body { height: 100% !important; background: #0b0b12 !important; "
        "margin: 0 !important; }"
        ".bk-root, .bk-Row, .bk-Column, .bk-GridBox "
        "{ background: #0b0b12 !important; color: #e8ecf4 !important; "
        "margin: 0 !important; height: auto !important; overflow: hidden !important; "
        "max-width: 1280px !important; box-sizing: border-box !important; }"
    )
    if css not in (pn.config.raw_css or []):
        pn.config.raw_css.append(css)
    pn.extension()
    obj = _hv_obj(scene)
    pane = pn.pane.HoloViews(
        obj,
        backend="bokeh",
        width=PLOT_W,
        height=PLOT_H,
        linked_axes=False,
    )
    if sid:
        PANES[sid] = pane
    # Flex on the body did not move the plot: the Bokeh root fills the
    # viewport and the figure stays on its top edge. A spacer of the
    # centered inset puts air above the figure inside the document.
    from hsengine.engine.webrtc_cdp import VIEW_W, figure_top

    pn.Column(
        pn.Spacer(height=figure_top(), width=VIEW_W),
        pane,
        width=VIEW_W,
    ).server_doc(doc)
    doc.title = title
    log.info(
        "holoviews document session=%s kind=%s roots=%s",
        sid or "-",
        scene.get("kind"),
        [type(r).__name__ for r in doc.roots],
    )
