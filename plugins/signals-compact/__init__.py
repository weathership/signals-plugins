"""Signals compaction plugin — stock ContextEngine via ContextCompressor.

Select with ``context.engine: signals``. Same protect-head/tail + summary
algorithm as the built-in compressor; the Signals name lets lattice config
pin compaction without a core fork. Summary LLM can later pin to OIP
instruct; v1 keeps the compressor's auxiliary path.
"""
from __future__ import annotations

from agent.context_compressor import ContextCompressor


class SignalsContextEngine(ContextCompressor):
    @property
    def name(self) -> str:
        return "signals"


def register(ctx) -> None:
    ctx.register_context_engine(SignalsContextEngine(model=""))
