"""Voice-loop operational snapshot: facts for Cerebras, spoken analysis after."""
from __future__ import annotations

import json

from hsengine.engine import ops
from hsengine.engine.webrtc_moshi import SPOKEN_SYSTEM


def test_spoken_system_treats_casual_checkin_as_ops():
    text = SPOKEN_SYSTEM.lower()
    assert "how things are going" in text
    assert "casually" in text
    assert "special words" in text
    assert " fmp" in text or "call fmp" in text


def test_sitrep_tool_description_does_not_require_jargon():
    desc = ops.CEREBRAS_TOOLS[0]["function"]["description"].lower()
    assert "how's it going" in desc or "hows it going" in desc
    assert "even if they never say a tool name" in desc


def test_brief_activity_shortens_id():
    brief = ops._brief_activity(
        {
            "activity_id": "abcdefghijklmnop",
            "kind": "interactive_session",
            "peer": "hermes",
            "state": "running",
            "reason": "agent-rtc",
            "claims": [{"leaf": "root.internal.inference.agent-rtc", "gpu": 1}],
        }
    )
    assert brief["id"] == "ijklmnop"
    assert brief["state"] == "running"


def test_dispatch_unknown_is_json_error():
    data = json.loads(ops.dispatch("nope"))
    assert data["ok"] is False


def test_dispatch_kb_and_web_search(monkeypatch):
    seen: list[tuple] = []

    def _search(*, query, stream="all", limit=6):
        seen.append((query, stream))
        return {"ok": True, "query": query, "stream": stream, "hits": []}

    monkeypatch.setattr(ops, "search", _search)
    kb = json.loads(ops.dispatch("kb_search", {"query": "theta cycle"}))
    web = json.loads(ops.dispatch("web_search", {"query": "intel 18A"}))
    assert kb["stream"] == "kb"
    assert web["stream"] == "web"
    assert seen == [("theta cycle", "kb"), ("intel 18A", "web")]


def test_search_kind_union_accepts_web_and_buffer(monkeypatch):
    """tuple | frozenset TypeError used to kill web_search and silence glance."""
    monkeypatch.setattr(ops, "_status_targets", lambda: [])
    web = ops.search(query="hn", stream="web")
    buf = ops.search(query="", stream="buffer")
    assert web["ok"] is True and web["stream"] == "web"
    assert buf["ok"] is True and buf["stream"] == "buffer"


def test_dispatch_fmp(monkeypatch):
    def _fmp(*, query, stream="search", limit=6):
        return {"ok": True, "query": query, "stream": stream, "hits": [{"symbol": "SLB"}]}

    monkeypatch.setattr(ops, "fmp", _fmp)
    data = json.loads(ops.dispatch("fmp", {"query": "schlumberger", "stream": "search"}))
    assert data["hits"][0]["symbol"] == "SLB"
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    assert "fmp" in names
    assert "hermes" in names


def test_dispatch_hermes_requires_interactive(monkeypatch):
    monkeypatch.setattr(
        "agent.interactive_cerebras.overlay_runtime", lambda: None
    )
    data = json.loads(ops.dispatch("hermes", {"prompt": "list skills"}))
    assert data["ok"] is False
    assert "not in force" in data["error"]


def test_glance_spoken_uses_buffer_note():
    text = ops.glance_spoken(
        {
            "ok": True,
            "note": "gaius: Attending ADMIT prospects fmp: SLB. HN: Show HN. FMP: SLB",
            "hits": [],
        }
    )
    assert "Attending" in text and "HN:" in text
    assert "Show HN" in text and "SLB" in text
    assert ops.glance_spoken({"ok": True, "note": "gaius: dual cognition buffer empty", "hits": []}) == ""
    assert ops.glance_spoken({"ok": False}) == ""


def test_spoken_system_mentions_kb_and_web_search():
    text = SPOKEN_SYSTEM.lower()
    assert "kb_search" in text
    assert "web_search" in text
    assert "conversation" in text
    assert "session_search" in text
    assert "shares this same session" in text or "share this same session" in text
    assert "gaius" in text
    assert "local wiki" in text
    assert "this minute" not in text
    assert "elapsed" not in text


def test_hermes_tool_keeps_files_in_hermes_home():
    hermes = next(t for t in ops.CEREBRAS_TOOLS if t["function"]["name"] == "hermes")
    desc = hermes["function"]["description"].lower()
    assert "hermes_home" in desc
    assert "operator home" in desc
    assert "kb_search" in desc
    assert "gaius" in desc
    assert "session_search" in desc


def test_kb_search_is_gaius_not_hermes_notes():
    kb = next(t for t in ops.CEREBRAS_TOOLS if t["function"]["name"] == "kb_search")
    desc = kb["function"]["description"].lower()
    assert "gaius" in desc
    assert "session_search" in desc
    assert "our notes" not in desc


def test_conversation_tool_does_not_ask_to_announce_the_clock():
    conv = next(t for t in ops.CEREBRAS_TOOLS if t["function"]["name"] == "conversation")
    desc = conv["function"]["description"].lower()
    assert "do not announce elapsed time" in desc
    narr = next(t for t in ops.CEREBRAS_TOOLS if t["function"]["name"] == "narrative")
    assert "clock" in narr["function"]["description"].lower()


def test_dispatch_conversation(monkeypatch):
    monkeypatch.setattr(
        ops,
        "conversation",
        lambda **k: {"ok": True, "count": 2, "turns": [{"role": "user", "text": "hi"}]},
    )
    data = json.loads(ops.dispatch("conversation", {}))
    assert data["count"] == 2
    assert data["turns"][0]["role"] == "user"


def test_session_search_is_a_cerebras_tool():
    names = [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    assert "session_search" in names
    assert "conversation" in names
    assert "hermes" in names


def test_session_search_this_call_finds_overflow(monkeypatch, tmp_path):
    from hermes_state import SessionDB
    from hsengine.engine import session_history

    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.open_session("cafe")
        session_history.record_turn("cafe", user="the xylophone briefing")
        session_history.record_turn("cafe", assistant="got it")
        for i in range(16):
            session_history.record_turn("cafe", user=f"later-{i}", assistant=f"ack-{i}")
        monkeypatch.setattr(session_history, "live_webrtc_id", lambda: "cafe")
        data = json.loads(ops.dispatch("session_search", {"query": "xylophone"}))
        assert data["ok"] is True
        assert data["mode"] == "this_call"
        assert data["hermes_session_id"] == "agent-rtc-cafe"
        assert any("xylophone" in h["text"] for h in data["hits"])
    finally:
        session_history.configure(None)
        db.close()


def test_conversation_reports_overflow(monkeypatch, tmp_path):
    from hermes_state import SessionDB
    from hsengine.engine import session_history

    db = SessionDB(db_path=tmp_path / "state.db")
    session_history.configure(db)
    try:
        session_history.open_session("cafe")
        for i in range(20):
            session_history.record_turn("cafe", user=f"u{i}", assistant=f"a{i}")
        monkeypatch.setattr(session_history, "live_webrtc_id", lambda: "cafe")
        monkeypatch.setattr(
            "hsengine.engine.webrtc_session.HUB.narrative_checkin", lambda **k: {}
        )
        out = ops.conversation(limit=8)
        assert out["ok"] is True
        assert out["hermes_session_id"] == "agent-rtc-cafe"
        assert out["older_count"] > 0
        assert out["count"] == 8
    finally:
        session_history.configure(None)
        db.close()


def test_hermes_binds_live_agent_rtc_session(monkeypatch):
    seen: dict = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            seen["init"] = kwargs
            self._end_session_on_close = True

        def run_conversation(self, prompt, conversation_history=None):
            seen["prompt"] = prompt
            seen["history"] = conversation_history
            return {"final_response": "done"}

        def close(self):
            seen["ended"] = self._end_session_on_close

    monkeypatch.setattr(
        "agent.interactive_cerebras.overlay_runtime",
        lambda: {
            "base_url": "https://api.cerebras.ai/v1",
            "api_key": "k",
            "provider": "cerebras",
            "model": "qwen-3.8-27b",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)
    monkeypatch.setattr(
        "hsengine.engine.session_history.live_webrtc_id", lambda: "cafe"
    )
    monkeypatch.setattr(
        "hsengine.engine.session_history.transcript_messages",
        lambda _wid: [{"role": "user", "content": "we talked about the lattice"}],
    )
    monkeypatch.setattr("hsengine.engine.session_history._store", lambda: "db")
    data = json.loads(ops.dispatch("hermes", {"prompt": "what did we just say"}))
    assert data["ok"] is True
    assert data["text"] == "done"
    assert data["session_id"] == "agent-rtc-cafe"
    assert seen["init"]["session_id"] == "agent-rtc-cafe"
    assert seen["init"]["session_db"] == "db"
    assert seen["init"]["platform"] == "agent-rtc"
    assert seen["history"][0]["content"] == "we talked about the lattice"
    assert seen["ended"] is False


def test_dispatch_narrative(monkeypatch):
    monkeypatch.setattr(
        ops,
        "narrative",
        lambda **k: {"ok": True, "elapsed_min": 4.0, "title": "Intel", "slide": 2},
    )
    data = json.loads(ops.dispatch("narrative", {"at_minute": 4}))
    assert data["title"] == "Intel"
    assert data["elapsed_min"] == 4.0


def test_sitrep_bundles_local_peers_and_activities(monkeypatch):
    monkeypatch.setattr(
        ops,
        "hermes_local",
        lambda: {
            "project": "hermes",
            "dashboard": {"healthy": True, "detail": "http 200"},
            "moshi": True,
            "interactive": True,
            "gpus": [5],
            "workload": "interactive.agent_rtc",
        },
    )
    monkeypatch.setattr(ops, "_status_targets", lambda: ["127.0.0.1:50051"])
    monkeypatch.setattr(
        ops,
        "_peer_row",
        lambda target: {
            "target": target,
            "reachable": True,
            "project": "gaius",
            "total_gpus": 6,
            "endpoints": [
                {"capability": "thinking", "model": "Qwen", "healthy": True, "gpus": [0]}
            ],
            "surfaces": [
                {
                    "kind": "coordination",
                    "healthy": False,
                    "url": "#CO.00000002.STREAMDROP",
                }
            ],
        },
    )
    monkeypatch.setattr(
        ops,
        "activities",
        lambda **_k: {
            "ok": True,
            "activities": [
                {"kind": "interactive_session", "peer": "hermes", "state": "running"}
            ],
        },
    )
    snap = ops.sitrep()
    assert snap["hermes"]["interactive"] is True
    assert snap["reachable_peers"] == 1
    assert snap["peers"][0]["project"] == "gaius"
    assert snap["activities"][0]["state"] == "running"
    assert snap["activities_ok"] is True
    assert snap["airflow_hub"][0]["healthy"] is False
    assert "STREAMDROP" in snap["airflow_hub"][0]["detail"]


def test_dispatch_sitrep_returns_json(monkeypatch):
    monkeypatch.setattr(ops, "sitrep", lambda: {"when": "now", "peer_count": 2})
    data = json.loads(ops.dispatch("sitrep"))
    assert data["peer_count"] == 2


# ── recent_thoughts: "what have you been thinking about?" over the protocol ──

def peers_have_brief(out):
    return any(p.get("brief", {}).get("written") for p in out["peers"])


def test_recent_thoughts_merges_peer_hints_newest_first(monkeypatch):
    import time
    from concurrent import futures

    import grpc

    from hsengine.engine import ops
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    now_ms_ref = [int(time.time() * 1000)]

    class FakeEngine(zpb_grpc.EngineServicer):
        def __init__(self, project, thoughts, note=""):
            self.project, self.thoughts, self.note = project, thoughts, note
            self.requests = []

        def ServerQuery(self, request, context):  # noqa: N802
            self.requests.append(request)
            resp = zpb.ServerQueryResponse(project=self.project)
            if request.kind == zpb.SERVER_QUERY_KIND_THOUGHTS and (self.thoughts or self.note):
                # a peer WITHOUT a cognition unit leaves the hint unset (honest silence)
                h = resp.thoughts_hint
                h.project = self.project
                h.note = self.note
                h.total_in_window = len(self.thoughts)
                for i, (title, at_ms) in enumerate(self.thoughts):
                    h.thoughts.append(zpb.Thought(id=f"t{i}", at_ms=at_ms, kind="connection", title=title,
                                                  summary=f"{title} — summary", domains=["biorxiv"], salience=0.5))
                if self.thoughts:
                    h.newest_ms = max(a for _, a in self.thoughts)
                if getattr(self, 'brief', ''):
                    h.brief = self.brief
                    h.spoken = self.brief + ' (spoken)'
                    h.brief_at_ms = now_ms_ref[0] - 120_000
                    h.brief_thoughts = 7
            return resp

    now_ms = now_ms_ref[0]
    gaius = FakeEngine("gaius", [("older", now_ms - 3_600_000), ("newest", now_ms - 60_000)])
    gaius.brief = "Lately I have been thinking about state as a control plane."
    silent = FakeEngine("aegir", [])  # no cognition unit: empty hint → honest silence
    servers, targets = [], []
    for fake in (gaius, silent):
        srv = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        zpb_grpc.add_EngineServicer_to_server(fake, srv)
        port = srv.add_insecure_port("127.0.0.1:0"); srv.start()
        servers.append(srv); targets.append(f"127.0.0.1:{port}")
    targets.append("127.0.0.1:1")  # unreachable peer
    monkeypatch.setattr(ops, "_status_targets", lambda: targets)
    try:
        out = ops.recent_thoughts(limit=5, since_hours=6, kind="connection")
    finally:
        for srv in servers:
            srv.stop(0)
    assert out["ok"] and out["count"] == 2
    assert out["briefs"][0]["project"] == "gaius" and out["briefs"][0]["spoken"].endswith("(spoken)")
    assert out["briefs"][0]["thoughts_considered"] == 7 and 1 <= out["briefs"][0]["age_min"] <= 3
    assert peers_have_brief(out)
    assert [t["title"] for t in out["thoughts"]] == ["newest", "older"]
    assert out["thoughts"][0]["project"] == "gaius" and out["thoughts"][0]["kind"] == "connection"
    peers = {p.get("target"): p for p in out["peers"]}
    assert peers[targets[0]]["reachable"] and peers[targets[0]]["in_window"] == 2
    assert targets[1] not in peers  # silent peer omitted
    assert peers["127.0.0.1:1"]["reachable"] is False
    req = gaius.requests[0]
    assert req.kind == zpb.SERVER_QUERY_KIND_THOUGHTS and req.limit == 5 and req.stream == "connection"
    assert req.since_ms > now_ms - 7 * 3_600_000 and req.origin_project == "hermes"
    # the tool is dispatchable and declared to Cerebras
    assert "recent_thoughts" in [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    import json
    assert json.loads(ops.dispatch("recent_thoughts", {"limit": "2"}))["ok"] is True


# ── agenda: the peer's Agenda BRIEF + item index, and one item on request ─────

def test_agenda_tool_brief_index_and_single_item(monkeypatch):
    import json
    import time
    from concurrent import futures

    import grpc

    from hsengine.engine import ops
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from hsengine.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc

    now_ms = int(time.time() * 1000)

    class FakeAgendaEngine(zpb_grpc.EngineServicer):
        def __init__(self):
            self.requests = []

        def ServerQuery(self, request, context):  # noqa: N802
            self.requests.append(request)
            resp = zpb.ServerQueryResponse(project="gaius")
            if request.kind != zpb.SERVER_QUERY_KIND_AGENDA:
                return resp
            h = resp.agenda_hint
            h.project, h.timezone, h.today = "gaius", "UTC", "2026-09-07"
            h.brief, h.spoken = "Today: one check-in.", "Today there is one check-in at four."
            h.brief_at_ms = now_ms - 600_000
            h.total_in_window = 2
            a = h.items.add(id="scratch/2026-09-06/x_discover-check-in.md", starts_ms=now_ms + 3_600_000, kind="event",
                            intent="session", title="Discover coherence check-in", summary="Weekly look", day="today")
            h.items.add(id="scratch/2026-09-06/y_operator-follow-ups.md", kind="list", intent="reminder",
                        title="Operator follow-ups", open_checks=3, day="week")
            if request.note_id == a.id:
                h.item.CopyFrom(a)
                h.item.body = "Full body of the check-in note."
            elif request.note_id:
                h.note = "item not found"
            return resp

    fake = FakeAgendaEngine()
    srv = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    zpb_grpc.add_EngineServicer_to_server(fake, srv)
    port = srv.add_insecure_port("127.0.0.1:0"); srv.start()
    monkeypatch.setattr(ops, "_status_targets", lambda: [f"127.0.0.1:{port}", "127.0.0.1:1"])
    try:
        out = ops.agenda()
        assert out["ok"] and out["briefs"][0]["spoken"].startswith("Today there is one")
        assert out["briefs"][0]["today"] == "2026-09-07" and out["briefs"][0]["age_min"] in (9, 10, 11)
        assert [i["title"] for i in out["items"]] == ["Discover coherence check-in", "Operator follow-ups"]
        assert out["items"][0]["day"] == "today" and out["items"][1]["open_checks"] == 3
        assert any(p.get("reachable") is False for p in out["peers"])
        one = json.loads(ops.dispatch("agenda", {"item_id": "scratch/2026-09-06/x_discover-check-in.md"}))
        assert one["item"]["body"].startswith("Full body") and one["item"]["kind"] == "event"
        assert fake.requests[-1].note_id == "scratch/2026-09-06/x_discover-check-in.md"
        missing = json.loads(ops.dispatch("agenda", {"item_id": "nope"}))
        assert missing["item"] is None and "no peer has an agenda item" in missing["item_note"]
        assert "agenda" in [t["function"]["name"] for t in ops.CEREBRAS_TOOLS]
    finally:
        srv.stop(0)
