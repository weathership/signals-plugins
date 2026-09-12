"""Signals memory provider — profile-scoped hybrid recall.

Lexical (SessionDB FTS + wiki/MEMORY.md + JSONL turns) outranks semantic
lattice SEARCH (Gaius). AgentRTC and CLI share this MemoryProvider so
interactive sessions use the same subsystem.

Does not land under plugins/memory/ (that set is closed). Discovered from
$HERMES_HOME/plugins/signals-memory via the stock MemoryProvider loader.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider, RecallStatus, is_trivial_prompt
from hermes_constants import get_hermes_home

log = logging.getLogger("hsengine.plugins.signals_memory")

_RECALL_SCHEMA = {
    "name": "signals_recall",
    "description": (
        "Hybrid recall over Hermes talks, the local wiki, and Gaius lattice "
        "SEARCH. Tiers: recent sessions (newest first), wiki/MEMORY.md, then "
        "lattice. Use to invent the next move; do not read hits aloud as a "
        "briefing. Pass keywords, not the whole question."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords to recall."},
            "limit": {"type": "integer", "description": "Max JSONL hits (default 8)."},
        },
        "required": ["query"],
    },
}


class SignalsMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str:
        return "signals-memory"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""
        home = Path(kwargs.get("hermes_home") or get_hermes_home())
        self._home = home
        self._path = home / "signals-memory" / "turns.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hits = 0
        self._platform = str(kwargs.get("platform") or "")

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if is_trivial_prompt(query):
            self._last_hits = 0
            return ""
        sid = session_id or getattr(self, "_session_id", "")
        home = getattr(self, "_home", None) or get_hermes_home()
        jsonl = self._search(query, limit=4)
        try:
            block = _prefetch_block(
                query, session_id=sid, hermes_home=Path(home), jsonl_hits=jsonl
            )
        except Exception:
            log.debug("signals-memory hybrid prefetch failed", exc_info=True)
            block = ""
            if jsonl:
                lines = [f"- {h.get('role', 'turn')}: {h.get('text', '')[:240]}" for h in jsonl]
                block = "Signals memory (local):\n" + "\n".join(lines)
        self._last_hits = (1 if block else 0) + len(jsonl)
        return block

    def recall_status(self) -> Optional[RecallStatus]:
        if self._last_hits <= 0:
            return None
        return RecallStatus(provider_label="signals-memory", count=self._last_hits, glyph="📡")

    def sync_turn(
        self, user_content: str, assistant_content: str, *,
        session_id: str = "", messages: Optional[List[Dict[str, Any]]] = None,
        turn_author: Optional[Dict[str, Any]] = None,
    ) -> None:
        sid = session_id or getattr(self, "_session_id", "")
        self._append({"session_id": sid, "role": "user", "text": (user_content or "")[:4000]})
        self._append({"session_id": sid, "role": "assistant", "text": (assistant_content or "")[:4000]})

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [_RECALL_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name != "signals_recall":
            return json.dumps({"success": False, "error": f"unknown tool {tool_name}"})
        query = str(args.get("query") or "")
        limit = int(args.get("limit") or 8)
        jsonl = self._search(query, limit=limit)
        home = getattr(self, "_home", None) or get_hermes_home()
        sid = str(kwargs.get("session_id") or getattr(self, "_session_id", "") or "")
        try:
            block = _prefetch_block(
                query,
                session_id=sid,
                hermes_home=Path(home),
                jsonl_hits=jsonl,
            )
        except Exception as e:
            block = ""
            log.debug("signals_recall hybrid failed: %s", e, exc_info=True)
        return json.dumps(
            {
                "success": True,
                "hits": jsonl,
                "block": block,
                "invent": True,
                "note": "Invent from tiers; do not read as a briefing. Talks/wiki outrank Gaius.",
            },
            ensure_ascii=False,
        )

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        texts = []
        for msg in messages[-12:]:
            content = msg.get("content") if isinstance(msg, dict) else ""
            if isinstance(content, str) and content.strip():
                texts.append(content.strip()[:400])
        if not texts:
            return ""
        return "Signals memory checkpoint (turns about to compact):\n" + "\n---\n".join(texts)

    def _append(self, row: dict[str, str]) -> None:
        path = getattr(self, "_path", None)
        if path is None:
            return
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _search(self, query: str, *, limit: int) -> list[dict[str, str]]:
        path = getattr(self, "_path", None)
        if path is None or not path.is_file() or not (query or "").strip():
            return []
        try:
            from hsengine.engine.recall import focus_query

            needle = (focus_query(query) or query).strip().lower()
        except Exception:
            needle = query.strip().lower()
        if not needle:
            return []
        tokens = [t for t in needle.split() if t]
        hits: list[dict[str, str]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = str(row.get("text") or "")
            blob = text.lower()
            if tokens and not all(t in blob for t in tokens):
                continue
            if not tokens and needle not in blob:
                continue
            hits.append(row)
            if len(hits) >= max(1, limit):
                break
        return hits


def _prefetch_block(
    query: str,
    *,
    session_id: str,
    hermes_home: Path,
    jsonl_hits: list[dict[str, Any]],
) -> str:
    """Import hybrid from this plugin directory (Hermes loads us by path, not package)."""
    import importlib.util

    hybrid_path = Path(__file__).resolve().parent / "hybrid.py"
    spec = importlib.util.spec_from_file_location("signals_memory_hybrid", hybrid_path)
    if spec is None or spec.loader is None:
        return ""
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(
        mod.prefetch_block(
            query,
            session_id=session_id,
            hermes_home=hermes_home,
            jsonl_hits=jsonl_hits,
        )
        or ""
    )
