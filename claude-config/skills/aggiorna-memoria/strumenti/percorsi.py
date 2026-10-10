#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Dove sta la memoria condivisa e quali sono gli spazi: una sola fonte, ~/.jarvis/percorsi.json.

Il file lo scrive strumenti/collega_memoria.py all'installazione. Forma:
  {"memoria": "~/Jarvis-Memoria", "repo": "~/Jarvis", "progetti": "~/Progetti"}
I progetti stanno in <repo>/command-center/spazi.json (fonte unica, scritta da strumenti/crea_progetto.py).
Ordine per la memoria: variabile JARVIS_MEMORIA (o JARVIS_VAULT), poi percorsi.json, poi ~/Jarvis-Memoria.

    python3 percorsi.py      stampa cosa ha trovato
"""
import json
import os
from pathlib import Path

CASA = Path.home()
FILE = CASA / ".jarvis" / "percorsi.json"
PREDEFINITA = CASA / "Jarvis-Memoria"


def _leggi():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _p(v):
    return Path(os.path.expanduser(str(v))) if v else None


def memoria():
    for v in (os.environ.get("JARVIS_MEMORIA"), os.environ.get("JARVIS_VAULT"), _leggi().get("memoria")):
        if v and str(v).strip():
            return _p(v.strip())
    return PREDEFINITA


def repo():
    return _p(os.environ.get("JARVIS_REPO") or _leggi().get("repo")) or CASA / "Jarvis"


def spazi():
    """[(nome dello spazio, [cartelle])]: dalla fonte unica dei progetti, <repo>/command-center/spazi.json
    (la scrivono crea_progetto.py e il Command Center); poi, per le installazioni vecchie, gli «spazi» di percorsi.json."""
    out = []
    f = os.environ.get("JARVIS_SPAZI") or (repo() / "command-center" / "spazi.json")
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    for s in (d.get("spazi") if isinstance(d, dict) else d) or []:
        if isinstance(s, dict) and s.get("nome"):
            out.append((s["nome"], [_p(p["cartella"]) for p in s.get("progetti", []) if p.get("cartella")]))
    for s in _leggi().get("spazi", []) or []:
        if isinstance(s, dict) and any(n == s.get("nome") for n, _ in out):
            continue
        if isinstance(s, dict) and s.get("nome"):
            out.append((s["nome"], [_p(c) for c in s.get("cartelle", []) if c]))
    return out


def progetti():
    """nome progetto -> (cartella del progetto, cartella delle note relativa alla memoria)."""
    out = {}
    for nome, cartelle in spazi():
        for c in cartelle:
            out[c.name] = (str(c), f"{nome}/{c.name}")
    return out


def spazio_di(cartella):
    """Lo spazio che contiene la cartella (o None)."""
    c = Path(cartella).expanduser().resolve()
    for nome, cartelle in spazi():
        for d in cartelle:
            try:
                d = d.resolve()
            except OSError:
                continue
            if c == d or d in c.parents:
                return nome, d
    return None


if __name__ == "__main__":
    print(f"file:     {FILE} ({'c' if FILE.is_file() else 'non c'}'è)")
    print(f"memoria:  {memoria()}")
    print(f"repo:     {repo()}")
    for nome, cartelle in spazi():
        print(f"spazio «{nome}»: " + ", ".join(map(str, cartelle)))
