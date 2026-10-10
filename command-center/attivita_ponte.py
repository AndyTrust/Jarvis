#!/usr/bin/env python3
"""Il registro delle attività fra Mac e VPS, in pochi secondi (2026-10-05, «lavagna viva»).

L'utente guarda la lavagna sul sito (Command Center della VPS) e sul Mac. Gli agenti della chat master girano sul
Mac e il gancio scrive nel registro del Mac (~/my-agent/backtalk/attivita/AAAA-MM-GG.jsonl); la coda incarichi
e la chat del sito scrivono in quello della VPS. Il registro dei lavori su OneDrive arriva alla VPS con minuti
di ritardo (rclone bisync ogni 5 minuti): troppo per un Dot che cammina. Qui, solo sul Mac, due fili ssh:

  manda   righe nuove del registro del Mac  → VPS  ~/my-agent/backtalk/attivita/remoti/mac-<giorno del Mac>.jsonl
          (un `cat >>` che resta aperto: ogni riga arriva appena scritta)
  ricevi  righe nuove del registro della VPS → Mac  remoti/vps-<giorno UTC>.jsonl   (`tail -c +N -F`)

attivita.Lettore legge anche remoti/ (stesso formato, righe intatte). Le righe della coda incarichi
(fonte «incarichi», id «inc:») non viaggiano: le due macchine le scrivono già ciascuna con il suo ponte.
Le righe arrivate da fuori stanno solo in remoti/, quindi non tornano indietro (niente giri a vuoto).
Nessun segreto: le righe sono quelle del registro (chi, a chi, testo corto); la connessione è la stessa
`ssh vps-tuo` degli altri strumenti. Se la VPS non risponde: si riprova ogni 10 s, una riga di log
ogni 5 minuti. Dove si è arrivati sta in remoti/.ponte-stato.json: dopo un riavvio si riparte da lì
(la prima volta dalla fine: lo storico non si rigioca).

Prova:  python3 attivita_ponte.py prova     (un «ssh» finto: due shell locali)
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

HOST = os.environ.get("JARVIS_VPS_SSH", "vps-tuo")
REMOTO_DIR = "~/my-agent/backtalk/attivita"
OGNI_S = 1.0
RIPROVA_S = 10
LOG_OGNI_S = 300
SSH_OPZ = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=20",
           "-o", "ServerAliveCountMax=3"]
_THREADS = []
_LOCK = threading.Lock()


def viaggia(riga_b):
    """True se la riga va all'altra macchina (non la coda incarichi, che ognuno legge da sé)."""
    try:
        e = json.loads(riga_b)
    except ValueError:
        return False
    return isinstance(e, dict) and e.get("fonte") != "incarichi" and not str(e.get("id", "")).startswith("inc:")


class Stato:
    def __init__(self, file):
        self.file = Path(file)
        self.lock = threading.Lock()

    def leggi(self):
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return {}

    def metti(self, chiave, valore):
        with self.lock:
            d = self.leggi()
            d[chiave] = valore
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.file.with_name(self.file.name + ".tmp")
                tmp.write_text(json.dumps(d))
                os.replace(tmp, self.file)
            except OSError:
                pass


class Log:
    def __init__(self, log=None):
        self.ultimo = {}
        self.log = log or (lambda t: print(t, file=sys.stderr, flush=True))

    def __call__(self, chiave, testo):
        t = time.time()
        if t - self.ultimo.get(chiave, 0) >= LOG_OGNI_S:
            self.ultimo[chiave] = t
            self.log(testo)


class Manda:
    """Mac → VPS: segue il file del giorno del registro locale e scrive le righe nuove nello stdin di ssh."""

    def __init__(self, attivita, stato, comando, log):
        self.att, self.stato, self.comando, self.log = attivita, stato, comando, log
        self.proc = None
        self.giorno = None

    def _apri(self, giorno):
        self.chiudi()
        cmd = self.comando(f"d={REMOTO_DIR}/remoti; mkdir -p $d && exec cat >> $d/mac-{giorno}.jsonl")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.giorno = giorno

    def chiudi(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def giro(self):
        giorno = date.today().isoformat()
        f = self.att.file_del_giorno()
        st = self.stato.leggi().get("manda") or {}
        if st.get("file") != f.name:
            # un giorno nuovo parte da 0; la prima volta in assoluto (o dopo giorni) si parte dalla fine
            st = {"file": f.name, "offset": 0 if st.get("file") else (f.stat().st_size if f.exists() else 0)}
            self.stato.metti("manda", st)
        try:
            dim = f.stat().st_size
        except OSError:
            return 0
        off = st["offset"]
        if dim < off:              # file rifatto a mano: si riparte dalla fine
            self.stato.metti("manda", {"file": f.name, "offset": dim})
            return 0
        if dim == off:
            if self.proc and self.proc.poll() is not None:
                self.proc = None
            return 0
        with open(f, "rb") as fh:
            fh.seek(off)
            pezzo = fh.read(dim - off)
        fine = pezzo.rfind(b"\n") + 1
        if not fine:
            return 0
        righe = [r for r in pezzo[:fine].splitlines() if r.strip() and viaggia(r)]
        if righe:
            if not self.proc or self.proc.poll() is not None or self.giorno != giorno:
                self._apri(giorno)
            self.proc.stdin.write(b"".join(r + b"\n" for r in righe))
            self.proc.stdin.flush()       # BrokenPipeError se ssh è caduto: si riprova dallo stesso offset
        self.stato.metti("manda", {"file": f.name, "offset": off + fine})
        return len(righe)


class Ricevi:
    """VPS → Mac: `tail -c +N -F` del file del giorno (UTC) della VPS, righe scritte in remoti/vps-<giorno>.jsonl."""

    def __init__(self, attivita, stato, comando, log, giorno_utc=None):
        self.att, self.stato, self.comando, self.log = attivita, stato, comando, log
        self.giorno_utc = giorno_utc or (lambda: datetime.now(timezone.utc).date().isoformat())

    def una_volta(self, fermati=lambda: False):
        giorno = self.giorno_utc()
        st = self.stato.leggi().get("ricevi") or {}
        off = st.get("offset", -1) if st.get("giorno") == giorno else (0 if st.get("giorno") else -1)
        remoto = f"{REMOTO_DIR}/{giorno}.jsonl"
        cmd = self.comando(f'f={remoto}; o={int(off)}; s=$(($(wc -c < "$f" 2>/dev/null || echo 0))); '
                           f'if [ "$o" -lt 0 ] || [ "$o" -gt "$s" ]; then o=$s; fi; echo "@@da $o"; '
                           f'exec tail -c +$((o+1)) -F "$f" 2>/dev/null')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        dest = self.att.cartella_remoti() / f"vps-{giorno}.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            prima = proc.stdout.readline()
            if not prima.startswith(b"@@da "):
                raise OSError("la VPS non ha risposto")
            pos = int(prima.split()[1])
            self.stato.metti("ricevi", {"giorno": giorno, "offset": pos})
            # al cambio di giorno UTC si chiude: il giro dopo segue il file nuovo
            guardia = threading.Thread(target=self._guardia, args=(proc, giorno, fermati), daemon=True)
            guardia.start()
            for riga in proc.stdout:
                pos += len(riga)
                if riga.endswith(b"\n") and riga.strip() and viaggia(riga):
                    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    try:
                        os.write(fd, riga)
                    finally:
                        os.close(fd)
                self.stato.metti("ricevi", {"giorno": giorno, "offset": pos})
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    def _guardia(self, proc, giorno, fermati):
        while proc.poll() is None:
            if self.giorno_utc() != giorno or fermati():
                proc.kill()
                return
            time.sleep(5)


def comando_ssh(remoto):
    return ["ssh", *SSH_OPZ, HOST, remoto]


def _ciclo_manda(m):
    while True:
        try:
            m.giro()
            time.sleep(OGNI_S)
        except Exception as e:  # noqa: BLE001
            m.chiudi()
            m.log("manda", f"attivita_ponte: Mac → VPS fermo ({type(e).__name__}: {str(e)[:160]}), riprovo ogni {RIPROVA_S} s")
            time.sleep(RIPROVA_S)


def _ciclo_ricevi(r):
    while True:
        t = time.time()
        try:
            r.una_volta()
        except Exception as e:  # noqa: BLE001
            r.log("ricevi", f"attivita_ponte: VPS → Mac fermo ({type(e).__name__}: {str(e)[:160]}), riprovo ogni {RIPROVA_S} s")
        if time.time() - t < RIPROVA_S:
            time.sleep(RIPROVA_S)


def avvia():
    """Sul Mac: i due fili, una volta sola. Sulla VPS e su Windows non fa niente."""
    with _LOCK:
        if _THREADS or sys.platform != "darwin" or os.environ.get("CC_ATTIVITA_PONTE") == "0":
            return list(_THREADS)
        import attivita
        stato = Stato(attivita.cartella_remoti() / ".ponte-stato.json")
        log = Log()
        for nome, fn, obj in (("attivita_manda", _ciclo_manda, Manda(attivita, stato, comando_ssh, log)),
                              ("attivita_ricevi", _ciclo_ricevi, Ricevi(attivita, stato, comando_ssh, log))):
            t = threading.Thread(target=fn, args=(obj,), name=nome, daemon=True)
            t.start()
            _THREADS.append(t)
        return list(_THREADS)


# ------------------------------------------------------------ prova (senza VPS: «ssh» = sh locale con HOME finta)

def prova():
    import shutil
    import tempfile
    c = Path(tempfile.mkdtemp(prefix="prova-attivita-ponte-"))
    mac, vps = c / "mac", c / "vps-home"
    (vps / "my-agent/backtalk/attivita").mkdir(parents=True)
    os.environ["JARVIS_ATTIVITA_DIR"] = str(mac)
    os.environ["JARVIS_ATTIVITA_CONDIVIDI"] = "0"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attivita
    attivita.DIR = mac
    esiti = []

    def v(nome, cond):
        esiti.append(bool(cond))
        print(("  ok   " if cond else "  NO   ") + nome)

    def finto(remoto):
        return ["sh", "-c", f"HOME={vps}; export HOME; " + remoto.replace("~", "$HOME")]

    def aspetta(cond, s=5):
        t = time.time()
        while time.time() - t < s:
            if cond():
                return True
            time.sleep(0.1)
        return False

    try:
        stato = Stato(attivita.cartella_remoti() / ".ponte-stato.json")
        log = Log(log=lambda t: None)
        attivita.registra("richiesta", "toolu_vecchio", "jarvis", "x", "prima del ponte")
        m = Manda(attivita, stato, finto, log)
        v("primo giro: lo storico non si manda", m.giro() == 0)
        attivita.registra("richiesta", "toolu_1", "jarvis", "Azienda Due:marketing", "riunione")
        attivita.registra("richiesta", "inc:in_1", "jarvis", "crm:ceo-ai", "coda", fonte="incarichi")
        attivita.registra("partito", "toolu_1", "jarvis", "Azienda Due:marketing")
        v("tre righe nuove: due viaggiano (la coda incarichi no)", m.giro() == 2)
        dest = vps / f"my-agent/backtalk/attivita/remoti/mac-{date.today().isoformat()}.jsonl"
        v("arrivate sulla «VPS» in remoti/mac-<giorno>.jsonl",
          aspetta(lambda: dest.exists() and len(dest.read_text().splitlines()) == 2))
        m.chiudi()
        # dopo un «riavvio» si riparte dall'offset salvato
        m2 = Manda(attivita, stato, finto, log)
        attivita.registra("risposta", "toolu_1", "Azienda Due:marketing", "jarvis", "fatto")
        v("dopo un riavvio: solo la riga nuova", m2.giro() == 1)
        v("…ed è arrivata", aspetta(lambda: len(dest.read_text().splitlines()) == 3))
        m2.chiudi()
        # ricevi: la «VPS» scrive nel suo registro, il Mac la legge in remoti/vps-<giorno>.jsonl
        giorno = "2026-10-05"
        fv = vps / f"my-agent/backtalk/attivita/{giorno}.jsonl"
        fv.write_text(json.dumps({"v": 1, "ts": 1.0, "ev": "richiesta", "id": "l:vecchia", "da": "utente", "a": "jarvis"}) + "\n")
        stop = [False]
        r = Ricevi(attivita, stato, finto, log, giorno_utc=lambda: giorno)
        t = threading.Thread(target=lambda: r.una_volta(fermati=lambda: stop[0]), daemon=True)
        t.start()
        time.sleep(1.0)
        with fv.open("a") as fh:
            fh.write(json.dumps({"v": 1, "ts": 2.0, "ev": "richiesta", "id": "l:sito", "da": "utente", "a": "jarvis",
                                 "fonte": "chat"}) + "\n")
            fh.write(json.dumps({"v": 1, "ts": 3.0, "ev": "richiesta", "id": "inc:x", "da": "jarvis", "a": "crm:ceo-ai",
                                 "fonte": "incarichi"}) + "\n")
        dv = attivita.cartella_remoti() / f"vps-{giorno}.jsonl"
        v("ricevi: la riga nuova del sito arriva, la vecchia e la coda no",
          aspetta(lambda: dv.exists() and [json.loads(x)["id"] for x in dv.read_text().splitlines()] == ["l:sito"]))
        stop[0] = True
        t.join(8)
        v("ricevi: si ferma quando deve", not t.is_alive())
        # il Lettore vede le righe di remoti/ (con un giorno valido nel nome)
        (attivita.cartella_remoti() / f"vps-{date.today().isoformat()}.jsonl").write_text(
            json.dumps({"v": 1, "ts": 4.0, "ev": "richiesta", "id": "l:oggi", "da": "utente", "a": "jarvis"}) + "\n")
        ids = {e["id"] for e in attivita.Lettore(giorni=3).eventi()}
        v("il Lettore legge anche remoti/ di oggi", "l:oggi" in ids and "toolu_1" in ids)
        v("riga ricevuta non torna indietro (manda legge solo il registro locale)", m2.giro() == 0)
    finally:
        shutil.rmtree(c, ignore_errors=True)
    print("tutto ok" if all(esiti) else f"{esiti.count(False)} prove fallite")
    return 0 if all(esiti) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["prova"]:
        sys.exit(prova())
    print(__doc__)
