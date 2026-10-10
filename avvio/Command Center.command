#!/bin/bash
# Apre il Command Center di Jarvis (http://127.0.0.1:7777).
# Se il server non gira lo avvia in background; resta acceso anche chiudendo questa finestra.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
CC="$(cd "$(dirname "$0")/../command-center" && pwd)"
mkdir -p "$CC/lavori"
if ! lsof -ti tcp:7777 -sTCP:LISTEN >/dev/null 2>&1; then
  cd "$CC" && nohup python3 server.py >> "$CC/lavori/server.log" 2>&1 &
  for i in $(seq 1 20); do
    lsof -ti tcp:7777 -sTCP:LISTEN >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
# Si apre come app: finestra propria di Chrome, senza barra degli indirizzi.
# Se Chrome non c'è, nel browser predefinito.
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="http://127.0.0.1:7777/#home"
else
  open "http://127.0.0.1:7777/"
fi
