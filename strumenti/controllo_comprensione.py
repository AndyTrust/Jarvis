#!/usr/bin/env python3
"""Controllo di comprensione degli agenti (l'utente, 2026-10-02): hanno LETTO il contesto e AGGIORNATO la memoria?

Legge i registri delle missioni del Command Center (command-center/missioni/*/registro.log: ogni strumento usato) e per
ogni missione dice, con la riga di prova, se chi ha lavorato ha letto lo Stato e la Guida del progetto, ha cercato nella
memoria, ha preso il badge, ha scritto in memoria e ha aggiornato il report. Non misura l'intelligenza: misura se ha fatto
le azioni che provano di aver letto. Scrive Memoria/00 Comune/Controllo comprensione.md.

    python3 controllo_comprensione.py [N]    # ultime N missioni di lavoro (default 20)
"""
import json, re, sys
from datetime import datetime
from pathlib import Path

QUI = Path(__file__).resolve().parents[1] / "command-center" / "missioni"
OUT = Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain/Memoria/00 Comune/Controllo comprensione.md"
PROVE = [("legge lo Stato", r"Stato\.md|Stato generale"), ("legge la Guida", r"Guida agenti"),
         ("cerca in memoria", r"cerca_memoria\.py|Jarvis Brain/Memoria|Memoria/"), ("badge", r"lavori\.py.* (prendo|finito)"),
         ("tombe (agenti tolti)", r"agenti-tolti\.json"),
         ("scrive in memoria", r"(Write|Edit): .*(Memoria/|\.claude/memoria)"), ("aggiorna il report", r"(Write|Edit): .*(Stato .*\.md|/Report/)")]


def missioni(n):
    out = []
    for d in sorted(QUI.glob("*"), reverse=True):
        try:
            c = json.loads((d / "missione.json").read_text())
            st = json.loads((d / "stato.json").read_text()) if (d / "stato.json").exists() else {}
        except Exception:
            continue
        if c.get("spazio_nome") == "Prova":
            continue
        out.append((d, c, st))
        if len(out) >= n:
            break
    return out


def main(n):
    righe = ["| Missione | Spazio | Stato | " + " | ".join(p for p, _ in PROVE) + " |", "|---|---|---|" + "---|" * len(PROVE)]
    manca = {p: 0 for p, _ in PROVE}
    tot = 0
    for d, c, st in missioni(n):
        reg = (d / "registro.log").read_text(errors="ignore") if (d / "registro.log").exists() else ""
        riga = [d.name + (" (catena)" if c.get("genere") == "aggiorna_catena" else ""), c.get("spazio_nome", "?"), st.get("stato", "?")]
        for p, rx in PROVE:
            ok = bool(re.search(rx, reg))
            riga.append("✅" if ok else "❌")
            manca[p] += 0 if ok else 1
        righe.append("| " + " | ".join(riga) + " |")
        tot += 1
    ora = datetime.now().strftime("%Y-%m-%d %H:%M")
    testo = (f"---\ntitolo: Controllo comprensione\ntipo: stato\nspazio: Comune\nprogetto: Comune\nstato: vivo\naggiornato: {ora}\n---\n\n"
             f"# Controllo comprensione degli agenti\n\nGenerato il {ora} da `strumenti/controllo_comprensione.py`. Collegato a [[Stato generale]] · [[LEGGIMI]].\n\n"
             "Per ogni missione di lavoro: gli agenti hanno fatto le azioni che provano di aver letto il contesto e aggiornato la memoria? "
             "✅ = c'è la riga nel registro; ❌ = non risulta. Non misura la comprensione vera, misura le prove.\n\n"
             + "\n".join(righe) + "\n\n## Dove si manca di più\n\n"
             + ("\n".join(f"- {p}: mancano {v} missioni su {tot}" for p, v in sorted(manca.items(), key=lambda x: -x[1]) if v) or "- niente")
             + "\n\nSe una colonna è quasi tutta ❌, il problema non è del singolo agente: l'istruzione non arriva (profilo o missione) e va corretta lì.\n")
    OUT.write_text(testo, encoding="utf-8")
    print(f"scritto {OUT.name}: {tot} missioni; mancano:", {k: v for k, v in manca.items() if v})


main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
