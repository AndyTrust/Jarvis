#!/usr/bin/env python3
"""Cerca nella memoria condivisa (le note Markdown), con SQLite FTS5.

Al posto di Ruflo (decisione dell'utente del 2026-09-23): niente MCP, niente database
a parte da tenere allineato a mano. L'indice sta sul Mac, fuori da OneDrive, e si
rifà da solo prima di ogni ricerca guardando solo i file cambiati (data e misura).

    python3 strumenti/cerca_memoria.py "rottamazione scaduta"
    python3 strumenti/cerca_memoria.py "token n8n" --spazio "<spazio>" -n 5
    python3 strumenti/cerca_memoria.py "saldo unicredit" --tipo errore
    python3 strumenti/cerca_memoria.py --rifai        # indice da zero

La ricerca ignora maiuscole e accenti. Le parole si cercano tutte (AND); per una
frase esatta si mettono le virgolette dentro: '"chiave ssh"'. Con --o basta una.
"""
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

WIN = sys.platform == "win32"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import crea_progetto as _cp  # noqa: E402
# una sola memoria: quella di ~/.jarvis/percorsi.json (predefinita ~/Jarvis-Memoria)
RADICI = {"memoria": _cp.memoria()}
# Cartelle che non sono note: allegati, copie, configurazione di Obsidian.
SALTA = {".obsidian", ".trash", ".git", "node_modules", ".playwright-mcp", "Archivio",
         "Progetti"}  # il codice dei progetti (riordino del 24/09/2026): non è memoria
INDICE = Path.home() / ".jarvis/cerca-memoria.sqlite"


def apri():
    INDICE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(INDICE)
    db.execute("create table if not exists file(percorso text primary key, mtime real, misura int)")
    db.execute(
        "create virtual table if not exists nota using fts5("
        "percorso unindexed, vault unindexed, titolo, spazio, tipo, testo, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    return db


def frontmatter(testo):
    """Restituisce (campi, corpo). Legge solo le righe «chiave: valore» semplici."""
    campi = {}
    if testo.startswith("---\n"):
        fine = testo.find("\n---", 4)
        if fine > 0:
            for riga in testo[4:fine].splitlines():
                m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", riga)
                if m:
                    campi[m.group(1)] = m.group(2).strip().strip('"')
            testo = testo[fine + 4:]
    return campi, testo


def titolo_di(corpo, nome):
    m = re.search(r"^#\s+(.+)$", corpo, re.M)
    return m.group(1).strip() if m else nome


def aggiorna(db, rifai=False):
    if rifai:
        db.execute("delete from file")
        db.execute("delete from nota")
    visti, nuovi = set(), 0
    for vault, radice in RADICI.items():
        if not radice.is_dir():
            print(f"avviso: {vault} non trovato in {radice}", file=sys.stderr)
            continue
        for cartella, sotto, files in os.walk(radice):
            sotto[:] = [s for s in sotto if s not in SALTA and not s.startswith(".")]
            for nome in files:
                if not nome.endswith(".md"):
                    continue
                p = Path(cartella) / nome
                chiave = str(p)
                visti.add(chiave)
                try:
                    st = p.stat()
                except OSError:
                    continue
                riga = db.execute("select mtime, misura from file where percorso=?", (chiave,)).fetchone()
                if riga and riga[0] == st.st_mtime and riga[1] == st.st_size:
                    continue
                try:
                    testo = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue  # file di OneDrive non ancora scaricato: si riprova al giro dopo
                campi, corpo = frontmatter(testo)
                spazio = campi.get("spazio", "")
                if not spazio:
                    rel = p.relative_to(radice).parts
                    spazio = rel[1] if len(rel) > 2 and rel[0] == "Memoria" else rel[0] if len(rel) > 1 else ""
                db.execute("delete from nota where percorso=?", (chiave,))
                db.execute(
                    "insert into nota(percorso, vault, titolo, spazio, tipo, testo) values(?,?,?,?,?,?)",
                    (chiave, vault, titolo_di(corpo, p.stem), spazio, campi.get("tipo", ""), corpo),
                )
                db.execute("insert or replace into file values(?,?,?)", (chiave, st.st_mtime, st.st_size))
                nuovi += 1
    spariti = [r[0] for r in db.execute("select percorso from file") if r[0] not in visti]
    for p in spariti:
        db.execute("delete from nota where percorso=?", (p,))
        db.execute("delete from file where percorso=?", (p,))
    db.commit()
    return nuovi, len(spariti)


def domanda(testo, o=False):
    """Trasforma le parole dell'utente in una query FTS5 sicura (niente sintassi da scrivere)."""
    frasi = re.findall(r'"([^"]+)"', testo)
    resto = re.sub(r'"[^"]+"', " ", testo)
    pezzi = ['"' + f.replace('"', "") + '"' for f in frasi]
    pezzi += ['"' + w + '"*' for w in re.findall(r"\w+", resto) if len(w) > 1]
    return (" OR " if o else " AND ").join(pezzi)


def main():
    ap = argparse.ArgumentParser(description="Cerca nelle note dei vault (SQLite FTS5).")
    ap.add_argument("parole", nargs="*")
    ap.add_argument("-n", type=int, default=10, help="quanti risultati (10)")
    ap.add_argument("--spazio", help="il nome di uno spazio (cartella della memoria), o Comune")
    ap.add_argument("--tipo", help="errore, decisione, fatto, regola, da-fare…")
    ap.add_argument("--o", action="store_true", help="basta una delle parole")
    ap.add_argument("--rifai", action="store_true", help="rifà l'indice da zero")
    a = ap.parse_args()

    db = apri()
    nuovi, spariti = aggiorna(db, a.rifai)
    if not a.parole:
        tot = db.execute("select count(*) from nota").fetchone()[0]
        print(f"indice: {tot} note ({nuovi} aggiornate, {spariti} tolte) in {INDICE}")
        return
    q = domanda(" ".join(a.parole), a.o)
    if not q:
        sys.exit("nessuna parola da cercare")
    sql = ("select percorso, vault, titolo, spazio, tipo, "
           "snippet(nota, 5, '«', '»', ' … ', 14), bm25(nota, 0, 0, 8.0, 2.0, 1.0, 1.0) as r "
           "from nota where nota match ?")
    par = [q]
    if a.spazio:
        sql += " and spazio like ?"
        par.append(f"%{a.spazio}%")
    if a.tipo:
        sql += " and tipo = ?"
        par.append(a.tipo)
    sql += " order by r limit ?"
    par.append(a.n)
    righe = db.execute(sql, par).fetchall()
    if not righe:
        print("nessuna nota trovata")
        return
    for percorso, vault, titolo, spazio, tipo, pezzo, _ in righe:
        rel = Path(percorso).relative_to(RADICI[vault])
        link = f"obsidian://open?vault={quote(vault)}&file={quote(str(rel.with_suffix('')))}"
        etichetta = " · ".join(x for x in (spazio, tipo) if x)
        print(f"■ {titolo}" + (f"  [{etichetta}]" if etichetta else ""))
        print(f"  {' '.join(pezzo.split())}")
        print(f"  {percorso}")
        print(f"  {link}\n")


if __name__ == "__main__":
    main()
