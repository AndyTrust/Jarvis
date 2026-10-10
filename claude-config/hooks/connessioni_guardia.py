#!/usr/bin/env python3
"""Hook PreToolUse: le connessioni a tre posizioni dell'utente (2026-10-04). Vale anche con il bypass dei permessi.
Legge ~/.locale-onedrive/jarvis-cc/connessioni.json tramite ~/Jarvis/strumenti/connessioni.py.
  spento  -> blocca sempre
  chiedi  -> con il bypass blocca e dice a Jarvis di chiedere all'utente; senza bypass lascia il gestore normale («ask»)
  consentito, nessun servizio, errore qualunque -> non dice niente (passa)
Un errore QUI non blocca niente: la rete di sicurezza è la guardia dei comandi, che è un altro hook."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/Jarvis/strumenti"))


def _log(riga):
    try:
        d = os.path.expanduser("~/.locale-onedrive/jarvis-cc")
        with open(os.path.join(d, "connessioni.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {riga}\n")
    except OSError:
        pass


def main():
    try:
        dati = json.load(sys.stdin)
        import connessioni as C
        strumento = dati.get("tool_name") or ""
        ingresso = dati.get("tool_input") or {}
        esito, servizio, motivo = C.valuta(strumento, ingresso, modo=dati.get("permission_mode"))
        if servizio and esito != "blocca":
            C.segna_uso(servizio["id"])
        sid = servizio["id"] if servizio else "piano"
    except Exception as e:  # noqa: BLE001 — mai bloccare per un errore di questo hook
        _log(f"errore {type(e).__name__}: {str(e)[:120]}")
        return 0
    if esito == "passa":
        return 0
    decisione = "deny" if esito == "blocca" else "ask"
    _log(f"{decisione} servizio={sid} strumento={strumento} modo={dati.get('permission_mode')}")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decisione,
                                             "permissionDecisionReason": motivo}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
