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
| `hsengine/` (pip extra `signals-hsengine`) | sidecar process | Lattice engine + AgentRTC (`python -m hsengine`) |

Listen is a Hermes **plugin**. The voice/media plane is a **sidecar**
(`signals-hsengine`), not a `plugin.yaml` kind — WebRTC, moshi, and YK
claims cannot live in the dashboard process. `./scripts/install.sh`
symlinks the plugins **and** `pip install -e` this checkout.

`signals-oip` converts OpenAI-shaped `tools` and `messages` to OIP
`llm_tools_v1` when the peer advertises that extension; otherwise it uses
`Engine/Complete` (`tools_json`). The engine itself is this repo's
`signals-hsengine` package. Hermes core stays stock plus a few generic
seams (session runtime overlay, plugin tab `position:`).

## Install

Canonical — clone each plugin from GitHub into `$HERMES_HOME/plugins/`:

```bash
hermes plugins install weathership/signals-plugins/plugins/signals-oip --enable
hermes plugins install weathership/signals-plugins/plugins/signals-memory --enable
hermes plugins install weathership/signals-plugins/plugins/signals-compact --enable
hermes plugins install weathership/signals-plugins/plugins/signals-listen --enable
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
  signals-oip/       plugin.yaml + __init__.py + client.py
  signals-memory/    plugin.yaml + __init__.py
  signals-compact/   plugin.yaml + __init__.py
  signals-listen/    plugin.yaml + dashboard/ (WebRTC tab)
scripts/install.sh
tests/
```

Do not point Hermes at `plugins/` in this repository. Published installs
clone into `$HERMES_HOME/plugins/` via `hermes plugins install`.

## Tests

```bash
python3 -m unittest discover -s tests -q
bash -n scripts/install.sh
```
