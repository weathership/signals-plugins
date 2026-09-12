# Packaging

The canonical install clones from GitHub into `$HERMES_HOME/plugins/<name>/`:

```bash
hermes plugins install weathership/signals-plugins/plugins/signals-oip
```

- `scripts/install-from-github.sh` runs that for all four plugins.
- Hermes accepts `owner/repo/subdir` (and `#subdir` on a full Git URL).
- `scripts/install.sh` is the developer path: symlink a local checkout
  into the active profile (`HERMES_HOME` or
  `~/.hermes/profiles/$HERMES_PROFILE`). It is not the published install.
- This repository is not a pip package. Hermes discovers plugins by finding
  `plugin.yaml` and `__init__.py` on its plugin search path.

These plugins live in this repository so they can integrate a Hermes
profile with a Signals federated workspace. Signals memory is provided
here rather than by Hermes's bundled `plugins/memory/`.

The lattice engine (`hsengine`) is packaged here as **`signals-hsengine`**
(`pip install -e .` from this checkout, or `uv pip install -e`). It is
not a Hermes plugin kind: it is a sidecar process (`hermes-engine` /
`python -m hsengine`) that Listen's `plugin_api` talks to over gRPC.
`scripts/install.sh` installs both the plugin symlinks and that extra.

Hermes itself should stay stock plus generic seams (session runtime
overlay entry point `hermes_agent.session_runtime`, dashboard
`tab.position`). AgentRTC-specific code does not belong in hermes-agent.

Going forward, that workspace requires
[impala_fdw](https://github.com/weathership/impala_fdw) on Signals
Postgres so Impala's transparent hierarchical storage (Kudu hot, Iceberg
cold, unified SQL views) is available as foreign tables. Certain local
plugin functions may assume those tables exist. The README Impala FDW
section describes that requirement.
