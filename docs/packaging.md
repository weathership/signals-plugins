# Packaging

The canonical install clones from GitHub into `$HERMES_HOME/plugins/<name>/`:

```bash
hermes plugins install weathership/signals-plugins/plugins/signals-oip
```

- `scripts/install-from-github.sh` runs that for all three plugins.
- Hermes accepts `owner/repo/subdir` (and `#subdir` on a full Git URL).
- `scripts/install.sh` is the developer path: symlink a local checkout
  into the active profile (`HERMES_HOME` or
  `~/.hermes/profiles/$HERMES_PROFILE`). It is not the published install.
- This repository is not a pip package. Hermes discovers plugins by finding
  `plugin.yaml` and `__init__.py` on its plugin search path.

These plugins live in this repository so they can integrate a Hermes
profile with a Signals federated workspace. Signals memory is provided
here rather than by Hermes's bundled `plugins/memory/`. The **signals**
extra (`hsengine`) comes from
[zndx/oss-hermes-agent](https://github.com/zndx/oss-hermes-agent) on the
[`rch/devenv`](https://github.com/zndx/oss-hermes-agent/tree/rch/devenv)
branch, which has the Signals engine integration.

Going forward, that workspace requires
[impala_fdw](https://github.com/weathership/impala_fdw) on Signals
Postgres so Impala's transparent hierarchical storage (Kudu hot, Iceberg
cold, unified SQL views) is available as foreign tables. Certain local
plugin functions may assume those tables exist. The README Impala FDW
section describes that requirement.
