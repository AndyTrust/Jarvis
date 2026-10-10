"""La barra in alto del Command Center: ordine delle voci e quali stanno in «Altro» (l'utente, 2026-10-04).

Dati: ~/.locale-onedrive/jarvis-cc/menu-barra.json (0600, scrittura atomica, fuori da git e da OneDrive).
CC_MENU_DIR cambia la cartella (per le prove). Solo libreria standard.

    leggi()       -> {"ordine": [ids], "in_barra": [ids], "predefinito": bool}
    scrivi(dati)  -> lo stesso dizionario, validato e salvato; ValueError con un messaggio chiaro se non va

«ordine» è l'ordine di tutte le voci conosciute; «in_barra» quelle che stanno nella barra (le altre vanno in «Altro»).
Le voci che la pagina trova e qui non ci sono finiscono in «Altro», in coda: lo decide barra.js.
File assente o rotto: valgono le voci di partenza (predefinito = True).
"""
import json
import os
import re
import tempfile
from pathlib import Path

ID = re.compile(r"[a-z0-9-]{1,30}")
MAX_VOCI = 40
NOME_FILE = "menu-barra.json"

IN_BARRA_PARTENZA = ["chat", "lavagna", "agenti", "home", "missioni", "incarichi", "piani"]
# 2026-10-05 (l'utente): Server, VPS, Terminale e Schermo uniti in «computer», Tecnico dentro «telefono» (barra.js mappa i file vecchi)
# 2026-10-05 (l'utente): «routine» (pagina Routine, routine.js) subito dopo «scadenze»
IN_ALTRO_PARTENZA = ["scadenze", "routine", "registro", "memoria", "connessioni", "computer", "telefono"]


def _file():
    cartella = os.environ.get("CC_MENU_DIR") or str(Path.home() / ".locale-onedrive" / "jarvis-cc")
    return Path(cartella) / NOME_FILE


def predefinito():
    return {"ordine": IN_BARRA_PARTENZA + IN_ALTRO_PARTENZA, "in_barra": list(IN_BARRA_PARTENZA), "predefinito": True}


def _lista(dati, chiave):
    v = dati.get(chiave)
    if not isinstance(v, list):
        raise ValueError(f"«{chiave}» deve essere una lista di voci")
    if len(v) > MAX_VOCI:
        raise ValueError(f"«{chiave}» ha {len(v)} voci: al massimo {MAX_VOCI}")
    visti = set()
    for x in v:
        if not isinstance(x, str) or not ID.fullmatch(x):
            raise ValueError(f"voce non valida in «{chiave}»: {str(x)[:40]!r} (solo a-z, 0-9 e trattino, da 1 a 30 caratteri)")
        if x in visti:
            raise ValueError(f"voce ripetuta in «{chiave}»: {x}")
        visti.add(x)
    return list(v)


def valida(dati):
    if not isinstance(dati, dict):
        raise ValueError("servono «ordine» e «in_barra» in un oggetto JSON")
    ordine = _lista(dati, "ordine")
    in_barra = _lista(dati, "in_barra")
    fuori = [x for x in in_barra if x not in ordine]
    if fuori:
        raise ValueError(f"in «in_barra» ci sono voci che non stanno in «ordine»: {', '.join(fuori[:5])}")
    # in_barra segue sempre l'ordine generale: una sola fonte per la posizione
    in_barra = [x for x in ordine if x in set(in_barra)]
    return {"ordine": ordine, "in_barra": in_barra}


def leggi():
    f = _file()
    try:
        dati = valida(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return predefinito()
    dati["predefinito"] = False
    return dati


def scrivi(dati):
    pulito = valida(dati)
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{f.name}.", dir=str(f.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(pulito, h, ensure_ascii=False, indent=1)
            h.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dict(pulito, predefinito=False)
