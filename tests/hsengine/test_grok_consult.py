"""Grok consult uses the Hermes xAI subscription, not the Cerebras overlay."""
from __future__ import annotations

from hsengine.engine.grok_consult import consult, configured_model


def test_consult_requires_a_question():
    out = consult(question="  ")
    assert out["ok"] is False
    assert "question" in out["error"]


def test_configured_model_uses_hermes_default(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"model": {"default": "grok-4.6", "provider": "xai-oauth"}},
    )
    assert configured_model() == "grok-4.6"


def test_consult_without_bearer(monkeypatch):
    monkeypatch.setattr(
        "tools.xai_http.resolve_xai_http_credentials",
        lambda **k: {
            "api_key": "",
            "base_url": "https://api.x.ai/v1",
            "provider": "xai-oauth",
        },
    )
    out = consult(question="why is this looping")
    assert out["ok"] is False
    assert "bearer" in out["error"].lower() or "xai" in out["error"].lower()


def test_consult_posts_chat_completions_with_oauth(monkeypatch):
    seen: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "grok-4.6",
                "choices": [
                    {
                        "message": {
                            "content": "Name the stuck distinction: kasten vs archive."
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20},
            }

    class _Client:
        def __init__(self, timeout=None):
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            return _Resp()

    def _creds(**k):
        seen["prefer_api_key"] = k.get("prefer_api_key")
        return {
            "api_key": "oauth-token",
            "base_url": "https://api.x.ai/v1",
            "provider": "xai-oauth",
        }

    monkeypatch.setattr("tools.xai_http.resolve_xai_http_credentials", _creds)
    monkeypatch.setattr(
        "hsengine.engine.grok_consult.configured_model", lambda: "grok-4.6"
    )
    monkeypatch.setattr("httpx.Client", _Client)
    out = consult(question="kasten or archive?", context="three turns")
    assert out["ok"] is True
    assert out["provider"] == "xai-oauth"
    assert out["model"] == "grok-4.6"
    assert "kasten vs archive" in out["text"]
    assert seen.get("prefer_api_key") is False
    assert seen["url"].endswith("/chat/completions")
    assert seen["json"]["model"] == "grok-4.6"
    assert "Bearer oauth-token" in seen["headers"]["Authorization"]
    user = seen["json"]["messages"][1]["content"]
    assert "kasten or archive" in user
    assert "three turns" in user
    assert "tools" not in seen["json"]


def test_consult_honors_custom_system(monkeypatch):
    seen: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "grok-4.6",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            }

    class _Client:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            seen["json"] = json
            return _Resp()

    monkeypatch.setattr(
        "tools.xai_http.resolve_xai_http_credentials",
        lambda **k: {
            "api_key": "oauth-token",
            "base_url": "https://api.x.ai/v1",
            "provider": "xai-oauth",
        },
    )
    monkeypatch.setattr("httpx.Client", _Client)
    out = consult(question="review this", system="Write a zettel.", max_tokens=128)
    assert out["ok"] is True
    assert seen["json"]["messages"][0]["content"] == "Write a zettel."
    assert seen["json"]["max_tokens"] == 128


def test_consult_uses_reasoning_when_content_empty(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "grok-4.6",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "the next move is a scratch zettel",
                        }
                    }
                ],
                "usage": {},
            }

    class _Client:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(
        "tools.xai_http.resolve_xai_http_credentials",
        lambda **k: {
            "api_key": "oauth-token",
            "base_url": "https://api.x.ai/v1",
            "provider": "xai-oauth",
        },
    )
    monkeypatch.setattr("httpx.Client", _Client)
    out = consult(question="what next")
    assert out["ok"] is True
    assert "scratch zettel" in out["text"]
