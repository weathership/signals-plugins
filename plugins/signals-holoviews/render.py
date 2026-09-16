"""Render a program still with HoloViews (required) onto PNG.

HoloViews is a Signals-hsengine dependency, not an extra. Matplotlib is
the PNG backend / chord fallback when ``hv.Chord`` cannot draw on Agg
(Aegir chords are a Bokeh GraphRenderer). No Dask/Datashader in this pass.
"""
from __future__ import annotations

import io
import math
from typing import Any

try:
    from . import scenes
except ImportError:  # loaded via spec_from_file_location from hsengine
    import importlib.util
    from pathlib import Path

    _scenes = Path(__file__).with_name("scenes.py")
    _spec = importlib.util.spec_from_file_location("signals_holoviews_scenes", _scenes)
    scenes = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(scenes)


def render_scene(
    *,
    kind: str = "chord",
    title: str = "",
    highlight: str = "",
    source: str = "",
    data: str = "",
    **_kw: Any,
) -> tuple[Any, dict]:
    name = (kind or "chord").strip().lower()
    if name in ("aperture", "aegir", "skos"):
        nodes, edges, origin = scenes.aperture_nodes_edges(source or "aegir")
        name = "chord"
    else:
        nodes, edges = scenes.parse_data(data)
        origin = "data" if (data or "").strip() else "demo"
        if (source or "").strip().lower() in ("aegir", "aperture"):
            nodes, edges, origin = scenes.aperture_nodes_edges(source)
            name = "chord"
    label = (title or "").strip() or _default_title(name, origin)
    try:
        import holoviews as _hv  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "holoviews is required for AgentRTC program stills "
            "(signals-hsengine / hermes-agent[signals])"
        ) from e
    try:
        image = _render_holoviews(name, nodes, edges, highlight, label)
        backend = "holoviews"
    except Exception:
        # hv.Chord is a Bokeh GraphRenderer; matplotlib Agg cannot always draw it.
        image = _render_matplotlib(name, nodes, edges, highlight, label)
        backend = "matplotlib"
    meta = {
        "kind": name,
        "title": label,
        "source": origin,
        "backend": backend,
        "nodes": nodes,
        "highlight": (highlight or "").strip(),
        "n_nodes": len(nodes),
        "n_edges": len(edges),
    }
    return image, meta


def _default_title(kind: str, origin: str) -> str:
    if kind == "chord" and origin == "aegir":
        return "Aperture — SKOS constituent lattice"
    if kind == "chord":
        return "Ontology chord"
    return kind.replace("_", " ").title()


def _render_holoviews(
    kind: str,
    nodes: list[str],
    edges: list[tuple[int, int, float]],
    highlight: str,
    title: str,
) -> Any:
    import holoviews as hv
    import pandas as pd

    hv.extension("matplotlib", logo=False)
    if kind in ("scatter", "curve", "heatmap"):
        obj = _hv_simple(kind, nodes, edges, title)
    else:
        node_df = pd.DataFrame({"index": list(range(len(nodes))), "name": nodes})
        edge_df = pd.DataFrame(edges, columns=["source", "target", "value"])
        obj = hv.Chord((edge_df, hv.Dataset(node_df, "index"))).opts(
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
    fig = hv.render(obj, backend="matplotlib")
    return _fig_to_image(fig)


def _hv_simple(kind: str, nodes: list[str], edges: list[tuple[int, int, float]], title: str):
    import holoviews as hv

    xs = list(range(max(2, len(nodes))))
    ys = [1.0 + (i % 5) * 0.3 for i in xs]
    if kind == "curve":
        return hv.Curve(list(zip(xs, ys)), "index", "value").opts(title=title, width=720, height=420)
    if kind == "heatmap":
        data = [(i, j, ((i + j) % 7) / 7.0) for i in range(6) for j in range(6)]
        return hv.HeatMap(data, ["x", "y"], "v").opts(title=title, width=560, height=560, cmap="Viridis")
    return hv.Scatter(list(zip(xs, ys)), "index", "value").opts(title=title, width=720, height=420)


def _render_matplotlib(
    kind: str,
    nodes: list[str],
    edges: list[tuple[int, int, float]],
    highlight: str,
    title: str,
) -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    fig, ax = plt.subplots(figsize=(9.6, 9.6), dpi=80, facecolor="#0b0b12")
    ax.set_facecolor("#0b0b12")
    ax.set_xlim(-1.45, 1.45)
    ax.set_ylim(-1.45, 1.45)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, color="#e8ecf4", fontsize=14, pad=12)
    n = max(1, len(nodes))
    pos = [
        (
            math.cos(2 * math.pi * i / n - math.pi / 2),
            math.sin(2 * math.pi * i / n - math.pi / 2),
        )
        for i in range(n)
    ]
    palette = (
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#59a14f",
        "#edc948",
        "#b07aa1",
        "#ff9da7",
    )
    hit = (highlight or "").strip().lower()
    for s, t, w in edges:
        if not (0 <= int(s) < n and 0 <= int(t) < n):
            continue
        p, q = pos[int(s)], pos[int(t)]
        mid = ((p[0] + q[0]) * 0.12, (p[1] + q[1]) * 0.12)
        path = MPath([p, mid, q], [MPath.MOVETO, MPath.CURVE3, MPath.CURVE3])
        ax.add_patch(
            PathPatch(
                path,
                facecolor="none",
                edgecolor=palette[int(s) % len(palette)],
                alpha=0.55,
                lw=0.6 + min(4.0, float(w)),
            )
        )
    for i, name in enumerate(nodes):
        color = "#f5c542" if hit and hit in name.lower() else palette[i % len(palette)]
        ax.scatter(*pos[i], s=120 if color == "#f5c542" else 70, color=color, zorder=3)
        ax.text(
            pos[i][0] * 1.2,
            pos[i][1] * 1.2,
            name[:20],
            color="#e8ecf4",
            ha="center",
            va="center",
            fontsize=9,
        )
    fig.tight_layout()
    image = _fig_to_image(fig)
    plt.close(fig)
    return image


def _fig_to_image(fig: Any) -> Any:
    from PIL import Image

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    buf.seek(0)
    return Image.open(buf).convert("RGB")
