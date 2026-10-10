#!/bin/bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
git pull --ff-only && python3 strumenti/installa_guidata.py
echo
echo "Fatto. Fatto: codice aggiornato e installazione guidata rilanciata."
read -n 1 -s -r -p "Premi un tasto per chiudere."
