#!/usr/bin/env python3
"""La coda degli incarichi (l'utente, 2026-10-04): Fase 1, solo VPS e Mac. Contratto: ~/Jarvis/docs/incarichi-contratto.md

Dati sulla VPS in INCARICHI_DIR (default /var/lib/jarvis-incarichi, 0700):
    incarichi/in_<8 esadecimali>.json   un file per incarico (0600, scrittura atomica, mai sovrascritto alla creazione)
    battiti/<agente>.json               l'ultimo battito di ogni agente («vivo» se più recente di 5 minuti)
    .lock                               il lucchetto (fcntl.flock) di ogni cambio di stato: un solo vincitore su «prendi»

Riga di comando (output JSON su stdout, tranne «prova»; uscita 0 ok, 1 validazione o non trovato, 2 uso sbagliato):
    python3 incarichi.py nuovo --da X --a Y --testo "..." [--tipo domanda|lavoro|messaggio] [--ore 24]
    python3 incarichi.py elenco [--stato nuovo] [--a Y] [--limite 50]
    python3 incarichi.py leggi ID
    python3 incarichi.py prendi ID --da X
    python3 incarichi.py rispondi ID --da X --testo "..." [--esito ok|fallito] [--token-stimati N]
    python3 incarichi.py annulla ID --da X
    python3 incarichi.py battito AGENTE --macchina M [--nota ".."]
    python3 incarichi.py stato
    python3 incarichi.py scadi
    python3 incarichi.py prova

Modo remoto: sul Mac (sys.platform == "darwin") senza INCARICHI_DIR, ogni comando e ogni funzione della libreria
passa da «ssh -o ConnectTimeout=8 vps-tuo python3 /root/jarvis/strumenti/incarichi.py <stessi argomenti>».
Sulla VPS lavora in locale. «prova» gira sempre in locale, in una cartella temporanea.

Solo libreria standard.
"""
import argparse
import fcntl
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

DIR_DEFAULT = "/var/lib/jarvis-incarichi"
SSH_HOST = "vps-tuo"
SSH_SCRIPT = "/root/jarvis/strumenti/incarichi.py"
SSH_TIMEOUT = 60
TIPI = ("domanda", "lavoro", "messaggio")
STATI = ("nuovo", "preso", "fatto", "fallito", "annullato", "scaduto")
ESITI = ("ok", "fallito")
MAX_TESTO = 4000
MAX_RISPOSTA = 8000
MAX_NOTA = 300
ORE_MAX = 24 * 7
VIVO_SECONDI = 5 * 60
NOME_RE = re.compile(r"[a-z0-9-]{1,40}")
MACCHINA_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")
ID_RE = re.compile(r"in_[0-9a-f]{8}")


class IncaricoNonValido(ValueError):
    pass


class NonTrovato(KeyError):
    pass


class GiaPreso(ValueError):
    pass


_ERRORI = {"IncaricoNonValido": IncaricoNonValido, "NonTrovato": NonTrovato, "GiaPreso": GiaPreso}


# ------------------------------------------------------------------ modo remoto

def remoto():
    """True sul Mac quando INCARICHI_DIR non è impostata: allora si lavora sulla VPS via ssh."""
    return sys.platform == "darwin" and not os.environ.get("INCARICHI_DIR")


def comando_ssh(args):
    """Gli argomenti di subprocess per lanciare questo script sulla VPS. ssh unisce gli argomenti con spazi e li
    passa alla shell remota, quindi ognuno va quotato: un testo con spazi, virgolette o «;» resta un argomento solo."""
    return ["ssh", "-o", "ConnectTimeout=8", SSH_HOST, "python3", SSH_SCRIPT] + [shlex.quote(str(a)) for a in args]


# 2026-10-04 (Dots vivi): il ponte della lavagna chiede lo stato ogni 8 s; una sola connessione ssh riusata
# (ControlMaster) invece di una nuova a ogni chiamata. Solo qui, nel modo remoto: comando_ssh resta quello del contratto.
SSH_RIUSO = ["-o", "ControlMaster=auto", "-o", "ControlPath=~/.ssh/cm-incarichi-%C", "-o", "ControlPersist=120"]


def _esegui_remoto(args):
    cmd = comando_ssh(args)
    cmd[1:1] = SSH_RIUSO
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise OSError(f"ssh {SSH_HOST}: nessuna risposta in {SSH_TIMEOUT} s")
    return r.returncode, r.stdout, r.stderr


def _remoto_json(args):
    codice, out, err = _esegui_remoto(args)
    if codice == 0:
        return json.loads(out) if out.strip() else None
    if codice == 1:
        try:
            e = json.loads(out)
            classe, msg = _ERRORI.get(e.get("classe"), IncaricoNonValido), str(e.get("errore", "errore"))
        except (ValueError, AttributeError):
            classe, msg = IncaricoNonValido, (err or out).strip() or "errore remoto"
        raise classe(msg)
    if codice == 2:
        raise IncaricoNonValido("uso sbagliato: " + (err.strip().splitlines() or ["?"])[-1])
    raise OSError(f"ssh {SSH_HOST} (uscita {codice}): {(err or out).strip()[:300]}")


# ------------------------------------------------------------------ file e cartelle

def _base():
    return Path(os.environ.get("INCARICHI_DIR") or DIR_DEFAULT)


def _cartella(p):
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (p.stat().st_mode & 0o777) != 0o700:
        os.chmod(p, 0o700)
    return p


def _dir_incarichi():
    _cartella(_base())
    return _cartella(_base() / "incarichi")


def _dir_battiti():
    _cartella(_base())
    return _cartella(_base() / "battiti")


def _temporaneo(cartella, nome, dati):
    fd, tmp = tempfile.mkstemp(prefix=f".{nome}.", suffix=".tmp", dir=str(cartella))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(dati, h, ensure_ascii=False, indent=1)
            h.write("\n")
            h.flush()
            os.fsync(h.fileno())
        os.chmod(tmp, 0o600)
    except BaseException:
        _togli(tmp)
        raise
    return tmp


def _togli(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def _scrivi(p, dati):
    """Temporaneo + rename: chi legge vede il file vecchio o quello nuovo, mai mezzo."""
    tmp = _temporaneo(p.parent, p.name, dati)
    try:
        os.replace(tmp, p)
    except BaseException:
        _togli(tmp)
        raise


def _crea_esclusivo(p, dati):
    """Come _scrivi, ma se il file c'è già fallisce (os.link non sovrascrive): un incarico non si sovrascrive mai."""
    tmp = _temporaneo(p.parent, p.name, dati)
    try:
        os.link(tmp, p)
    finally:
        _togli(tmp)


@contextmanager
def _lucchetto():
    fd = os.open(str(_cartella(_base()) / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _file(id_):
    if not isinstance(id_, str) or not ID_RE.fullmatch(id_):
        raise NonTrovato(f"incarico non trovato: {id_!r}")
    return _dir_incarichi() / f"{id_}.json"


def _carica(id_):
    f = _file(id_)
    try:
        with open(f, encoding="utf-8") as h:
            return json.load(h)
    except FileNotFoundError:
        raise NonTrovato(f"incarico non trovato: {id_}")


# ------------------------------------------------------------------ validazione

def _nome(v, campo):
    if not isinstance(v, str) or not NOME_RE.fullmatch(v):
        raise IncaricoNonValido(f"{campo}: nome di agente non valido (servono [a-z0-9-], da 1 a 40)")
    return v


def _testo(v, campo, massimo, vuoto_ok=False):
    if v is None and vuoto_ok:
        return ""
    if not isinstance(v, str):
        raise IncaricoNonValido(f"{campo}: serve un testo")
    v = v.strip()
    if not v and not vuoto_ok:
        raise IncaricoNonValido(f"{campo}: vuoto")
    if len(v) > massimo:
        raise IncaricoNonValido(f"{campo}: oltre {massimo} caratteri ({len(v)})")
    return v


def _ore(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= ORE_MAX:
        raise IncaricoNonValido(f"ore: un numero maggiore di 0 e al massimo {ORE_MAX}")
    return v


# ------------------------------------------------------------------ API

def nuovo(da, a, testo, tipo="domanda", ore=24):
    if remoto():
        return _remoto_json(["nuovo", "--da", da, "--a", a, "--testo", testo, "--tipo", tipo, "--ore", ore])
    da, a = _nome(da, "da"), _nome(a, "a")
    testo = _testo(testo, "testo", MAX_TESTO)
    if tipo not in TIPI:
        raise IncaricoNonValido(f"tipo: uno fra {', '.join(TIPI)}")
    ore = _ore(ore)
    adesso = int(time.time())
    cartella = _dir_incarichi()
    for _ in range(20):
        inc = {"id": "in_" + secrets.token_hex(4), "da": da, "a": a, "tipo": tipo, "testo": testo,
               "creato": adesso, "scade": int(adesso + ore * 3600), "stato": "nuovo",
               "preso_da": None, "preso_il": None, "risposta": None}
        try:
            _crea_esclusivo(cartella / f"{inc['id']}.json", inc)
            return inc
        except FileExistsError:
            continue
    raise OSError("impossibile trovare un id libero")


def _tutti():
    out = []
    for f in _dir_incarichi().glob("in_*.json"):
        if not ID_RE.fullmatch(f.stem):
            continue
        try:
            with open(f, encoding="utf-8") as h:
                d = json.load(h)
            if isinstance(d, dict) and d.get("id") == f.stem:
                out.append(d)
        except (OSError, ValueError):
            continue
    out.sort(key=lambda d: (d.get("creato", 0), d.get("id", "")), reverse=True)
    return out


def elenco(stato=None, a=None, limite=50):
    if remoto():
        args = ["elenco", "--limite", limite]
        if stato is not None:
            args += ["--stato", stato]
        if a is not None:
            args += ["--a", a]
        return _remoto_json(args)
    if stato is not None and stato not in STATI:
        raise IncaricoNonValido(f"stato: uno fra {', '.join(STATI)}")
    if a is not None:
        _nome(a, "a")
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= 1000:
        raise IncaricoNonValido("limite: un intero da 1 a 1000")
    out = [d for d in _tutti() if (stato is None or d.get("stato") == stato) and (a is None or d.get("a") == a)]
    return out[:limite]


def leggi(id_):
    if remoto():
        return _remoto_json(["leggi", id_])
    return _carica(id_)


def prendi(id_, da):
    """Solo da «nuovo». Sotto il lucchetto: con due concorrenti uno vince, l'altro riceve GiaPreso."""
    if remoto():
        return _remoto_json(["prendi", id_, "--da", da])
    da = _nome(da, "da")
    with _lucchetto():
        inc = _carica(id_)
        adesso = int(time.time())
        if inc["stato"] == "nuovo" and inc.get("scade") and adesso > inc["scade"]:
            inc["stato"] = "scaduto"
            _scrivi(_file(id_), inc)
        if inc["stato"] != "nuovo":
            chi = f" da {inc.get('preso_da')}" if inc["stato"] == "preso" else ""
            raise GiaPreso(f"{id_} è «{inc['stato']}»{chi}: si prende solo un incarico nuovo")
        inc.update(stato="preso", preso_da=da, preso_il=adesso)
        _scrivi(_file(id_), inc)
        return inc


def rispondi(id_, da, testo, esito="ok", token_stimati=None):
    if remoto():
        args = ["rispondi", id_, "--da", da, "--testo", testo, "--esito", esito]
        if token_stimati is not None:
            args += ["--token-stimati", token_stimati]
        return _remoto_json(args)
    da = _nome(da, "da")
    if esito not in ESITI:
        raise IncaricoNonValido(f"esito: uno fra {', '.join(ESITI)}")
    testo = _testo(testo, "testo", MAX_RISPOSTA, vuoto_ok=(esito == "fallito")) or "fallito senza dettagli"
    if token_stimati is not None and (isinstance(token_stimati, bool) or not isinstance(token_stimati, int)
                                      or token_stimati < 0):
        raise IncaricoNonValido("token_stimati: un intero da 0 in su, oppure niente")
    with _lucchetto():
        inc = _carica(id_)
        if inc["stato"] != "preso":
            raise IncaricoNonValido(f"{id_} è «{inc['stato']}»: si risponde solo a un incarico preso")
        if inc.get("preso_da") != da:
            raise IncaricoNonValido(f"{id_} l'ha preso {inc.get('preso_da')}: solo lui può rispondere")
        inc["risposta"] = {"testo": testo, "esito": esito, "da": da, "il": int(time.time()),
                           "token_stimati": token_stimati}
        inc["stato"] = "fatto" if esito == "ok" else "fallito"
        _scrivi(_file(id_), inc)
        return inc


def annulla(id_, da):
    """Lo annulla chi l'ha mandato o chi lo deve fare, finché è nuovo o preso."""
    if remoto():
        return _remoto_json(["annulla", id_, "--da", da])
    da = _nome(da, "da")
    with _lucchetto():
        inc = _carica(id_)
        if inc["stato"] not in ("nuovo", "preso"):
            raise IncaricoNonValido(f"{id_} è «{inc['stato']}»: non si annulla più")
        if da not in (inc.get("da"), inc.get("a")):
            raise IncaricoNonValido(f"{id_}: lo annulla solo chi l'ha mandato ({inc.get('da')}) o chi lo deve fare ({inc.get('a')})")
        inc["stato"] = "annullato"
        inc["annullato_da"] = da
        inc["annullato_il"] = int(time.time())
        _scrivi(_file(id_), inc)
        return inc


def battito(agente, macchina, nota=""):
    if remoto():
        _remoto_json(["battito", agente, "--macchina", macchina, "--nota", nota or ""])
        return None
    agente = _nome(agente, "agente")
    if not isinstance(macchina, str) or not MACCHINA_RE.fullmatch(macchina):
        raise IncaricoNonValido("macchina: [A-Za-z0-9._-], da 1 a 40")
    nota = _testo(nota, "nota", MAX_NOTA, vuoto_ok=True)
    _scrivi(_dir_battiti() / f"{agente}.json",
            {"agente": agente, "macchina": macchina, "il": int(time.time()), "nota": nota})
    return None


def _battiti(adesso):
    out = []
    for f in sorted(_dir_battiti().glob("*.json")):
        try:
            with open(f, encoding="utf-8") as h:
                b = json.load(h)
            il = int(b.get("il") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        out.append({"agente": b.get("agente", f.stem), "macchina": b.get("macchina", ""), "il": il,
                    "vivo": abs(adesso - il) < VIVO_SECONDI,
                    "nota": b.get("nota", "")})
    return out


def stato_pubblico():
    if remoto():
        return _remoto_json(["stato"])
    adesso = int(time.time())
    tutti = _tutti()
    contatori = {s: 0 for s in STATI}
    for d in tutti:
        if d.get("stato") in contatori:
            contatori[d["stato"]] += 1
    contatori["totale"] = len(tutti)
    battiti = _battiti(adesso)
    contatori["agenti_vivi"] = sum(1 for b in battiti if b["vivo"])
    return {"incarichi": tutti[:50], "battiti": battiti, "contatori": contatori}


def scadi():
    """Segna «scaduto» i nuovi e i presi oltre «scade». Idempotente: la seconda volta torna una lista vuota."""
    if remoto():
        return _remoto_json(["scadi"])
    adesso = int(time.time())
    fatti = []
    with _lucchetto():
        for d in _tutti():
            if d.get("stato") in ("nuovo", "preso") and d.get("scade") and adesso > d["scade"]:
                d["stato"] = "scaduto"
                _scrivi(_file(d["id"]), d)
                fatti.append(d)
    return fatti


# ------------------------------------------------------------------ prova

def _prova_concorrenti_processo(dir_, id_, nome, via):
    """Figlio della prova: aspetta il via e prova a prendere."""
    os.environ["INCARICHI_DIR"] = dir_
    while time.time() < via:
        time.sleep(0.0005)
    try:
        prendi(id_, nome)
        return 0
    except GiaPreso:
        return 3


def prova():
    import shutil
    import threading
    base = Path(tempfile.mkdtemp(prefix="prova-incarichi-"))
    prima = os.environ.get("INCARICHI_DIR")
    os.environ["INCARICHI_DIR"] = str(base / "dati")
    ok = True

    def v(nome, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + nome)

    def solleva(nome, classe, f, *a, **k):
        try:
            f(*a, **k)
        except classe:
            return v(nome, True)
        except Exception as e:  # noqa: BLE001
            return v(f"{nome} (eccezione sbagliata: {type(e).__name__}: {e})", False)
        v(nome + " (nessun errore)", False)

    try:
        v("in prova non è in modo remoto", not remoto())
        # validazione
        solleva("testo vuoto", IncaricoNonValido, nuovo, "jarvis-utente", "ceo-ai", "   ")
        solleva("testo oltre 4000", IncaricoNonValido, nuovo, "jarvis-utente", "ceo-ai", "x" * 4001)
        solleva("nome con maiuscole", IncaricoNonValido, nuovo, "Jarvis", "ceo-ai", "ciao")
        solleva("nome con spazio", IncaricoNonValido, nuovo, "jarvis-utente", "ceo ai", "ciao")
        solleva("nome con ../", IncaricoNonValido, battito, "../etc", "vps")
        solleva("nome oltre 40", IncaricoNonValido, nuovo, "a" * 41, "ceo-ai", "ciao")
        solleva("tipo sbagliato", IncaricoNonValido, nuovo, "jarvis-utente", "ceo-ai", "ciao", tipo="ordine")
        solleva("ore a zero", IncaricoNonValido, nuovo, "jarvis-utente", "ceo-ai", "ciao", ore=0)
        solleva("stato sbagliato in elenco", IncaricoNonValido, elenco, stato="boh")
        solleva("id sbagliato", NonTrovato, leggi, "../../etc/passwd")
        solleva("id inesistente", NonTrovato, leggi, "in_00000000")
        # ciclo nuovo -> preso -> fatto
        i = nuovo("jarvis-utente", "ceo-ai", "Quanto abbiamo incassato ieri? È una prova «àèì»", tipo="domanda")
        v("id in_ + 8 esadecimali", ID_RE.fullmatch(i["id"]) is not None)
        v("nuovo: stato nuovo e scade a +24h", i["stato"] == "nuovo" and i["scade"] - i["creato"] == 86400)
        v("campi del contratto", set(i) >= {"id", "da", "a", "tipo", "testo", "creato", "scade", "stato",
                                             "preso_da", "preso_il", "risposta"})
        v("UTF-8 senza escape nel file", "«àèì»" in (base / "dati" / "incarichi" / f"{i['id']}.json").read_text("utf-8"))
        v("elenco per destinatario e stato", [d["id"] for d in elenco(stato="nuovo", a="ceo-ai")] == [i["id"]])
        p = prendi(i["id"], "ceo-ai")
        v("preso da ceo-ai", p["stato"] == "preso" and p["preso_da"] == "ceo-ai" and p["preso_il"])
        solleva("non si prende due volte", GiaPreso, prendi, i["id"], "commercialista")
        solleva("risposta da chi non ha preso rifiutata", IncaricoNonValido, rispondi, i["id"], "commercialista", "io")
        r = rispondi(i["id"], "ceo-ai", "Ieri 1.234 euro (prova)", token_stimati=1200)
        v("fatto con risposta", r["stato"] == "fatto" and r["risposta"]["esito"] == "ok"
          and r["risposta"]["token_stimati"] == 1200 and r["risposta"]["da"] == "ceo-ai")
        solleva("non si risponde due volte", IncaricoNonValido, rispondi, i["id"], "ceo-ai", "ancora")
        solleva("un fatto non si annulla", IncaricoNonValido, annulla, i["id"], "jarvis-utente")
        f2 = rispondi(prendi(nuovo("jarvis-utente", "cambusa", "lavoro", tipo="lavoro")["id"], "cambusa")["id"],
                      "cambusa", "", esito="fallito")
        v("esito fallito -> stato fallito", f2["stato"] == "fallito")
        a = nuovo("jarvis-utente", "legale-societario", "da annullare", tipo="messaggio")
        solleva("annulla da un estraneo rifiutato", IncaricoNonValido, annulla, a["id"], "commerciale")
        v("annulla dal mittente", annulla(a["id"], "jarvis-utente")["stato"] == "annullato")
        # un incarico non si sovrascrive mai
        fisso = base / "dati" / "incarichi" / "in_abcdef01.json"
        try:
            _crea_esclusivo(fisso, {"id": "in_abcdef01"})
            _crea_esclusivo(fisso, {"id": "in_abcdef01", "altro": 1})
            v("creazione esclusiva", False)
        except FileExistsError:
            v("creazione esclusiva: il secondo fallisce", json.loads(fisso.read_text()) == {"id": "in_abcdef01"})
        fisso.unlink()
        # un solo vincitore: thread
        for giro in range(5):
            c = nuovo("jarvis-utente", "ceo-ai", f"gara {giro}")
            vinti, persi = [], []
            barriera = threading.Barrier(8)

            def corri(n, c=c, vinti=vinti, persi=persi, barriera=barriera):
                barriera.wait()
                try:
                    prendi(c["id"], f"agente-{n}")
                    vinti.append(n)
                except GiaPreso:
                    persi.append(n)
            th = [threading.Thread(target=corri, args=(n,)) for n in range(8)]
            [t.start() for t in th]
            [t.join() for t in th]
            fin = leggi(c["id"])
            if not (len(vinti) == 1 and len(persi) == 7 and fin["preso_da"] == f"agente-{vinti[0]}"):
                v(f"thread giro {giro}: vinti {vinti}", False)
                break
        else:
            v("un solo vincitore con 8 thread insieme (5 giri)", True)
        # un solo vincitore: processi veri
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        for giro in range(3):
            c = nuovo("jarvis-utente", "ceo-ai", f"gara processi {giro}")
            via = time.time() + 1.5
            with ctx.Pool(6) as pool:
                esiti = pool.starmap(_prova_concorrenti_processo,
                                     [(os.environ["INCARICHI_DIR"], c["id"], f"proc-{n}", via) for n in range(6)])
            fin = leggi(c["id"])
            vince = [n for n, e in enumerate(esiti) if e == 0]
            if not (len(vince) == 1 and esiti.count(3) == 5 and fin["preso_da"] == f"proc-{vince[0]}"):
                v(f"processi giro {giro}: esiti {esiti}", False)
                break
        else:
            v("un solo vincitore con 6 processi insieme (3 giri)", True)
        # scadenza
        s1 = nuovo("jarvis-utente", "cruscotto-bi", "scadrà")
        s2 = prendi(nuovo("jarvis-utente", "cruscotto-bi", "scadrà presa")["id"], "cruscotto-bi")
        s3 = nuovo("jarvis-utente", "cruscotto-bi", "non scade")
        for s in (s1, s2):
            d = leggi(s["id"])
            d["scade"] = int(time.time()) - 10
            _scrivi(_file(s["id"]), d)
        scaduti = {d["id"] for d in scadi()}
        v("scadi segna nuovi e presi oltre la scadenza", scaduti == {s1["id"], s2["id"]})
        v("gli altri restano", leggi(s3["id"])["stato"] == "nuovo" and leggi(i["id"])["stato"] == "fatto")
        v("scadi idempotente", scadi() == [])
        solleva("uno scaduto non si prende", GiaPreso, prendi, s1["id"], "cruscotto-bi")
        # battiti
        battito("ceo-ai", "vps", "giro delle 10")
        battito("commercialista", "vps")
        d = json.loads((base / "dati" / "battiti" / "commercialista.json").read_text())
        d["il"] = int(time.time()) - 301
        _scrivi(base / "dati" / "battiti" / "commercialista.json", d)
        st = stato_pubblico()
        b = {x["agente"]: x for x in st["battiti"]}
        v("battito recente: vivo", b["ceo-ai"]["vivo"] is True and b["ceo-ai"]["nota"] == "giro delle 10")
        v("battito di 301 s fa: non vivo", b["commercialista"]["vivo"] is False)
        v("stato_pubblico: chiavi e contatori", set(st) == {"incarichi", "battiti", "contatori"}
          and st["contatori"]["fatto"] == 1 and st["contatori"]["scaduto"] == 2
          and st["contatori"]["totale"] == len(_tutti()) and st["contatori"]["agenti_vivi"] == 1
          and len(st["incarichi"]) <= 50)
        for n in range(55):
            nuovo("jarvis-utente", "garante-dati", f"riempio {n}")
        st = stato_pubblico()
        v("stato_pubblico: al massimo 50, i più recenti", len(st["incarichi"]) == 50
          and st["incarichi"][0]["creato"] >= st["incarichi"][-1]["creato"])
        # permessi
        dati = base / "dati"
        cartelle = [dati, dati / "incarichi", dati / "battiti"]
        file_ = list((dati / "incarichi").glob("*.json")) + list((dati / "battiti").glob("*.json")) + [dati / ".lock"]
        v("cartelle 0700", all((c.stat().st_mode & 0o777) == 0o700 for c in cartelle))
        v(f"file 0600 ({len(file_)})", all((f.stat().st_mode & 0o777) == 0o600 for f in file_))
        v("nessun temporaneo rimasto", not list(dati.rglob("*.tmp")))
        # modo remoto: solo il comando, senza ssh vero
        cmd = comando_ssh(["nuovo", "--da", "jarvis-utente", "--a", "ceo-ai", "--testo", "ciao 'mondo'; rm -rf /",
                           "--ore", 24])
        v("comando ssh: prefisso del contratto", cmd[:6] == ["ssh", "-o", "ConnectTimeout=8", "vps-tuo",
                                                             "python3", "/root/jarvis/strumenti/incarichi.py"])
        v("comando ssh: argomenti quotati per la shell remota", shlex.split(" ".join(cmd[4:]))[2:] ==
          ["nuovo", "--da", "jarvis-utente", "--a", "ceo-ai", "--testo", "ciao 'mondo'; rm -rf /", "--ore", "24"])
        os.environ["INCARICHI_DIR"] = ""
        v("sul Mac senza INCARICHI_DIR è remoto" if sys.platform == "darwin" else "fuori dal Mac è locale",
          remoto() == (sys.platform == "darwin"))
        # il modo remoto della libreria passa da _esegui_remoto: lo sostituisco per vedere gli argomenti
        global _esegui_remoto
        vero = _esegui_remoto
        visti = []

        def finto(args):
            visti.append(args)
            if args[0] == "prendi":
                return 1, json.dumps({"errore": "già preso", "classe": "GiaPreso"}), ""
            return 0, json.dumps({"ok": True}), ""
        _esegui_remoto = finto
        try:
            if sys.platform == "darwin":
                rispondi("in_12345678", "ceo-ai", "fatto", token_stimati=5)
                v("libreria remota: argomenti di rispondi", visti[-1] == ["rispondi", "in_12345678", "--da", "ceo-ai",
                  "--testo", "fatto", "--esito", "ok", "--token-stimati", 5])
                solleva("libreria remota: l'errore torna con la sua classe", GiaPreso, prendi, "in_12345678", "x")
        finally:
            _esegui_remoto = vero
            os.environ["INCARICHI_DIR"] = str(base / "dati")
        # riga di comando: codici di uscita
        env = dict(os.environ, INCARICHI_DIR=str(base / "dati"))
        me = [sys.executable, str(Path(__file__).resolve())]

        def cli(*a):
            r = subprocess.run(me + list(a), capture_output=True, text=True, env=env)
            return r.returncode, r.stdout
        c, out = cli("nuovo", "--da", "jarvis-utente", "--a", "ceo-ai", "--testo", "da riga di comando «ok»")
        idc = json.loads(out)["id"] if c == 0 else None
        v("cli nuovo: 0 e JSON con «» non escapati", c == 0 and "«ok»" in out)
        v("cli testo vuoto: 1", cli("nuovo", "--da", "jarvis-utente", "--a", "ceo-ai", "--testo", "")[0] == 1)
        v("cli non trovato: 1", cli("leggi", "in_ffffffff")[0] == 1)
        v("cli uso sbagliato: 2", cli("nuovo", "--da", "x")[0] == 2 and cli("boh")[0] == 2)
        v("cli prendi + rispondi", cli("prendi", idc, "--da", "ceo-ai")[0] == 0
          and cli("rispondi", idc, "--da", "ceo-ai", "--testo", "ok", "--token-stimati", "3")[0] == 0)
        v("cli prendi di nuovo: 1", cli("prendi", idc, "--da", "ceo-ai")[0] == 1)
        c, out = cli("stato")
        v("cli stato: JSON", c == 0 and "contatori" in json.loads(out))
        v("cli battito", cli("battito", "ceo-ai", "--macchina", "vps", "--nota", "x")[0] == 0)
    finally:
        if prima is None:
            os.environ.pop("INCARICHI_DIR", None)
        else:
            os.environ["INCARICHI_DIR"] = prima
        shutil.rmtree(base, ignore_errors=True)
    print("tutto ok" if ok else "CI SONO ERRORI")
    return 0 if ok else 1


# ------------------------------------------------------------------ riga di comando

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"uso sbagliato: {message}", file=sys.stderr)
        sys.exit(2)


def _parser():
    p = _Parser(prog="incarichi.py", description="La coda degli incarichi (Fase 1).")
    s = p.add_subparsers(dest="cmd", parser_class=_Parser)
    x = s.add_parser("nuovo")
    x.add_argument("--da", required=True)
    x.add_argument("--a", required=True)
    x.add_argument("--testo", required=True)
    x.add_argument("--tipo", default="domanda")
    x.add_argument("--ore", type=float, default=24)
    x = s.add_parser("elenco")
    x.add_argument("--stato")
    x.add_argument("--a")
    x.add_argument("--limite", type=int, default=50)
    x = s.add_parser("leggi")
    x.add_argument("id")
    x = s.add_parser("prendi")
    x.add_argument("id")
    x.add_argument("--da", required=True)
    x = s.add_parser("rispondi")
    x.add_argument("id")
    x.add_argument("--da", required=True)
    x.add_argument("--testo", required=True)
    x.add_argument("--esito", default="ok")
    x.add_argument("--token-stimati", type=int, dest="token_stimati")
    x = s.add_parser("annulla")
    x.add_argument("id")
    x.add_argument("--da", required=True)
    x = s.add_parser("battito")
    x.add_argument("agente")
    x.add_argument("--macchina", required=True)
    x.add_argument("--nota", default="")
    s.add_parser("stato")
    s.add_parser("scadi")
    s.add_parser("prova")
    return p


def _stampa(dati):
    print(json.dumps(dati, ensure_ascii=False, indent=1))


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if remoto() and not (argv and argv[0] == "prova"):
        try:
            codice, out, err = _esegui_remoto(argv)
        except OSError as e:
            _stampa({"errore": str(e), "classe": "OSError"})
            return 1
        sys.stdout.write(out)
        sys.stderr.write(err)
        if codice == 255:
            return 1
        return codice
    a = _parser().parse_args(argv)
    if a.cmd is None:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if a.cmd == "nuovo":
            ore = int(a.ore) if a.ore == int(a.ore) else a.ore
            _stampa(nuovo(a.da, a.a, a.testo, tipo=a.tipo, ore=ore))
        elif a.cmd == "elenco":
            _stampa(elenco(stato=a.stato, a=a.a, limite=a.limite))
        elif a.cmd == "leggi":
            _stampa(leggi(a.id))
        elif a.cmd == "prendi":
            _stampa(prendi(a.id, a.da))
        elif a.cmd == "rispondi":
            _stampa(rispondi(a.id, a.da, a.testo, esito=a.esito, token_stimati=a.token_stimati))
        elif a.cmd == "annulla":
            _stampa(annulla(a.id, a.da))
        elif a.cmd == "battito":
            battito(a.agente, a.macchina, a.nota)
            _stampa({"ok": True, "agente": a.agente, "macchina": a.macchina})
        elif a.cmd == "stato":
            _stampa(stato_pubblico())
        elif a.cmd == "scadi":
            _stampa(scadi())
        elif a.cmd == "prova":
            return prova()
    except (IncaricoNonValido, NonTrovato, GiaPreso) as e:
        msg = e.args[0] if e.args else str(e)
        _stampa({"errore": msg, "classe": type(e).__name__})
        print(f"errore: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
