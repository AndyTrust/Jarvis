#!/usr/bin/env python3
"""Cartellino uguale per ogni nota di Memoria, come l'etichetta delle mail (l'utente, 2026-10-02).

Campi: spazio · progetto · variante (solo Jarvis: mac, windows, test, business, comune) · tipo · stato · aggiornato.
Aggiunge solo i campi che mancano: i valori già scritti non si toccano.

    python3 vault_cartellini.py            # a secco: conta cosa aggiungerebbe
    python3 vault_cartellini.py --applica
"""
import re, sys, collections
from datetime import datetime
from pathlib import Path

MEM = Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain/Memoria"
SPAZI = {"00 Comune": "Comune", "Azienda Uno": "Azienda Uno", "CRM Azienda Uno": "Azienda Uno", "Sito Azienda Uno": "Azienda Uno",
         "Azienda Due": "Azienda Due", "Vita personale": "Vita personale", "Patrimonio": "Patrimonio",
         "Agenti di Jarvis": "Vita personale", "Memoria": "Comune"}
PROGETTI = {"Jarvis": "Jarvis", "App Android": "App Android", "prodotto-uno": "prodotto-uno", "Progetto B": "Progetto B",
            "CRM": "CRM Azienda Uno", "Sito": "Sito Azienda Uno", "AZD": "Azienda Due", "AZD": "Azienda Due",
            "Social": "Social", "Hobby": "Hobby", "Demo": "Demo", "Metatrader": "Metatrader", "L'utente Business": "L'utente Business",
            "Strategie": "Strategie"}
TIPO_CARTELLA = {"Fatti": "fatto", "Decisioni": "decisione", "Errori da non ripetere": "errore", "Wiki": "wiki",
                 "Report": "report", "Diario": "diario", "Sviluppi": "sviluppo", "Agenti": "agente", "Inbox": "inbox",
                 "Business": "guida", "Regole di lavoro": "regola", "Strategie": "strategia"}
SALTA = (".claude", "_archivio", "Diario")
VAR = [("windows", r"windows|powershell|\.ps1|\bwin32\b|pc windows"), ("test", r"privato-test|jarvis-privato-test|repo[- ]privato[- ]test|template di prova|copia di prova"),
       ("business", r"jarvis business|licenza|patreon|sponsors|operatore|vendita a moduli|assistenza a ore|prodotto"),
       ("mac", r"\bmac\b|launchd|command[- ]center|voce|lavagna|backtalk|barehands|mani libere|passbolt|portiere|sentinella|hook")]


def variante(testo, nome):
    t = (nome + " " + testo[:6000]).lower()
    punti = {v: len(re.findall(rx, t)) for v, rx in VAR}
    if punti["windows"] >= 3 and punti["windows"] >= punti["mac"] // 3:
        return "windows"
    if punti["test"] >= 2:
        return "test"
    if punti["business"] >= 3 and punti["business"] >= punti["mac"] // 2:
        return "business"
    return "mac" if punti["mac"] >= 2 else "comune"


def parti(testo):
    m = re.match(r"---\n(.*?)\n---\n?", testo, re.S)
    return (m.group(1), testo[m.end():]) if m else (None, testo)


def calcola(p):
    rel = p.relative_to(MEM).parts
    if len(rel) < 2 or any(x in rel for x in SALTA):
        return None
    spazio = SPAZI.get(rel[0])
    if not spazio:
        # spazio nuovo creato dalla lavagna (Memoria/<nome>/<progetto>/…): vale il nome della cartella
        if rel[0] in ("Memoria",) or not (MEM / rel[0] / f"{rel[0]}.md").exists():
            return None
        spazio = rel[0]
    progetto = None
    for r in rel[1:-1]:
        if r in PROGETTI:
            progetto = PROGETTI[r]; break
    if not progetto and rel[0] not in SPAZI and len(rel) >= 3:
        progetto = rel[1]
    if not progetto and rel[0] == "CRM Azienda Uno":
        progetto = "CRM Azienda Uno"
    if not progetto and rel[0] == "Sito Azienda Uno":
        progetto = "Sito Azienda Uno"
    if not progetto and rel[0] == "00 Comune":
        progetto = "Comune"
    tipo = next((TIPO_CARTELLA[r] for r in rel[1:-1][::-1] if r in TIPO_CARTELLA), None)
    return spazio, progetto, tipo


def main(applica):
    aggiunti = collections.Counter(); toccati = 0; per_var = collections.Counter()
    for p in sorted(MEM.rglob("*.md")):
        c = calcola(p)
        if not c:
            continue
        spazio, progetto, tipo = c
        testo = p.read_text(encoding="utf-8", errors="ignore")
        fm, corpo = parti(testo)
        campi = dict(re.findall(r"^([A-Za-zàèéìòù_]+):\s*(.*)$", fm or "", re.M))
        nuovi = {}
        if "spazio" not in campi: nuovi["spazio"] = spazio
        if "progetto" not in campi and progetto: nuovi["progetto"] = progetto
        prog = campi.get("progetto", progetto)
        if prog and prog.strip("\"' ") == "Jarvis" and "variante" not in campi:
            nuovi["variante"] = variante(testo, p.stem)
            per_var[nuovi["variante"]] += 1
        if "tipo" not in campi: nuovi["tipo"] = tipo or "nota"
        if "stato" not in campi: nuovi["stato"] = "vivo"
        if "aggiornato" not in campi:
            nuovi["aggiornato"] = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        if not nuovi:
            continue
        toccati += 1
        aggiunti.update(nuovi.keys())
        if applica:
            righe = "\n".join(f"{k}: {v}" for k, v in nuovi.items())
            nuovo = f"---\n{fm}\n{righe}\n---\n{corpo}" if fm is not None else f"---\n{righe}\n---\n\n{testo}"
            p.write_text(nuovo, encoding="utf-8")
    print(("scritti" if applica else "da scrivere"), toccati, "file; campi aggiunti:", dict(aggiunti))
    print("variante Jarvis:", dict(per_var))


if __name__ == "__main__":
    main("--applica" in sys.argv)
