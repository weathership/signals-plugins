# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from hsengine.engine.sdg_iris import resolve_sdg_iri, subtree
from hsengine.engine.source_drop import _workflow_payload, run_system_one

SPECIMEN = "https://signals.zndx.org/sdg#LIMS_SPECIMEN_LIFECYCLE"
LIMS = "https://signals.zndx.org/sdg#LIMS"
ASSAY = "https://signals.zndx.org/sdg#LIMS_ASSAY_EXECUTION"
FINTECH = "https://signals.zndx.org/sdg#FINTECH"


def test_a_leaf_genus_offers_only_itself() -> None:
    iris = [point["iri"] for point in subtree(SPECIMEN)]
    assert iris == [SPECIMEN]


def test_a_genus_offers_itself_and_its_narrower_points() -> None:
    iris = [point["iri"] for point in subtree(LIMS)]
    assert iris[0] == LIMS
    assert SPECIMEN in iris
    assert ASSAY in iris
    assert FINTECH not in iris
    assert "https://signals.zndx.org/sdg#Healthcare" not in iris


def test_a_notation_or_label_resolves_only_inside_the_subtree() -> None:
    offered = subtree(LIMS)
    assert resolve_sdg_iri("16.2.1", offered) == SPECIMEN
    assert resolve_sdg_iri("Specimen Lifecycle Management", offered) == SPECIMEN
    assert resolve_sdg_iri("LIMS_SPECIMEN_LIFECYCLE", offered) == SPECIMEN
    assert resolve_sdg_iri(FINTECH, offered) == ""


def test_a_nested_workflow_result_keeps_the_assigned_iri() -> None:
    payload = _workflow_payload({"result": {"sdg_iri": SPECIMEN, "confidence": 0.8, "note": "specimen"}})
    assert payload["sdg_iri"] == SPECIMEN


def test_run_system_one_accepts_a_child_iri_under_the_genus(monkeypatch) -> None:
    captured = {}

    def execute(name, payload, *, wait, sleep=None, key=None):
        captured["payload"] = payload
        return {"result": {"result": {"sdg_iri": "16.2.1", "confidence": 0.7, "note": "cells"}}}

    monkeypatch.setattr("hsengine.engine.source_drop.mistral_preprint_urgent", lambda: True)
    monkeypatch.setattr("hsengine.engine.source_drop.system_one_name", lambda home=None: "signals-system-one")
    monkeypatch.setattr("hsengine.engine.source_drop.execute_workflow", execute)
    done = run_system_one("the specimen is accessioned", {"genus_iri": LIMS, "genus_code": "16.2", "genus_label": "Laboratory Information Management"})
    assert done["sdg_iri"] == SPECIMEN
    assert SPECIMEN in done["offered"]
    assert FINTECH not in done["offered"]
    assert captured["payload"]["offered"][0]["iri"] == LIMS
