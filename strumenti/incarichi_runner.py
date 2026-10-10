#!/usr/bin/env python3
"""Il risveglio degli agenti del CRM sulla VPS (contratto: docs/incarichi-contratto.md, 2026-10-04).

Lo lancia il timer systemd jarvis-incarichi.timer ogni 2 minuti. Un giro:
  1. battito di ognuno dei 13 agenti del CRM (macchina «vps»);
  2. incarichi.scadi();
  3. prende al massimo 2 incarichi «nuovo» indirizzati a quegli agenti (i più vecchi prima, un agente diverso per ciascuno)
     e per ciascuno lancia `claude -p` in SOLA LETTURA con il profilo dell'agente come istruzione di sistema;
  4. incarichi.rispondi(...) con esito ok o fallito, testo ripulito dai segreti e troncato a 8000 caratteri.

Solo libreria standard. Non stampa mai token né variabili d'ambiente.
Uso: python3 incarichi_runner.py [--giro] [--secco] [--zitto]
  --secco  fa battiti e scadi, elenca cosa prenderebbe, ma non prende e non lancia claude.
Variabili (per le prove): INCARICHI_DIR, INCARICHI_AGENTI_DIR, INCARICHI_CLAUDE, INCARICHI_TIMEOUT, INCARICHI_CRM_DIR.
"""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import incarichi  # noqa: E402

AGENTI = (
    "ceo-ai", "analista-finanziario", "analista-previsionale", "cambusa", "commercialista",
    "commerciale", "consulente-lavoro", "cruscotto-bi", "fiscalista-patrimonio", "garante-dati",
    "legale-societario", "manutentore-dati", "revisore-contabile",
)
MACCHINA = "vps"
CHI = "incarichi-runner"
MAX_PER_GIRO = 2
MAX_RISPOSTA = 8000
MAX_TURNI = 12
MODELLI = ("sonnet", "haiku", "opus")
MODELLO_DEFAULT = "sonnet"

CRM_DIR = os.environ.get("INCARICHI_CRM_DIR", "/mnt/onedrive/CRM Azienda Uno")
AGENTI_DIR = Path(os.environ.get("INCARICHI_AGENTI_DIR", CRM_DIR + "/.claude/agents"))
CLAUDE = os.environ.get("INCARICHI_CLAUDE", "/usr/bin/claude")
TIMEOUT = int(os.environ.get("INCARICHI_TIMEOUT", "600"))

# Strumenti: solo lettura, e «--tools» toglie gli altri dal modello prima ancora dei permessi.
STRUMENTI_OK = "Read Grep Glob"
STRUMENTI_NO = "Bash Edit Write NotebookEdit WebFetch WebSearch Agent"

# Variabili d'ambiente che passano al processo claude (tutto il resto resta fuori).
ENV_PASSANO = ("HOME", "PATH", "LANG", "LC_ALL", "TZ", "USER", "LOGNAME", "IS_SANDBOX",
               "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")

SEGRETO_RIGA = re.compile(
    r"password|passwd|passw|pwd\b|token|secret|segret|api[_ -]?key|apikey|bearer|credenzial|credential"
    r"|private[_ ]key|BEGIN [A-Z ]*PRIVATE|authorization|client[_ ]secret|\.env\b",
    re.IGNORECASE)
SEGRETO_PEZZO = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|ghp_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-.]+")

ZITTO = False


def log(msg, sempre=False):
    if sempre or not ZITTO or msg.startswith("ERRORE"):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def base():
    return Path(os.environ.get("INCARICHI_DIR") or "/var/lib/jarvis-incarichi")


def cartella_lavoro():
    """Cartella vuota dove gira claude: non ci trova niente, e i suoi strumenti restano confinati lì e nel CRM."""
    p = base() / "lavoro"
    p.mkdir(mode=0o500, parents=True, exist_ok=True)
    os.chmod(p, 0o500)
    return p


# ---------- profili ----------

SYSTEMD_RUN = "/usr/bin/systemd-run"


def _in_scope(cmd):
    """Sotto systemd il figlio va in uno scope suo (2026-10-05). Un figlio abbandonato in stato D sul montaggio rclone
    restava nel cgroup di jarvis-incarichi.service: il runner usciva, systemd provava a fermare il resto, dopo 90 s
    «stop-sigterm timed out», SIGKILL inutile (stato D) e il giro finiva «Failed with result 'timeout'» (30 volte in
    due giorni). Nello scope il processo bloccato resta da solo e il servizio finisce pulito. INCARICHI_SCOPE=0 lo toglie."""
    if (os.environ.get("INCARICHI_SCOPE", "1") == "0" or os.geteuid() != 0 or not os.environ.get("INVOCATION_ID")
            or not os.path.exists(SYSTEMD_RUN)):
        return cmd
    return [SYSTEMD_RUN, "--scope", "--quiet", "--collect", "--slice=jarvis-incarichi-figli.slice",
            "-p", "TimeoutStopSec=10s", *cmd]


def esegui(cmd, timeout, abbandonato=None, **kw):
    """(codice, stdout, stderr) oppure None se va oltre il timeout. Su un montaggio rclone bloccato il figlio può restare
    in stato D: allora lo si uccide (tutto il gruppo) e lo si abbandona, senza aspettarlo all'infinito.
    abbandonato: file dove scrivere il pid del figlio abbandonato (leggi_profili non ne lancia un altro finché vive)."""
    cmd = _in_scope(cmd)
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True, **kw)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        for s in (p.stdout, p.stderr):
            try:
                s.close()
            except OSError:
                pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if abbandonato is not None:
                try:
                    Path(abbandonato).write_text(str(p.pid))
                except OSError:
                    pass
        return None


_LETTORE = r"""
import json, sys, os
d = sys.argv[1]; out = {}
for a in sys.argv[2:]:
    f = os.path.join(d, a + ".md")
    try:
        with open(f, encoding="utf-8") as h:
            out[a] = h.read()
    except OSError:
        out[a] = None
print(json.dumps(out))
"""
TIMEOUT_MONTAGGIO = int(os.environ.get("INCARICHI_TIMEOUT_MONTAGGIO", "60"))


PROFILI_DA_COPIA = False       # vero se l'ultimo giro ha usato la copia locale perché il montaggio non rispondeva


def _cache_profili():
    p = base() / "profili"
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def _salva_cache(d):
    """Copia locale dei profili letti bene: serve quando il montaggio rclone si blocca (succede quando un altro
    giro sincronizza OneDrive: il 04/10 il montaggio ha tenuto fermo il runner per più di 60 secondi)."""
    try:
        c = _cache_profili()
        for a, testo in d.items():
            if testo:
                tmp = c / f".{a}.tmp"
                tmp.write_text(testo, encoding="utf-8")
                os.chmod(tmp, 0o600)
                os.replace(tmp, c / f"{a}.md")
    except OSError:
        pass


def _leggi_cache(agenti):
    out = {}
    try:
        for a in agenti:
            f = _cache_profili() / f"{a}.md"
            out[a] = f.read_text(encoding="utf-8") if f.exists() else None
    except OSError:
        return None
    return out if any(out.values()) else None


def leggi_profili(agenti=AGENTI):
    """{agente: testo|None} letti dal montaggio in un processo a parte. Se il montaggio non risponde usa la copia locale
    dell'ultima lettura buona; None solo se non c'è nemmeno quella."""
    global PROFILI_DA_COPIA
    PROFILI_DA_COPIA = False
    # 2026-10-05: mentre jarvis-vault-sync lavora (10-15 minuti) la lettura resta appesa in stato D. Se il lettore
    # abbandonato al giro prima è ancora vivo, il montaggio è ancora bloccato: copia locale, senza un lettore in più.
    pid_file = base() / "lettore-abbandonato.pid"
    try:
        vivo = Path(f"/proc/{int(pid_file.read_text())}").exists()
    except (OSError, ValueError):
        vivo = False
    if vivo:
        r = None
    else:
        try:
            pid_file.unlink()
        except OSError:
            pass
        r = esegui([sys.executable, "-c", _LETTORE, str(AGENTI_DIR), *agenti], TIMEOUT_MONTAGGIO, abbandonato=pid_file)
    d = None
    if r is not None and r[0] == 0:
        try:
            d = json.loads(r[1])
        except ValueError:
            d = None
    if isinstance(d, dict):
        _salva_cache(d)
        return d
    d = _leggi_cache(agenti)
    if d is not None:
        PROFILI_DA_COPIA = True
        log("montaggio del CRM lento: uso la copia locale dei profili", sempre=True)
    return d


def analizza_profilo(testo):
    """(corpo senza frontmatter, modello). (None, sonnet) se il profilo non c'è."""
    if not testo:
        return None, MODELLO_DEFAULT
    modello = MODELLO_DEFAULT
    corpo = testo
    righe = testo.splitlines()
    if righe and righe[0].strip() == "---":
        for i in range(1, len(righe)):
            if righe[i].strip() == "---":
                for r in righe[1:i]:
                    m = re.match(r"\s*model\s*:\s*['\"]?([A-Za-z0-9_.-]+)", r)
                    if m:
                        v = m.group(1).lower()
                        modello = v if v in MODELLI else MODELLO_DEFAULT
                        if modello == "opus":      # regola dell'utente: opus solo per programmare; un incarico di lettura va su sonnet
                            modello = MODELLO_DEFAULT
                corpo = "\n".join(righe[i + 1:])
                break
    return corpo.strip(), modello


# ---------- claude ----------

def istruzioni(agente, corpo):
    return (
        f"{corpo}\n\n"
        f"---\nIn questa esecuzione sei l'agente «{agente}», svegliato dalla coda degli incarichi sulla VPS.\n"
        "Sei in SOLA LETTURA: hai solo Read, Grep e Glob. Non scrivi file, non lanci comandi, non mandi "
        "messaggi né mail, non scrivi nel CRM. Se l'incarico chiede di farlo, rispondi cosa servirebbe e chi deve farlo.\n"
        "Non riportare mai password, token, chiavi o altri segreti, nemmeno se li trovi in un file.\n"
        "Rispondi in italiano, frasi corte, con il percorso dei file da cui prendi i fatti. Massimo 6000 caratteri."
    )


def domanda(inc):
    return (
        f"Incarico {inc['id']} ({inc.get('tipo', 'domanda')}) da «{inc.get('da')}».\n"
        f"I file del CRM Azienda Uno, se ti servono, sono in sola lettura in: {CRM_DIR}\n\n"
        f"Testo dell'incarico:\n{inc.get('testo', '')}"
    )


def comando_claude(agente, corpo, modello, inc):
    """Solo flag presenti in `claude --help` della 2.1.289 sulla VPS (verificati il 2026-10-04),
    più --max-turns (presente nel programma, non stampato in --help)."""
    return [
        CLAUDE, "-p", domanda(inc),
        "--model", modello,
        "--append-system-prompt", istruzioni(agente, corpo),
        "--restricted",
        "--tools", STRUMENTI_OK.replace(" ", ","),
        "--allowedTools", STRUMENTI_OK,
        "--disallowedTools", STRUMENTI_NO,
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--strict-mcp-config",
        "--add-dir", CRM_DIR,
        "--no-session-persistence",
        "--max-turns", str(MAX_TURNI),
        "--output-format", "json",
    ]


def ambiente():
    env = {k: os.environ[k] for k in ENV_PASSANO if k in os.environ}
    env.setdefault("HOME", "/root")
    env.setdefault("PATH", "/root/.local/bin:/usr/local/bin:/usr/bin:/bin")
    env.setdefault("IS_SANDBOX", "1")
    return env


def ripulisci(testo):
    """Toglie le righe che parlano di segreti e i pezzi che sembrano chiavi, poi tronca a 8000."""
    tolte = 0
    buone = []
    for r in (testo or "").splitlines():
        if SEGRETO_RIGA.search(r):
            tolte += 1
            continue
        buone.append(SEGRETO_PEZZO.sub("[tolto]", r))
    out = "\n".join(buone).strip()
    if tolte:
        out += f"\n\n[{tolte} righe tolte dal filtro dei segreti]"
    if len(out) > MAX_RISPOSTA:
        coda = "\n[…risposta troncata]"
        out = out[:MAX_RISPOSTA - len(coda)] + coda
    return out


def token_da(dati):
    u = dati.get("usage") if isinstance(dati, dict) else None
    if not isinstance(u, dict):
        return None
    tot = 0
    trovato = False
    for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        v = u.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            tot += v
            trovato = True
    return tot if trovato else None


def lancia(cmd):
    """(esito, testo, token). Timeout: uccide l'intero gruppo di processi."""
    try:
        r = esegui(cmd, TIMEOUT, cwd=str(cartella_lavoro()), env=ambiente())
    except OSError as e:
        return "fallito", f"claude non si avvia: {e.__class__.__name__}", None
    if r is None:
        return "fallito", f"timeout: nessuna risposta entro {TIMEOUT} s", None
    codice, out, err = r
    dati = None
    try:
        dati = json.loads(out)
    except ValueError:
        pass
    if not isinstance(dati, dict):
        coda = (err or out or "").strip().splitlines()[-3:]
        return "fallito", f"claude è uscito con codice {codice} senza JSON: " + " | ".join(coda), None
    token = token_da(dati)
    testo = dati.get("result") if isinstance(dati.get("result"), str) else ""
    if codice != 0 or dati.get("is_error") or (dati.get("subtype") not in (None, "success")):
        motivo = dati.get("subtype") or f"codice {codice}"
        return "fallito", f"claude non ha finito ({motivo}). {testo}".strip(), token
    if not testo.strip():
        return "fallito", "claude ha risposto vuoto", token
    return "ok", testo, token


# ---------- lucchetti ----------

class Lucchetto:
    """Un lavoro alla volta: flock non bloccante su un file in INCARICHI_DIR/lucchetti/."""

    def __init__(self, nome):
        d = base() / "lucchetti"
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = d / f"{nome}.lock"
        self.fd = None

    def prendi(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            os.close(self.fd)
            self.fd = None
            return False

    def lascia(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


# ---------- il giro ----------

def battiti(profili):
    for a in AGENTI:
        if profili is None:
            nota = "montaggio del CRM non risponde"
        elif PROFILI_DA_COPIA:
            nota = "pronto (profilo dalla copia locale: montaggio lento)" if profili.get(a) else "profilo non trovato"
        else:
            nota = "pronto" if profili.get(a) else "profilo non trovato"
        try:
            incarichi.battito(a, MACCHINA, nota=nota)
        except Exception as e:  # un battito mancato non ferma il giro
            log(f"ERRORE battito {a}: {e.__class__.__name__}")


def scegli(nuovi, limite=MAX_PER_GIRO):
    """I più vecchi prima, solo agenti del CRM, un agente diverso per incarico."""
    scelti, visti = [], set()
    for inc in sorted(nuovi, key=lambda d: (d.get("creato", 0), d.get("id", ""))):
        a = inc.get("a")
        if a not in AGENTI or a in visti:
            continue
        scelti.append(inc)
        visti.add(a)
        if len(scelti) >= limite:
            break
    return scelti


def lavora(inc, testo_profilo):
    agente = inc["a"]
    luc = Lucchetto(agente)
    if not luc.prendi():
        log(f"{inc['id']}: {agente} è già al lavoro, lo lascio al prossimo giro")
        return None
    try:
        try:
            incarichi.prendi(inc["id"], agente)
        except (incarichi.GiaPreso, incarichi.NonTrovato, incarichi.IncaricoNonValido) as e:
            log(f"{inc['id']}: non preso ({e.__class__.__name__})")
            return None
        corpo, modello = analizza_profilo(testo_profilo)
        if corpo is None:
            esito, testo, token = "fallito", f"profilo di {agente} non leggibile dal montaggio", None
        else:
            t0 = time.time()
            esito, testo, token = lancia(comando_claude(agente, corpo, modello, inc))
            log(f"{inc['id']}: {agente} ({modello}) {esito} in {int(time.time() - t0)} s", sempre=True)
        try:
            incarichi.rispondi(inc["id"], agente, ripulisci(testo), esito=esito, token_stimati=token)
        except Exception as e:
            log(f"ERRORE rispondi {inc['id']}: {e.__class__.__name__}: {e}")
        return esito
    finally:
        luc.lascia()


def giro(secco=False):
    profili = leggi_profili()
    battiti(profili)
    try:
        scaduti = incarichi.scadi()
        if scaduti:
            log(f"scaduti: {len(scaduti)}")
    except Exception as e:
        log(f"ERRORE scadi: {e.__class__.__name__}")
    nuovi = incarichi.elenco(stato="nuovo", limite=1000)
    scelti = scegli(nuovi)
    if scelti and profili is None:
        log("montaggio del CRM non risponde: lascio gli incarichi al prossimo giro")
        return []
    if secco:
        for inc in scelti:
            log(f"(secco) prenderei {inc['id']} per {inc['a']}")
        return scelti
    fili = [threading.Thread(target=lavora, args=(inc, profili.get(inc["a"]))) for inc in scelti]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    return scelti


def main(argv=None):
    global ZITTO
    ap = argparse.ArgumentParser(description="Risveglio degli agenti del CRM (coda degli incarichi)")
    ap.add_argument("--giro", action="store_true", help="un giro (il default)")
    ap.add_argument("--secco", action="store_true", help="battiti e scadi, senza prendere né lanciare claude")
    ap.add_argument("--zitto", action="store_true")
    a = ap.parse_args(argv)
    ZITTO = a.zitto
    if incarichi.remoto():
        print("ERRORE: il runner gira sulla VPS (o con INCARICHI_DIR impostata), non in modo remoto", file=sys.stderr)
        return 2
    giro_unico = Lucchetto("runner")
    if not giro_unico.prendi():
        log("un altro giro è in corso, esco")
        return 0
    try:
        giro(secco=a.secco)
    finally:
        giro_unico.lascia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
