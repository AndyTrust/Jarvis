#!/usr/bin/env python3
"""Controllo minimo di un backtest: niente sguardo al futuro, errore e copertura contro una base banale.

Creato il 2026-09-30 per la riunione degli agenti (strumenti/riunione.py). Solo libreria
standard. Legge un file di risultati per periodo, CSV o JSON, con una riga per mese:

    periodo,realizzato,previsto,basso,alto
    2019-01,12.5,10,2,18

`previsto`, `basso` e `alto` possono mancare nei mesi di taratura. Il periodo è AAAA-MM
(accetta anche AAAA-MM-GG: conta il mese). Nel JSON: una lista di oggetti con le stesse
chiavi, oppure {"righe": [...]}.

Cosa controlla:
1. Anti look-ahead: il periodo di prova comincia dopo la fine della taratura, e nessuna
   previsione del periodo di prova arriva da righe segnate come taratura (colonna `fase`,
   facoltativa, con valori taratura/prova).
2. Per 1, 3 e 12 mesi dall'inizio della prova: errore medio assoluto della previsione,
   copertura dell'intervallo (quota di mesi con basso <= realizzato <= alto) e lo stesso
   errore della base banale, cioè la media dei 12 mesi prima dell'inizio della prova.
   Se i mesi non bastano lo scrive e non calcola.

Uso:
    python3 strumenti/backtest_check.py risultati.csv --taratura 2011-01:2018-12 --prova 2019-01:2026-08
Stampa un JSON. Esce 1 se c'è sguardo al futuro, 2 se il file non si legge, 0 altrimenti.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ORIZZONTI = (1, 3, 12)


def mese(testo) -> int:
    """AAAA, AAAA-MM o AAAA-MM-GG -> numero di mese assoluto (anno*12 + mese-1).
    Solo l'anno vale gennaio per l'inizio: chi chiama usa fine_periodo() per la fine."""
    t = str(testo).strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-\d{1,2})?", t)
    if not m:
        raise ValueError(f"periodo non leggibile: «{t}» (serve AAAA-MM)")
    anno, me = int(m.group(1)), int(m.group(2) or 1)
    if not 1 <= me <= 12:
        raise ValueError(f"mese fuori scala: «{t}»")
    return anno * 12 + me - 1


def fine_periodo(testo) -> int:
    """Come mese(), ma «2016» vuol dire dicembre 2016."""
    t = str(testo).strip()
    return mese(t) + 11 if re.fullmatch(r"\d{4}", t) else mese(t)


def nome_mese(n: int) -> str:
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def intervallo(testo: str) -> tuple[int, int]:
    """«2011-01:2018-12» -> (inizio, fine) in mesi assoluti."""
    if ":" not in testo:
        raise ValueError(f"intervallo senza «:»: «{testo}» (serve DA:A)")
    da, a = testo.split(":", 1)
    return mese(da), fine_periodo(a)


def numero(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(" ", "")
    if t == "" or t.lower() in ("null", "none", "na", "-"):
        return None
    if "," in t:  # scrittura italiana: 1.234,5
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def carica(percorso) -> list[dict]:
    p = Path(percorso)
    testo = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        dati = json.loads(testo)
        righe = dati.get("righe", []) if isinstance(dati, dict) else dati
    else:
        righe = list(csv.DictReader(testo.splitlines()))
    out = []
    for r in righe:
        out.append({
            "mese": mese(r["periodo"]),
            "realizzato": numero(r.get("realizzato")),
            "previsto": numero(r.get("previsto")),
            "basso": numero(r.get("basso")),
            "alto": numero(r.get("alto")),
            "fase": (r.get("fase") or "").strip().lower() or None,
        })
    out.sort(key=lambda r: r["mese"])
    return out


def periodi_ok(taratura: tuple[int, int], prova: tuple[int, int]) -> list[str]:
    """Gli errori di ordine fra i due periodi. Lista vuota = va bene."""
    errori = []
    if taratura[0] > taratura[1]:
        errori.append("la taratura finisce prima di cominciare")
    if prova[0] > prova[1]:
        errori.append("la prova finisce prima di cominciare")
    if prova[0] <= taratura[1]:
        errori.append(f"sguardo al futuro: la prova comincia {nome_mese(prova[0])}, "
                      f"la taratura finisce {nome_mese(taratura[1])}")
    return errori


def controlla(righe: list[dict], taratura: tuple[int, int], prova: tuple[int, int]) -> dict:
    errori = periodi_ok(taratura, prova)
    for r in righe:
        if r["fase"] == "taratura" and r["mese"] >= prova[0]:
            errori.append(f"sguardo al futuro: {nome_mese(r['mese'])} è segnato taratura ma sta nella prova")
        if r["fase"] == "prova" and r["mese"] <= taratura[1]:
            errori.append(f"{nome_mese(r['mese'])} è segnato prova ma sta nella taratura")

    per_mese = {r["mese"]: r for r in righe}
    # base banale: media dei 12 mesi prima dell'inizio della prova, solo dati già noti
    anno_prima = [per_mese[m]["realizzato"] for m in range(prova[0] - 12, prova[0])
                  if m in per_mese and per_mese[m]["realizzato"] is not None]
    base = sum(anno_prima) / 12 if len(anno_prima) == 12 else None

    orizzonti = {}
    for h in ORIZZONTI:
        mesi = list(range(prova[0], prova[0] + h))
        if mesi[-1] > prova[1]:
            orizzonti[str(h)] = {"esito": "dati insufficienti", "motivo": f"la prova dura meno di {h} mesi"}
            continue
        sotto = [per_mese.get(m) for m in mesi]
        if any(r is None or r["realizzato"] is None for r in sotto):
            orizzonti[str(h)] = {"esito": "dati insufficienti", "motivo": "manca il realizzato di qualche mese"}
            continue
        prev = [r for r in sotto if r["previsto"] is not None]
        voce = {"mesi": h, "da": nome_mese(mesi[0]), "a": nome_mese(mesi[-1])}
        if len(prev) < h:
            voce.update(esito="dati insufficienti", motivo="manca la previsione di qualche mese")
        else:
            voce["errore_medio"] = round(sum(abs(r["realizzato"] - r["previsto"]) for r in prev) / h, 6)
            con_int = [r for r in prev if r["basso"] is not None and r["alto"] is not None]
            voce["copertura"] = (round(sum(r["basso"] <= r["realizzato"] <= r["alto"] for r in con_int)
                                       / len(con_int), 6) if len(con_int) == h else None)
            voce["esito"] = "calcolato"
        if base is None:
            voce["errore_base"] = None
            voce["nota_base"] = "mancano i 12 mesi prima della prova: base non calcolata"
        else:
            voce["errore_base"] = round(sum(abs(r["realizzato"] - base) for r in sotto) / h, 6)
        if voce.get("errore_medio") is not None and voce.get("errore_base") is not None:
            voce["batte_la_base"] = voce["errore_medio"] < voce["errore_base"]
        orizzonti[str(h)] = voce

    return {
        "taratura": [nome_mese(taratura[0]), nome_mese(taratura[1])],
        "prova": [nome_mese(prova[0]), nome_mese(prova[1])],
        "sguardo_al_futuro": any("sguardo al futuro" in e for e in errori),
        "errori": errori,
        "base_banale": None if base is None else round(base, 6),
        "orizzonti": orizzonti,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("file")
    ap.add_argument("--taratura", required=True, help="DA:A, per esempio 2011-01:2018-12")
    ap.add_argument("--prova", required=True, help="DA:A, per esempio 2019-01:2026-08")
    a = ap.parse_args(argv)
    try:
        righe = carica(a.file)
        esito = controlla(righe, intervallo(a.taratura), intervallo(a.prova))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(json.dumps({"errore": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(esito, ensure_ascii=False, indent=1))
    return 1 if esito["sguardo_al_futuro"] else 0


if __name__ == "__main__":
    sys.exit(main())
