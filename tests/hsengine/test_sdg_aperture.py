# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from hsengine.engine.sdg_aperture import attach, links_in_message, slice_for_mistral


def test_offsets_slice_the_local_text_and_do_not_call_a_workflow() -> None:
    message = "xxxxHELLO"
    links = links_in_message(4, "HELLO", [{
        "start": 4,
        "end": 9,
        "genus_iri": "https://signals.zndx.org/sdg#LIMS",
        "genus_code": "9",
        "genus_label": "LIMS",
        "rel_margin_h": 0.55,
        "tau": 0.10,
    }])
    assert links[0]["start"] == 0
    assert links[0]["end"] == 5
    assert slice_for_mistral("HELLO", links[0]) == "HELLO"
    stamped = attach("HELLO", links, workflow_name="")
    assert "sdg.iri" not in stamped["links"][0]
    assert "semantica.confidence" not in stamped["links"][0]
    assert message[4:9] == "HELLO"


def test_a_range_outside_the_message_writes_no_link() -> None:
    assert links_in_message(0, "HELLO", [{"start": 10, "end": 12, "genus_iri": "https://signals.zndx.org/sdg#LIMS"}]) == []


def test_an_empty_admission_list_writes_no_link() -> None:
    assert links_in_message(0, "HELLO", []) == []
