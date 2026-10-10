"""L'aspetto del Command Center uguale su ogni dispositivo (l'utente, 2026-10-04): tema colore e avatar.
Prima stavano solo nel localStorage di ogni browser (temi.js «cc.tema», dots.js «cc.avatar»), quindi telefono e computer
potevano avere un aspetto diverso. Ora la scelta sta qui e ogni dispositivo la applica. Solo libreria standard."""
import json
import os
import tempfile
import time
from pathlib import Path

TEMI = ("scuro", "nero", "chiaro", "claude", "auto")
AVATAR = ("dots", "volti", "iniziali")
CARTELLA = Path(os.environ.get("CC_ASPETTO_DIR", Path.home() / ".locale-onedrive" / "jarvis-cc"))
FILE = CARTELLA / "aspetto.json"


def _scrivi(dati):
    CARTELLA.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".aspetto.", dir=str(CARTELLA))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(dati, h, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def leggi():
    """{tema, avatar, fermi, v, predefinito}. File assente o rotto = predefinito (nessuna scelta condivisa ancora)."""
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        if d.get("tema") in TEMI and d.get("avatar") in AVATAR and isinstance(d.get("fermi"), bool):
            return {"tema": d["tema"], "avatar": d["avatar"], "fermi": d["fermi"], "v": int(d.get("v", 1)), "predefinito": False}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return {"tema": "scuro", "avatar": "dots", "fermi": False, "v": 0, "predefinito": True}


def scrivi(dati):
    """Unisce i campi dati (tema, avatar, fermi) a quelli attuali e salva. ValueError con messaggio chiaro se non valido."""
    if not isinstance(dati, dict) or not dati or set(dati) - {"tema", "avatar", "fermi"}:
        raise ValueError("campi ammessi: tema, avatar, fermi")
    if "tema" in dati and dati["tema"] not in TEMI:
        raise ValueError("tema: " + ", ".join(TEMI))
    if "avatar" in dati and dati["avatar"] not in AVATAR:
        raise ValueError("avatar: " + ", ".join(AVATAR))
    if "fermi" in dati and not isinstance(dati["fermi"], bool):
        raise ValueError("fermi: true o false")
    cur = leggi()
    if not cur["predefinito"] and all(cur[k] == dati[k] for k in dati):
        return cur                      # nessun cambio: niente nuova versione (le pagine che applicano un valore non lo rimandano)
    nuovo = {"tema": dati.get("tema", cur["tema"]), "avatar": dati.get("avatar", cur["avatar"]),
             "fermi": dati.get("fermi", cur["fermi"]), "v": cur["v"] + 1, "aggiornato": int(time.time())}
    _scrivi(nuovo)
    return leggi()
