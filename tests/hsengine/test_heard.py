"""The heard-you line has to be about what they just said."""
from __future__ import annotations

from unittest.mock import patch

from hsengine.engine.heard import heard_prompts, line_is_fresh


def test_long_copy_of_the_previous_turn_is_a_repeat():
    from hsengine.engine.heard import repeats_previous_turn

    thoughts = (
        "I've been turning over durable state as the control plane for "
        "distributed and agentic systems. The question that keeps coming back "
        "is what has to survive a failure."
    )
    assert repeats_previous_turn(thoughts, thoughts) is True
    assert repeats_previous_turn(thoughts, thoughts + " And then more.") is True
    assert (
        repeats_previous_turn(
            thoughts,
            "In-home boxes are a different problem from the data-center metrics.",
        )
        is False
    )
    assert repeats_previous_turn("Yeah.", "Yeah.") is False


def test_repeat_is_replaced_before_it_is_spoken(monkeypatch):
    import hsengine.engine.interactive as interactive

    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    thoughts = (
        "I've been turning over durable state as the control plane for "
        "distributed and agentic systems. The question that keeps coming back "
        "is what has to survive a failure, a partial step, or a gray failure."
    )
    copied = {
        "model": "qwen-3.8-27b",
        "choices": [
            {"message": {"content": thoughts, "reasoning": ""}, "finish_reason": "stop"}
        ],
        "usage": {},
    }
    answered = {
        "model": "qwen-3.8-27b",
        "choices": [
            {
                "message": {
                    "content": "DGX Spark and a Mac Studio are not the same buy.",
                    "reasoning": "",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {},
    }
    from tests.hsengine.test_interactive import _client_with_payloads

    client = _client_with_payloads([copied, answered])
    with patch("hsengine.engine.interactive.httpx.Client", return_value=client):
        with patch("hsengine.engine.interactive._speak_cerebras") as speak:
            result = interactive.complete_cerebras(
                prompt="What about four DGX Spark boxes versus a Mac Studio?",
                tools=False,
                history=[
                    {"role": "user", "content": "What have you been thinking about?"},
                    {"role": "assistant", "content": thoughts},
                ],
            )
    assert result.text.startswith("DGX Spark")
    assert speak.call_count == 1
    assert "durable state" not in speak.call_args.args[0]
    retry = client.post.call_args_list[-1].kwargs["json"]
    assert "tools" not in retry
    assert "already said" in retry["messages"][-1]["content"]


def test_stock_ack_is_not_fresh():
    assert line_is_fresh("tell me about the card", "On it.") is False
    assert line_is_fresh("tell me about the card", "Let me look.") is False


def test_line_that_uses_their_word_is_fresh():
    assert line_is_fresh("tell me about the card", "The card, I'm going after that.") is True


def test_unrelated_sentence_is_not_fresh():
    assert line_is_fresh("tell me about the card", "I'll see what I can find.") is False


def test_prompts_carry_their_words_and_a_rejected_try():
    _system, user = heard_prompts("tell me about the card", rejected="On it.")
    assert "tell me about the card" in user
    assert "On it." in user


class _InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, **_k):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target is not None:
            self._target(*self._args, **self._kwargs)


def test_aside_starts_only_when_tools_start(monkeypatch):
    import hsengine.engine.interactive as interactive

    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    monkeypatch.setattr(interactive.threading, "Thread", _InlineThread)
    heard: list[str] = []
    monkeypatch.setattr(
        interactive, "_heard_aside", lambda utterance, *_a, **_k: heard.append(utterance)
    )
    tool = {
        "model": "qwen-3.8-27b",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "kb_search", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {},
    }
    said = {
        "model": "qwen-3.8-27b",
        "choices": [
            {"message": {"content": "Charter.", "reasoning": ""}, "finish_reason": "stop"}
        ],
        "usage": {},
    }
    from tests.hsengine.test_interactive import _client_with_payloads

    client = _client_with_payloads([tool, said])
    with patch("hsengine.engine.interactive.httpx.Client", return_value=client):
        with patch("hsengine.engine.ops.dispatch", return_value="{}"):
            with patch("hsengine.engine.interactive._speak_cerebras"):
                interactive.complete_cerebras(prompt="tell me about the card", tools=True)
    assert heard == ["tell me about the card"]


def test_direct_answer_does_not_aside(monkeypatch):
    import hsengine.engine.interactive as interactive

    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    heard: list[str] = []
    monkeypatch.setattr(
        interactive, "_heard_aside", lambda utterance, *_a, **_k: heard.append(utterance)
    )
    said = {
        "model": "qwen-3.8-27b",
        "choices": [
            {"message": {"content": "Charter.", "reasoning": ""}, "finish_reason": "stop"}
        ],
        "usage": {},
    }
    from tests.hsengine.test_interactive import _client_with_payloads

    client = _client_with_payloads([said])
    with patch("hsengine.engine.interactive.httpx.Client", return_value=client):
        with patch("hsengine.engine.interactive._speak_cerebras"):
            interactive.complete_cerebras(prompt="tell me about the card", tools=True)
    assert heard == []
