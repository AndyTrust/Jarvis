#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Quando l'utente conferma o chiude («ok», «perfetto», «va bene», «chiuso», «fatto», «salva»), il salvataggio parte da solo.

Gancio UserPromptSubmit di Claude Code (JSON su stdin: prompt, cwd, session_id). Se il messaggio è solo una conferma:
  1. lancia subito il giro meccanico (stato_avanzamento.py --giro --evento conferma): Stato.md dello spazio e diario
     del giorno, muto se non c'è niente di nuovo;
  2. aggiunge al contesto l'istruzione di fare, nello stesso turno, il salvataggio con giudizio della skill
     aggiorna-memoria (FATTO, DA FARE, ERRORI DA NON RIPETERE del progetto corrente).
Un messaggio lungo o una domanda non è una conferma: niente. Esce sempre 0 e non ferma mai Claude.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFERMA = re.compile(r"^\s*(ok(ay)?|perfetto|va bene|chiuso|chiudi|fatto|salva(\s+in\s+memoria)?|ottimo|bene così)"
                      r"(\s*(grazie|così|,|\.|!|boss))*[\s.!]*$", re.I)
QUI = Path(__file__).resolve().parent


def e_conferma(testo):
    t = str(testo or "").strip()
    return 0 < len(t) <= 40 and "?" not in t and bool(CONFERMA.match(t))


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    if not e_conferma(ev.get("prompt")):
        return
    cwd = ev.get("cwd") or os.getcwd()
    gancio = QUI / "stato_avanzamento.py"
    if gancio.is_file():
        try:
            subprocess.run([sys.executable, str(gancio), "--giro", "--evento", "conferma", "--cwd", cwd],
                           capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass
    istruzione = ("L'utente ha confermato o chiuso il lavoro. Nello stesso turno, prima di rispondere: salva in memoria con la "
                  "skill aggiorna-memoria (modalità progetto, cartella corrente): FATTO, DA FARE ed ERRORI DA NON RIPETERE con "
                  "data e ora; lo Stato.md dello spazio e il diario del giorno sono già stati aggiornati dal gancio. "
                  "Se non c'è niente di nuovo da salvare, dillo in una riga.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": istruzione}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001  — un gancio non ferma mai Claude
        pass
    sys.exit(0)
