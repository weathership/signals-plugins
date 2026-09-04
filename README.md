# signals-plugins

Standalone Hermes plugins for the [Signals lattice](https://github.com/weathership/signals).
A checkout you symlink (or `hermes plugins install`) into `$HERMES_HOME/plugins/`.
Not vendored into `hermes-agent`.

| Directory | Hermes kind | Activate |
|-----------|-------------|----------|
| `plugins/signals-oip` | model-provider (`create_client`) | `model.provider: signals` |
| `plugins/signals-memory` | `MemoryProvider` | `memory.provider: signals-memory` |
| `plugins/signals-compact` | `ContextEngine` via `register(ctx)` | `context.engine: signals` |

`signals-oip` lowers OpenAI-shaped `tools` / `messages` to OIP `llm_tools_v1`
when the peer advertises that extension, otherwise `Engine/Complete`
(`tools_json`). Requires the Hermes **signals** extra (`hsengine`) for generated
stubs.

## Install

From this checkout (profile-aware; refuses to clobber a non-symlink):

```bash
./scripts/install.sh
# HERMES_PROFILE=coder ./scripts/install.sh
# ./scripts/install.sh --uninstall
```

The repo stays the source of truth; `$HERMES_HOME/plugins/<name>` is a symlink.

One plugin via Hermes (subdir clone):

```bash
hermes plugins install file://$PWD#plugins/signals-oip
hermes plugins install file://$PWD#plugins/signals-memory
hermes plugins install file://$PWD#plugins/signals-compact
```

After a GitHub publish:

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

Restart Hermes. `hermes plugins list` should show the three names;
`hermes doctor` should see provider `signals`.

## Layout

```
plugins/
  signals-oip/       plugin.yaml + __init__.py + client.py
  signals-memory/    plugin.yaml + __init__.py
  signals-compact/   plugin.yaml + __init__.py
scripts/install.sh
tests/
```

Do not use `plugins/` in this repo as the Hermes runtime path — that is
what `install.sh` is for.

## Tests

```bash
python3 -m unittest discover -s tests -q
bash -n scripts/install.sh
```
