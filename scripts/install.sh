#!/usr/bin/env bash
# Install Signals Hermes plugins into the active HERMES_HOME.
#
# Symlinks each plugins/<name>/ directory to $HERMES_HOME/plugins/<name>/.
# Does not clone into the runtime path — the checkout stays the source of truth.
#
#   ./scripts/install.sh
#   ./scripts/install.sh --quiet
#   HERMES_PROFILE=coder ./scripts/install.sh
set -euo pipefail

QUIET=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --quiet|-q) QUIET=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGINS_SRC="$REPO_ROOT/plugins"

if [[ -n "${HERMES_PROFILE:-}" ]]; then
  HOME_ROOT="${HERMES_HOME:-$HOME/.hermes}"
  # Profile homes are ~/.hermes/profiles/<name>, not nested under an already-overridden HERMES_HOME.
  TARGET_ROOT="$HOME/.hermes/profiles/${HERMES_PROFILE}"
else
  TARGET_ROOT="${HERMES_HOME:-$HOME/.hermes}"
fi

PLUGIN_ROOT="$TARGET_ROOT/plugins"
PLUGINS=(signals-oip signals-memory signals-compact)

preflight_link() {
  local dest="$1" src="$2"
  if [[ -L "$dest" ]]; then
    local current
    current="$(readlink -f "$dest" 2>/dev/null || readlink "$dest")"
    local want
    want="$(readlink -f "$src" 2>/dev/null || echo "$src")"
    if [[ "$current" == "$want" ]]; then
      return 0
    fi
    die "$dest is a symlink to $current (expected $want). Remove it or pass --uninstall."
  fi
  if [[ -e "$dest" ]]; then
    die "$dest already exists and is not our symlink."
  fi
}

if [[ "$UNINSTALL" -eq 1 ]]; then
  for name in "${PLUGINS[@]}"; do
    dest="$PLUGIN_ROOT/$name"
    if [[ -L "$dest" ]]; then
      rm "$dest"
      say "removed $dest"
    elif [[ -e "$dest" ]]; then
      die "$dest exists and is not a symlink; not removing."
    fi
  done
  say "uninstalled Signals plugins from $PLUGIN_ROOT"
  exit 0
fi

[[ -d "$PLUGINS_SRC" ]] || die "missing $PLUGINS_SRC"
mkdir -p "$PLUGIN_ROOT"

for name in "${PLUGINS[@]}"; do
  src="$PLUGINS_SRC/$name"
  dest="$PLUGIN_ROOT/$name"
  [[ -d "$src" && -f "$src/plugin.yaml" ]] || die "missing plugin $src"
  preflight_link "$dest" "$src"
  if [[ ! -e "$dest" && ! -L "$dest" ]]; then
    ln -s "$src" "$dest"
  fi
  say "linked $dest -> $src"
done

say ""
say "Installed Signals plugins at $PLUGIN_ROOT"
say "Activate in config.yaml:"
say ""
say "  plugins:"
say "    enabled:"
say "      - signals-oip"
say "      - signals-memory"
say "      - signals-compact"
say "  model:"
say "    provider: signals"
say "    model: thinking"
say "  memory:"
say "    provider: signals-memory"
say "  context:"
say "    engine: signals"
say ""
say "Published install (GitHub, not this checkout):"
say "  hermes plugins install weathership/signals-plugins/plugins/signals-oip"
say "  ./scripts/install-from-github.sh --enable"
say "Restart Hermes after enabling."
