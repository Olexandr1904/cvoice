#!/usr/bin/env bash
# Remove the hooks and the installation. User data is kept unless --purge is given.
set -euo pipefail

HOME_DIR="${CVOICE_HOME:-$HOME/.cvoice}"
PURGE=0
REMOVE_HOOKS=1

while [ $# -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --no-hooks) REMOVE_HOOKS=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# Hooks always live under the real Claude config directories, never under
# CVOICE_HOME, so this loop touches $HOME even when CVOICE_HOME points
# elsewhere (e.g. during a sandboxed test run). --no-hooks is the escape hatch,
# mirroring install.sh, for runs that must not touch real settings.json files.
if [ "$REMOVE_HOOKS" = 1 ]; then
  for config_dir in "$HOME"/.claude*; do
    [ -d "$config_dir" ] || continue
    [ -x "$HOME_DIR/bin/cv-hook" ] && "$HOME_DIR/bin/cv-hook" remove-hooks "$config_dir" || true
  done
fi

PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
[ -n "$PLUGIN_DIR" ] && rm -f "$PLUGIN_DIR/cvoice.10s.sh"

rm -rf "$HOME_DIR/.venv" "$HOME_DIR/bin"
if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME_DIR"
  echo "Removed everything, including history and settings."
else
  echo "Removed the installation. History and settings are still in $HOME_DIR."
fi
