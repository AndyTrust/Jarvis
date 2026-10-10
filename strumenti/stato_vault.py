#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Rifà lo Stato.md di ogni spazio e lo «Stato generale» della memoria, dalla fonte unica (spazi.json).

Una sola logica: lo Stato.md di uno spazio lo scrive claude-config/hooks/stato_avanzamento.py (aggiorna_spazio):
FATTO / DA FARE / ERRORI di ogni progetto, i diari degli agenti, gli errori ripetuti. Qui lo si chiama per tutti
gli spazi e si scrive <memoria>/Comune/Stato generale.md con l'elenco degli spazi. Nessun progetto = niente da fare.

    python3 strumenti/stato_vault.py            rifà tutto
    python3 strumenti/stato_vault.py --prova    dice cosa toccherebbe, senza scrivere
"""
import importlib.util
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
import crea_progetto as cp  # noqa: E402


def gancio():
    spec = importlib.util.spec_from_file_location("stato_avanzamento", QUI.parent / "claude-config" / "hooks" / "stato_avanzamento.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    prova = "--prova" in sys.argv
    g = gancio()
    percorsi = {"memoria": str(cp.memoria()), "repo": str(QUI.parent)}
    spazi = g.spazi_json(percorsi)
    if not spazi:
        print("nessun progetto ancora: niente da fare")
        return 0
    righe = [f"# Stato generale\n\n_Rifatto da stato_vault.py il {time.strftime('%Y-%m-%d %H:%M')}. Non modificarlo a mano._\n"]
    for s in spazi:
        if prova:
            print(f"farei: {cp.memoria() / s['cartella_memoria'] / 'Stato.md'}")
        else:
            cambiato = g.aggiorna_spazio(percorsi, s, "giro stato_vault")
            print(f"{s['nome']}: Stato.md " + ("aggiornato" if cambiato else "già aggiornato"))
        righe.append(f"- [[{s['cartella_memoria']}/Stato|{s['nome']}]] · progetti: " + ", ".join(n for n, _ in s["progetti"]))
    f = cp.memoria() / "Comune" / "Stato generale.md"
    testo = "\n".join(righe) + "\n"
    if prova:
        print(f"farei: {f}")
    elif not f.is_file() or f.read_text(encoding="utf-8").split("\n", 3)[3:] != testo.split("\n", 3)[3:]:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(testo, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
