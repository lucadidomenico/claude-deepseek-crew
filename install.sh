#!/usr/bin/env bash
# claude-deepseek-crew installer / installer di claude-deepseek-crew
#   ./install.sh [--test] [--no-skill] [--uninstall]
#   --test       tiny end-to-end check with DeepSeek (~$0.002) / verifica completa minima con DeepSeek
#   --no-skill   do not install the /deepseek-crew skill / non installa la skill
#   --uninstall  remove tools and skill / rimuove strumenti e skill
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
. "$SRC/bin/ds-i18n.sh"
PREFIX="${PREFIX:-$HOME/.local}"
DEST="$PREFIX/share/claude-deepseek-crew"; BIN="$PREFIX/bin"
SKILL=1; TEST=0; UNINSTALL=0
for a in "$@"; do case "$a" in --skill) SKILL=1;; --no-skill) SKILL=0;; --test) TEST=1;; --uninstall) UNINSTALL=1;;
  -h|--help) sed -n '2,6p' "$0"; exit 0;; *) t "opzione sconosciuta: $a" "unknown option: $a"; exit 2;; esac; done
if [ "$UNINSTALL" = 1 ]; then
  for f in ds-claude ds-worker ds-worker-batch ds-cost; do rm -f "$BIN/$f"; done
  rm -rf "$DEST" "$HOME/.claude/skills/deepseek-crew"
  t "strumenti e skill rimossi (resta ~/.config/claude-deepseek-crew: cancellala a mano se vuoi)" \
    "tools and skill removed (~/.config/claude-deepseek-crew is kept: delete it by hand if you want)"; exit 0
fi
need() { command -v "$1" >/dev/null || { t "manca una dipendenza: $1 ($2)" "missing dependency: $1 ($3)"; exit 1; }; }
need claude "installa Claude Code: https://code.claude.com" "install Claude Code: https://code.claude.com"
need python3 "Python 3.8+" "Python 3.8+"
need flock "util-linux (su macOS: brew install flock)" "util-linux (macOS: brew install flock)"
need timeout "coreutils (su macOS: brew install coreutils)" "coreutils (macOS: brew install coreutils)"
mkdir -p "$DEST" "$BIN"
cp "$SRC"/bin/ds-* "$DEST/"; chmod +x "$DEST"/ds-*
for f in ds-claude ds-worker ds-worker-batch ds-cost; do ln -sf "$DEST/$f" "$BIN/$f"; done
t "installati: $BIN/{ds-claude,ds-worker,ds-worker-batch,ds-cost}" "installed: $BIN/{ds-claude,ds-worker,ds-worker-batch,ds-cost}"
case ":$PATH:" in *":$BIN:"*) ;; *) t "NOTA: aggiungi $BIN al tuo PATH" "NOTE: add $BIN to your PATH";; esac
if [ "$SKILL" = 1 ]; then
  mkdir -p "$HOME/.claude/skills/deepseek-crew"; cp "$SRC/skill/deepseek-crew/SKILL.md" "$HOME/.claude/skills/deepseek-crew/"
  t "skill installata: ~/.claude/skills/deepseek-crew  → in Claude Code: /model opus, poi /deepseek-crew <cosa sviluppare>" \
    "skill installed: ~/.claude/skills/deepseek-crew  → in Claude Code: /model opus, then /deepseek-crew <what to build>"
fi
KEYFILE="${CREW_HOME:-$HOME/.config/claude-deepseek-crew}/env"
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f "$KEYFILE" ]; then . "$KEYFILE"; fi
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  t "NOTA: manca la chiave DeepSeek (https://platform.deepseek.com/api_keys). Salvala con:" \
    "NOTE: the DeepSeek key is missing (https://platform.deepseek.com/api_keys). Save it with:"
  P=$(t "Chiave DeepSeek: " "DeepSeek key: "); OK=$(t "salvata" "saved")
  echo "  mkdir -p ~/.config/claude-deepseek-crew && printf '$P' && read -rs K && printf 'DEEPSEEK_API_KEY=%s\n' \"\$K\" > ~/.config/claude-deepseek-crew/env && chmod 600 ~/.config/claude-deepseek-crew/env && echo && echo $OK"
elif [ "$TEST" = 1 ]; then
  T=$(mktemp -d); cd "$T"
  t "test: chiedo a DeepSeek (tramite Claude Code) di creare un file..." "test: asking DeepSeek (through Claude Code) to create a file..."
  "$BIN/ds-worker" "$(t "Crea il file hello.txt con questo contenuto esatto: crew-ok. Poi esegui cat hello.txt." \
                        "Create the file hello.txt with exactly this content: crew-ok. Then run cat hello.txt.")" | tail -3
  if [ "$(cat hello.txt 2>/dev/null)" = "crew-ok" ]; then t "TEST SUPERATO" "TEST PASSED"
  else t "TEST FALLITO (vedi $T/.crew)" "TEST FAILED (see $T/.crew)"; exit 1; fi
  "$BIN/ds-cost" "$T/.crew" | tail -1
fi
