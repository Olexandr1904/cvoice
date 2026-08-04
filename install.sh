#!/usr/bin/env bash
# Bootstrap cvoice: virtual environment, shim, hooks, menu-bar plugin.
set -euo pipefail

HOME_DIR="${CVOICE_HOME:-$HOME/.cvoice}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGUAGE=""
INSTALL_HOOKS=1
INSTALL_PLUGIN=1

while [ $# -gt 0 ]; do
  case "$1" in
    --language) LANGUAGE="$2"; shift 2 ;;
    --no-hooks) INSTALL_HOOKS=0; shift ;;
    --no-menubar) INSTALL_PLUGIN=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

echo "==> Creating $HOME_DIR"
mkdir -p "$HOME_DIR/bin"
python3 -m venv "$HOME_DIR/.venv"
"$HOME_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$HOME_DIR/.venv/bin/pip" install --quiet "$SOURCE_DIR"
# Re-running the installer must actually replace the code. The version number does
# not change between edits, so without this pip can decide the requirement is
# already satisfied and leave the old copy in place - fixes then look like no-ops.
"$HOME_DIR/.venv/bin/pip" install --quiet --no-deps --force-reinstall "$SOURCE_DIR"

# The hooks in settings.json point at this path forever; upgrading never rewrites them.
cat > "$HOME_DIR/bin/cv-hook" <<EOF
#!/usr/bin/env bash
exec "$HOME_DIR/.venv/bin/cvoice" "\$@"
EOF
chmod +x "$HOME_DIR/bin/cv-hook"

if [ -z "$LANGUAGE" ]; then
  echo
  echo "Which language should it speak?"
  echo "  1) English"
  echo "  2) Ukrainian"
  echo "  3) Other"
  printf 'Choice [1]: '
  read -r CHOICE || true
  case "${CHOICE:-1}" in
    1|"") LANGUAGE="en" ;;
    2)    LANGUAGE="uk" ;;
    3)    printf 'Language name (for example: Polish, German, 日本語): '
          read -r LANGUAGE || true
          # Anything outside the two bundled packs is generated on the spot: the phrases
          # are translated and a matching voice is picked from what this Mac can speak.
          [ -n "$LANGUAGE" ] || LANGUAGE="en" ;;
    *)    echo "    not an option, using English"; LANGUAGE="en" ;;
  esac
fi
if ! "$HOME_DIR/bin/cv-hook" language "$LANGUAGE"; then
  echo "    could not set up $LANGUAGE, falling back to English"
  "$HOME_DIR/bin/cv-hook" language en >/dev/null
fi

if [ "$INSTALL_HOOKS" = 1 ]; then
  echo "==> Installing hooks"
  found=0
  for config_dir in "$HOME"/.claude*; do
    [ -d "$config_dir" ] || continue
    # A glob on ~/.claude* also catches our own state directory, stray directories and
    # backups. Only a directory Claude Code itself populated is a real config dir.
    is_config=0
    for marker in projects commands .credentials.json; do
      [ -e "$config_dir/$marker" ] && is_config=1
    done
    [ "$is_config" = 1 ] || continue
    "$HOME_DIR/bin/cv-hook" install-hooks "$config_dir"
    found=1
  done
  [ "$found" = 1 ] || echo "    no Claude config directories found under $HOME"
fi

if [ "$INSTALL_PLUGIN" = 1 ]; then
  PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
  if [ -n "$PLUGIN_DIR" ] && [ -d "$PLUGIN_DIR" ]; then
    ln -sf "$HOME_DIR/.venv/lib"/python*/site-packages/cvoice/menubar/plugin.sh \
      "$PLUGIN_DIR/cvoice.10s.sh"
    echo "==> Menu-bar plugin linked into $PLUGIN_DIR"
  else
    echo "    SwiftBar not detected; skipping the menu-bar plugin"
  fi
fi

echo
echo "Done. Try:  $HOME_DIR/bin/cv-hook doctor"
echo "Add to your shell:  alias cv='$HOME_DIR/bin/cv-hook'"
