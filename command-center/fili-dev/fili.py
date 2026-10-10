"""Archivio dei fili di chat del Command Center (2026-10-03, cc-fili-opus).

L'utente: «la lavagna non fa aggiornare la chat». Fino a oggi la conversazione stava solo nel
localStorage di ogni browser: una chat aperta sul Mac non si vedeva sul telefono, e una risposta
arrivata a scheda chiusa restava solo dove era partita la domanda. Da qui il server tiene la sua
copia di ogni filo e la pagina la unisce alla sua (static/fili.js).

Un filo = la sessione uuid della pagina (THREADS[k].sessione in app.js). Un file JSON per filo:

    <cartella>/<uuid>.json      0600, cartella 0700
    {"formato": 1, "sessione", "interlocutore", "titolo", "creato", "aggiornato", "versione",
     "in_attesa": [id lavoro], "messaggi": [{id, chi, testo, ts, ora, errore?, motore?, box?,
     troncato?, log?}]}

Cartella: CC_FILI_DIR, altrimenti ~/.locale-onedrive/jarvis-cc/fili (fuori da git e da OneDrive).

Chi scrive: SOLO il server. domanda() quando arriva una «chiedi» dalla pagina, risposta() quando il
lavoro finisce, reset() per «nuova conversazione», riavvio() all'avvio (le attese rimaste a metà
diventano «Risposta persa», come dice la pagina). La pagina legge e basta (GET /api/fili).

Id stabili: q-<id lavoro> la domanda, a-<id lavoro> la risposta (anche quella persa), r-<sessione>
il messaggio del reset. Riscrivere lo stesso id aggiorna il messaggio, non ne aggiunge un altro.

Limiti: testo di un messaggio fino a MAX_TESTO caratteri (oltre si tronca e si dice in quale log
sta il testo intero), MAX_MESSAGGI per filo, MAX_BYTE_FILO per file, MAX_FILI file in tutto (i più
vecchi escono). I token riconoscibili (sk-ant-, ghp_, Bearer…) e il token della pagina si
mascherano prima di scrivere. Solo libreria standard; su Windows il lock è solo fra thread.
"""
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import fcntl          # Mac e Linux: lock anche fra processi
except ImportError:       # Windows (il PC dell'amministrazione): basta il lock fra thread
    fcntl = None

FORMATO = 1
MAX_TESTO = 40000          # come la coda del log che /api/lavoro/<id> dà alla pagina
MAX_MESSAGGI = 400
MAX_BYTE_FILO = 2_000_000
MAX_FILI = 500
MAX_TITOLO = 80
MAX_INTERLOCUTORE = 160
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ID_LAVORO_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
LOG_RE = re.compile(r"[A-Za-z0-9_.-]{1,120}")
PERSA = "Risposta persa: il Command Center è ripartito. Rimanda la domanda."

AVVISA = None              # funzione(dati) che il server imposta: evento «fili» sul flusso
_LOCK = threading.RLock()
_CACHE = {}                # nome file -> (mtime_ns, dimensione, riassunto)
_SEGRETI_EXTRA = []        # il token della pagina (nascondi_anche)

_SEGRETI = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"),
]


def nascondi_anche(segreto):
    """Un segreto in più da mascherare (il server passa il suo TOKEN)."""
    if segreto and len(segreto) >= 8 and segreto not in _SEGRETI_EXTRA:
        _SEGRETI_EXTRA.append(segreto)


def pulisci(testo):
    testo = str(testo or "")
    for s in _SEGRETI_EXTRA:
        testo = testo.replace(s, "[nascosto]")
    for r in _SEGRETI:
        testo = r.sub(lambda m: (m.group(1) + " [nascosto]") if m.lastindex else "[nascosto]", testo)
    return testo


def cartella():
    base = os.environ.get("CC_FILI_DIR") or str(Path.home() / ".locale-onedrive" / "jarvis-cc" / "fili")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
    return p


def valida_sessione(s):
    return isinstance(s, str) and bool(UUID_RE.fullmatch(s))


def _file(sessione):
    if not valida_sessione(sessione):
        raise ValueError("sessione non valida")
    return cartella() / f"{sessione}.json"


class _Blocco:
    """Lock fra thread (RLock) e, dove c'è fcntl, fra processi (flock su .lock)."""

    def __enter__(self):
        _LOCK.acquire()
        self.fd = None
        if fcntl:
            try:
                self.fd = os.open(str(cartella() / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
                fcntl.flock(self.fd, fcntl.LOCK_EX)
            except OSError:
                if self.fd is not None:
                    os.close(self.fd)
                self.fd = None
        return self

    def __exit__(self, *a):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
        _LOCK.release()


def _ora(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _leggi_file(f):
    try:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("messaggi"), list) or not valida_sessione(d.get("sessione")):
        return None
    return d


def _scrivi_file(f, d):
    testo = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    fd, tmp = tempfile.mkstemp(prefix=".filo-", suffix=".tmp", dir=str(f.parent))
    try:
        os.fchmod(fd, 0o600) if hasattr(os, "fchmod") else None
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(testo)
            h.flush()
            os.fsync(h.fileno())
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _nuovo(sessione, interlocutore, ts):
    return {"formato": FORMATO, "sessione": sessione, "interlocutore": interlocutore, "titolo": "",
            "creato": ts, "aggiornato": ts, "versione": 0, "in_attesa": [], "messaggi": []}


def _testo_limitato(testo, log_nome=""):
    """(testo, troncato): oltre MAX_TESTO si tiene la testa e si dice dove sta il resto."""
    testo = pulisci(testo)
    if len(testo) <= MAX_TESTO:
        return testo, False
    dove = f" Il testo intero è nel log lavori/{log_nome}." if log_nome else ""
    nota = f"\n\n… (risposta troncata a {MAX_TESTO} caratteri su {len(testo)}.{dove})"
    return testo[:MAX_TESTO - len(nota)] + nota, True


def _riassunto(d):
    ultimo = d["messaggi"][-1] if d["messaggi"] else None
    return {"sessione": d["sessione"], "interlocutore": d.get("interlocutore") or "", "titolo": d.get("titolo") or "",
            "creato": d.get("creato"), "aggiornato": d.get("aggiornato"), "versione": d.get("versione", 0),
            "messaggi": len(d["messaggi"]), "attesa": (d.get("in_attesa") or [None])[-1],
            "ultimo": ({"chi": ultimo["chi"], "testo": ultimo["testo"][:120], "errore": bool(ultimo.get("errore"))}
                       if ultimo else None)}


def _limita(d):
    if len(d["messaggi"]) > MAX_MESSAGGI:
        d["messaggi"] = d["messaggi"][-MAX_MESSAGGI:]
    while len(d["messaggi"]) > 1 and len(json.dumps(d, ensure_ascii=False).encode()) > MAX_BYTE_FILO:
        d["messaggi"] = d["messaggi"][max(1, len(d["messaggi"]) // 10):]


def _pota():
    """Oltre MAX_FILI file si tolgono i fili aggiornati meno di recente (per data del file)."""
    fili = sorted(cartella().glob("*.json"), key=lambda f: f.stat().st_mtime)
    for f in fili[:max(0, len(fili) - MAX_FILI)]:
        try:
            f.unlink()
        except OSError:
            pass
        _CACHE.pop(f.name, None)


def _cambia(sessione, interlocutore, fn, ts=None):
    """Legge (o crea) il filo, applica fn(d) e lo riscrive con versione + 1. Torna il riassunto."""
    ts = time.time() if ts is None else ts
    with _Blocco():
        f = _file(sessione)
        d = _leggi_file(f) if f.exists() else None
        nuovo = d is None
        if nuovo:
            d = _nuovo(sessione, interlocutore, ts)
        if interlocutore and not d.get("interlocutore"):
            d["interlocutore"] = interlocutore
        if fn(d) is False:
            return _riassunto(d)
        d["aggiornato"] = max(ts, d.get("aggiornato") or 0)
        d["versione"] = int(d.get("versione") or 0) + 1
        _limita(d)
        _scrivi_file(f, d)
        if nuovo:
            _pota()
        r = _riassunto(d)
    if AVVISA:
        try:
            AVVISA({"sessione": r["sessione"], "interlocutore": r["interlocutore"], "versione": r["versione"],
                    "aggiornato": r["aggiornato"]})
        except Exception:  # noqa: BLE001  (l'avviso non deve mai fermare la chat)
            pass
    return r


def _metti(d, msg):
    """Aggiunge il messaggio, o sostituisce quello con lo stesso id (mai doppioni)."""
    for i, m in enumerate(d["messaggi"]):
        if m.get("id") == msg["id"]:
            d["messaggi"][i] = {**m, **msg, "ts": m.get("ts", msg["ts"]), "ora": m.get("ora", msg["ora"])}
            return
    d["messaggi"].append(msg)


def _interlocutore(x):
    x = str(x or "").strip()
    return "".join(c for c in x if c.isprintable())[:MAX_INTERLOCUTORE] or "jarvis"


def domanda(sessione, interlocutore, testo, lavoro_id, box="", motore="", ts=None):
    if not ID_LAVORO_RE.fullmatch(str(lavoro_id or "")):
        raise ValueError("id lavoro non valido")
    ts = time.time() if ts is None else ts
    t, tronc = _testo_limitato(testo)

    def fn(d):
        msg = {"id": f"q-{lavoro_id}", "chi": "io", "testo": t, "ts": ts, "ora": _ora(ts), "lavoro": lavoro_id}
        if box:
            msg["box"] = str(box)[:80]
        if tronc:
            msg["troncato"] = True
        _metti(d, msg)
        if not d.get("titolo"):
            d["titolo"] = " ".join(t.split())[:MAX_TITOLO]
        if not any(m.get("id") == f"a-{lavoro_id}" for m in d["messaggi"]) and lavoro_id not in d["in_attesa"]:
            d["in_attesa"].append(lavoro_id)
        d["motore"] = motore or d.get("motore") or ""
    return _cambia(sessione, _interlocutore(interlocutore), fn, ts)


def risposta(sessione, lavoro_id, testo, ok, motore="", log_nome="", ts=None, interlocutore=""):
    if not ID_LAVORO_RE.fullmatch(str(lavoro_id or "")):
        raise ValueError("id lavoro non valido")
    log_nome = log_nome if LOG_RE.fullmatch(log_nome or "") else ""
    ts = time.time() if ts is None else ts
    t, tronc = _testo_limitato(str(testo or "").strip() or "(nessuna risposta)", log_nome)

    def fn(d):
        msg = {"id": f"a-{lavoro_id}", "chi": "lui", "testo": t, "ts": ts, "ora": _ora(ts), "lavoro": lavoro_id}
        if not ok:
            msg["errore"] = True
        if motore:
            msg["motore"] = motore
        if tronc:
            msg.update(troncato=True, log=log_nome)
        _metti(d, msg)
        d["in_attesa"] = [x for x in d["in_attesa"] if x != lavoro_id]
    return _cambia(sessione, _interlocutore(interlocutore) if interlocutore else "", fn, ts)


def reset(sessione_nuova, interlocutore, messaggio, ts=None):
    """«nuova conversazione»: il filo nuovo nasce con il messaggio del server, così gli altri
    dispositivi lo vedono come il più recente e ci passano."""
    ts = time.time() if ts is None else ts

    def fn(d):
        _metti(d, {"id": f"r-{sessione_nuova[:8]}", "chi": "lui", "testo": pulisci(messaggio)[:2000], "ts": ts,
                   "ora": _ora(ts)})
    return _cambia(sessione_nuova, _interlocutore(interlocutore), fn, ts)


def riavvio():
    """All'avvio del server i lavori di prima non ci sono più: ogni attesa diventa «Risposta persa»
    (lo stesso testo che la pagina scrive quando /api/lavoro/<id> dice «non trovato»)."""
    toccati = 0
    for f in sorted(cartella().glob("*.json")):
        d = _leggi_file(f)
        if not d or not d.get("in_attesa"):
            continue
        attese = list(d["in_attesa"])

        def fn(d, attese=attese):
            for lid in attese:
                if ID_LAVORO_RE.fullmatch(str(lid)) and not any(m.get("id") == f"a-{lid}" for m in d["messaggi"]):
                    ts = time.time()
                    _metti(d, {"id": f"a-{lid}", "chi": "lui", "testo": PERSA, "ts": ts, "ora": _ora(ts),
                               "errore": True, "lavoro": lid})
            d["in_attesa"] = []
        _cambia(d["sessione"], "", fn)
        toccati += 1
    return toccati


def leggi(sessione):
    if not valida_sessione(sessione):
        return None
    with _LOCK:
        f = cartella() / f"{sessione}.json"
        return _leggi_file(f) if f.exists() else None


def elenco():
    """I riassunti di tutti i fili, dal più recente. Si rilegge solo il file cambiato (mtime e dimensione)."""
    fuori = []
    with _LOCK:
        visti = set()
        for e in os.scandir(cartella()):
            if not e.name.endswith(".json") or not UUID_RE.fullmatch(e.name[:-5]):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            visti.add(e.name)
            c = _CACHE.get(e.name)
            if not c or c[0] != st.st_mtime_ns or c[1] != st.st_size:
                d = _leggi_file(e.path)
                if not d:
                    continue
                c = (st.st_mtime_ns, st.st_size, _riassunto(d))
                _CACHE[e.name] = c
            fuori.append(c[2])
        for k in [k for k in _CACHE if k not in visti]:
            _CACHE.pop(k, None)
    fuori.sort(key=lambda r: r.get("aggiornato") or 0, reverse=True)
    return {"fili": fuori, "ora": time.time(), "formato": FORMATO}
