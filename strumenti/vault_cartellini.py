#!/usr/bin/env python3
"""Cartellino uguale per ogni nota di Memoria, come l'etichetta delle mail (l'utente, 2026-10-02).

Campi: spazio · progetto · tipo · stato · aggiornato (spazi e progetti da command-center/spazi.json).
Aggiunge solo i campi che mancano: i valori già scritti non si toccano.

    python3 vault_cartellini.py            # a secco: conta cosa aggiungerebbe
    python3 vault_cartellini.py --applica
"""
import re, sys, collections
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crea_progetto as _cp  # noqa: E402

MEM = _cp.memoria()                       # la memoria condivisa (~/.jarvis/percorsi.json)


def _da_spazi():
    """{cartella dello spazio nella memoria: nome dello spazio}, {nome progetto: nome progetto} da spazi.json."""
    spazi, progetti = {"Comune": "Comune"}, {}
    for s in _cp.carica_spazi().get("spazi", []):
        cart = s.get("cartella_nome") or (Path(s["memoria"]).parent.name if s.get("memoria") else s["nome"])
        spazi[cart] = s["nome"]
        for pr in s.get("progetti", []):
            progetti[pr["nome"]] = pr["nome"]
    return spazi, progetti


SPAZI, PROGETTI = _da_spazi()
TIPO_CARTELLA = {"Fatti": "fatto", "Decisioni": "decisione", "Errori da non ripetere": "errore", "Wiki": "wiki",
                 "Report": "report", "Diario": "diario", "Sviluppi": "sviluppo", "Agenti": "agente", "Inbox": "inbox",
                 "Business": "guida", "Regole di lavoro": "regola", "Strategie": "strategia"}
SALTA = (".claude", "_archivio", "Diario")
def parti(testo):
    m = re.match(r"---\n(.*?)\n---\n?", testo, re.S)
    return (m.group(1), testo[m.end():]) if m else (None, testo)


def calcola(p):
    rel = p.relative_to(MEM).parts
    if len(rel) < 2 or any(x in rel for x in SALTA):
        return None
    spazio = SPAZI.get(rel[0])
    if not spazio:
        # cartella con la sua porta (<nome>/<nome>.md) ma non ancora in spazi.json: vale il nome della cartella
        if not (MEM / rel[0] / f"{rel[0]}.md").exists():
            return None
        spazio = rel[0]
    progetto = None
    for r in rel[1:-1]:
        if r in PROGETTI:
            progetto = PROGETTI[r]; break
    if not progetto and rel[0] not in SPAZI and len(rel) >= 3:
        progetto = rel[1]
    if not progetto and rel[0] == "Comune":
        progetto = "Comune"
    tipo = next((TIPO_CARTELLA[r] for r in rel[1:-1][::-1] if r in TIPO_CARTELLA), None)
    return spazio, progetto, tipo


def main(applica):
    if not MEM.is_dir():
        print("memoria non ancora creata: niente da fare")
        return
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


if __name__ == "__main__":
    main("--applica" in sys.argv)
