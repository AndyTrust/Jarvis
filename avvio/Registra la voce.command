#!/bin/bash
# Registra l'impronta vocale dell'utente (5 frasi, impronta-utente.npy): serve
# solo alla sicurezza delle mani libere, per riconoscere che sei tu a
# parlare. MODIFICA LOCALE 2026-09-26: tolta la raccolta guidata delle 20
# frasi per tipo, che alimentava il clone vocale F5-TTS (disinstallato,
# decisione dell'utente: troppo lento e inutile).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$HOME/Jarvis/backtalk" || exit 1
.venv/bin/python -W ignore strumenti/impronta.py registra "$@"
echo
read -n 1 -s -r -p "Fatto. Premi un tasto per chiudere."
