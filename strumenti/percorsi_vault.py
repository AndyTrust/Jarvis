#!/usr/bin/env python3
"""Dove sono il vault «Jarvis Brain», la cartella OneDrive e il repo di Jarvis, su Mac e su VPS (2026-10-04).

Ordine per il vault:
  1. variabile JARVIS_VAULT, poi la chiave «memoria» di ~/.jarvis/percorsi.json (scelta all'installazione);
  2. ~/Library/CloudStorage/OneDrive/Jarvis Brain  (Mac; sulla VPS è la copia locale a due vie
     tenuta dal timer jarvis-vault-sync ogni 5 minuti: scrittura su disco locale, nessuna attesa di rete);
  3. /mnt/onedrive/Jarvis Brain  (VPS, mount rclone).
Se nessuno esiste si torna il percorso del Mac, così chi lo usa si comporta come prima.
Ordine per il repo: JARVIS_REPO, ~/Jarvis, /root/jarvis.

    python3 percorsi_vault.py      stampa cosa ha trovato
"""
import os
import sys
from pathlib import Path

CASA = Path.home()
OD_MAC = CASA / "Library/CloudStorage/OneDrive"
OD_VPS = Path("/mnt/onedrive")
NOME_VAULT = "Jarvis Brain"


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
    p = _env("JARVIS_VAULT") or _percorsi("memoria")
    if p:
        return p
    for od in (OD_MAC, OD_VPS):
        if (od / NOME_VAULT).is_dir():
            return od / NOME_VAULT
    return CASA / "Jarvis-Memoria"   # la memoria predefinita (strumenti/collega_memoria.py)


def onedrive():
    """La cartella OneDrive che contiene il vault scelto (per tradurre «OD/…» di spazi.json)."""
    v = vault()
    if v.name == NOME_VAULT:
        return v.parent
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
