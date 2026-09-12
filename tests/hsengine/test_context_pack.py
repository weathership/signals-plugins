"""Pipeline briefs for AgentRTC openings come from agenda + thoughts tools."""
from __future__ import annotations

from hsengine.engine.context_pack import (
    conversational_context,
    pipeline_block,
    usable_spoken,
    workspace_freshness,
)


def test_pipeline_block_joins_spoken_briefs():
    text = pipeline_block(
        {
            "agenda_spoken": "Today is the retrospective.",
            "thoughts_spoken": "Cell state should be auditable.",
        }
    )
    assert "Today's agenda brief" in text
    assert "retrospective" in text
    assert "Latest thoughts brief" in text
    assert "auditable" in text


def test_pipeline_block_empty_when_pipelines_are_silent():
    assert pipeline_block({}) == ""
    assert pipeline_block(None) == ""
    assert pipeline_block({"agenda_spoken": "cannot reach the pipeline brief"}) == ""


def test_workspace_freshness_is_the_first_turn_signal():
    assert workspace_freshness(thoughts_age_min=30, agenda_age_min=60, has_spoken=True) == "fresh"
    assert workspace_freshness(thoughts_age_min=9 * 60, agenda_age_min=10, has_spoken=True) == "stale"
    assert workspace_freshness(thoughts_age_min=None, agenda_age_min=10, has_spoken=True) == "stale"
    assert workspace_freshness(thoughts_age_min=10, agenda_age_min=10, has_spoken=False) == "empty"


def test_stale_pack_leads_the_pipeline_block():
    text = pipeline_block(
        {
            "workspace": "stale",
            "workspace_note": "stale (thoughts 45h)",
            "thoughts_spoken": "State as a hidden control plane on the edge.",
        }
    )
    assert text.startswith("Workspace freshness: stale")
    assert "45h" in text


def test_usable_spoken_drops_fetch_failures():
    assert usable_spoken("cannot reach the pipeline brief") == ""
    assert usable_spoken("idle") == ""
    assert usable_spoken("#CG.00000001.NOPOOL no database") == ""
    assert "retrospective" in usable_spoken(
        "Today is the AgentRTC retrospective after the voice session."
    )


def test_conversational_context_reads_spoken_briefs(monkeypatch):
    from hsengine.engine import ops

    monkeypatch.setattr(
        ops,
        "agenda",
        lambda item_id="": {
            "ok": True,
            "briefs": [{"spoken": "Today is the AgentRTC retrospective."}],
            "item": {"title": "AgentRTC retrospective", "body": "Theta after the voice."}
            if item_id
            else None,
        },
    )
    monkeypatch.setattr(
        ops,
        "recent_thoughts",
        lambda **k: {
            "ok": True,
            "briefs": [
                {
                    "spoken": "I keep thinking about verifiable cell state on the edge.",
                    "age_min": 40,
                }
            ],
        },
    )
    pack = conversational_context(agenda_id="note/today")
    assert pack["agenda_spoken"].startswith("Today is the AgentRTC")
    assert pack["thoughts_spoken"].startswith("I keep thinking")
    assert pack["agenda_title"] == "AgentRTC retrospective"
    assert pack["workspace"] == "fresh"
    monkeypatch.setattr(
        ops,
        "recent_thoughts",
        lambda **k: {
            "ok": True,
            "briefs": [
                {
                    "spoken": "I keep thinking about verifiable cell state on the edge.",
                    "age_min": 50 * 60,
                }
            ],
        },
    )
    stale = conversational_context()
    assert stale["workspace"] == "stale"
    assert "thoughts" in stale["workspace_note"]
