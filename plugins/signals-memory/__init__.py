"""Signals memory provider — local JSONL under get_hermes_home(), not Atlas.

Does not land under plugins/memory/ (that set is closed). Discovered from
$HERMES_HOME/plugins/signals-memory via the stock MemoryProvider loader.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider, RecallStatus
from hermes_constants import get_hermes_home

log = logging.getLogger("hsengine.plugins.signals_memory")

_RECALL_SCHEMA = {
    "name": "signals_recall",
    "description": "Search this profile's Signals-local turn memory.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to match in stored turns."},
            "limit": {"type": "integer", "description": "Max hits (default 8)."},
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
        self._path = home / "signals-memory" / "turns.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hits = 0

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        hits = self._search(query, limit=6)
        self._last_hits = len(hits)
        if not hits:
            return ""
        lines = [f"- {h.get('role', 'turn')}: {h.get('text', '')[:240]}" for h in hits]
        return "Signals memory (local):\n" + "\n".join(lines)

    def recall_status(self) -> Optional[RecallStatus]:
        if self._last_hits <= 0:
            return None
        return RecallStatus(provider_label="signals-memory", count=self._last_hits, glyph="📡")

    def sync_turn(
        self, user_content: str, assistant_content: str, *,
        session_id: str = "", messages: Optional[List[Dict[str, Any]]] = None,
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
        return json.dumps({"success": True, "hits": self._search(query, limit=limit)})

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
        needle = query.strip().lower()
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
            if needle in text.lower():
                hits.append(row)
            if len(hits) >= max(1, limit):
                break
        return hits
