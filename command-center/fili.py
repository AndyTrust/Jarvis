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
        d = _leggi_file(f) if f.exists() else None
    if d:
        # 2026-10-05 15:05: le notifiche scritte prima della regola (o arrivate da una VPS non ancora aggiornata)
        # ricevono la classe qui, in lettura: niente si sposta né si cancella nei file
        for m in d.get("messaggi") or []:
            if isinstance(m, dict) and m.get("notifica") and m.get("classe") not in CLASSI:
                m["classe"] = classifica(d.get("interlocutore"), m.get("titolo"), m.get("id", "")[2:], m.get("dati"))
    return d


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
        for k in [k for k in _CACHE if k not in visti and "/" not in k]:   # «origine/nome» = fili remoti
            _CACHE.pop(k, None)
    fuori.sort(key=lambda r: r.get("aggiornato") or 0, reverse=True)
    return {"fili": fuori, "ora": time.time(), "formato": FORMATO}



# ---------------------------------------------------------------- fili dell'altra macchina (2026-10-05, fonte unica)
# Ogni chat gira sulla macchina dove è partita e scrive lì il suo filo. fonte_vps.py (solo sul Mac) porta i fili
# del Mac sulla VPS in fili-remoti/mac/ e quelli della VPS sul Mac in fili-remoti/vps/. La pagina li vede tutti
# con elenco_unito() e leggi_unito(); le funzioni di prima (sessione_corrente, notifiche) guardano solo i fili
# di questa macchina. Stessa sessione qui e là: vince quella di questa macchina. Solo lettura: niente si scrive.
def cartelle_remote():
    base = cartella().parent / "fili-remoti"
    if not base.is_dir():
        return []
    return [(p.name, p) for p in sorted(base.iterdir()) if p.is_dir() and re.fullmatch(r"[a-z0-9-]{1,30}", p.name)]


def elenco_unito():
    d = elenco()
    visti = {r["sessione"] for r in d["fili"]}
    for origine, cart in cartelle_remote():
        for e in os.scandir(cart):
            if not e.name.endswith(".json") or not UUID_RE.fullmatch(e.name[:-5]) or e.name[:-5] in visti:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            chiave = f"{origine}/{e.name}"
            c = _CACHE.get(chiave)
            if not c or c[0] != st.st_mtime_ns or c[1] != st.st_size:
                f = _leggi_file(e.path)
                if not f:
                    continue
                c = (st.st_mtime_ns, st.st_size, {**_riassunto(f), "origine": origine})
                _CACHE[chiave] = c
            visti.add(e.name[:-5])
            d["fili"].append(c[2])
    d["fili"].sort(key=lambda r: r.get("aggiornato") or 0, reverse=True)
    return d


def leggi_unito(sessione):
    d = leggi(sessione)
    if d or not valida_sessione(sessione):
        return d
    for origine, cart in cartelle_remote():
        f = cart / f"{sessione}.json"
        if f.exists():
            r = _leggi_file(f)
            if r:
                return {**r, "origine": origine}
    return None

# ---------------------------------------------------------------- notifiche (2026-10-05, programmatore-notifiche)
# Decisione dell'utente del 05/10/2026: i report e gli avvisi arrivano in due fili dedicati della chat del
# Command Center (sito, Mac, app), non più su Telegram. Jarvis e Postino sono gli unici mittenti.
# Il filo di un mittente è il più recente con quell'interlocutore: dopo «Ricomincia» le notifiche
# vanno nel filo nuovo. Id dei messaggi: n-<chiave> (la stessa chiave riscrive lo stesso messaggio).
# Accanto all'archivio, notifiche-telefono.json (le ultime 50, testo corto) lo legge il ponte del
# telefono (jarvis-agent, GET /notifiche) per la notifica sull'app.
SPECIALI = {"notifiche-jarvis": "Jarvis", "postino": "Postino"}
MITTENTI = {"jarvis": "notifiche-jarvis", "postino": "postino"}
MAX_DATI = 60000
CHIAVE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
TELEFONO_MAX = 50


# ---------------------------------------------------------------- report o avviso (l'utente, 2026-10-05 15:05)
# «Nel Postino devo ricevere solo i briefing, i report e le routine che ti chiedo; nella chat principale riporti tutto
# quello che stiamo facendo, gli stati d'avanzamento. Non intasare il Postino.» Questo è l'UNICO punto che decide:
#   «report» → scheda Postino della chat: report e briefing (mattino, pranzo, cena, pomeriggio, direzione,
#              settimanale), rassegna, riunioni, la posta del Postino, gli esiti delle routine con
#              «avvisa_postino»: true in routine-gruppi.json;
#   «avviso» → chat principale di Jarvis, come messaggio di Jarvis (nessuna risposta di Claude parte): errori dei
#              lavori automatici, salvataggi delle routine, avanzamenti, prove tecniche, permessi, sentinella.
# Chi manda può dirlo da sé (notifica.py --tipo report|avviso); senza, decidono mittente, chiave e titolo.
# La pagina (app.js, FILI_UNITI) e il telefono (notifiche-telefono.json) leggono il campo «classe» del messaggio.
CLASSI = ("report", "avviso")
_REPORT_TITOLO = re.compile(r"\b(report|briefing|rassegna|riunione|digest|posta del|resoconto)\b", re.I)
_REPORT_CHIAVE = re.compile(r"^(report|briefing|rassegna|riunione|servizio|mattino|pomeriggio|posta|digest)[-_.:]", re.I)
_AVVISO_TITOLO = re.compile(r"^\s*(errore|allarme|routine (creata|aggiornata|non aggiornata|tolta|cancellata)|"
                            r"permess|prova\b|sentinella|app jarvis .*pubblicat)", re.I)
_GRAVE_TITOLO = re.compile(r"^\s*(errore|allarme)\b", re.I)


def _routine_al_postino(nome):
    """True se la routine «nome» (anche «vps:nome», «mac:nome») ha «avvisa_postino»: true in routine-gruppi.json."""
    nome = str(nome or "").strip()
    if not nome:
        return False
    try:
        f = Path(os.environ.get("CC_ROUTINE_GRUPPI") or Path(__file__).resolve().parent / "routine-gruppi.json")
        voci = (json.loads(f.read_text(encoding="utf-8")).get("routine") or {})
    except (OSError, ValueError, AttributeError):
        return False
    for k, v in voci.items():
        if (k == nome or k.split(":", 1)[-1] == nome.split(":", 1)[-1]) and isinstance(v, dict):
            return v.get("avvisa_postino") is True
    return False


def classifica(interlocutore, titolo="", chiave="", dati=None, tipo="", routine=""):
    """«report» o «avviso» (vedi sopra). interlocutore: «postino» o «notifiche-jarvis» (anche «jarvis»)."""
    tipo = str(tipo or "").strip().lower()
    if tipo in CLASSI:
        return tipo
    if isinstance(dati, dict) and str(dati.get("classe") or "").lower() in CLASSI:
        return str(dati["classe"]).lower()
    titolo = str(titolo or "")
    if _AVVISO_TITOLO.search(titolo):          # anche l'errore di una routine «al Postino» va a Jarvis
        return "avviso"
    if routine and _routine_al_postino(routine):
        return "report"
    if interlocutore in ("postino",):
        return "report"
    if _REPORT_CHIAVE.search(str(chiave or "")) or _REPORT_TITOLO.search(titolo):
        return "report"
    return "avviso"


def grave(titolo, dati=None):
    """Un avviso che fa suonare il telefono anche se non è un report: errori e allarmi."""
    return bool(_GRAVE_TITOLO.search(str(titolo or ""))) or (isinstance(dati, dict) and dati.get("grave") is True)


def interlocutore_di(chi):
    """«jarvis» o «postino» (anche il nome dell'interlocutore) → l'interlocutore del filo; ValueError se no."""
    c = str(chi or "").strip().lower()
    if c in MITTENTI:
        return MITTENTI[c]
    if c in SPECIALI:
        return c
    raise ValueError("mittente sconosciuto: solo jarvis o postino")


def sessione_corrente(interlocutore):
    """La sessione del filo più recente di quell'interlocutore (None se non ce n'è)."""
    for r in elenco()["fili"]:
        if r.get("interlocutore") == interlocutore:
            return r["sessione"]
    return None


def _ora_roma(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("Europe/Rome")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return _ora(ts)


def _dati_puliti(dati):
    if dati is None:
        return None
    testo = pulisci(json.dumps(dati, ensure_ascii=False, default=str))
    if len(testo) > MAX_DATI:
        return {"troncati": True, "nota": f"dati oltre {MAX_DATI} caratteri, non salvati"}
    return json.loads(testo)


def file_telefono():
    return cartella().parent / "notifiche-telefono.json"


def _scrivi_telefono(voce):
    """Aggiunge la notifica alla lista che legge il ponte del telefono (le ultime TELEFONO_MAX)."""
    f = file_telefono()
    try:
        lista = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(lista, list):
            lista = []
    except (OSError, ValueError):
        lista = []
    lista = [v for v in lista if isinstance(v, dict) and v.get("id") != voce["id"]]
    lista.append(voce)
    lista = lista[-TELEFONO_MAX:]
    fd, tmp = tempfile.mkstemp(prefix=".telefono-", suffix=".tmp", dir=str(f.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(lista, h, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def notifica(chi, titolo, testo, dati=None, prova=False, chiave="", ts=None, tipo="", routine=""):
    """Un messaggio di Jarvis o di Postino nel suo filo. Torna il riassunto del filo con «id» e «classe» del messaggio.
    tipo: «report» | «avviso» | "" (lo decide classifica()); routine: il nome della routine che manda, se c'è."""
    interlocutore = interlocutore_di(chi)
    mittente = SPECIALI[interlocutore]
    ts = time.time() if ts is None else ts
    titolo = " ".join(pulisci(titolo or "").split())[:120]
    t, tronc = _testo_limitato(str(testo or "").strip() or titolo or "(vuoto)")
    chiave = str(chiave or "").strip()
    if chiave and not CHIAVE_RE.fullmatch(chiave):
        raise ValueError("chiave non valida")
    mid = "n-" + (chiave or f"{int(ts * 1000):x}{os.urandom(2).hex()}")
    classe = classifica(interlocutore, titolo, chiave, dati, tipo, routine)
    msg = {"id": mid, "chi": "lui", "testo": t, "ts": ts, "ora": _ora_roma(ts), "mittente": mittente,
           "notifica": True, "classe": classe}
    if routine:
        msg["routine"] = str(routine)[:80]
    if titolo:
        msg["titolo"] = titolo
    d_puliti = _dati_puliti(dati)
    if d_puliti:
        msg["dati"] = d_puliti
    if prova:
        msg["prova"] = True
    if tronc:
        msg["troncato"] = True
    # niente _Blocco qui: _cambia lo prende già, e un secondo flock dello stesso processo si bloccherebbe
    sessione = sessione_corrente(interlocutore) or _uuid_nuovo()

    def fn(d):
        # la stessa chiave riscrive il messaggio: testo e ora nuovi, e torna in fondo al filo
        d["messaggi"] = [m for m in d["messaggi"] if m.get("id") != mid]
        d["messaggi"].append(msg)
        if not d.get("titolo"):
            d["titolo"] = f"Notifiche di {mittente}"
    r = _cambia(sessione, interlocutore, fn, ts)
    # il telefono suona per i report (apre la scheda Postino) e per errori e allarmi (apre la chat di Jarvis);
    # gli altri avvisi (salvataggi, avanzamenti, prove tecniche) restano nella chat senza suonare
    if classe == "report" or grave(titolo, dati):
        try:
            _scrivi_telefono({"id": mid, "ts": ts, "k": "postino" if classe == "report" else "notifiche-jarvis",
                              "mittente": mittente, "titolo": titolo, "classe": classe,
                              "testo": " ".join(t.split())[:300], "prova": bool(prova), "sessione": r["sessione"]})
        except Exception:  # noqa: BLE001  (il telefono non ferma mai la notifica nel filo)
            pass
    return {**r, "id": mid, "classe": classe}


def _uuid_nuovo():
    import uuid
    return str(uuid.uuid4())


def togli_notifiche(solo_prova=True, ids=()):
    """Toglie dai fili speciali i messaggi di prova (o quelli con gli id dati). Torna quanti ne ha tolti."""
    ids = set(ids or ())
    tolti = 0
    for r in elenco()["fili"]:
        if r.get("interlocutore") not in SPECIALI:
            continue
        conta = {"n": 0}

        def fn(d, conta=conta):
            prima = len(d["messaggi"])
            d["messaggi"] = [m for m in d["messaggi"]
                             if not ((solo_prova and m.get("prova")) or m.get("id") in ids)]
            conta["n"] = prima - len(d["messaggi"])
            return None if conta["n"] else False
        _cambia(r["sessione"], "", fn)
        tolti += conta["n"]
    f = file_telefono()
    try:
        lista = json.loads(f.read_text(encoding="utf-8"))
        nuova = [v for v in lista if not ((solo_prova and v.get("prova")) or v.get("id") in ids)]
        if len(nuova) != len(lista):
            f.write_text(json.dumps(nuova, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        pass
    return tolti


def contesto_notifiche(sessione, quante=3, classe=None, dopo=0):
    """Le ultime notifiche del filo (mittente, titolo, ora, testo, dati): il contesto di una risposta dell'utente.
    classe: solo «report» o solo «avviso»; dopo: solo quelle con ts maggiore."""
    d = leggi(sessione)
    if not d:
        return []
    out = [m for m in d["messaggi"] if m.get("notifica") and (not classe or m.get("classe") == classe)
           and (m.get("ts") or 0) > dopo]
    return out[-quante:]


def specchia(filo_remoto):
    """Sul Mac: unisce il filo speciale della VPS a quello locale (stessa sessione, messaggi per id).
    I messaggi solo locali (domande fatte dal Mac) restano; l'ordine è quello dei ts. Torna True se è cambiato."""
    if not isinstance(filo_remoto, dict) or filo_remoto.get("interlocutore") not in SPECIALI:
        return False
    sessione = filo_remoto.get("sessione")
    if not valida_sessione(sessione):
        return False
    remoti = [m for m in filo_remoto.get("messaggi") or [] if isinstance(m, dict) and m.get("id")]
    # 2026-10-05 (chat Postino): «Ricomincia» fatto dal Mac apre qui un filo nuovo che la VPS non conosce; le
    # notifiche della VPS continuano ad arrivare nel suo filo. Se il filo locale corrente è nato dopo quello
    # della VPS, le notifiche arrivate dopo la sua nascita entrano lì, così la chat del Mac le vede.
    attuale = sessione_corrente(filo_remoto["interlocutore"])
    if attuale and attuale != sessione:
        loc = leggi(attuale)
        nato = (loc or {}).get("creato") or 0
        if nato > (filo_remoto.get("creato") or 0):
            sessione = attuale
            remoti = [m for m in remoti if m.get("notifica") and (m.get("ts") or 0) >= nato]
    stato = {"cambiato": False}

    def fn(d):
        per_id = {m.get("id"): i for i, m in enumerate(d["messaggi"])}
        for m in remoti:
            i = per_id.get(m["id"])
            if i is None:
                d["messaggi"].append(m)
                stato["cambiato"] = True
            elif d["messaggi"][i] != m and m.get("notifica"):
                d["messaggi"][i] = m
                stato["cambiato"] = True
        # tolti sulla VPS (prove, ✕): via anche qui, solo le notifiche
        ids_remoti = {m["id"] for m in remoti}
        prima = len(d["messaggi"])
        d["messaggi"] = [m for m in d["messaggi"] if not (m.get("notifica") and m.get("id") not in ids_remoti)]
        if len(d["messaggi"]) != prima:
            stato["cambiato"] = True
        if not stato["cambiato"]:
            return False
        d["messaggi"].sort(key=lambda m: m.get("ts") or 0)
        d["titolo"] = d.get("titolo") or filo_remoto.get("titolo") or ""
    _cambia(sessione, filo_remoto["interlocutore"], fn, filo_remoto.get("aggiornato"))
    return stato["cambiato"]


def esporta_speciali():
    """I fili speciali correnti, interi (per lo specchio del Mac)."""
    out = []
    for k in SPECIALI:
        s = sessione_corrente(k)
        d = leggi(s) if s else None
        if d:
            out.append(d)
    return out
