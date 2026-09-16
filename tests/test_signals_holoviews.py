"""HoloViews plugin renderer: matplotlib path, no Datashader."""
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


def test_demo_chord_renders_without_holoviews():
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
