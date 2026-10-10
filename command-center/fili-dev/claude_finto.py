#!/usr/bin/env python3
"""Un «claude» finto per le prove dei fili (2026-10-03): niente rete, niente token.

Le prove lo copiano come <casa temporanea>/.local/bin/claude, che il server di prova trova per primo.
- «claude auth status» dice loggedIn: true (così il server lo considera pronto);
- «claude -p <testo> ... --output-format json» aspetta FINTO_ATTESA secondi (default 1) e risponde come
  claude -p: {"type":"result","result":…,"session_id":…}. Se il testo contiene LUNGA la risposta è di
  50.000 caratteri; se contiene ERRORE esce con codice 1; se contiene SEGRETO la risposta contiene un
  token finto «sk-ant-…» (deve uscire mascherato nell'archivio).
Le parole si cercano solo nell'ultima riga: in testa il server mette lo stato del filo con le domande di prima.
"""
import json
import os
import sys
import time

a = sys.argv[1:]
if a[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "finto"}))
    sys.exit(0)
testo = a[a.index("-p") + 1] if "-p" in a else ""
sessione = ""
for opz in ("--session-id", "--resume"):
    if opz in a:
        sessione = a[a.index(opz) + 1]
time.sleep(float(os.environ.get("FINTO_ATTESA", "1")))
ultima = [r for r in testo.strip().splitlines() if r.strip()][-1] if testo.strip() else ""
if "ERRORE" in ultima:
    print("errore finto del motore")
    sys.exit(1)
if "LUNGA" in ultima:
    risposta = "inizio " + ("x" * 50000) + " fine"
elif "SEGRETO" in ultima:
    risposta = "ecco la chiave sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX e basta"
else:
    risposta = f"Risposta finta a: {ultima[:80]}"
print(json.dumps({"type": "result", "subtype": "success", "result": risposta, "session_id": sessione,
                  "num_turns": 1, "total_cost_usd": 0}))
