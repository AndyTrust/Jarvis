#!/usr/bin/env python3
"""Mette nel profilo di ogni agente di progetto il blocco «Prima di lavorare: leggi lo Stato e la Guida» (2026-10-02).

Idempotente (marcatori HTML). Copia degli originali in ~/.jarvis/backup-profili/.
    python3 agenti_leggono_stato.py [--applica]
"""
import shutil, sys
from pathlib import Path
QUI = Path(__file__).resolve().parents[1] / "command-center"
sys.path.insert(0, str(QUI))
import spazi
sys.path.insert(0, str(Path(__file__).resolve().parent))
import crea_progetto as _cp  # noqa: E402
MEM = _cp.memoria()

I, F = "<!-- stato-vault:inizio (scritto da strumenti/agenti_leggono_stato.py) -->", "<!-- stato-vault:fine -->"
BACKUP = Path.home() / ".jarvis" / "backup-profili"


def blocco(sezioni):
    righe = "\n".join(f"- Stato: `{_cp.corto(MEM / s.split('/')[0] / 'Stato.md')}`" for s in sezioni)
    return (f"{I}\n## Prima di lavorare: stato e guida\n\nLeggi lo Stato del progetto (generato dalle note: cosa è aperto, ultime decisioni, "
            f"errori da non ripetere) e la Guida agenti (come si lavora qui). Dopo il lavoro scrivi la nota col cartellino "
            f"(spazio, progetto, tipo, stato, aggiornato) e spunta il «Da fare».\n{righe}\n{F}\n")


def main(applica):
    n = 0
    for s in spazi.carica():
        viste = set()
        for p in s["progetti"]:
            sez = [x for x in (p.get("sezioni_memoria") or []) if (MEM / x.split("/")[0] / "Stato.md").exists()]
            if not sez or not p["esiste"] or p["cartella"] in viste:
                continue
            viste.add(p["cartella"])
            for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                f = Path(a["file"]); t = f.read_text(encoding="utf-8")
                b = blocco(sez)
                if I in t:
                    i0, i1 = t.index(I), t.index(F) + len(F) + 1
                    nuovo = t[:i0] + b + t[i1:]
                else:
                    m = "<!-- comunica-con:inizio"
                    nuovo = t.replace(m, b + "\n" + m, 1) if m in t else t.rstrip() + "\n\n" + b
                if nuovo != t:
                    n += 1
                    if applica:
                        d = BACKUP / (str(f).replace("/", "__")); d.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(f, d)
                        f.write_text(nuovo, encoding="utf-8")
    print(("scritti" if applica else "da scrivere"), n, "profili")


main("--applica" in sys.argv)
