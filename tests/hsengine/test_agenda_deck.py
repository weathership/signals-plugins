"""Presenterm decks stay off the calendar invite and drive the opening."""
from __future__ import annotations

from hsengine.engine.agenda_deck import (
    OPENING_GESTURES,
    _prefer_session,
    load_agenda_session,
    pick_opening_gesture,
    propose_opening_prompt,
    spoken_opening_prompt,
    split_agenda_body,
    split_public_deck,
    strip_invented_prompt,
)


def test_split_session_prompt_is_not_speaker_notes():
    parts = split_agenda_body(
        "Catch up Discover reliability.\n\n"
        "## Session prompt\n\n"
        "Open on the Discover catch-up, not leftover thoughts.\n\n"
        "## Materials\n\n"
        "Theta skip is not success.\n\n"
        "## Deck\n\n"
        "Opening\n===\n\nHello.\n\n<!-- speaker_note: do not read this first. -->\n"
    )
    assert "Catch up Discover reliability" in parts["public"]
    assert "Open on the Discover catch-up" in parts["session_prompt"]
    assert "Theta skip is not success" in parts["materials"]
    assert "speaker_note" in parts["deck"]
    assert "speaker_note" not in parts["public"]
    assert "speaker_note" not in parts["session_prompt"]


def test_prefer_session_picks_owner_prompt_over_thin_copy():
    thin = {
        "title": "Discover",
        "public": "lede",
        "session_prompt": "",
        "materials": "",
        "origin_project": "gaius",
        "target": "127.0.0.1:50051",
    }
    rich = {
        "title": "Discover",
        "public": "lede",
        "session_prompt": "Open on the catch-up.",
        "materials": "skip≠success",
        "origin_project": "metabase",
        "target": "127.0.0.1:50451",
    }
    picked = _prefer_session([thin, rich])
    assert picked["origin_project"] == "metabase"
    assert "catch-up" in picked["session_prompt"]


def test_load_agenda_session_fetches_resources_from_origin(monkeypatch):
    from types import SimpleNamespace

    from hsengine.engine import federation
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    gaius_item = SimpleNamespace(
        id="scratch/x.md",
        title="Discover reliability catch-up",
        body="Public lede.\n",
        summary="lede",
        starts_ms=0,
        ends_ms=0,
        origin_project="hermes",
        origin_agent="ripley",
    )

    def _query(target, kind, **k):
        if kind == zpb.SERVER_QUERY_KIND_AGENDA:
            return SimpleNamespace(
                project="gaius",
                agenda_hint=SimpleNamespace(project="gaius", item=gaius_item),
            )
        if kind == zpb.SERVER_QUERY_KIND_RESOURCES:
            return SimpleNamespace(
                project="hermes",
                resources_hint=SimpleNamespace(
                    objects=[
                        SimpleNamespace(
                            name="prompt.md",
                            text="Open on Discover reliability, not thoughts.",
                            uri="s3://hermes/resources/scratch/x/prompt.md",
                        )
                    ]
                ),
            )
        return None

    monkeypatch.setattr("hsengine.engine.ops._status_targets", lambda: ["127.0.0.1:50051"])
    monkeypatch.setattr(federation, "query_peer", _query)
    monkeypatch.setattr(
        federation, "peer_target_for_project", lambda p: "127.0.0.1:50651" if p == "hermes" else ""
    )
    session = load_agenda_session("scratch/x.md")
    assert session["origin_project"] == "hermes"
    assert "not thoughts" in session["session_prompt"]
    assert session["target"] == "127.0.0.1:50051"


def test_put_agenda_item_identifies_ripley_to_gaius(monkeypatch):
    from types import SimpleNamespace

    from hsengine.engine.agenda_put import put_agenda_item

    seen: dict = {}

    class _Stub:
        def PutAgendaItem(self, req, timeout=None):
            seen["origin_project"] = req.origin_project
            seen["origin_agent"] = req.origin_agent
            seen["title"] = req.item.title
            seen["item_prompt"] = req.item.session_prompt
            return SimpleNamespace(
                ok=True,
                note="",
                item=SimpleNamespace(
                    id="scratch/2026-09-19/2026-09-19-210000_ripley-catch-up.md",
                    title=req.item.title,
                ),
            )

    class _Ch:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "hsengine.engine.federation.peer_target_for_project", lambda p: "127.0.0.1:50051"
    )
    monkeypatch.setattr("grpc.insecure_channel", lambda target: _Ch())
    monkeypatch.setattr(
        "hsengine.engine.generated.zndx.engine.v1.engine_pb2_grpc.EngineStub",
        lambda ch: _Stub(),
    )
    stored: list = []
    monkeypatch.setattr(
        "hsengine.engine.resources_store.put_session_materials",
        lambda note_id, **k: stored.append({"id": note_id, **k}) or [{"name": "prompt.md"}],
    )
    out = put_agenda_item(
        title="Ripley catch-up",
        origin_agent="ripley",
        session_prompt="Open on Discover.",
    )
    assert out["ok"] is True
    assert seen["origin_project"] == "hermes"
    assert seen["origin_agent"] == "ripley"
    assert not (seen.get("item_prompt") or "")
    assert out["path"].startswith("scratch/")
    assert stored and stored[0]["prompt"] == "Open on Discover."


def test_split_keeps_deck_off_the_public_lede():
    public, deck = split_public_deck(
        "A half hour to decide whether the book moves.\n\n"
        "## Deck\n\n"
        "Opening\n===\n\n"
        "Would you change the book today?\n\n"
        "<!-- speaker_note: Intel raise. -->\n"
        "<!-- end_slide -->\n"
    )
    assert "half hour" in public
    assert "speaker_note" not in public
    assert "end_slide" in deck
    assert "Would you change the book" in deck


def test_opening_uses_full_deck_when_present():
    prompt, system, max_tokens = propose_opening_prompt(
        {
            "title": "Watchlist after the tape",
            "public": "Decide whether the book moves.",
            "deck": "Opening\n===\n\nWould you change the book today?\n",
        }
    )
    assert "Invent a novel prompt" in prompt
    assert "Watchlist after the tape" in prompt
    assert "Would you change the book" in prompt
    assert "You write prompts" in system
    assert "You are Hermes" not in system
    assert max_tokens > 48


def test_opening_without_deck_uses_public_lede():
    prompt, system, max_tokens = propose_opening_prompt(
        {
            "title": "Discover coherence check-in",
            "public": "Would you send a colleague to this screen today?",
            "deck": "",
        }
    )
    assert "Discover coherence check-in" in prompt
    assert "colleague" in prompt
    assert "You write prompts" in system
    assert max_tokens > 48


def test_narrative_at_minute_four_is_not_always_the_opening():
    deck = (
        "Opening\n===\n\nHello.\n\n<!-- end_slide -->\n\n"
        "Intel\n===\n\nTwenty-three billion.\n\n<!-- speaker_note: fumes. -->\n\n"
        "<!-- end_slide -->\n\n"
        "Lilly\n===\n\nGrowth.\n\n<!-- end_slide -->\n\n"
        "Disney\n===\n\nThe gap.\n"
    )
    material = {"title": "Watchlist", "deck": deck, "starts_ms": 0, "ends_ms": 30 * 60 * 1000}
    from hsengine.engine.agenda_deck import narrative_at, parse_slides

    assert len(parse_slides(deck)) == 4
    early = narrative_at(material, elapsed_s=4 * 60)
    late = narrative_at(material, elapsed_s=20 * 60)
    assert early["slide"] == 1
    assert early["title"] == "Opening"
    assert late["slide"] >= 3
    assert late["title"] in ("Lilly", "Disney")
    assert "fumes" in " ".join(narrative_at(material, elapsed_s=10 * 60)["notes"])


def test_opening_without_material_still_offers_the_floor():
    prompt, system, max_tokens = propose_opening_prompt({})
    assert "You write prompts" in system
    assert "empty" in prompt.lower()
    assert "You are Hermes" not in system
    assert max_tokens >= 80


def test_stale_workspace_is_named_in_the_opening():
    prompt, system, _ = propose_opening_prompt(
        {},
        pipeline={
            "workspace": "stale",
            "workspace_note": "stale (thoughts 45h)",
            "thoughts_spoken": "State as a hidden control plane on the edge.",
        },
    )
    assert "stale" in prompt.lower() or "45h" in prompt
    assert "say so plainly" in system.lower() or "workspace failed" in system.lower()


def test_strip_invented_prompt_is_empty_when_invent_fails():
    assert strip_invented_prompt("") == ""
    assert strip_invented_prompt("   ") == ""
    assert "hello" in strip_invented_prompt('```\nSay hello and offer the floor.\n```').lower()


def test_spoken_pass_executes_the_invented_prompt_not_a_canned_one():
    invented = "Greet them, mention cell state and the retrospective, then ask if they want to go first."
    prompt, system, _ = spoken_opening_prompt(
        invented,
        {"title": "Watchlist"},
        pipeline={"thoughts_spoken": "State as a hidden control plane on the edge."},
    )
    assert prompt.startswith(invented)
    assert "cell state" in prompt.lower() or "control plane" in prompt.lower()
    assert "You write prompts" not in system
    assert "plain spoken" in system.lower()


def test_opening_gesture_is_stable_for_a_session_and_varies_across_sessions():
    a = pick_opening_gesture("session-aaa")
    b = pick_opening_gesture("session-aaa")
    assert a.id == b.id
    ids = {pick_opening_gesture(f"session-{i}").id for i in range(40)}
    assert len(ids) >= 2
    assert ids <= {g.id for g in OPENING_GESTURES}


def test_opening_uses_pipeline_briefs_when_there_is_no_session_material():
    prompt, system, max_tokens = propose_opening_prompt(
        {},
        pipeline={
            "agenda_spoken": "Today is the AgentRTC retrospective.",
            "thoughts_spoken": "I keep thinking about verifiable cell state.",
        },
    )
    assert "AgentRTC retrospective" in prompt
    assert "verifiable cell state" in prompt
    assert "You write prompts" in system
    assert max_tokens > 48


def test_opening_with_deck_still_carries_pipeline_briefs():
    prompt, system, _ = propose_opening_prompt(
        {
            "title": "Watchlist after the tape",
            "public": "Decide whether the book moves.",
            "deck": "Opening\n===\n\nWould you change the book today?\n",
        },
        pipeline={"thoughts_spoken": "Contracts and molecular partner specificity."},
    )
    assert "Would you change the book" in prompt
    assert "molecular partner" in prompt
    assert "You write prompts" in system
