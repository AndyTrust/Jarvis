#!/usr/bin/env python3
"""Perché un comando o un'azione è stata negata? Una risposta in un comando (l'utente, 2026-10-04: «una volta per tutte»).

  python3 strumenti/perche_negato.py [N]      ultime N negazioni (default 10), da tutti e due i registri

Chi decide cosa in Jarvis (Mac e VPS), in ordine:
 1. HOOK  ~/.claude/hooks/guardia_comandi.py      (PreToolUse su Bash)  messaggio «Bloccato dalla guardia dei comandi: …»
          solo comandi distruttivi (rm -rf, push forzati, DROP…). Si sblocca con JARVIS_CONFERMATO=1 davanti, dopo il sì dell'utente.
          Registro: ~/.locale-onedrive/jarvis-cc/registro/guardia.jsonl
 2. HOOK  ~/.claude/hooks/connessioni_guardia.py  servizi su «spento» / «chiedi prima» (Mac)
 3. PERMESSI  command-center/approvazioni_mcp.py → regole_permessi.py (classi nega/segreto/privato) → conformita.py
          (paletti duri, badge di lavoro 30 min, modello). Messaggi «Non rispetta la richiesta dell'utente: …» e «Permesso negato dalla regola …».
          Registro: ~/.locale-onedrive/jarvis-cc/registro/regole.jsonl. Interruttori: command-center/configurazione.json
          ("autorizza_jarvis", "badge") e, sulla VPS, il file ~/.locale-onedrive/jarvis-cc/segreti_con_conferma («libero»).
Le copie in claude-config/hooks/ sono quelle da installare su una macchina nuova (allineate al 2026-10-04); command-center/registro-dev/
è una copia di sviluppo. Quella attiva è sempre ~/.claude/hooks/.
"""
import json
import os
import sys
import time
from pathlib import Path

REG = Path.home() / ".locale-onedrive" / "jarvis-cc" / "registro"


def righe(f):
    try:
        for r in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                yield json.loads(r)
            except ValueError:
                continue
    except OSError:
        return


def main(a):
    n = int(a[0]) if a and a[0].isdigit() else 10
    voci = []
    for d in righe(REG / "guardia.jsonl"):
        if d.get("esito") == "rifiutato":
            voci.append((d.get("ts", 0), "HOOK guardia_comandi", d.get("motivo", ""), d.get("comando", "")))
    for d in righe(REG / "regole.jsonl"):
        if d.get("esito") == "rifiutato":
            voci.append((d.get("ts", 0), f"PERMESSI {d.get('regola', '')}/{d.get('metodo', '')}", d.get("motivo", ""), d.get("riepilogo", "")))
    voci.sort(reverse=True)
    if not voci:
        print("Nessuna negazione nei registri. Se un comando si ferma lo stesso, il blocco non viene da Jarvis (vedi l'intestazione di questo file).")
        return 0
    for ts, chi, motivo, cosa in voci[:n]:
        print(f"{time.strftime('%d/%m %H:%M', time.localtime(ts))}  {chi}\n    motivo: {motivo[:200]}\n    azione: {cosa[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
