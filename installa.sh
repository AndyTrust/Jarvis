#!/usr/bin/env bash
#
# installa.sh — porta Jarvis da un clone appena scaricato al Command Center acceso, con tutto quello che serve.
#   (consigliato: apri Claude Code nella cartella e scrivi /inizia; questo script è l'installazione classica)
#   cd ~/Jarvis && ./installa.sh --prova && ./installa.sh
#
# Fa, in quest'ordine (ogni passo salta quello che c'è già, si può rilanciare quando vuoi):
#   1. controlla Python 3.10+, git, curl (e dice se mancano Claude Code, Homebrew, Terminale con i permessi);
#   2. programmi di sistema dal Brewfile: uv, espeak-ng, ffmpeg, cliclick, tmux, ttyd, gh, node...  (chiede prima)
#   3. i tuoi file di configurazione dagli esempi, senza sovrascrivere i tuoi;
#   4. l'ambiente Python dell'orb (Pillow, numpy, PyObjC) e quello delle missioni/voce (claude-agent-sdk, Whisper, Kokoro),
#      più il filtro rumore di sottofondo e i modelli vocali (installa_voce.py);
#   5. ~/.claude: ganci, agenti di casa e skill «aggiorna-memoria» (senza toccare i tuoi file: copia prima);
#   5b. la memoria condivisa: la crea (~/Jarvis-Memoria se non scegli altro) e ci collega Claude Code (collega_memoria.py);
#   6. i lavori automatici (launchd): scritti, accesi solo con --launchd;
#   7. la verifica: compila tutto, accende il pannello in prova e controlla che risponda.
#
# Opzioni:  --prova (dice cosa farebbe)  --si (non chiede)  --senza-brew  --senza-voce  --senza-widget
#           --launchd (accende i lavori automatici)  --home DIR (casa finta, per provare)
# Dopo: docs/wiki/Installazione.md spiega i permessi di macOS, il login di Claude Code e le credenziali (.env.jarvis).
set -uo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROVA=0; SI=0; BREW=1; VOCE=1; WIDGET=1; LAUNCHD=0; TUTTI=0; CASA="$HOME"
while [ $# -gt 0 ]; do
  case "$1" in
    --prova) PROVA=1 ;; --si) SI=1 ;; --senza-brew) BREW=0 ;; --senza-voce) VOCE=0 ;; --senza-widget) WIDGET=0 ;;
    --launchd) LAUNCHD=1 ;; --tutti) TUTTI=1 ;; --home) shift; CASA="$1" ;;
    -h|--help|--aiuto) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "non conosco «$1» (vedi --aiuto)" >&2; exit 2 ;;
  esac; shift
done
export HOME_JARVIS="$CASA"
MAC=0; [ "$(uname)" = "Darwin" ] && MAC=1
AVVISI=()
dice() { printf '\n== %s\n' "$*"; }
fa() { if [ "$PROVA" = 1 ]; then echo "   [prova] $*"; else echo "   \$ $*"; "$@"; fi; }
chiede() { [ "$SI" = 1 ] && return 0; [ "$PROVA" = 1 ] && return 0; read -r -p "   $1 [S/n] " a; [ "$a" != "n" ] && [ "$a" != "N" ]; }

dice "1. Controlli"
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "   ERRORE: manca python3 (3.10 o più nuovo)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "   ERRORE: serve Python 3.10+, hai $("$PY" --version)"; exit 1; }
echo "   python3: $("$PY" --version)"
for c in git curl; do command -v "$c" >/dev/null && echo "   $c: ok" || { echo "   ERRORE: manca $c"; exit 1; }; done
command -v claude >/dev/null && echo "   claude: ok" || AVVISI+=("Claude Code non c'è: curl -fsSL https://claude.ai/install.sh | bash (oppure brew install --cask claude-code), poi «claude» una volta per il login")
[ "$MAC" = 1 ] && { command -v brew >/dev/null || AVVISI+=("Homebrew non c'è (https://brew.sh): serve per uv, espeak-ng, cliclick, tmux, ttyd"); }

dice "2. Programmi di sistema (Brewfile)"
if [ "$BREW" = 1 ] && command -v brew >/dev/null; then
  if chiede "Installo con «brew bundle» i programmi del Brewfile?"; then fa brew bundle --file="$QUI/Brewfile"; else echo "   saltato"; fi
else echo "   saltato (senza Homebrew o --senza-brew): installa a mano i programmi elencati in Brewfile"; fi

dice "3. Configurazione"
for f in configurazione spazi; do
  if [ -f "$QUI/command-center/$f.json" ]; then echo "   $f.json c'è già: lo lascio"
  elif [ -f "$QUI/command-center/$f.esempio.json" ]; then fa cp -n "$QUI/command-center/$f.esempio.json" "$QUI/command-center/$f.json"
  else echo "   nessun esempio per $f.json: il pannello usa i suoi valori"; fi
done
if [ "$PROVA" = 0 ] && [ -f "$QUI/command-center/configurazione.json" ]; then
  "$PY" - "$QUI" <<'PYEOF'
import json, sys
from pathlib import Path
qui = Path(sys.argv[1]); f = qui / "command-center" / "configurazione.json"
d = json.loads(f.read_text(encoding="utf-8"))
if not d.get("cartella_agente"):
    d["cartella_agente"] = str(qui)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("   cartella_agente =", qui)
PYEOF
fi
if [ ! -f "$QUI/profilo-jarvis.md" ] && [ -f "$QUI/profilo-jarvis.esempio.md" ]; then fa cp -n "$QUI/profilo-jarvis.esempio.md" "$QUI/profilo-jarvis.md"; fi
[ -f "$CASA/.env.jarvis" ] || AVVISI+=("Chiavi (facoltative): scrivile tu in ~/.env.jarvis e poi chmod 600 ~/.env.jarvis. Mai nella memoria, mai su GitHub. Vedi docs/wiki/Installazione.md")

dice "4. Ambienti Python"
if [ "$MAC" = 1 ] && [ "$WIDGET" = 1 ]; then
  W="$CASA/.locale-onedrive/jarvis-widget-venv"
  if [ -x "$W/bin/python3" ] && "$W/bin/python3" -c 'import PIL, numpy, AppKit' 2>/dev/null; then echo "   orb: ambiente già pronto ($W)"
  else fa mkdir -p "$CASA/.locale-onedrive" && fa "$PY" -m venv "$W" && fa "$W/bin/pip" install -q -r "$QUI/requirements/mac-widget.txt"; fi
else echo "   orb: saltato (non è un Mac o --senza-widget)"; fi
# il Vault (command-center/vault_cc.py) vuole «cryptography»: ambiente a parte, che il Vault trova da solo
VV="$CASA/.jarvis/vault-venv"
if [ -x "$VV/bin/python3" ] && "$VV/bin/python3" -c 'import cryptography' 2>/dev/null; then echo "   Vault: libreria di cifratura già pronta ($VV)"
elif "$PY" -c 'import cryptography' 2>/dev/null; then echo "   Vault: cryptography già presente in $PY"
else fa mkdir -p "$CASA/.jarvis" && fa "$PY" -m venv "$VV" && fa "$VV/bin/pip" install -q -r "$QUI/requirements/vault.txt" || AVVISI+=("Vault: la libreria di cifratura non si è installata (docs/wiki/Vault.md, «Se il Vault dice spento»)"); fi
if [ "$VOCE" = 1 ]; then
  if [ -f "$QUI/backtalk/install.sh" ]; then
    echo "   voce e missioni: backtalk/install.sh (scarica i modelli di Whisper e Kokoro, ~1 GB, può chiedere conferme)"
    chiede "Lancio backtalk/install.sh?" && fa bash "$QUI/backtalk/install.sh" || echo "   saltato"
  elif [ ! -x "$QUI/backtalk/.venv/bin/python3" ]; then
    echo "   missioni: ambiente minimo con l'SDK di Claude (senza la voce)"
    fa mkdir -p "$QUI/backtalk" && fa "$PY" -m venv "$QUI/backtalk/.venv" && fa "$QUI/backtalk/.venv/bin/pip" install -q -r "$QUI/requirements/missioni.txt"
  else echo "   missioni: ambiente già pronto"; fi
else echo "   voce e missioni: saltate (--senza-voce)"; fi
if [ "$VOCE" = 1 ] && [ -f "$QUI/strumenti/installa_voce.py" ]; then
  echo "   filtro rumore di sottofondo (GTCRN), impronta vocale, Whisper, Kokoro «Sara»:"
  if [ "$PROVA" = 1 ]; then "$PY" "$QUI/strumenti/installa_voce.py" --prova || true
  else "$PY" "$QUI/strumenti/installa_voce.py" || AVVISI+=("la voce non è completa: leggi sopra, poi rilancia strumenti/installa_voce.py"); fi
fi

dice "5. Claude Code: ganci, agenti di casa, skill «aggiorna-memoria»"
if [ "$PROVA" = 1 ]; then "$PY" "$QUI/strumenti/installa_claude_config.py" --prova --home "$CASA"; else "$PY" "$QUI/strumenti/installa_claude_config.py" --home "$CASA"; fi

dice "5b. Memoria condivisa e collegamenti"
if [ "$PROVA" = 1 ]; then "$PY" "$QUI/strumenti/collega_memoria.py" || true
else "$PY" "$QUI/strumenti/collega_memoria.py" --applica || AVVISI+=("la memoria condivisa non è a posto: leggi sopra, poi rilancia strumenti/collega_memoria.py --applica"); fi

dice "6. Lavori automatici (launchd, solo Mac)"
if [ "$MAC" = 1 ]; then
  opz=(); [ "$TUTTI" = 1 ] && opz+=(--tutti); [ "$LAUNCHD" = 1 ] && opz+=(--attiva); [ "$PROVA" = 1 ] && opz+=(--prova)
  "$PY" "$QUI/strumenti/installa_launchd.py" --home "$CASA" ${opz[@]+"${opz[@]}"}
else echo "   non è un Mac: saltato (su Linux usa systemd o cron con gli stessi comandi)"; fi

dice "7. Verifica"
if [ "$PROVA" = 1 ]; then echo "   [prova] python3 strumenti/verifica_installazione.py"
else "$PY" "$QUI/strumenti/verifica_installazione.py" --home "$CASA" || AVVISI+=("la verifica ha trovato errori: leggi sopra"); fi

dice "Fatto. Restano a mano"
for a in ${AVVISI[@]+"${AVVISI[@]}"}; do [ -n "$a" ] && echo " - $a"; done
[ "$MAC" = 1 ] && echo " - Impostazioni di Sistema → Privacy e sicurezza: dai a Terminale (e a Python) Accessibilità, Registrazione schermo e Gestione app: senza, mani sul Mac, schermo e file di OneDrive non partono"
echo " - Accendi il pannello: python3 command-center/server.py   →  http://127.0.0.1:7777"
echo " - Guida completa: docs/wiki/Installazione.md"
