#!/usr/bin/env python3
"""Le caselle di Jarvis: ogni richiesta dell'utente è una casella nella nota del giorno.

L'utente (19/09/2026): «usare dei task che si possano spuntare, così vai a leggere quello
che abbiamo fatto se non hai aggiornato». Le caselle stanno nel diario del vault,
sezione «Caselle del giorno»:

    - [ ] 09:52 · testo                  aperta, con l'ora in cui è arrivata
    - [x] 09:52 → 10:07 · testo          spuntata, con l'ora in cui è finita

Uso:
  python3 strumenti/task.py add "testo"        aggiunge una casella aperta
  python3 strumenti/task.py fatto "testo"      spunta la casella che contiene questo testo
  python3 strumenti/task.py lista              le aperte di oggi e dei 3 giorni prima
Ora e data vengono dal sistema, mai scritte a mano.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":     # la memoria di chi usa il PC (utente.json), non quella del capo
    _RADICE = Path(__file__).resolve().parent.parent
    try:
        VAULT = _RADICE / json.loads((_RADICE / "utente.json").read_text(encoding="utf-8"))["memoria_dir"]
    except (OSError, ValueError, KeyError):
        VAULT = _RADICE / ".claude" / "memoria"
else:                           # la memoria condivisa (~/.jarvis/percorsi.json), predefinita ~/Jarvis-Memoria
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import crea_progetto as _cp
    VAULT = _cp.memoria()
MESI = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto",
        "Settembre", "Ottobre", "Novembre", "Dicembre"]
TITOLO = "## Caselle del giorno"


def nota(giorno):
    return VAULT / "Diario" / f"{giorno.isoformat()}.md"      # il diario del giorno: <memoria>/Diario/AAAA-MM-GG.md


def apri(giorno, crea=False):
    p = nota(giorno)
    if p.exists():
        return p, p.read_text(encoding="utf-8")
    if not crea:
        return p, None
    p.parent.mkdir(parents=True, exist_ok=True)
    ora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return p, (f"---\ntitolo: {giorno.isoformat()}\ntipo: diario\naggiornato: {ora}\n---\n\n"
               f"# Giorno {giorno.day} {MESI[giorno.month - 1].lower()} {giorno.year}\n")


def salva(p, t):
    ora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    t = re.sub(r"^aggiornato:.*$", f"aggiornato: {ora}", t, count=1, flags=re.M)
    p.write_text(t, encoding="utf-8")


def aggiungi(testo):
    adesso = dt.datetime.now()
    p, t = apri(adesso.date(), crea=True)
    riga = f"- [ ] {adesso.strftime('%H:%M')} · {testo.strip()}"
    if TITOLO in t:
        i = t.index(TITOLO) + len(TITOLO)
        fine = t.find("\n## ", i)
        fine = len(t) if fine < 0 else fine
        t = t[:fine].rstrip("\n") + "\n" + riga + "\n" + t[fine:]
    else:
        t = t.rstrip("\n") + f"\n\n{TITOLO}\n\n{riga}\n"
    salva(p, t)
    print(riga)


def spunta(testo):
    adesso = dt.datetime.now()
    for indietro in range(4):
        p, t = apri(adesso.date() - dt.timedelta(days=indietro))
        if t is None:
            continue
        for riga in t.splitlines():
            m = re.match(r"- \[ \] (\d{2}:\d{2}) · (.*)", riga)
            if m and testo.lower() in m.group(2).lower():
                nuova = f"- [x] {m.group(1)} → {adesso.strftime('%H:%M')} · {m.group(2)}"
                salva(p, t.replace(riga, nuova, 1))
                print(nuova)
                return 0
    print(f"nessuna casella aperta con «{testo}» negli ultimi 4 giorni")
    return 1


def lista():
    oggi = dt.date.today()
    trovate = 0
    for indietro in range(4):
        g = oggi - dt.timedelta(days=indietro)
        _, t = apri(g)
        if t is None:
            continue
        for riga in t.splitlines():
            if riga.startswith("- [ ] "):
                print(f"{g.isoformat()}  {riga[6:]}")
                trovate += 1
    print(f"— {trovate} caselle aperte")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "add":
        aggiungi(a[1])
    elif len(a) == 2 and a[0] == "fatto":
        sys.exit(spunta(a[1]))
    elif a[:1] == ["lista"]:
        lista()
    else:
        sys.exit(__doc__)
