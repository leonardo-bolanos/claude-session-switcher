#!/usr/bin/env bash
# Instalador de claude-session-switcher.
# Crea un symlink en ~/.local/bin/ccl e imprime la funcion de shell que hay que anadir.
# NO modifica tu .zshrc / .bashrc: eso lo decides tu.
#
# Los comentarios van en español como el resto del repo, pero lo que SE IMPRIME va en
# ingles: es lo primero que ejecuta quien llega desde el README, que esta en ingles. Sin
# tabla de idiomas — meterle i18n a un instalador de 70 lineas no se sostiene.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ccl"
BIN_DIR="${HOME}/.local/bin"
DEST="${BIN_DIR}/ccl"

say()  { printf '  %s\n' "$1"; }
warn() { printf '  ⚠ %s\n' "$1" >&2; }

echo
echo "claude-session-switcher"
echo

# --- comprobaciones, sin abortar por avisos ---

if [[ "$(uname -s)" != "Darwin" ]]; then
  warn "This is macOS only. The window jump uses AppleScript against iTerm2."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  warn "Can't find python3. Install it with: brew install python"
  exit 1
fi

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,7) else 0)')
if [[ "$PY_OK" != "1" ]]; then
  warn "Python 3.7+ needed (you have $(python3 -V 2>&1)). It uses datetime.fromisoformat."
  exit 1
fi
say "python3 $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') ✓"

if ! command -v claude >/dev/null 2>&1; then
  warn "Can't find the 'claude' command. Install Claude Code first."
  exit 1
fi
say "claude $(claude --version 2>/dev/null | head -1) ✓"

if [[ ! -d "/Applications/iTerm.app" ]]; then
  warn "No iTerm2 in /Applications. The listing will work, the window jump won't."
else
  say "iTerm2 ✓"
fi

# --- instalar (idempotente) ---

mkdir -p "$BIN_DIR"
ln -sf "$SRC" "$DEST"
chmod +x "$SRC"
say "linked: $DEST -> $SRC"

echo
if ! printf '%s' ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
  warn "$BIN_DIR is not on your PATH. Add this too:"
  echo
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi

cat <<'EOF'
Done. To get `ccl` as a command, add this to your ~/.zshrc (or ~/.bashrc):

    # Claude Code session panel
    ccl() { ~/.local/bin/ccl "$@"; }

Reload with `source ~/.zshrc` and try:

    ccl --list      # static listing
    ccl             # interactive panel

The interface follows your locale; CCL_LANG=en or CCL_LANG=es forces one.

EOF
