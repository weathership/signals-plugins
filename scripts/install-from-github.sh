#!/usr/bin/env bash
# Install the three Signals Hermes plugins from GitHub (canonical).
#
#   ./scripts/install-from-github.sh
#   ./scripts/install-from-github.sh --force
#   ./scripts/install-from-github.sh --enable
#
# Requires `hermes` on PATH. Clones each subdirectory into $HERMES_HOME/plugins/.
set -euo pipefail

FORCE=0
ENABLE=--no-enable
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --enable) ENABLE=--enable ;;
    --no-enable) ENABLE=--no-enable ;;
    --quiet|-q) QUIET=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

say() { [[ "$QUIET" -eq 1 ]] || printf '%s\n' "$*"; }
die() { printf 'DENY: %s\n' "$*" >&2; exit 1; }

command -v hermes >/dev/null 2>&1 || die "hermes is not on PATH"

REPO="${SIGNALS_PLUGINS_GIT:-weathership/signals-plugins}"
PLUGINS=(signals-oip signals-memory signals-compact)

if [[ -n "${HERMES_PROFILE:-}" ]]; then
  PLUGIN_ROOT="$HOME/.hermes/profiles/${HERMES_PROFILE}/plugins"
else
  PLUGIN_ROOT="${HERMES_HOME:-$HOME/.hermes}/plugins"
fi

# Local symlink installs from scripts/install.sh must not shadow GitHub clones.
if [[ -x "$(dirname "$0")/install.sh" ]]; then
  "$(dirname "$0")/install.sh" --uninstall --quiet 2>/dev/null || true
fi

args=(plugins install)
[[ "$FORCE" -eq 1 ]] && args+=(--force)
args+=("$ENABLE")

for name in "${PLUGINS[@]}"; do
  dest="$PLUGIN_ROOT/$name"
  if [[ -e "$dest" && "$FORCE" -eq 0 ]]; then
    say "skip $name (already at $dest; pass --force to reinstall from GitHub)"
    continue
  fi
  say "hermes plugins install ${REPO}/plugins/${name}"
  hermes "${args[@]}" "${REPO}/plugins/${name}"
done

say ""
say "Installed from github.com/${REPO}"
say "Activate in config.yaml:"
say "  plugins.enabled: [signals-oip, signals-memory, signals-compact]"
say "  model.provider: signals"
say "  memory.provider: signals-memory"
say "  context.engine: signals"
