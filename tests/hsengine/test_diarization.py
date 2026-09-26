"""Diarization is part of agent-rtc. It does not add a GPU floor."""
from __future__ import annotations

from hsengine.engine.diarization import apply_label, speaker_label
from hsengine.engine.webrtc_captions import CaptionBoard
from hsengine.engine.workload_catalog import DESCRIPTION
from hsengine.engine.yk_sentinel import GPU_TOKENS, interactive_yk_claims


def test_worker_label_replaces_room_for_that_session():
    assert apply_label({"label": "speaker_1", "n_speakers": 2}, "sess-a") == "speaker_1"
    assert speaker_label("sess-a") == "speaker_1"
    assert speaker_label("sess-b") == "Room"


def test_room_caption_uses_the_diarized_label():
    board = CaptionBoard()
    board.set("the card on the list", label="speaker_0")
    assert board.get() == "speaker_0: the card on the list"


def test_diarization_does_not_add_a_yk_floor():
    assert "Nemotron 3 diarization" in DESCRIPTION
    assert "not its own DAG" in DESCRIPTION
    claims = interactive_yk_claims()
    gpu_tokens = [gpu for _leaf, gpu in claims]
    assert gpu_tokens.count(1) == 1
    assert sum(gpu_tokens) == GPU_TOKENS
