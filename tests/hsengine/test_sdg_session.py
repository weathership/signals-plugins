# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import grpc
from hermes_state import SessionDB

from hsengine.engine import sdg_session, session_history
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb


class _Unimplemented(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNIMPLEMENTED


def _genus(start: int, end: int) -> dict:
    return {
        "start": start,
        "end": end,
        "genus_iri": "https://signals.zndx.org/sdg#LIMS",
        "genus_code": "9",
        "genus_label": "LIMS",
        "rel_margin_h": 0.55,
        "tau": 0.10,
    }


def test_new_characters_keep_rising_seq_and_end_flushes() -> None:
    seen: list[tuple[int, str, bool]] = []

    class _Stub:
        def AdmitSession(self, frames):
            for frame in frames:
                seen.append((int(frame.seq), frame.text, bool(frame.end)))
                if frame.text == "HELLO":
                    yield zpb.SegmentAdmission(
                        session_id="call",
                        seq=frame.seq,
                        start=4,
                        end=9,
                        genus_iri="https://signals.zndx.org/sdg#LIMS",
                        genus_code="9",
                        genus_label="LIMS",
                        rel_margin_h=0.55,
                        tau=0.10,
                    )
            return

    calls: list[str] = []

    def run(piece: str, link: dict):
        calls.append(piece)
        return {"sdg_iri": link["genus_iri"], "confidence": 0.8, "offered": [link["genus_iri"]]}

    sdg_session.begin("call", "agent-rtc-call", target="127.0.0.1:1", dial_fn=lambda _t: (None, _Stub()))
    stream = sdg_session._LIVE["call"]
    stream.run = run
    try:
        sdg_session.note("call", "agent-rtc-call", "user", "xxxx")
        sdg_session.note("call", "agent-rtc-call", "user", "HELLO")
        sdg_session.end("call")
        assert stream.thread is not None
        stream.thread.join(timeout=2)
        assert seen == [(1, "xxxx", False), (2, "HELLO", False), (3, "", True)]
        assert calls == ["HELLO"]
    finally:
        sdg_session.end("call")


def test_unimplemented_does_not_raise() -> None:
    class _Stub:
        def AdmitSession(self, frames):
            for _frame in frames:
                raise _Unimplemented()
            return
            yield  # pragma: no cover

    sdg_session.begin("quiet", "agent-rtc-quiet", target="127.0.0.1:1", dial_fn=lambda _t: (None, _Stub()))
    sdg_session.note("quiet", "agent-rtc-quiet", "user", "hello")
    stream = sdg_session._LIVE["quiet"]
    assert stream.thread is not None
    stream.thread.join(timeout=2)
    assert stream.error is None
    sdg_session.end("quiet")


def test_note_without_begin_does_not_dial() -> None:
    sdg_session.note("absent", "agent-rtc-absent", "user", "hello")
    assert "absent" not in sdg_session._LIVE


def test_a_neighbor_span_is_not_sent_to_the_workflow() -> None:
    spans = [
        {"start": 0, "end": 4, "text": "xxxx", "links": []},
        {"start": 4, "end": 9, "text": "HELLO", "links": []},
    ]
    chosen = sdg_session.overlapping(spans, 4, 9)
    assert [span["text"] for span in chosen] == ["HELLO"]
    seen: list[str] = []

    def run(piece: str, link: dict):
        seen.append(piece)
        return {"sdg_iri": link["genus_iri"], "confidence": 0.4, "offered": [link["genus_iri"]]}

    meta = sdg_session.apply_span(chosen[0], _genus(4, 9), workflow_name="signals-system-one", run=run)
    assert seen == ["HELLO"]
    assert meta["links"][0]["sdg.iri"] == "https://signals.zndx.org/sdg#LIMS"
    assert meta["links"][0]["semantica.confidence"] == 0.4


def test_a_refused_genus_does_not_invent_an_iri() -> None:
    span = {"start": 0, "end": 5, "text": "HELLO", "links": []}
    meta = sdg_session.apply_span(span, _genus(0, 5), workflow_name="signals-system-one", run=lambda *_a: None)
    assert "sdg.iri" not in meta["links"][0]


def test_stored_turn_is_handed_to_an_open_stream(tmp_path, monkeypatch) -> None:
    seen: list[tuple] = []
    monkeypatch.setattr("hsengine.engine.sdg_session.note", lambda *args: seen.append(args))
    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.record_turn("abc", user="hello lattice")
    finally:
        session_history.configure(None)
        db.close()
    assert seen == [("abc", "agent-rtc-abc", "user", "hello lattice")]
