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

These plugins live in this repository so they can integrate a Hermes
profile with a Signals federated workspace. Signals memory is provided
here rather than by Hermes's bundled `plugins/memory/`.

Going forward, that workspace requires
[impala_fdw](https://github.com/weathership/impala_fdw) on Signals
Postgres so Hermes can reach Kudu-backed tables through foreign tables
instead of a first-class Impala JDBC client. The README Impala FDW
section describes that requirement.
