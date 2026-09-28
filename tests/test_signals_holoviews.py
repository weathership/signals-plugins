"""HoloViews plugin renderer. Holoviews is required; matplotlib may draw chords."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _load():
    import importlib.util

    root = Path(__file__).resolve().parents[1] / "plugins" / "signals-holoviews"
    spec = importlib.util.spec_from_file_location(
        "signals_holoviews_render_test", root / "render.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_chord_renders():
    pytest.importorskip("PIL")
    mod = _load()
    image, meta = mod.render_scene(kind="chord", title="Ontology chord")
    assert image.size[0] > 100 and image.size[1] > 100
    assert meta["kind"] == "chord"
    assert meta["n_nodes"] >= 3
    assert meta["backend"] in ("matplotlib", "holoviews")


def test_aperture_falls_back_to_demo_without_aegir():
    pytest.importorskip("PIL")
    mod = _load()
    image, meta = mod.render_scene(kind="aperture", source="aegir")
    assert image is not None
    assert meta["source"] in ("aegir", "demo")


def test_timeline_kind_builds_a_scatter_of_dates():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene(
        "tl",
        kind="timeline",
        title="Filings",
        data='{"events":[{"at":"2026-08-31","lane":"SLB","label":"8-K"},{"at":"2026-09-01","lane":"SLB","label":"Form 4"}]}',
    )
    obj = apps._hv_obj(scene)
    assert scene["kind"] == "timeline"
    names = [str(k) for k in getattr(obj, "kdims", [])]
    assert names == ["at"]


def test_curve_without_series_does_not_invent_a_line(monkeypatch):
    """Ticker names are not a series. An empty FMP pull stays an empty plot."""
    from hsengine.engine import webrtc_viz_apps as apps

    monkeypatch.setattr("hsengine.engine.ops.fmp", lambda **_k: {"hits": []})
    scene = apps.put_scene("c1", kind="curve", title="VTIP", data='{"tickers":["VTIP"]}')
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Text"


def test_curve_with_series_plots_those_points():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"series":[{"name":"VTIP","points":[[0,100],[1,101],[2,99]]}]}'
    scene = apps.put_scene("c2", kind="curve", title="VTIP", data=raw)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Curve"


def test_two_price_series_are_indexed_to_the_same_start():
    """XOM at 110 and SPY at 500 must not share a raw price axis."""
    from hsengine.engine import webrtc_viz_apps as apps

    raw = (
        '{"series":['
        '{"name":"XOM","points":[["d0",100],["d1",110]]},'
        '{"name":"SPY","points":[["d0",500],["d1",550]]}'
        "]}"
    )
    scene = apps.put_scene("rel", kind="curve", title="XOM vs SPY", data=raw)
    obj = apps._hv_obj(scene)
    starts = []
    ends = []
    for element in obj:
        col = [float(v) for v in element.dimension_values("y")]
        starts.append(col[0])
        ends.append(col[-1])
    assert starts == [100.0, 100.0]
    assert ends[0] == pytest.approx(110.0)
    assert ends[1] == pytest.approx(110.0)


def test_one_price_series_stays_in_dollars():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"series":[{"name":"XOM","points":[["d0",50],["d1",55]]}]}'
    scene = apps.put_scene("one", kind="curve", title="XOM", data=raw)
    obj = apps._hv_obj(scene)
    col = [float(v) for v in obj.dimension_values("y")]
    assert col == [50.0, 55.0]


def test_density_kind_is_a_week_by_lane_heatmap():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene(
        "dens",
        kind="density",
        title="Filings density",
        data='{"events":[{"at":"2026-08-31","lane":"SLB","label":"8-K"},{"at":"2026-09-01","lane":"SLB","label":"Form 4"},{"at":"2026-08-06","lane":"NOV","label":"13G/A"}]}',
    )
    obj = apps._hv_obj(scene)
    assert scene["kind"] == "density"
    assert [str(k) for k in obj.kdims] == ["week", "lane"]
    assert [str(v) for v in obj.vdims] == ["n"]


def test_parse_fmp_hit_title():
    from hsengine.engine.webrtc_viz_apps import _parse_fmp_hit

    assert _parse_fmp_hit("SLB — Form 4 — 2026-09-01", "SLB") == ("2026-09-01", "Form4")
    assert _parse_fmp_hit("8-K — 2026-08-31", "SLB") == ("2026-08-31", "8-K")
    assert _parse_fmp_hit("no date here", "SLB") is None


def test_tickers_from_json():
    from hsengine.engine.webrtc_viz_apps import _tickers_from_scene

    assert _tickers_from_scene({"data": '{"tickers":["SLB","HAL"]}'}) == ["SLB", "HAL"]


def test_modify_doc_does_not_crash_bokeh_active_inspect():
    """Bokeh 3.9 toolbar.active_inspect is 'auto'; HoloViews used to 500 the page."""
    from bokeh.document import Document

    from hsengine.engine import webrtc_viz_apps as apps

    apps.put_scene("anon", kind="chord", title="OFS")
    doc = Document()
    apps.modify_doc(doc)
    assert doc.roots


def test_modify_doc_attaches_a_bokeh_figure():
    from bokeh.document import Document

    from hsengine.engine import webrtc_viz_apps as apps

    apps.put_scene(
        "anon",
        kind="chord",
        title="OFS lattice",
        data='{"nodes":["SLB","HAL","BKR","NOV"],"edges":[[0,1,3],[0,2,2]]}',
    )
    doc = Document()
    apps.modify_doc(doc)
    kinds = [type(r).__name__ for r in doc.roots]
    assert any(k in ("Row", "Column", "figure", "GridBox") for k in kinds)
    blob = str(doc.roots)
    assert "figure" in blob.lower() or any(getattr(r, "children", None) for r in doc.roots)


def test_parse_custom_nodes():
    import importlib.util

    root = Path(__file__).resolve().parents[1] / "plugins" / "signals-holoviews"
    spec = importlib.util.spec_from_file_location(
        "signals_holoviews_scenes_test", root / "scenes.py"
    )
    assert spec is not None and spec.loader is not None
    scenes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenes)
    raw = json.dumps({"nodes": ["A", "B", "C"], "edges": [[0, 1, 2], [1, 2, 1]]})
    nodes, edges = scenes.parse_data(raw)
    assert nodes == ["A", "B", "C"]
    assert edges[0] == (0, 1, 2.0)
