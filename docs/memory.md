# Memory for AgentRTC (signals-memory)

AgentRTC uses Hermes' **MemoryProvider** subsystem — not a second store.
The plugin is `plugins/signals-memory`. Activate with:

```yaml
plugins:
  enabled: [signals-memory]
memory:
  provider: signals-memory   # CLI / hermes() subagents
```

If `memory.provider` is empty, the AgentRTC sidecar still loads
`signals-memory` when the plugin is installed. A configured Honcho (or
other) provider is not overridden.

## Hybrid, tier-aware, agent-mediated

`prefetch` (and `signals_recall`) return one pack. Bishop **invents**
from it; Ripley does **not** read it as a briefing.

| Tier | What | How |
|------|------|-----|
| Conversations | Recent Hermes/AgentRTC sessions | FTS5 + recency (`hsengine.engine.recall`) |
| Citations | `${HERMES_HOME}/wiki`, `memories/MEMORY.md` | Lexical, entity/concept pages first |
| Turns | Profile JSONL (`signals-memory/turns.jsonl`) | Keyword, newest last |
| Lattice | Gaius `ServerQuery SEARCH` | Semantic-ish, **lowest** priority |

Lexical talks and wiki always outrank Gaius. Empty Gaius / a Gaius
outage fails open.

## Seams

- `MemoryProvider.prefetch` / `sync_turn` — CLI and AgentRTC
- `hsengine.engine.session_history.recalled_memory` — spoken Cerebras prefix
- `bishop_run(utterance=...)` — invent pass recalls the **user** text, not Bishop's prompt
- `session_search` / `kb_search` remain tools for deepen; they are not the first hop
