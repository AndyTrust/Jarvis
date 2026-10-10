#!/usr/bin/env python3
"""L'elenco dei repository GitHub dell'utente per il Command Center (01/10/2026).

Fonti: `gh repo list` (i proprietari del registro, o l'utente di gh; in cache 5 minuti) più strumenti/repo-collegati.json
(chiavi «repo» = linea unica, «altri» = repo personali). Solo lettura: niente fetch, niente push.
Gruppi: jarvis (Privato e derivati), prodotti (in vendita), condiviso (repo in comune con un altro PC), altri.
"""
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
REGISTRO = QUI.parent / "strumenti" / "repo-collegati.json"
DURATA = 300
_cache = {"quando": 0.0, "dati": None}
_lock = threading.Lock()


def _gh(proprietario=None):   # senza proprietario: i repo dell'utente con cui gh è collegato
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"   # sotto launchd il PATH è corto
    p = subprocess.run([gh, "repo", "list", *([proprietario] if proprietario else []), "--limit", "100", "--json",
                        "name,visibility,pushedAt,description,url"], capture_output=True, text=True, timeout=25)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[:200])
    return json.loads(p.stdout or "[]")


def _git(cartella, *a):
    p = subprocess.run(["git", "-C", str(cartella), *a], capture_output=True, text=True, timeout=10)
    return p.returncode, p.stdout.strip()


def _locale(cartella):
    """Stato del clone: avanti/indietro rispetto all'ultimo fetch e file modificati."""
    if not cartella:
        return None
    c = Path(cartella.replace("~", str(Path.home()), 1))
    if not (c / ".git").exists():
        return None
    _, mod = _git(c, "status", "--porcelain")
    rc, ab = _git(c, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    avanti = indietro = None
    if rc == 0 and ab:
        avanti, indietro = (int(x) for x in ab.split()[:2])
    return {"modifiche": len(mod.splitlines()) if mod else 0, "avanti": avanti, "indietro": indietro}


def _riga(r, gruppo, tipo, gh_per_nome, cartella, nota=""):
    g = gh_per_nome.get(r.lower(), {})
    return {"nome": r, "gruppo": gruppo, "tipo": tipo, "visibilita": (g.get("visibility") or "?").lower(),
            "push": g.get("pushedAt", ""), "url": g.get("url", ""), "descrizione": g.get("description") or "",
            "nota": nota, "locale": _locale(cartella)}


def _costruisci():
    reg = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else {}   # su un PC senza registro si vede solo GitHub
    errori, gh = [], {}
    for o in reg.get("proprietari") or [None]:
        try:
            for x in _gh(o):
                gh[x["name"].lower()] = x
        except Exception as e:   # gh assente, rete giù, non loggato: il resto si vede comunque
            errori.append(f"{o or 'GitHub'}: {e}")
    righe, noti = [], set()
    for r in reg.get("repo", {}).values():
        gruppo = "prodotti" if r["tipo"] == "prodotto" else "jarvis"
        righe.append(_riga(r["nome"], gruppo, r["tipo"], gh, r.get("cartella"), r.get("nota", "")))
        noti.add(r["nome"].lower())
    for r in reg.get("altri", {}).values():
        righe.append(_riga(r["nome"], r.get("gruppo", "altri"), r.get("tipo", "personale"), gh, r.get("cartella"), r.get("nota", "")))
        noti.add(r["nome"].lower())
    for n, x in gh.items():   # un repo nuovo su GitHub che il registro non conosce si vede lo stesso
        if n not in noti:
            righe.append(_riga(x["name"], "altri", "da classificare", gh, ""))
    return {"repo": righe, "errori": errori, "aggiornato": time.strftime("%Y-%m-%d %H:%M")}


def elenco(forza=False):
    with _lock:
        if forza or not _cache["dati"] or time.time() - _cache["quando"] > DURATA:
            _cache["dati"] = _costruisci()
            _cache["quando"] = time.time()
        return _cache["dati"]


if __name__ == "__main__":
    d = elenco(True)
    for r in d["repo"]:
        print(f'{r["gruppo"]:9} {r["nome"]:32} {r["visibilita"]:8} {r["tipo"]:15} {r["push"][:16]} {r["locale"]}')
    print(d["errori"])
