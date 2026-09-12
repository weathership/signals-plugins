"""Hermes hosts zndx.agent.v1: ListAgents / Run, not Complete-as-agent."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hsengine.engine import agents, s2s
from hsengine.engine.generated.zndx.agent.v1 import agent_pb2 as apb
from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as zpb


def test_fmp_and_agents_kinds_do_not_collide():
    assert zpb.SERVER_QUERY_KIND_FMP == 16
    assert zpb.SERVER_QUERY_KIND_AGENTS == 17
    assert zpb.SERVER_QUERY_KIND_FMP != zpb.SERVER_QUERY_KIND_AGENTS


def test_offer_is_hermes_sdk_not_complete_capability():
    o = agents.offer()
    assert o.name == "hermes"
    assert o.project == "hermes"
    assert o.transport == apb.AGENT_TRANSPORT_SDK
    assert "thinking" in list(o.model_capabilities)
    assert "memory" in list(o.behaviours)
    assert o.agent_id.startswith("hermes/hermes@")


def test_server_query_agents_lists_the_offer():
    resp = s2s.local_response(zpb.SERVER_QUERY_KIND_AGENTS)
    assert resp.project == "hermes"
    assert len(resp.agents) == 1
    assert resp.agents[0].name == "hermes"
    assert resp.agents[0].transport == "sdk"


def test_run_unknown_agent_is_invalid():
    req = apb.RunRequest(agent="metabot", instruction="hi")
    try:
        list(agents.iter_run(req))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "hermes" in str(e)


def test_run_drives_aiagent_and_streams_done():
    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._end_session_on_close = True
            FakeAgent.seen = kwargs

        def chat(self, prompt):
            FakeAgent.prompt = prompt
            return "agenda is Discover"

        def close(self):
            FakeAgent.ended = self._end_session_on_close

    req = apb.RunRequest(agent="hermes", instruction="have Hermes brief the agenda")
    with patch("agent.interactive_cerebras.overlay_runtime", return_value=None):
        with patch("run_agent.AIAgent", FakeAgent):
            events = list(agents.iter_run(req))
    kinds = [ev.WhichOneof("event") for ev in events]
    assert kinds == ["accepted", "message", "done"]
    assert events[0].accepted.agent_id.startswith("hermes/hermes@")
    assert events[1].message.text == "agenda is Discover"
    assert events[2].done.state == apb.RUN_COMPLETED
    assert FakeAgent.seen["session_id"].startswith("agent-run-")
    assert FakeAgent.ended is False
    assert FakeAgent.prompt == "have Hermes brief the agenda"
