#!/usr/bin/env bash
# Instalador de claude-session-switcher.
# Crea un symlink en ~/.local/bin/ccl e imprime la funcion de shell que hay que anadir.
# NO modifica tu .zshrc / .bashrc: eso lo decides tu.
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
  warn "Esto es solo para macOS. El salto de ventana usa AppleScript contra iTerm2."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  warn "No encuentro python3. Instalalo con: brew install python"
  exit 1
fi

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,7) else 0)')
if [[ "$PY_OK" != "1" ]]; then
  warn "Necesitas Python 3.7+ (tienes $(python3 -V 2>&1)). Requiere datetime.fromisoformat."
  exit 1
fi
say "python3 $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') ✓"

if ! command -v claude >/dev/null 2>&1; then
  warn "No encuentro el comando 'claude'. Instala Claude Code primero."
  exit 1
fi
say "claude $(claude --version 2>/dev/null | head -1) ✓"

if [[ ! -d "/Applications/iTerm.app" ]]; then
  warn "No veo iTerm2 en /Applications. El listado funcionara, pero el salto de ventana no."
else
  say "iTerm2 ✓"
fi

# --- instalar (idempotente) ---

mkdir -p "$BIN_DIR"
ln -sf "$SRC" "$DEST"
chmod +x "$SRC"
say "enlazado: $DEST -> $SRC"

echo
if ! printf '%s' ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
  warn "$BIN_DIR no esta en tu PATH. Anade esto tambien:"
  echo
  echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo
fi

cat <<'EOF'
Listo. Para tener `ccl` como comando, anade esto a tu ~/.zshrc (o ~/.bashrc):

    # Panel de sesiones de Claude Code
    ccl() { ~/.local/bin/ccl "$@"; }

Recarga con `source ~/.zshrc` y prueba:

    ccl --list      # listado estatico
    ccl             # panel interactivo

EOF
