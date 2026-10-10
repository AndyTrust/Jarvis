#!/usr/bin/env python3
"""Serietà e umorismo per TUTTI gli agenti (l'utente, 29/09/2026): riempie i campi mancanti (tono, serieta, umorismo)
con un valore di partenza per ruolo, senza toccare quelli già scelti, e riscrive in ogni profilo il blocco
«Come parli» (spazi.con_come_parla), così l'agente li sente davvero. Poi si cambiano dalla scheda della lavagna.
  python3 strumenti/imposta_come_parla.py            mostra cosa cambierebbe (nessuna scrittura)
  python3 strumenti/imposta_come_parla.py --applica  scrive i profili
Idempotente: rilanciato non cambia niente."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "command-center"))
import spazi  # noqa: E402

HOME = Path.home()
SOBRI = re.compile(r"revisore|garante|commercialista|avvocato|fiscalista|legale|consulente|guardiano|manutentore|contabile|analista|cassa|gestionale")
VIVACI = re.compile(r"copywriter|contenuti|^x-|marketing|ricercatore|seo|vendit|opportunita|pubblicazione|partner|posta")


def valori_di_partenza(nome, capogruppo):
    if capogruppo:
        return {"tono": "diretto, da capo squadra", "serieta": 3, "umorismo": 1}
    if SOBRI.search(nome):
        return {"tono": "preciso e sobrio", "serieta": 3, "umorismo": 0}
    if VIVACI.search(nome):
        return {"tono": "chiaro e vivace", "serieta": 2, "umorismo": 2}
    return {"tono": "concreto e chiaro", "serieta": 3, "umorismo": 1}


def profili_da_fare():
    visti, out = set(), []
    for s in spazi.carica():
        for p in s["progetti"]:
            if not p["esiste"]:
                continue
            for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                f = Path(a["file"])
                if f.resolve() in visti:
                    continue
                visti.add(f.resolve())
                out.append((f, a["nome"], a["capogruppo"]))
    return out


def main():
    applica = "--applica" in sys.argv
    cambiati = 0
    for f, nome, capo in profili_da_fare():
        prima = spazi.leggi_testo(f)
        campi = {k: v for k, _, _, v in spazi._voci(spazi._FM.match(prima).group(1))} if spazi._FM.match(prima) else {}
        mancano = {k: v for k, v in valori_di_partenza(nome, capo).items() if not str(campi.get(k, "")).strip()}
        nuovo, _ = spazi.aggiorna_frontmatter(prima, mancano) if mancano else (prima, [])
        nuovo = spazi.con_come_parla(nuovo)
        if nuovo != prima:
            cambiati += 1
            print(f"{'scrivo' if applica else 'cambierebbe'}: {nome:32} {('+ ' + ', '.join(f'{k}={v}' for k, v in mancano.items())) if mancano else '(solo il blocco)'}")
            if applica:
                tmp = f.with_suffix(".md.tmp")
                tmp.write_text(nuovo, encoding="utf-8")
                os.replace(tmp, f)
    print(f"{cambiati} profili {'riscritti' if applica else 'da riscrivere'}")


if __name__ == "__main__":
    main()
