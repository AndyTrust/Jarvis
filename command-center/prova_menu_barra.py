#!/usr/bin/env python3
"""Prova di menu_barra.py (la barra in alto del Command Center, 2026-10-04) in una cartella temporanea.

    python3 command-center/prova_menu_barra.py      esito 0 = tutto passa, 1 = qualcosa no

Non tocca mai ~/.locale-onedrive/jarvis-cc/menu-barra.json: usa CC_MENU_DIR su una cartella temporanea.
"""
import importlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

QUI = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="prova-menu-barra-"))
os.environ["CC_MENU_DIR"] = str(TMP / "jarvis-cc")
sys.path.insert(0, str(QUI))
import menu_barra as M  # noqa: E402

importlib.reload(M)
esiti = []


def ok(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("✅" if cond else "❌"), nome, ("· " + str(dettaglio)) if dettaglio and not cond else "")


def errore(dati, parola):
    try:
        M.scrivi(dati)
    except ValueError as e:
        return parola in str(e)
    return False


F = TMP / "jarvis-cc" / "menu-barra.json"
try:
    d = M.leggi()
    ok("file assente: predefinito", d["predefinito"] is True and d["in_barra"][:2] == ["chat", "lavagna"], d)
    ok("predefinito: in_barra dentro ordine", set(d["in_barra"]) <= set(d["ordine"]))
    ok("predefinito: Altro con scadenze … terminale", d["ordine"][7:] == M.IN_ALTRO_PARTENZA, d["ordine"])

    r = M.scrivi({"ordine": ["lavagna", "chat", "home", "memoria"], "in_barra": ["chat", "lavagna"]})
    ok("scrivi: torna validato", r == {"ordine": ["lavagna", "chat", "home", "memoria"], "in_barra": ["lavagna", "chat"],
                                       "predefinito": False}, r)
    ok("scrivi: in_barra segue l'ordine", r["in_barra"] == ["lavagna", "chat"])
    ok("file creato 0600", F.exists() and stat.S_IMODE(F.stat().st_mode) == 0o600, oct(stat.S_IMODE(F.stat().st_mode)))
    ok("nessun file temporaneo rimasto", [p.name for p in F.parent.iterdir()] == ["menu-barra.json"], list(F.parent.iterdir()))
    d = M.leggi()
    ok("leggi dopo scrivi", d["ordine"][0] == "lavagna" and d["predefinito"] is False, d)

    ok("rifiuta: non oggetto", errore(["chat"], "oggetto"))
    ok("rifiuta: ordine mancante", errore({"in_barra": []}, "ordine"))
    ok("rifiuta: ordine non lista", errore({"ordine": "chat", "in_barra": []}, "lista"))
    ok("rifiuta: maiuscole", errore({"ordine": ["Chat"], "in_barra": []}, "non valida"))
    ok("rifiuta: id troppo lungo", errore({"ordine": ["a" * 31], "in_barra": []}, "non valida"))
    ok("rifiuta: id vuoto", errore({"ordine": [""], "in_barra": []}, "non valida"))
    ok("rifiuta: id non stringa", errore({"ordine": [3], "in_barra": []}, "non valida"))
    ok("rifiuta: caratteri strani", errore({"ordine": ["<script>"], "in_barra": []}, "non valida"))
    ok("rifiuta: doppioni", errore({"ordine": ["chat", "chat"], "in_barra": []}, "ripetuta"))
    ok("rifiuta: più di 40", errore({"ordine": [f"v{i}" for i in range(41)], "in_barra": []}, "al massimo 40"))
    ok("accetta: 40 esatte", M.scrivi({"ordine": [f"v{i}" for i in range(40)], "in_barra": ["v0"]})["in_barra"] == ["v0"])
    ok("rifiuta: in_barra fuori da ordine", errore({"ordine": ["chat"], "in_barra": ["lavagna"]}, "non stanno"))
    ok("un rifiuto non cambia il file", M.leggi()["ordine"][0] == "v0")

    F.write_text("{ rotto")
    d = M.leggi()
    ok("file rotto: predefinito", d["predefinito"] is True and d["ordine"][0] == "chat", d)
    F.write_text('{"ordine": ["chat", "chat"], "in_barra": []}')
    ok("file con doppioni: predefinito", M.leggi()["predefinito"] is True)
    F.write_text('[1, 2]')
    ok("file non oggetto: predefinito", M.leggi()["predefinito"] is True)
    r = M.scrivi({"ordine": ["chat"], "in_barra": []})
    ok("riscrive sopra un file rotto, 0600", r["ordine"] == ["chat"] and stat.S_IMODE(F.stat().st_mode) == 0o600)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{sum(esiti)}/{len(esiti)} passano")
sys.exit(0 if all(esiti) else 1)
