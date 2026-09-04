# Packaging

Canonical install is clone-or-symlink into `$HERMES_HOME/plugins/<name>/`,
the same contract as hermes-lcm and rtk's Hermes adapter.

- `scripts/install.sh` preflights, then `ln -s` each `plugins/<name>` into
  the active profile's plugin directory (`HERMES_HOME` or
  `~/.hermes/profiles/$HERMES_PROFILE`).
- `hermes plugins install <url>#plugins/<name>` clones a subdirectory of
  this repo (Hermes supports `owner/repo/subdir` and `#subdir`).
- This repository is not a pip application. Discovery needs `plugin.yaml`
  plus `__init__.py` on the Hermes plugin search path.

Do not copy plugin trees into `hermes-agent`. That tree's `plugins/memory/`
set is closed; Signals memory lives here on purpose.
