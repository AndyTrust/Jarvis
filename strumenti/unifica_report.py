#!/usr/bin/env python3
"""Unisce Postino-Report dentro Report e archivia i report vecchi (l'utente, 2026-10-02).

    python3 unifica_report.py            # a secco: dice cosa sposterebbe
    python3 unifica_report.py --applica  # sposta davvero, scrive il log per annullare
    python3 unifica_report.py --annulla <log.json>

Niente si cancella. Dentro ogni spazio resta il report di oggi e le sottocartelle di progetto; il resto va in
<spazio>/_archivio/AAAA-MM/. I report di posta vanno in Comune/Posta/ (solo l'ultimo di oggi resta fuori dall'archivio).
"""
import json, re, shutil, sys, time
from datetime import date, datetime
from pathlib import Path

BRAIN = Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain"
GROK, POSTINO = BRAIN / "Report", BRAIN / "Postino-Report"
OGGI = date.today()
SPAZI = {"Azienda Uno": "Azienda Uno", "Azienda Due": "Azienda Due", "Vita personale": "Vita personale",
         "L'utente": "Vita personale", "Comune": "Comune", "Posta": "Comune/Posta"}
LOG = Path.home() / "Jarvis/log" / f"unifica_report-{datetime.now():%Y%m%d-%H%M%S}.json"
mosse = []


def data_di(p):
    m = re.search(r"(20\d\d)-?(\d\d)-?(\d\d)", p.name)
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else date.fromtimestamp(p.stat().st_mtime)
    except ValueError:
        return date.fromtimestamp(p.stat().st_mtime)


def sposta(src, dst, motivo):
    """Registra la mossa. Se la destinazione c'è già, resta il file più recente e l'altro va in _archivio."""
    if dst.exists():
        if src.is_file() and dst.is_file() and src.stat().st_mtime > dst.stat().st_mtime:
            mosse.append({"da": str(dst), "a": str(dst.parent / "_archivio" / f"{data_di(dst):%Y-%m}" / dst.name),
                          "motivo": "sostituito da una versione più recente"})
        else:
            sposta_archivio(src, dst.parent)
            return
    mosse.append({"da": str(src), "a": str(dst), "motivo": motivo})


def sposta_archivio(src, cartella):
    mosse.append({"da": str(src), "a": str(cartella / "_archivio" / f"{data_di(src):%Y-%m}" / src.name),
                  "motivo": "doppio più vecchio"})


def pianifica():
    # 1. Postino-Report -> Report
    for x in sorted(POSTINO.iterdir()):
        if x.name in (".DS_Store",):
            continue
        if x.name == "README.md":
            sposta(x, GROK / "Comune" / "_archivio" / "README Postino-Report.md", "indice vecchio")
        elif x.is_dir() and x.name in SPAZI:
            for y in sorted(x.iterdir()):
                if y.name != ".DS_Store":
                    sposta(y, GROK / SPAZI[x.name] / y.name, f"da Postino-Report/{x.name}")
        elif x.is_file():
            sposta(x, GROK / "Comune" / "Posta" / x.name, "report posta in cartella radice")
        else:
            sposta(x, GROK / "Comune" / x.name, "cartella non prevista")
    for x in sorted(GROK.iterdir()):                       # i report di posta in radice di Report
        if x.is_file() and x.name != ".DS_Store" and x.name != "README.md":
            sposta(x, GROK / "Comune" / "Posta" / x.name, "report posta in cartella radice")


ESENTI = lambda n: n.endswith(" - Report.md") or n.endswith(" - Report.pdf") or n == "Stato aggiornamenti.md"


def archivia():
    """Dopo l'unione: in ogni spazio (e in Comune/Posta) i file di giorni passati vanno in _archivio/AAAA-MM.
    Le cartelle di progetto e quelle già in _archivio non si toccano."""
    for m in mosse:                                         # mosse già pianificate: la destinazione diventa l'archivio
        s, d = Path(m["da"]), Path(m["a"])
        if "_archivio" in d.parts or not s.is_file():
            continue
        if data_di(s) < OGGI and not ESENTI(d.name):
            m["a"] = str(d.parent / "_archivio" / f"{data_di(s):%Y-%m}" / d.name)
    gia = {m["da"] for m in mosse}
    for sp in ("Azienda Uno", "Azienda Due", "Vita personale", "Comune", "Comune/Posta"):   # file già in Report
        base = GROK / sp
        for f in sorted(base.glob("*")) if base.exists() else []:
            if f.is_file() and f.name != ".DS_Store" and str(f) not in gia and data_di(f) < OGGI and not ESENTI(f.name):
                mosse.append({"da": str(f), "a": str(base / "_archivio" / f"{data_di(f):%Y-%m}" / f.name), "motivo": "vecchio, archiviato"})


def applica():
    LOG.parent.mkdir(exist_ok=True)
    fatte = []
    for m in mosse:
        s, d = Path(m["da"]), Path(m["a"])
        if not s.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            d = d.with_name(f"{d.stem} (doppio {int(time.time())}){d.suffix}")
        shutil.move(str(s), str(d))
        fatte.append({**m, "a": str(d)})
    LOG.write_text(json.dumps(fatte, ensure_ascii=False, indent=1))
    return fatte


if __name__ == "__main__":
    if "--annulla" in sys.argv:
        for m in reversed(json.loads(Path(sys.argv[sys.argv.index("--annulla") + 1]).read_text())):
            Path(m["da"]).parent.mkdir(parents=True, exist_ok=True)
            if Path(m["a"]).exists():
                shutil.move(m["a"], m["da"])
        print("annullato"); sys.exit(0)
    pianifica(); archivia()
    if "--applica" in sys.argv:
        f = applica(); print(f"spostati {len(f)} file/cartelle. Log: {LOG}")
    else:
        import collections
        c = collections.Counter((Path(m["a"]).relative_to(GROK).parts[:2] if Path(m["a"]).is_relative_to(GROK) else ("?",)) [0:2] for m in mosse)
        for k, n in sorted(c.items()): print(n, "/".join(k))
        print("totale mosse:", len(mosse))
