# Packaging

The canonical install is to clone this repository and symlink each plugin
into `$HERMES_HOME/plugins/<name>/`.

- `scripts/install.sh` preflights, then `ln -s` each `plugins/<name>` into
  the active profile's plugin directory (`HERMES_HOME` or
  `~/.hermes/profiles/$HERMES_PROFILE`).
- `hermes plugins install <url>#plugins/<name>` clones a subdirectory of
  this repository (Hermes supports `owner/repo/subdir` and `#subdir`).
- This repository is not a pip package. Hermes discovers plugins by finding
  `plugin.yaml` and `__init__.py` on its plugin search path.

Do not copy plugin trees into `hermes-agent`. Its `plugins/memory/` tree is
closed; Signals memory lives in this repository on purpose.
