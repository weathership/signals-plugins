# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from hsengine.engine.sdg_iris import genus_of, resolve_sdg_iri, subtree
from hsengine.engine.source_drop import _workflow_payload, run_system_one
from hsengine.engine.system_one import assignments_from, word_sequences

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


def test_a_leaf_hit_rolls_up_to_the_aperture_genus() -> None:
    genus = genus_of(SPECIMEN)
    assert genus is not None
    assert genus["iri"] == LIMS
    assert genus["code"] == "16.2"


def test_word_sequences_are_contiguous_slices() -> None:
    text = "one two three four five six seven eight nine ten"
    spans = word_sequences(text, sizes=(4,), stride=4, limit=4)
    assert spans
    assert spans[0]["text"] == "one two three four"
    assert text[spans[0]["start"] : spans[0]["end"]] == spans[0]["text"]


def test_a_none_choice_is_not_an_assignment() -> None:
    sequences = [{"start": 0, "end": 4, "text": "cells"}]
    points = subtree(LIMS)
    body = {"answers": {"w0": {"choice": "none", "confidence": 0.9}}}
    assert assignments_from(body, sequences, points) == []
    body = {"answers": {"w0": {"choice": "LIMS_SPECIMEN_LIFECYCLE", "confidence": 0.8}}}
    found = assignments_from(body, sequences, points)
    assert found[0]["iri"] == SPECIMEN


def test_run_system_one_assigns_inside_the_genus_subtree(monkeypatch) -> None:
    def assign(text, points):
        assert any(point["iri"] == SPECIMEN for point in points)
        assert all(point["iri"] != FINTECH for point in points)
        return [{
            "start": 0,
            "end": 8,
            "text": text[:8],
            "iri": SPECIMEN,
            "label": "Specimen Lifecycle Management",
            "confidence": 0.8,
        }]

    monkeypatch.setattr("hsengine.engine.source_drop.mistral_preprint_urgent", lambda: True)
    monkeypatch.setattr("hsengine.engine.system_one.assign_word_sequences", assign)
    done = run_system_one(
        "the specimen is accessioned",
        {"genus_iri": SPECIMEN, "genus_code": "16.2.1", "genus_label": "Specimen Lifecycle Management"},
    )
    assert done["sdg_iri"] == SPECIMEN
    assert LIMS in done["offered"]
    assert FINTECH not in done["offered"]
    assert done["assignments"][0]["text"] == "the spec"
