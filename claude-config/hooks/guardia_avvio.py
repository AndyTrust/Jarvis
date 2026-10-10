#!/usr/bin/env python3
"""Lanciatore della guardia dei comandi (revisione 3, F7, 2026-10-04): se guardia_comandi.py non si carica
(errore di sintassi, file rotto o mancante) o va in errore, il comando Bash viene BLOCCATO, non lasciato passare.
Per Claude Code un hook che esce con 1 è un errore che non blocca: per questo qui si stampa sempre una decisione.

Nel settings.json il comando dell'hook diventa:  python3 "$HOME/.claude/hooks/guardia_avvio.py"
Solo libreria standard, niente da analizzare qui: legge l'ingresso una volta e lo passa alla guardia."""
import json
import os
import sys


def nega(perche):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                        "permissionDecisionReason": perche}}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def avvia():
    try:
        grezzo = sys.stdin.buffer.read()
    except BaseException:  # noqa: BLE001
        nega("Bloccato: la guardia dei comandi non riesce a leggere il comando.")
        return 0
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import guardia_comandi
        return guardia_comandi.main(grezzo) or 0
    except SystemExit as e:
        return e.code or 0
    except BaseException as e:  # noqa: BLE001
        nega(f"Bloccato: la guardia dei comandi è rotta ({type(e).__name__}): avvisa l'utente, che deve ripararla "
             "(python3 -m py_compile ~/.claude/hooks/guardia_comandi.py && python3 ~/.claude/hooks/guardia_comandi.py --prova).")
        return 0


if __name__ == "__main__":
    sys.exit(avvia())
