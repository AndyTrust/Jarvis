#!/usr/bin/env python3
"""handoff.py — il foglio per ripartire in una chat pulita. Zero token.

Oltre il 40-50% di contesto la qualità cala. `/compact` costa moltissimo per
riassumere e decide da solo cosa buttare; `rewind` non costa niente ma non
porta via nulla. La terza strada: si scrive un handoff, si apre una chat nuova
(zero token di cronologia) e si incolla.

Questo prepara lo scheletro con la parte deterministica già dentro (stato del
progetto, memoria, file toccati, git). Restano da riempire quattro caselle, che
sono giudizio: obiettivo, cosa si è già provato, decisioni, prossimo passo.

    ./handoff.py <cartella>              stampa
    ./handoff.py <cartella> --out H.md   scrive su file
"""
import argparse, subprocess, sys
from datetime import date
from pathlib import Path

QUI = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser(description="foglio di passaggio per una chat nuova")
    ap.add_argument("cartella", nargs="?", default=".")
    ap.add_argument("--out")
    a = ap.parse_args()

    base = Path(a.cartella).expanduser().resolve()
    if not base.is_dir(): sys.exit(f"{base} non è una cartella")

    r = subprocess.run([sys.executable, str(QUI / "stato.py"), str(base)],
                       capture_output=True, text=True)
    stato = r.stdout.strip() or "(stato non disponibile)"

    t = f"""# Handoff — {base.name} · {date.today().isoformat()}

Incolla questo in una chat nuova. La cronologia vecchia non serve: quello che
conta è qui sotto.

Cartella di lavoro: `{base}`

## Che cosa sto cercando di ottenere

DA RIEMPIRE — l'obiettivo, non il compito di adesso. Una o due righe.

## Che cosa è già stato provato e NON funziona

DA RIEMPIRE — la parte che vale di più: senza, la chat nuova ripete gli stessi
errori. Elenca i tentativi falliti **e perché** sono falliti.

## Decisioni prese, da non rimettere in discussione

DA RIEMPIRE — le scelte già fatte e la ragione. Se manca la ragione, la chat
nuova le rinegozia.

## Il prossimo passo

DA RIEMPIRE — uno solo, concreto, il primo comando o file da toccare.

---

## Stato del progetto (generato, non riscriverlo)

```
{stato}
```

## Come si lavora qui

Leggi `CLAUDE.md` nella radice (è un indice: il dettaglio sta nei `CLAUDE.md`
delle sottocartelle). La memoria dei fatti è in `.claude/memoria/`: aprine uno
solo quando serve, non tutti.
"""
    if a.out:
        p = Path(a.out).expanduser(); p.write_text(t, encoding="utf-8")
        print(f"✅ {p} — riempi le quattro caselle DA RIEMPIRE, poi apri una chat nuova e incolla.")
    else:
        print(t)

if __name__ == "__main__":
    main()
