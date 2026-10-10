#!/usr/bin/env python3
"""Eliminazione in blocco nel Vault: tutta una categoria, una sezione o un tag.

Elimina tutte le voci di una categoria (tipo: Accessi web, Carte, PIN, Ambiente, Note), di una sezione (con le sue
sottosezioni, es. «Da riordinare» o «Altro / Social») o di un tag (es. «chrome»). Regole per non fare danni:
- conferma col NUMERO esatto di voci che la pagina ha mostrato: se nel frattempo è cambiato, non elimina niente;
- backup cifrato del Vault PRIMA;
- ogni voce diventa «eliminata» con una versione nuova (lo storico resta) e il blocco ha un numero di lotto:
  «Annulla l'eliminazione» rimette tutte le voci del lotto (anche dopo, dal menu ⋯, finché il lotto è in elenco);
- il file .env.jarvis non si tocca (sola lettura): una variabile eliminata dal Vault risulta «nuova nel file» e una
  nuova importazione la riporterebbe.
Restituisce solo conteggi. Usato da vault_cc.gestisci (rotte /api/vault/gruppo/*).
"""
from __future__ import annotations

import secrets
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
MAX_LOTTI = 30


def _vault():
    m = sys.modules.get("vault_cc")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("vault_cc", QUI / "vault_cc.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["vault_cc"] = m
        spec.loader.exec_module(m)
    return m


def _filtro(corpo):
    V = _vault()
    f = {k: str(corpo.get(k) or "").strip() for k in ("tipo", "sezione", "tag") if str(corpo.get(k) or "").strip()}
    if len(f) != 1:
        raise V.ErroreVault("Scegli una sola cosa da svuotare: una categoria, una sezione o un tag.")
    if "tipo" in f and f["tipo"] not in V.TIPI:
        raise V.ErroreVault("Categoria sconosciuta.")
    return f


def _combacia(v, f):
    if "tipo" in f:
        return v["tipo"] == f["tipo"]
    if "sezione" in f:
        s = v.get("sezione", "")
        return s == f["sezione"] or s.startswith(f["sezione"] + " / ")
    return f["tag"] in v.get("tag", [])


def conta(vault, chiavi, corpo):
    f = _filtro(corpo)
    with vault.mutex:
        d = vault._leggi()
        n = sum(1 for _r, v in vault._tutte(d, chiavi) if _combacia(v, f))
    return {"filtro": f, "voci": n}


def elimina(vault, chiavi, corpo):
    V = _vault()
    f = _filtro(corpo)
    with vault.mutex:
        d = vault._leggi()
        scelte = [(rec, v) for rec, v in vault._tutte(d, chiavi) if _combacia(v, f)]
        if not isinstance(corpo.get("conferma"), int) or corpo["conferma"] != len(scelte):
            raise V.ErroreVault(f"Conferma con il numero esatto di voci ({len(scelte)}): il numero è cambiato o manca.", 409,
                                voci=len(scelte))
        if not scelte:
            return {"eliminate": 0, "lotto": None}
        vault._backup_file(f"prima-eliminazione-{time.strftime('%Y%m%d-%H%M%S')}")
        lotto = "l_" + secrets.token_hex(6)
        for rec, v in scelte:
            v["eliminata"] = True
            v["lotto"] = lotto
            vault._nuova_versione(d, chiavi, rec, v, "eliminazione")
        imp = vault._impostazioni(d, chiavi)
        lotti = imp.setdefault("lotti_eliminati", [])
        lotti.append({"lotto": lotto, "quando": V._ora(), "filtro": f, "voci": [rec["id"] for rec, _v in scelte]})
        del lotti[:-MAX_LOTTI]
        if corpo.get("togli_sezione") and "sezione" in f:
            imp["sezioni"] = [s for s in imp["sezioni"] if s != f["sezione"] and not s.startswith(f["sezione"] + " / ")]
        vault._scrivi_impostazioni(d, chiavi, imp)
        vault._salva(d)
    vault.registra("elimina-gruppo", campo=f"{len(scelte)} voci · lotto {lotto}")
    return {"eliminate": len(scelte), "lotto": lotto, "backup_prima": True}


def ripristina(vault, chiavi, corpo):
    """Rimette le voci di un lotto che sono ancora eliminate da quel lotto (una voce ripresa o cambiata dopo resta com'è)."""
    V = _vault()
    lotto = str(corpo.get("lotto") or "")
    with vault.mutex:
        d = vault._leggi()
        imp = vault._impostazioni(d, chiavi)
        voce_lotto = next((x for x in imp.get("lotti_eliminati", []) if x["lotto"] == lotto), None)
        if not voce_lotto:
            raise V.ErroreVault("Eliminazione non trovata (già annullata o troppo vecchia).", 404)
        n = 0
        for id_voce in voce_lotto["voci"]:
            rec = d["voci"].get(id_voce)
            if not rec:
                continue
            v = vault._apri(chiavi, rec)
            if v.get("eliminata") and v.get("lotto") == lotto:
                v["eliminata"] = False
                v.pop("lotto", None)
                vault._nuova_versione(d, chiavi, rec, v, "ripristino")
                if v.get("sezione") and v["sezione"] not in imp["sezioni"]:
                    imp["sezioni"].append(v["sezione"])
                n += 1
        imp["lotti_eliminati"] = [x for x in imp["lotti_eliminati"] if x["lotto"] != lotto]
        vault._scrivi_impostazioni(d, chiavi, imp)
        vault._salva(d)
    vault.registra("ripristina-gruppo", campo=f"{n} voci · lotto {lotto}")
    return {"ripristinate": n}


def lotti(vault, chiavi):
    with vault.mutex:
        imp = vault._impostazioni(vault._leggi(), chiavi)
    return {"lotti": [{"lotto": x["lotto"], "quando": x["quando"], "filtro": x["filtro"], "voci": len(x["voci"])}
                      for x in reversed(imp.get("lotti_eliminati", []))]}


def gestisci(metodo, percorso, query, corpo, vault, chiavi):
    if metodo == "GET" and percorso == "/api/vault/gruppo/conta":
        return 200, conta(vault, chiavi, {k: (v or [""])[0] for k, v in query.items()})
    if metodo == "GET" and percorso == "/api/vault/gruppo/lotti":
        return 200, lotti(vault, chiavi)
    if metodo == "POST" and percorso == "/api/vault/gruppo/elimina":
        return 200, elimina(vault, chiavi, corpo)
    if metodo == "POST" and percorso == "/api/vault/gruppo/ripristina":
        return 200, ripristina(vault, chiavi, corpo)
    return 404, {"errore": "non trovato"}
