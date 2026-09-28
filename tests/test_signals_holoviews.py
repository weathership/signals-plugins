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


_BARS = (
    '{"bars":['
    '{"at":"2026-09-01","open":10,"high":12,"low":9,"close":11,"volume":100},'
    '{"at":"2026-09-02","open":11,"high":11.5,"low":8,"close":9,"volume":140},'
    '{"at":"2026-09-03","open":9,"high":13,"low":8.5,"close":12,"volume":90}'
    "]}"
)


def test_daily_returns_drop_the_first_close():
    from hsengine.engine.webrtc_viz_apps import daily_returns

    assert daily_returns([("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]) == [
        ("d1", 10.0),
        ("d2", -10.0),
    ]


def test_candle_is_wicks_and_bodies_not_a_heatmap():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene("cndl", kind="candle", title="XOM", data=_BARS)
    obj = apps._hv_obj(scene)
    names = [el.__class__.__name__ for el in obj]
    assert "Segments" in names
    assert "Rectangles" in names
    assert "HeatMap" not in names


def test_return_heatmap_uses_daily_change_not_a_demo_grid():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = (
        '{"series":['
        '{"name":"XOM","points":[["d0",100],["d1",110],["d2",99]]},'
        '{"name":"SPY","points":[["d0",500],["d1",500],["d2",550]]}'
        "]}"
    )
    scene = apps.put_scene("hm", kind="heatmap", title="moves", data=raw)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "HeatMap"
    values = [float(v) for v in obj.dimension_values("return %")]
    assert 10.0 in values
    assert 0.0 in values


def test_heatmap_without_two_names_is_not_a_demo():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene("hm0", kind="heatmap", title="empty", data="{}")
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Text"


def test_volume_is_a_layout_of_close_and_size():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene("vol", kind="volume", title="XOM", data=_BARS)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Layout"


def test_range_is_a_high_low_band_with_the_close():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene("rng", kind="range", title="XOM", data=_BARS)
    obj = apps._hv_obj(scene)
    names = [el.__class__.__name__ for el in obj]
    assert "Area" in names
    assert "Curve" in names


def test_return_board_is_the_callers_horizons():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"assets":[{"name":"XOM","d":1.0,"w":-2.0,"ytd":4.0}]}'
    scene = apps.put_scene("rb", kind="return_board", title="board", data=raw)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "HeatMap"
    assert 1.0 in [float(v) for v in obj.dimension_values("return %")]


def test_consensus_snapshot_is_not_a_revision_history():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"estimates":[{"as_of":"2026-09-28","period":"FY2026","mean":5.1}]}'
    scene = apps.put_scene("est", kind="consensus", title="estimates", data=raw)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Text"


def test_reverse_dcf_omits_masked_cells():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"cells":[{"growth":0.02,"roic":0.12,"value":80},{"growth":0.09,"roic":0.12,"value":null}]}'
    scene = apps.put_scene("dcf", kind="reverse_dcf", title="model", data=raw)
    obj = apps._hv_obj(scene)
    values = [float(v) for v in obj.dimension_values("enterprise value")]
    assert values == [80.0]


def test_options_kind_is_refused():
    from hsengine.engine import webrtc_viz_apps as apps

    scene = apps.put_scene("opt", kind="payoff_comparison", title="covered call", data="{}")
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Text"


def test_cash_bridge_is_rectangles():
    from hsengine.engine import webrtc_viz_apps as apps

    raw = '{"steps":[{"label":"Net income","value":100},{"label":"Capex","value":-20}]}'
    scene = apps.put_scene("cash", kind="cash_conversion", title="bridge", data=raw)
    obj = apps._hv_obj(scene)
    assert obj.__class__.__name__ == "Rectangles"


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
