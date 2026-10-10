"""Memoria continua del filo di chat (l'utente, 2026-10-01).

Il filo è l'uuid della sessione della pagina. Qui, per ogni filo, il pannello tiene:
  active_work    la domanda su cui il motore sta lavorando adesso
  pending_asks   le domande arrivate mentre il motore lavorava, in ordine, in sospeso
  fatte          le ultime domande chiuse (testo, esito, ora)
  interrotte     quelle rimaste a metà perché il pannello è ripartito

Ogni domanda nuova parte con in testa un piccolo stato del filo (intestazione), così la ripresa
del lavoro precedente è esplicita e non dipende dalla memoria di chi risponde. Le domande dello
stesso filo vanno una alla volta, in ordine di arrivo (Turni): la seconda non parte finché la
prima non ha scritto la sua sessione, quindi la riprende invece di partire da zero.

Il filo si azzera solo con un comando esplicito (vedi e_reset): «nuova conversazione» o «reset».
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

QUI = Path(__file__).resolve().parent
FILE = QUI / "conversazioni.json"
_LOCK = threading.RLock()
_TURNI = threading.Condition()
_CODE = {}                 # sessione -> [id domanda] in ordine di arrivo
MAX_FILI = 300
MAX_FATTE = 5
RESET = re.compile(r"^\s*/?(nuova\s+(conversazione|chat)|reset(\s+(conversazione|chat))?)\s*[.!]*\s*$", re.I)


def e_reset(testo):
    """True se il testo è, da solo, il comando esplicito per ripartire da zero."""
    return bool(RESET.match(testo or ""))


def _ora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _leggi():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}


def _scrivi(d):
    if len(d) > MAX_FILI:
        d = dict(sorted(d.items(), key=lambda kv: kv[1].get("ts", 0))[-MAX_FILI:])
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    os.replace(tmp, FILE)


def _filo(d, sessione):
    return d.setdefault(sessione, {"active_work": None, "pending_asks": [], "fatte": [], "interrotte": [], "ts": 0})


def _breve(testo, n=160):
    testo = " ".join((testo or "").split())
    return testo if len(testo) <= n else testo[:n - 1] + "…"


def accoda(sessione, ask_id, testo):
    """Registra la domanda come in sospeso e la mette in fila per il suo turno."""
    with _LOCK:
        d = _leggi()
        f = _filo(d, sessione)
        f["pending_asks"].append({"id": ask_id, "testo": _breve(testo), "ts": _ora()})
        f["ts"] = time.time()
        _scrivi(d)
    with _TURNI:
        _CODE.setdefault(sessione, []).append(ask_id)


def aspetta_turno(sessione, ask_id):
    """Blocca finché tutte le domande arrivate prima, nello stesso filo, non hanno finito."""
    with _TURNI:
        _TURNI.wait_for(lambda: _CODE.get(sessione, [None])[0] == ask_id)


def avvia(sessione, ask_id):
    with _LOCK:
        d = _leggi()
        f = _filo(d, sessione)
        for p in list(f["pending_asks"]):
            if p["id"] == ask_id:
                f["pending_asks"].remove(p)
                f["active_work"] = {**p, "da": _ora()}
        f["ts"] = time.time()
        _scrivi(d)


def chiudi(sessione, ask_id, ok):
    with _LOCK:
        d = _leggi()
        f = _filo(d, sessione)
        a = f.get("active_work")
        if a and a["id"] == ask_id:
            f["fatte"] = (f["fatte"] + [{"testo": a["testo"], "ok": bool(ok), "fine": _ora()}])[-MAX_FATTE:]
            f["active_work"] = None
        else:       # chiusa senza essere partita (errore prima dell'avvio): non resta in sospeso
            f["pending_asks"] = [p for p in f["pending_asks"] if p["id"] != ask_id]
        f["ts"] = time.time()
        _scrivi(d)
    with _TURNI:
        q = _CODE.get(sessione, [])
        if ask_id in q:
            q.remove(ask_id)
        if not q:
            _CODE.pop(sessione, None)
        _TURNI.notify_all()


def azzera(sessione):
    """Comando esplicito di reset: il filo e il suo stato spariscono."""
    with _LOCK:
        d = _leggi()
        d.pop(sessione, None)
        _scrivi(d)


def riavvio():
    """All'avvio del pannello i thread che lavoravano non ci sono più: quello che era in corso o
    in fila diventa «interrotta», così la prossima domanda del filo lo sa e può riprenderlo."""
    with _LOCK:
        d = _leggi()
        for f in d.values():
            rimaste = ([f["active_work"]] if f.get("active_work") else []) + f.get("pending_asks", [])
            if rimaste:
                f["interrotte"] = (f.get("interrotte", []) + rimaste)[-MAX_FATTE:]
            f["active_work"], f["pending_asks"] = None, []
        _scrivi(d)


def stato(sessione):
    with _LOCK:
        return dict(_leggi().get(sessione) or {})


def intestazione(sessione, ask_id):
    """Lo stato del filo da mettere in testa alla domanda. '' se il filo è nuovo e non c'è altro."""
    f = stato(sessione)
    righe = []
    if f.get("active_work") and f["active_work"]["id"] != ask_id:
        righe.append(f"Lavoro in corso: {f['active_work']['testo']} (dalle {f['active_work']['da']})")
    altre = [p for p in f.get("pending_asks", []) if p["id"] != ask_id]
    if altre:
        righe.append("Domande in sospeso, dopo questa: " + " | ".join(f"{i}) {p['testo']}" for i, p in enumerate(altre, 1)))
    if f.get("interrotte"):
        righe.append("Rimaste a metà per un riavvio del pannello, da riprendere se ancora servono: "
                     + " | ".join(p["testo"] for p in f["interrotte"]))
    if f.get("fatte"):
        righe.append("Già trattato in questo filo: " + " | ".join(
            f"{x['testo']} ({'ok' if x['ok'] else 'in errore'})" for x in f["fatte"]))
    if not righe:
        return ""
    return (f"[Stato del filo · {_ora()}]\n" + "\n".join(righe) +
            "\n(È la stessa conversazione di prima: riprendi da dove eravamo, non ripartire da zero. "
            "Rispondi a questa domanda e tieni presenti quelle in sospeso.)\n\n")


def pulisci_interrotte(sessione):
    """Dopo che la domanda successiva le ha viste, le interrotte non si ripetono."""
    with _LOCK:
        d = _leggi()
        if sessione in d and d[sessione].get("interrotte"):
            d[sessione]["interrotte"] = []
            _scrivi(d)
