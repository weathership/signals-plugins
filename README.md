# signals-plugins

These standalone Hermes plugins integrate Hermes with a
[Signals](https://github.com/weathership/signals) federated workspace.
Install them from GitHub with `hermes plugins install` (same subdirectory
clone as other third-party plugins).

| Directory | Hermes kind | Activate |
|-----------|-------------|----------|
| `plugins/signals-oip` | model-provider (`create_client`) | `model.provider: signals` |
| `plugins/signals-memory` | `MemoryProvider` | `memory.provider: signals-memory` |
| `plugins/signals-compact` | `ContextEngine` via `register(ctx)` | `context.engine: signals` |
| `plugins/signals-listen` | dashboard UI + `plugin_api.py` | WebRTC viewer / AgentRTC Listen tab |
| `plugins/signals-zettel` | general (`/zettel`, `zettel_capture`) | Clipboard → scratch zettel in the wiki vault |
| `hsengine/` (pip extra `signals-hsengine`) | sidecar process | Lattice engine + AgentRTC (`python -m hsengine`) |

Listen is a Hermes **plugin**. The voice/media plane is a **sidecar**
(`signals-hsengine`), not a `plugin.yaml` kind — WebRTC, moshi, and YK
claims cannot live in the dashboard process. `./scripts/install.sh`
symlinks the plugins **and** `pip install -e` this checkout.

`signals-oip` converts OpenAI-shaped `tools` and `messages` to OIP
`llm_tools_v1` when the peer advertises that extension; otherwise it uses
`Engine/Complete` (`tools_json`). The engine itself is this repo's
`signals-hsengine` package. Hermes core stays stock plus a few generic
seams (session runtime overlay `hermes_agent.session_runtime`, dashboard
`tab.position:`). AgentRTC-specific code does not belong in hermes-agent.
See [docs/packaging.md](docs/packaging.md).

## AgentRTC: named agents and delegation

An AgentRTC Connect is one Hermes session (`source=agent-rtc`) plus two
**named bots** — Hermes profiles under `$HERMES_HOME/profiles/<name>/`
with Bot-Mode `ui_meta['hermes-bots']`, created on first interactive
enter if missing:

| Bot | Role |
|-----|------|
| **Ripley** | Spoken voice. First person. Tools on user turns; execute pass has no tools. |
| **Bishop** | Silent invent pass. Tools, including `hermes` / `delegate_task`. Never heard. |

**Agent-mediated:** Bishop invents; Ripley speaks. Named agents and
sub-agents **are** that pattern, not a sideline. Connect openings,
“what’s next,” and quiet-line contemplation all use invent-then-execute.

While the `interactive_session` Activity is in force, both bots (and
`hermes()` children) use Cerebras via the session-runtime overlay — not
an env var, not a process-wide model swap.

Delegation cap on a Bishop turn: `hermes` at most twice, and Hermes may
run at most **two** `delegate_task` children. Subagents share the
AgentRTC session (transcript + memory). Files they create stay under
`HERMES_HOME` (this profile or the common Hermes home), never the
operator home.

Personas: `hsengine/bots/{ripley,bishop}/SOUL.md`.

## Memory (signals-memory)

AgentRTC uses Hermes' **MemoryProvider** subsystem — not a second store.
CLI/dashboard chat and AgentRTC share `$HERMES_HOME/state.db`,
`${HERMES_HOME}/wiki`, `memories/MEMORY.md`, and
`signals-memory/turns.jsonl`. A note filed in Hermes chat is on the next
Connect; recall lines are tagged `[cli]` vs `[agent-rtc]` so the invent
pass can tell text chat from a voice call. At similar recency, AgentRTC
sessions are boosted; cron is demoted.

Activate:

```yaml
plugins:
  enabled: [signals-memory]
memory:
  provider: signals-memory   # CLI / hermes() subagents
```

If `memory.provider` is empty, the AgentRTC sidecar still loads
`signals-memory` when the plugin is installed. A configured Honcho (or
other) provider is not overridden.

`prefetch` (and `signals_recall`) return **one pack**. Bishop invents
from it; Ripley does not read it as a briefing.

| Tier | What | How |
|------|------|-----|
| Conversations | Recent Hermes / AgentRTC sessions | FTS5 + recency |
| Citations | `${HERMES_HOME}/wiki`, `memories/MEMORY.md` | Lexical; entity/concept pages first |
| Turns | Profile JSONL | Keyword, newest last |
| Lattice | Gaius `ServerQuery SEARCH` | Semantic-ish, **lowest** priority |

Lexical talks and wiki always outrank Gaius. A Gaius outage fails open.
`session_search` / `kb_search` remain tools for deepen, not the first hop.

Details: [docs/memory.md](docs/memory.md).

## Scratch zettel (`/zettel`)

The dashboard **Plugin catalog** is Nous-reviewed pins only — local Signals
plugins show under **installed plugins** on that page, not in the catalog
search. The zettel skill is linked into `$HERMES_HOME/skills/note-taking/zettel`
so it appears on the Skills page.

`signals-zettel` files host clipboard text as a Gaius-style scratch note in
the Hermes wiki vault (`OBSIDIAN_VAULT_PATH` or `WIKI_PATH` or
`${HERMES_HOME}/wiki`):

```
/zettel optional title
```

Writes `scratch/YYYY-MM-DD/HHMMSS_slug.md` and returns `wiki:scratch/…`.
`/paste` stays image-only. If the process cannot see the host clipboard
(jail/SSH), paste the body into chat and the `zettel_capture` tool uses
`body`. Does not change the bundled `obsidian` skill.

## Install

Canonical — clone each plugin from GitHub into `$HERMES_HOME/plugins/`:

```bash
hermes plugins install weathership/signals-plugins/plugins/signals-oip --enable
hermes plugins install weathership/signals-plugins/plugins/signals-memory --enable
hermes plugins install weathership/signals-plugins/plugins/signals-compact --enable
hermes plugins install weathership/signals-plugins/plugins/signals-listen --enable
hermes plugins install weathership/signals-plugins/plugins/signals-zettel --enable
```

All four:

```bash
./scripts/install-from-github.sh --enable
```

Developer checkout (symlink this tree; not the published path):

```bash
./scripts/install.sh
# HERMES_PROFILE=coder ./scripts/install.sh
# ./scripts/install.sh --uninstall
# ./scripts/install.sh --engine   # pip install -e this checkout (hsengine)
```

## Activate

```yaml
# $HERMES_HOME/config.yaml
plugins:
  enabled:
    - signals-oip
    - signals-memory
    - signals-compact
    - signals-listen
    - signals-zettel
model:
  provider: signals
  model: thinking
memory:
  provider: signals-memory
context:
  engine: signals
```

Restart Hermes. `hermes plugins list` should list the four plugins;
`hermes doctor` should report provider `signals`.

## Impala FDW

Going forward, a Signals federated workspace must expose its data plane
through [impala_fdw](https://github.com/weathership/impala_fdw). That
PostgreSQL foreign data wrapper surfaces Impala's transparent hierarchical
storage: Kudu for the hot mutable tier, Iceberg for the cold tier, and
unified Impala SQL views over both.

Certain local plugin functions may assume those foreign tables are
available on the Signals Postgres instance. Build and usage are documented
in that repository; this checkout does not ship the extension.

## Layout

```
plugins/
  signals-oip/          plugin.yaml + client (OIP / Engine Complete)
  signals-memory/       MemoryProvider + hybrid.py (tiered recall)
  signals-compact/      ContextEngine
  signals-listen/       dashboard Listen tab + plugin_api
  signals-zettel/       /zettel clipboard capture into wiki/scratch
hsengine/               sidecar: AgentRTC, named bots, overlay, ops
  bots/{ripley,bishop}/ SOUL.md
docs/
  packaging.md
  memory.md
scripts/install.sh
tests/
  hsengine/             sidecar tests (named bots, recall, overlay, …)
```

Do not point Hermes at `plugins/` in this repository. Published installs
clone into `$HERMES_HOME/plugins/` via `hermes plugins install`.

## Tests

```bash
python3 -m unittest discover -s tests -q
python3 -m pytest tests/hsengine tests/test_signals_memory.py -q
bash -n scripts/install.sh
```
