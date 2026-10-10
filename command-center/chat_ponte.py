#!/usr/bin/env python3
"""La chat a voce fra Mac e VPS, in pochi secondi (2026-10-05, l'utente: «il riquadro Chat a voce non è collegato»).

La voce di Jarvis ha due conversazioni vere, ognuna con il suo file backtalk/chat.jsonl:
  Mac   backtalk (Command destro, «Hey Jarvis», «Manda» dal pannello del Mac)
  VPS   jarvis-agent (l'app del telefono e il «Manda» del sito), in /root/jarvis/backtalk/chat.jsonl
L'utente guarda il riquadro dal sito mentre parla col Mac (e viceversa): ogni pannello deve vedere tutte e due.
Qui, solo sul Mac, due fili ssh come attivita_ponte.py:

  manda   righe nuove di backtalk/chat.jsonl del Mac → VPS  ~/jarvis/backtalk/remoti/mac/chat.jsonl
  ricevi  righe nuove di ~/jarvis/backtalk/chat.jsonl della VPS → Mac  backtalk/remoti/vps/chat.jsonl

/api/chat/storia (server.py, storia_chat_voce) unisce il file locale e quello arrivato, in ordine di ora,
e dice da dove viene ogni battuta (mac, telefono, sito). I nomi «chat.jsonl» stanno nel .gitignore di
backtalk a ogni profondità: niente finisce su GitHub. La prima volta si mandano le ultime ~64 KB
(abbastanza per le 150 battute che il riquadro legge), poi solo le righe nuove; dove si è arrivati sta in
backtalk/remoti/.chat-ponte.json. Nessun segreto: solo le battute, sulla stessa `ssh vps-tuo`.

Prova:  python3 chat_ponte.py prova     (un «ssh» finto: shell locali)
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from attivita_ponte import SSH_OPZ, Log, Stato

HOST = os.environ.get("JARVIS_VPS_SSH", "vps-tuo")
REMOTO_BACKTALK = "~/jarvis/backtalk"
PRIMA_VOLTA_BYTE = 64 * 1024
OGNI_S = 1.0
RIPROVA_S = 10
_THREADS = []
_LOCK = threading.Lock()


def file_locale(backtalk):
    return Path(backtalk) / "chat.jsonl"


def file_remoto(backtalk, macchina):
    """La copia della chat dell'altra macchina: backtalk/remoti/<mac|vps>/chat.jsonl."""
    return Path(backtalk) / "remoti" / macchina / "chat.jsonl"


def _inizio_coda(f, quanti):
    """Offset del primo inizio riga nelle ultime «quanti» byte (0 se il file è più corto)."""
    try:
        dim = f.stat().st_size
    except OSError:
        return 0
    if dim <= quanti:
        return 0
    with open(f, "rb") as fh:
        fh.seek(dim - quanti)
        pezzo = fh.read(quanti)
    i = pezzo.find(b"\n")
    return dim - quanti + i + 1 if i >= 0 else dim


class Manda:
    """Mac → VPS: segue backtalk/chat.jsonl e scrive le righe nuove nello stdin di un `cat >>` via ssh."""

    def __init__(self, locale, stato, comando, log):
        self.f, self.stato, self.comando, self.log = Path(locale), stato, comando, log
        self.proc = None

    def _apri(self):
        self.chiudi()
        cmd = self.comando(f"d={REMOTO_BACKTALK}/remoti/mac; mkdir -p $d && exec cat >> $d/chat.jsonl")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        st = self.stato.leggi().get("manda")
        if not isinstance(st, dict) or "offset" not in st:
            st = {"offset": _inizio_coda(self.f, PRIMA_VOLTA_BYTE)}
            self.stato.metti("manda", st)
        try:
            dim = self.f.stat().st_size
        except OSError:
            return 0
        off = int(st["offset"])
        if dim < off:                       # file rifatto: si riparte dalla fine
            self.stato.metti("manda", {"offset": dim})
            return 0
        if dim == off:
            if self.proc and self.proc.poll() is not None:
                self.proc = None
            return 0
        with open(self.f, "rb") as fh:
            fh.seek(off)
            pezzo = fh.read(dim - off)
        fine = pezzo.rfind(b"\n") + 1
        if not fine:
            return 0
        righe = [r for r in pezzo[:fine].splitlines() if r.strip()]
        if righe:
            if not self.proc or self.proc.poll() is not None:
                self._apri()
            self.proc.stdin.write(b"".join(r + b"\n" for r in righe))
            self.proc.stdin.flush()         # BrokenPipeError se ssh è caduto: si riprova dallo stesso offset
        self.stato.metti("manda", {"offset": off + fine})
        return len(righe)


class Ricevi:
    """VPS → Mac: `tail -c +N -F` di ~/jarvis/backtalk/chat.jsonl, righe in backtalk/remoti/vps/chat.jsonl."""

    def __init__(self, dest, stato, comando, log):
        self.dest, self.stato, self.comando, self.log = Path(dest), stato, comando, log

    def una_volta(self, fermati=lambda: False):
        st = self.stato.leggi().get("ricevi")
        # -1 = prima volta: dalla coda (le ultime PRIMA_VOLTA_BYTE), non dall'inizio
        off = int(st["offset"]) if isinstance(st, dict) and "offset" in st else -1
        remoto = f"{REMOTO_BACKTALK}/chat.jsonl"
        cmd = self.comando(
            f'f={remoto}; o={off}; s=$(($(wc -c < "$f" 2>/dev/null || echo 0))); '
            f'if [ "$o" -lt 0 ]; then o=$((s>{PRIMA_VOLTA_BYTE} ? s-{PRIMA_VOLTA_BYTE} : 0)); fi; '
            f'if [ "$o" -gt "$s" ]; then o=$s; fi; echo "@@da $o"; '
            f'exec tail -c +$((o+1)) -F "$f" 2>/dev/null')
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            prima = proc.stdout.readline()
            if not prima.startswith(b"@@da "):
                raise OSError("la VPS non ha risposto")
            pos = int(prima.split()[1])
            salta_mezza = off < 0 and pos > 0       # partendo dalla coda, la prima riga può essere a metà
            guardia = threading.Thread(target=self._guardia, args=(proc, fermati), daemon=True)
            guardia.start()
            for riga in proc.stdout:
                pos += len(riga)
                if salta_mezza:
                    salta_mezza = False
                    try:
                        json.loads(riga)
                    except ValueError:
                        self.stato.metti("ricevi", {"offset": pos})
                        continue
                if riga.endswith(b"\n") and riga.strip():
                    fd = os.open(self.dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    try:
                        os.write(fd, riga)
                    finally:
                        os.close(fd)
                self.stato.metti("ricevi", {"offset": pos})
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()

    @staticmethod
    def _guardia(proc, fermati):
        while proc.poll() is None:
            if fermati():
                proc.kill()
                return
            time.sleep(0.5)


def comando_ssh(remoto):
    return ["ssh", *SSH_OPZ, HOST, remoto]


def _ciclo_manda(m):
    while True:
        try:
            m.giro()
            time.sleep(OGNI_S)
        except Exception as e:  # noqa: BLE001
            m.chiudi()
            m.log("chat_manda", f"chat_ponte: Mac → VPS fermo ({type(e).__name__}: {str(e)[:160]}), riprovo ogni {RIPROVA_S} s")
            time.sleep(RIPROVA_S)


def _ciclo_ricevi(r):
    while True:
        t = time.time()
        try:
            r.una_volta()
        except Exception as e:  # noqa: BLE001
            r.log("chat_ricevi", f"chat_ponte: VPS → Mac fermo ({type(e).__name__}: {str(e)[:160]}), riprovo ogni {RIPROVA_S} s")
        if time.time() - t < RIPROVA_S:
            time.sleep(RIPROVA_S)


def avvia(backtalk):
    """Sul Mac: i due fili, una volta sola. Sulla VPS e su Windows non fa niente."""
    with _LOCK:
        if _THREADS or sys.platform != "darwin" or os.environ.get("CC_CHAT_PONTE") == "0":
            return list(_THREADS)
        backtalk = Path(backtalk)
        stato = Stato(backtalk / "remoti" / ".chat-ponte.json")
        log = Log()
        for nome, fn, obj in (
                ("chat_manda", _ciclo_manda, Manda(file_locale(backtalk), stato, comando_ssh, log)),
                ("chat_ricevi", _ciclo_ricevi, Ricevi(file_remoto(backtalk, "vps"), stato, comando_ssh, log))):
            t = threading.Thread(target=fn, args=(obj,), name=nome, daemon=True)
            t.start()
            _THREADS.append(t)
        return list(_THREADS)


# ------------------------------------------------------------ unione delle due chat (usata da server.py)

def leggi_righe(f, ultime=150):
    out = []
    try:
        for r in Path(f).read_text(encoding="utf-8").splitlines()[-ultime:]:
            try:
                d = json.loads(r)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("testo") is not None:
                out.append(d)
    except OSError:
        pass
    return out


def storia(backtalk, su_vps, ultime=150):
    """Le battute delle due conversazioni a voce, in ordine di ora, con «origine» sempre presente:
    «mac» (backtalk del Mac), «telefono» o «sito» (jarvis-agent della VPS)."""
    backtalk = Path(backtalk)
    locali = leggi_righe(file_locale(backtalk), ultime)
    altre = leggi_righe(file_remoto(backtalk, "mac" if su_vps else "vps"), ultime)
    tutte = []
    for b in locali:
        tutte.append({**b, "origine": b.get("origine") or ("sito" if su_vps else "mac")})
    for b in altre:
        tutte.append({**b, "origine": b.get("origine") or ("mac" if su_vps else "sito")})
    # le ore sono tutte ora di Roma senza fuso (backtalk e jarvis-agent con TZ=Europe/Rome): la stringa si ordina
    tutte.sort(key=lambda b: str(b.get("ts") or ""))
    return tutte[-ultime:]


# ------------------------------------------------------------ prova (senza VPS: «ssh» = sh locale con HOME finta)

def prova():
    import shutil
    import tempfile
    c = Path(tempfile.mkdtemp(prefix="prova-chat-ponte-"))
    mac, vps = c / "mac-backtalk", c / "vps-home"
    mac.mkdir()
    (vps / "jarvis/backtalk").mkdir(parents=True)
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

    def riga(chi, testo, ts, **k):
        return json.dumps({"chi": chi, "testo": testo, "ts": ts, **k}) + "\n"

    try:
        stato = Stato(mac / "remoti" / ".chat-ponte.json")
        log = Log(log=lambda t: None)
        fm = file_locale(mac)
        fm.write_text(riga("utente", "vecchia del Mac", "2026-10-05T08:00:00"))
        m = Manda(fm, stato, finto, log)
        v("primo giro: manda la coda della chat del Mac (file corto = tutto)", m.giro() == 1)
        dest = vps / "jarvis/backtalk/remoti/mac/chat.jsonl"
        v("arrivata sulla «VPS» in remoti/mac/chat.jsonl", aspetta(lambda: dest.exists() and len(dest.read_text().splitlines()) == 1))
        with fm.open("a") as fh:
            fh.write(riga("jarvis", "risposta del Mac", "2026-10-05T15:10:00"))
        v("riga nuova: parte solo quella", m.giro() == 1)
        v("…ed è arrivata", aspetta(lambda: len(dest.read_text().splitlines()) == 2))
        m.chiudi()
        m2 = Manda(fm, stato, finto, log)
        v("dopo un riavvio niente si rimanda", m2.giro() == 0)
        # ricevi
        fv = vps / "jarvis/backtalk/chat.jsonl"
        fv.write_text(riga("utente", "dal sito", "2026-10-05T09:00:00", origine="sito"))
        stop = [False]
        r = Ricevi(file_remoto(mac, "vps"), stato, finto, log)
        t = threading.Thread(target=lambda: r.una_volta(fermati=lambda: stop[0]), daemon=True)
        t.start()
        dv = file_remoto(mac, "vps")
        v("ricevi, prima volta: la coda della VPS (file corto = tutto)", aspetta(lambda: dv.exists() and "dal sito" in dv.read_text()))
        with fv.open("a") as fh:
            fh.write(riga("jarvis", "OK dal telefono", "2026-10-05T15:11:00", origine="telefono"))
        v("ricevi: la riga nuova arriva in pochi secondi", aspetta(lambda: "OK dal telefono" in dv.read_text()))
        stop[0] = True
        t.join(5)
        v("ricevi si ferma quando deve", not t.is_alive())
        # unione vista dal Mac e dalla VPS
        s = storia(mac, su_vps=False)
        v("storia sul Mac: 4 battute in ordine di ora", [b["testo"] for b in s] ==
          ["vecchia del Mac", "dal sito", "risposta del Mac", "OK dal telefono"])
        v("storia sul Mac: origine mac / sito / telefono", [b["origine"] for b in s] == ["mac", "sito", "mac", "telefono"])
        vb = vps / "jarvis/backtalk"
        s2 = storia(vb, su_vps=True)
        v("storia sulla VPS: le battute del Mac con origine mac", [b["origine"] for b in s2] == ["mac", "sito", "mac", "telefono"])
    finally:
        shutil.rmtree(c, ignore_errors=True)
    print("tutto ok" if all(esiti) else f"{esiti.count(False)} prove fallite")
    return 0 if all(esiti) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["prova"]:
        sys.exit(prova())
    print(__doc__)
