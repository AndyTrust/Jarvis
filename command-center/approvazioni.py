#!/usr/bin/env python3
"""Archivio delle approvazioni del modo «approvazione» della chat (2026-10-03).

Decisione dell'utente del 2026-10-03: niente --dangerously-skip-permissions. In modo «approvazione»
claude parte in modalità normale e ogni permesso che non è nella lista automatica passa da qui:
lo crea approvazioni_mcp.py (il gestore dei permessi lanciato da claude), lo mostra il Command
Center (server.py: GET /api/approvazioni, evento «approvazione» sul flusso, Telegram), lo decide
L'utente (POST /api/azione tipo «approva»). Contratto: command-center/CONTRATTO-approvazioni.md.

Perché un file condiviso e non l'API del Command Center: il gestore dei permessi gira dentro il
processo di claude, e tutto quello che sa lui lo può leggere anche il modello (ambiente, argomenti,
file temporanei). Il token delle POST del pannello non deve arrivare lì: con quello il modello
potrebbe approvarsi da solo con un curl. Il file sta fuori da git e fuori da OneDrive
(~/.locale-onedrive/jarvis-cc/approvazioni/, permessi 0700), con un lock (fcntl) per le scritture
di più processi. Il Command Center scrive anche un «battito»: se manca da più di 30 s il gestore
risponde subito «no» invece di aspettare 15 minuti una scheda che nessuno vede.

Formato: approvazioni.jsonl, una riga per ogni cambio (l'ultima riga di un id vince). Si compatta
da solo oltre 2000 righe. Solo libreria standard. Importabile da server.py e dal gestore.
"""
import hashlib
import json
import os
import re
import shlex
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:          # Windows: un processo solo, basta il lock dei thread
    fcntl = None

HOME = Path.home()
QUI = Path(__file__).resolve().parent


def cartella():
    """La cartella dei dati. CC_APPROVAZIONI_DIR serve alle prove (cartella temporanea)."""
    c = Path(os.environ.get("CC_APPROVAZIONI_DIR") or HOME / ".locale-onedrive" / "jarvis-cc" / "approvazioni")
    c.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(c, 0o700)
    except OSError:
        pass
    return c


def scadenza_s():
    """15 minuti; CC_APPROVAZIONI_SCADENZA_S la accorcia nelle prove."""
    try:
        return max(1, int(os.environ.get("CC_APPROVAZIONI_SCADENZA_S") or 900))
    except ValueError:
        return 900


try:                          # oltre, il Command Center si considera spento (le prove lo accorciano)
    BATTITO_MAX_S = max(1, int(os.environ.get("CC_APPROVAZIONI_BATTITO_S") or 30))
except ValueError:
    BATTITO_MAX_S = 30
RIGHE_MAX = 2000              # oltre, il file si compatta
TIENI = 300                   # quante approvazioni decise restano dopo la compattazione
STATI = ("attesa", "approvata", "rifiutata", "scaduta")
DA_AMMESSI = ("web", "mac", "telegram", "nessuno")
_LOCK_THREAD = threading.Lock()


class NonTrovata(KeyError):
    pass


class Scaduta(ValueError):
    pass


class Troncata(ValueError):
    """Revisione 4: il comando mostrato è tagliato, la parte finale non si è vista: si può solo rifiutare."""


def e_troncata(a):
    d = (a or {}).get("dettagli")
    return isinstance(d, dict) and d.get("troncato") is True


class TroppeInAttesa(RuntimeError):
    """Revisione 3 (F8): troppe schede in attesa (in tutto o dello stesso lavoro): si rifiuta senza scheda."""


MAX_IN_ATTESA = 50            # in tutto
MAX_IN_ATTESA_LAVORO = 10     # dello stesso lavoro


# ---------------------------------------------------------------- testi senza segreti

SEGRETI = re.compile(r"(sk-ant-[\w-]+|sk-[\w-]{20,}|gh[pousr]_\w{20,}|github_pat_\w+|xox[abpr]-[\w-]+|"
                     r"AKIA[0-9A-Z]{16}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+|\b\d{8,10}:[\w-]{30,}\b|"
                     r"-----BEGIN [A-Z ]*PRIVATE KEY-----)")
PAROLE_SEGRETE = re.compile(r"(token|password|passwd|passw|pwd|chiave|secret|segret|api[_-]?key|apikey|"
                            r"bearer|authorization|credential|cookie|private[_-]?key)", re.I)
FILE_SEGRETI = re.compile(r"(^|/)(\.env[\w.-]*|[\w.-]*\.env|\.ssh/|id_(rsa|ed25519|ecdsa)\w*|[\w.-]*\.(pem|key|p12|pfx)$|"
                          r"\.segreti[\w-]*/|\.netrc$|\.pgpass$|credentials(\.json)?$|\.npmrc$|\.pypirc$|"
                          r"\.git-credentials$|\.aws/|\.docker/config\.json$|keychain)", re.I)


def e_file_segreto(percorso):
    return bool(percorso) and bool(FILE_SEGRETI.search(str(percorso)))


def pulisci(testo, n=800):
    """Testo pronto da mostrare: righe con parole da segreto nascoste, token noti mascherati, troncato a n."""
    if testo is None:
        return ""
    if not isinstance(testo, str):
        testo = json.dumps(testo, ensure_ascii=False, default=str)
    righe = []
    for r in testo.splitlines() or [testo]:
        if PAROLE_SEGRETE.search(r):
            righe.append("[riga nascosta: possibile segreto]")
        else:
            righe.append(SEGRETI.sub(lambda m: m.group(0)[:4] + "…[nascosto]", r))
    out = "\n".join(righe)
    return out if len(out) <= n else out[:max(0, n - 1)] + "…"


# ---------------------------------------------------------------- testi da approvare (revisione 2, F3)
# La scheda mostra quello che l'utente approva: mai una riga nascosta. Si maschera solo il VALORE di un segreto
# (CHIAVE=valore, --token valore, Authorization: Bearer xxx, token noti, password negli URL), il resto resta
# leggibile; i caratteri di controllo diventano visibili; oltre il tetto lo si dice con il numero dei caratteri.
MOSTRA_MAX = 4000
RIEPILOGO_MAX = 300
MASCHERA = "«valore mascherato»"
_NOMI_CHIAVE = r"[A-Za-z0-9_.-]*(?:token|password|passwd|passw|pwd|secret|segret|api[_-]?key|apikey|chiave|credential|cookie|auth|private[_-]?key|client[_-]?secret)[A-Za-z0-9_.-]*"
_NO = r"(?![«$`])(?!(?:bearer|basic|token)\b)"
_VALORI = [
    (re.compile(r"(?i)((?:authorization|proxy-authorization|cookie|set-cookie|x-token|x-api-key|x-auth-token)\s*:\s*)((?:bearer|basic|token)\s+)?" + _NO + r"([^\s'\"]+)"), 3),
    (re.compile(r"(?i)\b(bearer\s+)(?!«)([A-Za-z0-9._~+/=-]{8,})"), 2),
    (re.compile(r"(?i)(--?" + _NOMI_CHIAVE + r"(?:=|\s+))" + _NO + r"(\"[^\"]*\"|'[^']*'|[^\s'\"]+)"), 2),
    (re.compile(r"(?i)(\b" + _NOMI_CHIAVE + r"\s*[=:]\s*)" + _NO + r"(\"[^\"]*\"|'[^']*'|[^\s,;'\"]+)"), 2),
    (re.compile(r"(?i)(\w+://[^/\s:@]+:)(?!«)([^@/\s]+)(@)"), 2),
]
_CONTROLLO = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _maschera_valori(t):
    n = 0

    def sost(gruppo):
        def f(m):
            nonlocal n
            if m.group(gruppo) in (None, "") or m.group(gruppo) == MASCHERA:
                return m.group(0)
            n += 1
            return m.group(0)[:m.start(gruppo) - m.start(0)] + MASCHERA + m.group(0)[m.end(gruppo) - m.start(0):]
        return f
    for rx, g in _VALORI:
        t = rx.sub(sost(g), t)

    def noto(m):
        nonlocal n
        n += 1
        return m.group(0)[:4] + "…" + MASCHERA
    t = SEGRETI.sub(noto, t)
    return t, n


def mostra(testo, n=MOSTRA_MAX):
    """(testo da mostrare, {"troncato": caratteri non mostrati, "mascherati": valori mascherati}).
    Nessuna riga sparisce; i caratteri di controllo (\\r compreso) si vedono come ␍ o \\xNN."""
    if testo is None:
        return "", {"troncato": 0, "mascherati": 0}
    if not isinstance(testo, str):
        testo = json.dumps(testo, ensure_ascii=False, default=str)
    t = testo.replace("\r", "␍").replace("\t", "    ")
    t = _CONTROLLO.sub(lambda m: f"\\x{ord(m.group(0)):02x}", t)
    t, k = _maschera_valori(t)
    via = max(0, len(t) - n)
    if via:
        t = t[:n] + f"\n… [comando troncato: {via} caratteri non mostrati]"
    return t, {"troncato": via, "mascherati": k}


def breve_percorso(p):
    s = str(p or "")
    h = str(HOME)
    return "~" + s[len(h):] if s.startswith(h) else s


# ---------------------------------------------------------------- rischio

STRUMENTI_LETTURA = {"Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "TodoWrite", "NotebookRead",
                     "BashOutput", "ToolSearch"}
STRUMENTI_SCRITTURA = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASH_ALTO = re.compile(
    r"(^|[\s;&|(`$])(rm|mv|sudo|chmod|chown|kill|pkill|killall|dd|launchctl|crontab|osascript|ssh|scp|rsync|"
    r"shutdown|reboot|diskutil|security|defaults\s+write)\b"
    r"|curl[^|;&]*\|\s*(ba|z)?sh\b|wget[^|;&]*\|\s*(ba|z)?sh\b"
    r"|\bgit\s+(push|reset|clean|rebase|filter-repo|filter-branch|checkout\s+--)\b"
    r"|\b(pip3?|pipx|uv\s+pip)\s+install\b|\bnpm\s+(install|i|ci|uninstall)\b|\bbrew\s+(install|uninstall)\b"
    r"|\bdocker\s+(rm|rmi|prune|stop|kill|compose\s+down|system|volume)\b"
    r"|\b(DROP|TRUNCATE|DELETE\s+FROM)\b", re.I)


def _percorso_ingresso(ingresso):
    return (ingresso or {}).get("file_path") or (ingresso or {}).get("notebook_path") or (ingresso or {}).get("path") or ""


def _dentro(percorso, cwd):
    """Il percorso sta dentro la cartella di lavoro (dopo aver risolto collegamenti e ~)."""
    if not percorso or not cwd:
        return False
    try:
        p = Path(os.path.expanduser(str(percorso)))
        if not p.is_absolute():
            p = Path(cwd) / p
        p = Path(os.path.realpath(p))
        c = Path(os.path.realpath(os.path.expanduser(str(cwd))))
        return p == c or c in p.parents
    except (OSError, ValueError):
        return False


def rischio(strumento, ingresso, cwd=None):
    """basso / medio / alto, con euristiche semplici (vedi CONTRATTO, sez. 1)."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    if strumento == "Bash":
        cmd = str(ingresso.get("command") or "")
        if BASH_ALTO.search(cmd):
            return "alto"
        if re.search(r">\s*[~/]", cmd) or e_file_segreto(cmd):
            return "alto"          # scrive con una redirezione su un percorso assoluto, o tocca segreti
        return "basso" if bash_sola_lettura(cmd, cwd) else "medio"
    if strumento in STRUMENTI_SCRITTURA:
        p = _percorso_ingresso(ingresso)
        if e_file_segreto(p) or re.search(r"(^|/)(\.git|\.claude)(/|$)", str(p)):
            return "alto"
        return "medio" if _dentro(p, cwd) else "alto"
    if strumento in STRUMENTI_LETTURA:
        return "medio" if e_file_segreto(_percorso_ingresso(ingresso)) else "basso"
    if strumento in ("Task", "Agent"):
        return "basso"
    return "medio"


# ---------------------------------------------------------------- lista automatica

DEFAULT_AUTO = {
    "strumenti": ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"],
    "bash": ["ls", "cat", "head", "tail", "pwd", "wc", "date", "whoami",
             "git status", "git log", "git diff", "git show", "git branch",
             "python3 ~/Jarvis/strumenti/cerca_memoria.py",
             "python3 ~/Jarvis/strumenti/lavori.py chi"],
}
_META_SHELL = re.compile(r"[;&|<>`$\n\\(){}*?\[\]!]")


def config_auto(file_config=None):
    """approvazioni_auto da configurazione.json ({"strumenti": [...], "bash": [...]}); se manca, il default."""
    f = Path(file_config) if file_config else QUI / "configurazione.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8")).get("approvazioni_auto")
    except (OSError, ValueError, AttributeError):
        d = None
    if not isinstance(d, dict):
        return {k: list(v) for k, v in DEFAULT_AUTO.items()}
    return {"strumenti": [str(x) for x in d.get("strumenti", DEFAULT_AUTO["strumenti"]) if isinstance(x, str)],
            "bash": [str(x) for x in d.get("bash", DEFAULT_AUTO["bash"]) if isinstance(x, str)]}


def _norma_token(t, cwd):
    """~, $HOME e collegamenti risolti: «~/Jarvis/x» e «/Users/…/.locale-onedrive/Jarvis/x» sono uguali."""
    t = t.replace("$HOME", str(HOME))
    if t.startswith("~") or t.startswith("/") or ("/" in t and cwd):
        p = os.path.expanduser(t)
        if not os.path.isabs(p) and cwd:
            p = os.path.join(cwd, p)
        return os.path.realpath(p)
    return t


def bash_sola_lettura(cmd, cwd=None, regole=None):
    """Il comando è uno solo, senza metacaratteri della shell, e comincia come una delle regole."""
    cmd = (cmd or "").strip()
    if not cmd or _META_SHELL.search(cmd):
        return False
    try:
        parti = shlex.split(cmd)
    except ValueError:
        return False
    if any(p.startswith("--output") or p in ("-o",) for p in parti):
        return False                     # git log --output=file scrive
    if any(e_file_segreto(p) for p in parti):
        return False                     # cat ~/.env.jarvis non passa da solo
    norm = [_norma_token(p, cwd) for p in parti]
    for regola in (regole if regole is not None else DEFAULT_AUTO["bash"]):
        try:
            r = [_norma_token(p, cwd) for p in shlex.split(regola)]
        except ValueError:
            continue
        if r and norm[:len(r)] == r:
            return True
    return False


def auto_approvata(strumento, ingresso, cwd=None, conf=None):
    """True se la richiesta passa senza chiedere (lista automatica). Mai per i file di segreti."""
    conf = conf or config_auto()
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    if strumento == "Bash":
        return bash_sola_lettura(ingresso.get("command"), cwd, conf.get("bash"))
    if strumento in conf.get("strumenti", []):
        if e_file_segreto(_percorso_ingresso(ingresso)) or e_file_segreto(ingresso.get("pattern") if strumento == "Glob" else ""):
            return False
        return True
    return False


# ---------------------------------------------------------------- riepilogo e dettagli

def _riga(testo, n=RIEPILOGO_MAX):
    """Una riga di al massimo n caratteri, indicatore compreso."""
    t, info = mostra(" ".join(str(testo or "").split()), 10 ** 6)
    if len(t) <= n:
        return t
    tenuti = n - len(f" … [troncato: {len(t)} caratteri non mostrati]")
    return t[:tenuti] + f" … [troncato: {len(t) - tenuti} caratteri non mostrati]"


def riepilogo(strumento, ingresso):
    """Una riga (fino a 300 caratteri) con i valori dei segreti mascherati, mai una riga nascosta."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    p = breve_percorso(_percorso_ingresso(ingresso))
    if strumento == "Bash":
        return _riga("Lanciare: " + str(ingresso.get("command") or ""))
    if strumento == "Write":
        return _riga(f"Scrivere {p}")
    if strumento in ("Edit", "MultiEdit", "NotebookEdit"):
        return _riga(f"Modificare {p}")
    if strumento == "Read":
        return _riga(f"Leggere {p}")
    if strumento in ("Grep", "Glob"):
        return _riga(f"Cercare {ingresso.get('pattern', '')} in {breve_percorso(ingresso.get('path') or '.')}"
                     + (f" (file {ingresso.get('glob')})" if ingresso.get("glob") else ""))
    if strumento == "WebFetch":
        return _riga(f"Aprire {ingresso.get('url', '')}")
    if strumento == "WebSearch":
        return _riga(f"Cercare sul web: {ingresso.get('query', '')}")
    if strumento in ("Task", "Agent"):
        return _riga(f"Chiedere a un agente: {ingresso.get('description') or ingresso.get('subagent_type') or ''}")
    return _riga(f"Usare {strumento}")


def _con_info(d, campo, testo):
    t, info = mostra(testo)
    d[campo] = t
    if info["troncato"]:
        d["troncato"] = True
        d["caratteri_non_mostrati"] = d.get("caratteri_non_mostrati", 0) + info["troncato"]
    if info["mascherati"]:
        d["valori_mascherati"] = d.get("valori_mascherati", 0) + info["mascherati"]
    return d


def dettagli(strumento, ingresso, cwd=None):
    """I campi pertinenti, interi fino a 4000 caratteri (oltre: «troncato» e quanti caratteri mancano), con i
    soli VALORI dei segreti mascherati. Il contenuto di un file di segreti non si mostra."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    p = _percorso_ingresso(ingresso)
    segreto = e_file_segreto(p)
    nascosto = "[file di segreti: contenuto non mostrato]"
    if strumento == "Bash":
        return _con_info({}, "comando", ingresso.get("command"))
    if strumento == "Write":
        testo = str(ingresso.get("content") or "")
        d = {"percorso": breve_percorso(p), "righe_aggiunte": len(testo.splitlines()), "righe_tolte": 0}
        return dict(d, anteprima=nascosto) if segreto else _con_info(d, "anteprima", testo)
    if strumento in ("Edit", "MultiEdit"):
        modifiche = ingresso.get("edits") if strumento == "MultiEdit" else [ingresso]
        agg = tol = 0
        pezzi = []
        for m in modifiche or []:
            if not isinstance(m, dict):
                continue
            vecchio, nuovo = str(m.get("old_string") or ""), str(m.get("new_string") or "")
            tol += len(vecchio.splitlines())
            agg += len(nuovo.splitlines())
            pezzi += ["- " + r for r in vecchio.splitlines()] + ["+ " + r for r in nuovo.splitlines()]
        d = {"percorso": breve_percorso(p), "righe_aggiunte": agg, "righe_tolte": tol}
        return dict(d, anteprima=nascosto) if segreto else _con_info(d, "anteprima", "\n".join(pezzi))
    if strumento == "NotebookEdit":
        return _con_info({"percorso": breve_percorso(p)}, "anteprima", ingresso.get("new_source"))
    if p:
        return {"percorso": breve_percorso(p)}
    if strumento == "WebFetch":
        return _con_info({}, "url", ingresso.get("url"))
    return _con_info({}, "anteprima", json.dumps(ingresso, ensure_ascii=False, default=str))


# ---------------------------------------------------------------- archivio

def _file():
    return cartella() / "approvazioni.jsonl"


@contextmanager
def _bloccato(esclusivo=True):
    with _LOCK_THREAD:
        f = os.fdopen(os.open(cartella() / "approvazioni.lock", os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), "a+")
        try:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX if esclusivo else fcntl.LOCK_SH)
            yield
        finally:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
            f.close()


def _leggi_tutte():
    """{id: A} nell'ordine di nascita. Le righe rotte (scrittura a metà) si saltano."""
    out = {}
    try:
        with open(_file(), encoding="utf-8") as f:
            for riga in f:
                try:
                    a = json.loads(riga)
                except ValueError:
                    continue
                if isinstance(a, dict) and a.get("id"):
                    out[a["id"]] = a
    except FileNotFoundError:
        pass
    return out


def _accoda(a):
    nuovo = not _file().exists()
    with open(_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(a, ensure_ascii=False) + "\n")
    if nuovo:
        try:
            os.chmod(_file(), 0o600)
        except OSError:
            pass


def _compatta_se_serve(tutte):
    try:
        with open(_file(), encoding="utf-8") as f:
            n = sum(1 for _ in f)
    except FileNotFoundError:
        return
    if n <= RIGHE_MAX:
        return
    attesa = [a for a in tutte.values() if a.get("stato") == "attesa"]
    decise = [a for a in tutte.values() if a.get("stato") != "attesa"][-TIENI:]
    tmp = _file().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for a in sorted(attesa + decise, key=lambda x: x.get("creata") or 0):
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, _file())


def _scadi_dentro(tutte, adesso):
    cambiate = []
    for a in tutte.values():
        if a.get("stato") == "attesa" and adesso >= (a.get("scade") or 0):
            a.update(stato="scaduta", deciso_da="nessuno", deciso=int(adesso))
            _accoda(a)
            cambiate.append(dict(a))
    return cambiate


def pubblica(a):
    """La forma del contratto: senza i campi interni."""
    return {k: v for k, v in a.items() if k not in ("chiave", "corsa")} if a else a


def _chiave(strumento, ingresso, lavoro_id, sessione):
    base = json.dumps([strumento, ingresso, lavoro_id or "", sessione or ""], sort_keys=True, default=str)
    return hashlib.sha1(base.encode()).hexdigest()


def crea(strumento, ingresso, cwd=None, lavoro_id=None, sessione=None, agente="Jarvis", regola=None, rischio_regola=None):
    """(A, nuova). Se la stessa richiesta dello stesso lavoro è già in attesa, torna quella (una scheda sola).
    regola (2026-10-03, CONTRATTO-registro.md): l'id della regola di regole_permessi.py che ha chiesto la scheda,
    o «predefinita»; rischio_regola: il rischio scritto nella regola, se c'è (altrimenti quello calcolato qui)."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    chiave = _chiave(strumento, ingresso, lavoro_id, sessione)
    adesso = time.time()
    with _bloccato():
        tutte = _leggi_tutte()
        _scadi_dentro(tutte, adesso)
        for a in tutte.values():
            if a.get("stato") == "attesa" and a.get("chiave") == chiave:
                return pubblica(a), False
        attesa = [a for a in tutte.values() if a.get("stato") == "attesa"]
        if len(attesa) >= MAX_IN_ATTESA or (lavoro_id and sum(1 for a in attesa if a.get("lavoro_id") == lavoro_id) >= MAX_IN_ATTESA_LAVORO):
            raise TroppeInAttesa(f"troppe richieste in attesa ({len(attesa)}): rifiutata senza scheda")
        dett = dettagli(strumento, ingresso, cwd)
        a = {"id": "ap_" + uuid.uuid4().hex[:8], "creata": int(adesso), "scade": int(adesso + scadenza_s()),
             "lavoro_id": lavoro_id or None, "sessione": sessione or None, "agente": str(agente or "Jarvis")[:80],
             "strumento": str(strumento)[:80], "riepilogo": riepilogo(strumento, ingresso),
             "dettagli": dett,
             # testo non mostrabile intero = rischio alto, qualunque cosa dica la regola (revisione 2, F3)
             "rischio": "alto" if dett.get("troncato") else (rischio_regola if rischio_regola in ("basso", "medio", "alto")
                                                            else rischio(strumento, ingresso, cwd)),
             "regola": str(regola)[:48] if regola else None,
             "stato": "attesa", "deciso_da": None, "deciso": None, "chiave": chiave}
        _accoda(a)
        _compatta_se_serve({**tutte, a["id"]: a})
    return pubblica(a), True


def leggi(id_):
    """A aggiornata (con la scadenza applicata), o None."""
    with _bloccato():
        tutte = _leggi_tutte()
        _scadi_dentro(tutte, time.time())
        a = tutte.get(id_)
    return pubblica(a) if a else None


def decidi(id_, decisione, da="web", motivo=""):
    """(A, gia_deciso). decisione «si»/«no». NonTrovata se non c'è, Scaduta se è scaduta."""
    if decisione not in ("si", "no"):
        raise ValueError("decisione: si o no")
    if not isinstance(id_, str) or not re.fullmatch(r"ap_[0-9a-f]{8}", id_):
        raise NonTrovata("approvazione non trovata")
    da = da if da in DA_AMMESSI else "web"
    with _bloccato():
        tutte = _leggi_tutte()
        _scadi_dentro(tutte, time.time())
        a = tutte.get(id_)
        if not a:
            raise NonTrovata("approvazione non trovata")
        if a["stato"] == "scaduta":
            raise Scaduta("approvazione scaduta: il motore ha già ricevuto un rifiuto")
        if a["stato"] != "attesa":
            return pubblica(a), True
        if decisione == "si" and e_troncata(a):
            raise Troncata("il comando è stato tagliato e la parte finale non si è vista: si può solo rifiutare")
        a.update(stato="approvata" if decisione == "si" else "rifiutata", deciso_da=da, deciso=int(time.time()))
        if motivo:
            a["motivo"] = pulisci(str(motivo), 300)
        _accoda(a)
    return pubblica(a), False


def scadi():
    """Segna «scaduta» quelle oltre il tempo. Torna le cambiate."""
    with _bloccato():
        return [pubblica(a) for a in _scadi_dentro(_leggi_tutte(), time.time())]


def chiudi_lavoro(lavoro_id):
    """Il lavoro è finito: le sue richieste ancora in attesa non le aspetta più nessuno → «scaduta»."""
    if not lavoro_id:
        return []
    cambiate = []
    with _bloccato():
        for a in _leggi_tutte().values():
            if a.get("stato") == "attesa" and a.get("lavoro_id") == lavoro_id:
                a.update(stato="scaduta", deciso_da="nessuno", deciso=int(time.time()))
                _accoda(a)
                cambiate.append(pubblica(a))
    return cambiate


def elenco(n_recenti=20):
    with _bloccato():
        tutte = _leggi_tutte()
        _scadi_dentro(tutte, time.time())
    vals = list(tutte.values())
    attesa = [pubblica(a) for a in vals if a.get("stato") == "attesa"]
    decise = sorted((a for a in vals if a.get("stato") != "attesa"), key=lambda a: a.get("deciso") or 0)
    return {"in_attesa": attesa, "recenti": [pubblica(a) for a in decise[-n_recenti:]][::-1], "ora": int(time.time())}


def istantanea():
    """{id: (stato, deciso)} per chi deve accorgersi dei cambi (il sorvegliante di server.py)."""
    with _bloccato(esclusivo=False):
        return {k: (a.get("stato"), a.get("deciso")) for k, a in _leggi_tutte().items()}


def tutte_pubbliche():
    with _bloccato(esclusivo=False):
        return {k: pubblica(a) for k, a in _leggi_tutte().items()}


# ---------------------------------------------------------------- battito del Command Center

def batti(porta=None):
    f = cartella() / "battito.json"
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # 0600 (revisione 2, R6)
    with os.fdopen(fd, "w") as h:
        h.write(json.dumps({"ts": time.time(), "pid": os.getpid(), "porta": porta}))
    os.replace(tmp, f)


def command_center_vivo():
    try:
        d = json.loads((cartella() / "battito.json").read_text())
        return time.time() - float(d.get("ts") or 0) < BATTITO_MAX_S
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------- attività in diretta (contratto, sez. 2)

def _nome_file(p):
    return os.path.basename(str(p).rstrip("/")) or str(p)


def voce_attivita(strumento, ingresso):
    """(tipo, testo, percorso|None) di un tool_use. Testo max 120 caratteri, in italiano, senza segreti."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    p = _percorso_ingresso(ingresso)
    if strumento == "Read":
        return "leggo", pulisci(f"leggo {_nome_file(p)}", 120), p
    if strumento in STRUMENTI_SCRITTURA:
        return "scrivo", pulisci(f"scrivo {_nome_file(p)}", 120), p
    if strumento == "Bash":
        return "lancio", pulisci("lancio " + " ".join(str(ingresso.get("command") or "").split()), 120), None
    if strumento == "Grep":
        return "cerco", pulisci(f"cerco «{ingresso.get('pattern', '')}»", 120), None
    if strumento == "Glob":
        return "cerco", pulisci(f"cerco i file {ingresso.get('pattern', '')}", 120), None
    if strumento == "WebSearch":
        return "web", pulisci(f"cerco sul web: {ingresso.get('query', '')}", 120), None
    if strumento == "WebFetch":
        url = str(ingresso.get("url") or "")
        host = re.sub(r"^\w+://", "", url).split("/")[0]
        return "web", pulisci(f"cerco sul web: {host}", 120), None
    if strumento in ("Task", "Agent"):
        cosa = ingresso.get("description") or ingresso.get("subagent_type") or ""
        return "agente", pulisci(f"chiedo a un agente{': ' + str(cosa) if cosa else ''}", 120), None
    if strumento == "TodoWrite":
        return "penso", "penso (aggiorno la lista delle cose da fare)", None
    return "lancio", pulisci(f"uso {strumento}", 120), None


class LettoreAttivita:
    """Legge le righe stream-json di claude e restituisce le voci nuove o cambiate.

    tool_use → voce «in corso»; il tool_result con lo stesso id la chiude «ok» o «errore»;
    il testo del modello → «penso». Ogni voce restituita è un dict nuovo (chi la tiene in una
    lista la sostituisce, non la modifica sul posto)."""

    def __init__(self):
        self.per_id = {}
        self.file = []          # percorsi toccati, il più recente in fondo (senza file di segreti)

    def riga(self, riga, adesso=None):
        try:
            ev = json.loads(riga)
        except (ValueError, TypeError):
            return []
        if not isinstance(ev, dict):
            return []
        adesso = int(adesso or time.time())
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        contenuti = msg.get("content") if isinstance(msg.get("content"), list) else []
        out = []
        if ev.get("type") == "assistant":
            for c in contenuti:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    tipo, testo, p = voce_attivita(str(c.get("name") or ""), c.get("input"))
                    v = {"ts": adesso, "tipo": tipo, "testo": testo, "esito": "in corso"}
                    if c.get("id"):
                        self.per_id[c["id"]] = v
                    if p and not e_file_segreto(p):
                        bp = breve_percorso(p)
                        self.file = [x for x in self.file if x != bp][-9:] + [bp]
                    out.append(v)
                elif c.get("type") == "text" and str(c.get("text") or "").strip():
                    out.append({"ts": adesso, "tipo": "penso", "testo": "penso", "esito": "ok"})
        elif ev.get("type") == "user":
            for c in contenuti:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in self.per_id:
                    vecchia = self.per_id.pop(c["tool_use_id"])
                    out.append({**vecchia, "esito": "errore" if c.get("is_error") else "ok", "_sostituisce": vecchia})
        return out


# ---------------------------------------------------------------- regole «ask» per claude

ASK_BASE = ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"]


def regole_ask(file_settings=None):
    """Le regole «ask» da passare a claude con --settings: Bash, scritture e TUTTE le regole «allow» già
    presenti nei settings dell'utente (in ~/.claude/settings.json c'è, per esempio, Bash(python3 *), Bash(curl *),
    Bash(ssh *), Bash(git push *), l'invio di Gmail e Slack). In Claude Code «ask» vince su «allow»
    (verificato il 2026-10-03 con claude 2.1.288: python3 -c, coperto da Bash(python3 *), è passato dal
    gestore dei permessi). Così nessuna regola vecchia approva da sola: decide la lista automatica di qui."""
    file_settings = file_settings or [HOME / ".claude" / "settings.json", HOME / ".claude" / "settings.local.json",
                                      QUI.parent / ".claude" / "settings.json", QUI.parent / ".claude" / "settings.local.json"]
    regole = list(ASK_BASE)
    try:                         # 2026-10-03: gli strumenti delle regole «chiedi» e «nega» del file delle regole
        import regole_permessi
        regole += regole_permessi.strumenti_da_chiedere()
    except Exception:  # noqa: BLE001 — senza il file delle regole resta la lista di prima
        pass
    for f in file_settings:
        try:
            allow = (json.loads(Path(f).read_text(encoding="utf-8")).get("permissions") or {}).get("allow") or []
        except (OSError, ValueError, AttributeError):
            continue
        regole += [r for r in allow if isinstance(r, str)]
    return list(dict.fromkeys(regole))
