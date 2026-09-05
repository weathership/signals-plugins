# signals-plugins

These standalone Hermes plugins integrate Hermes with a
[Signals](https://github.com/weathership/signals) federated workspace.
Clone this repository, then symlink the plugins into `$HERMES_HOME/plugins/`
or install them with `hermes plugins install`.

| Directory | Hermes kind | Activate |
|-----------|-------------|----------|
| `plugins/signals-oip` | model-provider (`create_client`) | `model.provider: signals` |
| `plugins/signals-memory` | `MemoryProvider` | `memory.provider: signals-memory` |
| `plugins/signals-compact` | `ContextEngine` via `register(ctx)` | `context.engine: signals` |

`signals-oip` converts OpenAI-shaped `tools` and `messages` to OIP
`llm_tools_v1` when the peer advertises that extension; otherwise it uses
`Engine/Complete` (`tools_json`). It requires the **signals** extra
(`hsengine`) from the
[zndx/oss-hermes-agent](https://github.com/zndx/oss-hermes-agent) fork.
The [`rch/devenv`](https://github.com/zndx/oss-hermes-agent/tree/rch/devenv)
branch carries the Signals engine integration and the generated stubs.

## Install

From this checkout, `scripts/install.sh` is profile-aware and refuses to
overwrite a path that is not already our symlink:

```bash
./scripts/install.sh
# HERMES_PROFILE=coder ./scripts/install.sh
# ./scripts/install.sh --uninstall
```

This repository remains the source of truth. Each
`$HERMES_HOME/plugins/<name>` entry is a symlink back to it.

To install a single plugin through Hermes (subdirectory clone):

```bash
hermes plugins install file://$PWD#plugins/signals-oip
hermes plugins install file://$PWD#plugins/signals-memory
hermes plugins install file://$PWD#plugins/signals-compact
```

To install a plugin from GitHub:

```bash
hermes plugins install weathership/signals-plugins/plugins/signals-oip
```

## Activate

```yaml
# $HERMES_HOME/config.yaml
plugins:
  enabled:
    - signals-oip
    - signals-memory
    - signals-compact
model:
  provider: signals
  model: thinking
memory:
  provider: signals-memory
context:
  engine: signals
```

Restart Hermes. `hermes plugins list` should list the three plugins;
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
scripts/install.sh
tests/
```

Do not point Hermes at `plugins/` in this repository. Use `install.sh` so
the runtime path is `$HERMES_HOME/plugins/`.

## Tests

```bash
python3 -m unittest discover -s tests -q
bash -n scripts/install.sh
```
