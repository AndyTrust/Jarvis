#!/usr/bin/env python3
"""Dove sono la memoria condivisa, la cartella OneDrive (se c'è) e il repo di Jarvis, su Mac e su VPS.

Ordine per la memoria: variabile JARVIS_MEMORIA o JARVIS_VAULT, poi la chiave «memoria» di ~/.jarvis/percorsi.json
(scelta all'installazione), poi ~/Jarvis-Memoria (predefinita).
Ordine per il repo: JARVIS_REPO, chiave «repo» di percorsi.json, ~/Jarvis, /root/jarvis.

    python3 percorsi_vault.py      stampa cosa ha trovato
"""
import os
import sys
from pathlib import Path

CASA = Path.home()
OD_MAC = CASA / "Library/CloudStorage/OneDrive"
OD_VPS = Path("/mnt/onedrive")


def _env(nome):
    v = os.environ.get(nome, "").strip()
    return Path(os.path.expanduser(v)) if v else None


def radici_onedrive():
    """Le cartelle OneDrive che esistono su questa macchina, in ordine di preferenza."""
    out = []
    for p in (_env("JARVIS_OD"), OD_MAC, OD_VPS):
        if p and p.is_dir() and p not in out:
            out.append(p)
    return out


PERCORSI = CASA / ".jarvis" / "percorsi.json"   # lo scrive strumenti/collega_memoria.py all'installazione


def _percorsi(chiave):
    """Il percorso scelto all'installazione (~/.jarvis/percorsi.json), se c'è."""
    try:
        import json
        v = json.loads(PERCORSI.read_text(encoding="utf-8")).get(chiave)
        return Path(os.path.expanduser(v)) if v else None
    except (OSError, ValueError):
        return None


def vault():
    return _env("JARVIS_MEMORIA") or _env("JARVIS_VAULT") or _percorsi("memoria") or CASA / "Jarvis-Memoria"


def onedrive():
    """La cartella OneDrive di questa macchina (per tradurre «OD/…» in spazi.json vecchi)."""
    r = radici_onedrive()
    return r[0] if r else OD_MAC


def repo():
    for p in (_env("JARVIS_REPO"), _percorsi("repo"), CASA / "Jarvis", CASA / "jarvis", Path("/root/jarvis")):
        if p and (p / "strumenti").is_dir():
            return p
    return CASA / "Jarvis"


def macchina():
    """«mac» sul Mac dell'utente, «vps» altrove (JARVIS_MACCHINA per forzarlo nelle prove)."""
    m = os.environ.get("JARVIS_MACCHINA", "").strip().lower()
    if m:
        return m
    return "mac" if sys.platform == "darwin" else "vps"


if __name__ == "__main__":
    print(f"macchina: {macchina()}\nvault:    {vault()}\nonedrive: {onedrive()}\nrepo:     {repo()}\n"
          f"radici OneDrive presenti: {', '.join(map(str, radici_onedrive())) or 'nessuna'}")
