"""Signals lattice as a Hermes model-provider plugin.

Uses the stock ``ProviderProfile.create_client`` seam (same as copilot-acp):
AIAgent keeps OpenAI-shaped chat.completions; this client lowers tools to
OIP ``llm_tools_v1`` or ``Engine/Complete``.
"""
from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile

from .client import SignalsOipClient


class SignalsProfile(ProviderProfile):
    def create_client(self, **client_kwargs: Any) -> Any:
        return SignalsOipClient(**client_kwargs)

    def fetch_models(
        self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 8.0
    ) -> list[str] | None:
        return ["thinking", "instruct", "agent"]


signals = SignalsProfile(
    name="signals",
    aliases=("signals-oip", "lattice"),
    display_name="Signals lattice",
    description="Federated OIP / Complete (Gaius thinking, Ægir instruct)",
    env_vars=("SIGNALS_ENGINE_TARGET",),
    base_url="oip://127.0.0.1:50051",
    auth_type="api_key",
    supports_health_check=False,
    fallback_models=("thinking", "instruct", "agent"),
)

register_provider(signals)
