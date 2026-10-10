#!/usr/bin/env python3
"""Avviso e pulsante di aggiornamento del software di Jarvis (01/10/2026, richiesta dell'utente; rifatto il 05/10/2026).

Ogni copia di Jarvis sa da quale repository GitHub arriva. Ogni 10 minuti il pannello fa `git fetch` e confronta
la versione CON CUI IL PANNELLO È PARTITO (avvio) con quella su disco (HEAD) e con quella su GitHub (@{u}).
«Aggiornamento disponibile» compare se:
  - GitHub ha commit nuovi (si scaricano con un avanti veloce), oppure
  - il codice su disco è già più nuovo di quello in esecuzione (Mac: si committa qui; VPS: jarvis-repo-sync scarica
    da solo ogni 10 minuti) e serve solo riavviare.
Il pulsante «Aggiorna ora» (POST /api/aggiorna):
  1. se una chat o una missione è in corso e non c'è «forza», risponde chiede_conferma (la pagina chiede «riavvia lo stesso?»);
  2. se GitHub è avanti fa `git merge --ff-only @{u}`: mai reset, mai stash. Se git rifiuta (file modificati qui che
     l'aggiornamento cambierebbe, rami divergenti) si ferma e lo dice;
  3. risponde, poi riavvia il pannello staccato: launchd (kickstart -k) sul Mac, systemd-run → systemctl restart sulla VPS,
     su Windows un aiutante staccato che rilancia server.py (pythonw), altrimenti si rilancia da sé (execv).
  La pagina aspetta che il pannello torni con la versione nuova e si ricarica da sola.
Ogni passo lascia una riga in lavori/aggiornamento.log.
Copie installate senza .git (Windows, CLONE.txt): resta l'aggiornatore della copia (AGGIORNA.ps1 / aggiorna_jarvis.py).
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
DURATA = 600
LOG = QUI / "lavori" / "aggiornamento.log"
_cache = {"quando": 0.0, "dati": None}
_lock = threading.Lock()
_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")
_avvio = {"sha": None}
_riavvio = {"in_corso": False}


def radice():
    """La cartella con il .git da cui si aggiorna, o None."""
    segno = QUI.parent / "CLONE.txt"
    if segno.exists():
        p = Path(segno.read_text(encoding="utf-8-sig").strip())
        if (p / ".git").exists():
            return p
    return QUI.parent if (QUI.parent / ".git").exists() else None


def copia_installata():
    """True se il pannello gira da una copia installata (CLONE.txt) e non dal repository stesso."""
    r = radice()
    return bool(r) and r.resolve() != QUI.parent.resolve()


def _git(r, *a, tempo=30):
    p = subprocess.run(["git", "-C", str(r), *a], capture_output=True, text=True, timeout=tempo, env=_ENV)
    return p.returncode, (p.stdout or "").strip() or (p.stderr or "").strip()


def scrivi_log(testo):
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {testo}\n")
    except OSError:
        pass


def segna_avvio():
    """Da chiamare all'avvio del server: la versione del codice che sta girando."""
    r = radice()
    if r and not copia_installata():
        try:
            rc, sha = _git(r, "rev-parse", "HEAD", tempo=10)
            _avvio["sha"] = sha if rc == 0 else None
        except Exception:
            _avvio["sha"] = None
    return _avvio["sha"]


def _corto(sha):
    return (sha or "")[:7]


def _leggi():
    r = radice()
    base = {"attivo": False, "disponibile": False, "indietro": 0, "avanti": 0, "novita": [], "locale": "", "remoto": "",
            "da_riavviare": False, "da_scaricare": False, "avvio": _corto(_avvio["sha"]),
            "controllato": time.strftime("%Y-%m-%d %H:%M")}
    if not r:
        return base
    rc_f, err_f = _git(r, "fetch", "--quiet", "origin")
    rc, ab = _git(r, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    if rc:
        return dict(base, attivo=True, errore="la copia non segue un ramo di GitHub")
    avanti, indietro = (int(x) for x in ab.split()[:2])
    _, head = _git(r, "rev-parse", "HEAD")
    _, rem = _git(r, "rev-parse", "@{u}")
    avvio = _avvio["sha"] if not copia_installata() else None
    da_riavviare = bool(avvio) and avvio != head
    if copia_installata():
        # Windows (05/10/2026): il clone può essere già aggiornato e la copia installata no (VERSIONE.installata vecchia):
        # anche questo è un aggiornamento da fare, AGGIORNA.ps1 la riallinea
        try:
            inst = (QUI.parent / "VERSIONE.installata").read_text(encoding="utf-8-sig").strip()
        except OSError:
            inst = ""
        if inst and inst != head:
            avvio, da_riavviare = inst, True
    da_scaricare = indietro > 0 and avanti == 0
    # da dove a dove: dalla versione in esecuzione a quella che ci sarà dopo l'aggiornamento
    da = avvio or head
    a = rem if da_scaricare else head
    novita, quante = [], 0
    if da != a:
        _, n = _git(r, "rev-list", "--count", f"{da}..{a}")
        quante = int(n) if n.isdigit() else 0
        _, log = _git(r, "log", "--format=%s", "-n", "6", f"{da}..{a}")
        novita = log.splitlines() if log else []
    d = dict(base, attivo=True, indietro=quante or indietro, avanti=avanti, da_riavviare=da_riavviare,
             da_scaricare=da_scaricare, disponibile=da_scaricare or da_riavviare,
             novita=novita or ([] if da != a else ["la copia installata va riallineata al codice scaricato"]),
             locale=_corto(da), remoto=_corto(a), avvio=_corto(avvio), head=_corto(head))
    if indietro > 0 and avanti > 0:
        d["nota"] = f"questa copia ha {avanti} commit non pubblicati: da GitHub non si scarica (niente avanti veloce)"
    if rc_f:
        d["nota"] = "GitHub non raggiungibile: confronto solo con il codice su disco"
    return d


def stato(forza=False):
    with _lock:
        if forza or not _cache["dati"] or time.time() - _cache["quando"] > DURATA:
            try:
                _cache["dati"] = _leggi()
            except Exception as e:   # git assente o rete giù: il pannello continua
                _cache["dati"] = {"attivo": False, "disponibile": False, "errore": str(e)[:160]}
            _cache["quando"] = time.time()
        d = dict(_cache["dati"])
    d["riavvio_in_corso"] = _riavvio["in_corso"]
    return d


def _unita_systemd():
    """Il nome del servizio systemd che ci fa girare (es. jarvis-cc.service), o None."""
    try:
        for riga in Path("/proc/self/cgroup").read_text().splitlines():
            ultimo = riga.rsplit("/", 1)[-1]
            if ultimo.endswith(".service"):
                return ultimo
    except OSError:
        pass
    return None


def comando_riavvio():
    """Come riavviare QUESTO pannello: (descrizione, argv) oppure (descrizione, None) = rilancio da sé."""
    if sys.platform == "darwin" and os.environ.get("XPC_SERVICE_NAME", "").startswith("com.jarvis.command-center"):
        etichetta = os.environ["XPC_SERVICE_NAME"]
        return f"launchd {etichetta}", ["/bin/sh", "-c", f"sleep 2; launchctl kickstart -k gui/{os.getuid()}/{etichetta}"]
    unita = _unita_systemd() if sys.platform.startswith("linux") else None
    if unita and os.environ.get("INVOCATION_ID"):
        return f"systemd {unita}", ["systemd-run", "--quiet", "--collect", "--on-active=2",
                                    f"--unit=cc-riavvio-{int(time.time())}", "systemctl", "restart", unita]
    return "rilancio del processo", None


def _riavvia_windows(attendi_pid=None, dopo=1.5):
    """Windows: non c'è launchd né systemd e os.execv lì non sostituisce il processo (il pannello resterebbe spento
    o con la porta occupata). Un aiutante staccato aspetta che finisca l'aggiornatore (attendi_pid) e che questo pannello
    esca, poi rilancia lo stesso server.py senza finestra (pythonw). Il pannello esce dopo aver risposto alla pagina."""
    exe = Path(sys.executable)
    senza = exe.with_name("pythonw.exe")
    exe = senza if senza.exists() else exe
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else str(QUI / "server.py")
    argv = [str(exe), script, *sys.argv[1:]]
    codice = (
        "import os,subprocess,sys,time\n"
        "def viva(p):\n"
        "    if not p: return False\n"
        "    r=subprocess.run(['tasklist','/FI','PID eq '+str(p),'/NH'],capture_output=True,text=True,creationflags=0x08000000)\n"
        "    return (' '+str(p)+' ') in (' '+r.stdout+' ')\n"
        "t=time.time()\n"
        "while time.time()-t<300 and (viva(%d) or viva(%d)): time.sleep(1)\n"
        "time.sleep(2)\n"
        "subprocess.Popen(%r,cwd=%r,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "creationflags=0x00000008|0x00000200|0x08000000,close_fds=True)\n"
    ) % (attendi_pid or 0, os.getpid(), argv, str(QUI))
    scrivi_log("riavvio Windows: aiutante staccato, poi rilancio " + " ".join(argv))
    subprocess.Popen([str(exe), "-c", codice], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200 | 0x08000000, close_fds=True)

    def esci():
        time.sleep(dopo)
        scrivi_log("riavvio Windows: il pannello esce, l'aiutante lo rilancia")
        os._exit(0)

    threading.Thread(target=esci, daemon=True).start()
    return "rilancio Windows"


def _riavvia(dopo=1.5):
    """Dopo la risposta: lancia il riavvio staccato (o si rilancia da sé)."""
    if os.name == "nt":
        return _riavvia_windows(None, dopo)
    descr, cmd = comando_riavvio()

    def via():
        time.sleep(dopo)
        scrivi_log(f"riavvio: {descr}")
        if cmd:
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True, close_fds=True)
                return
            except OSError as e:
                scrivi_log(f"riavvio con {descr} non riuscito ({e}): mi rilancio da solo")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=via, daemon=True).start()
    return descr


def applica(forza=False, occupato=None, prova=False):
    """Il pulsante «Aggiorna ora». occupato: elenco di testi (chat o missioni in corso) passato dal server.
    prova=True fa tutto tranne il riavvio (per le prove automatiche)."""
    r = radice()
    if copia_installata() or (os.name == "nt" and not r):
        return _applica_copia(r)
    if _riavvio["in_corso"]:
        return {"avviato": True, "riavvio": True, "gia": True, "motivo": "riavvio già in corso"}
    s = stato(True)
    if not s.get("attivo"):
        return {"avviato": False, "motivo": s.get("errore") or "questa copia non ha un repository da cui aggiornarsi"}
    if not s.get("disponibile"):
        return {"avviato": False, "motivo": "è già tutto aggiornato: il pannello gira sull'ultima versione"}
    occupato = [o for o in (occupato or []) if o]
    if occupato and not forza:
        return {"avviato": False, "chiede_conferma": True, "occupato": occupato[:6],
                "motivo": "c'è del lavoro in corso: il riavvio lo interrompe"}
    scrivi_log(f"=== aggiornamento avviato dal pannello: {s.get('locale')} → {s.get('remoto')}"
               + (f" (interrompe: {'; '.join(occupato)[:200]})" if occupato else ""))
    scaricato = False
    if s.get("da_scaricare"):
        rc, out = _git(r, "merge", "--ff-only", "@{u}", tempo=60)
        if rc:
            scrivi_log(f"avanti veloce rifiutato da git: {out[:300]}")
            if not s.get("da_riavviare"):
                return {"avviato": False, "motivo": "git non può scaricare senza toccare file modificati qui: "
                        + out.splitlines()[-1][:200] if out else "avanti veloce non riuscito"}
        else:
            scaricato = True
            scrivi_log("codice scaricato da GitHub (avanti veloce)")
    _, head = _git(r, "rev-parse", "--short", "HEAD")
    with _lock:
        _cache["quando"] = 0.0
    if prova:
        return {"avviato": True, "riavvio": False, "prova": True, "scaricato": scaricato, "a": head}
    _riavvio["in_corso"] = True
    descr = _riavvia()
    return {"avviato": True, "riavvio": True, "come": descr, "scaricato": scaricato, "da": s.get("avvio") or s.get("locale"),
            "a": head, "novita": s.get("novita", [])}


def _applica_copia(r):
    """Copie installate (Windows / CLONE.txt): lancia l'aggiornatore della copia, staccato dal pannello."""
    s = stato(True)
    if not s.get("disponibile"):
        return {"avviato": False, "motivo": "non c'è niente da aggiornare" if s.get("attivo") else "questa copia non ha un repository da cui aggiornarsi"}
    LOG.parent.mkdir(exist_ok=True)
    f = open(LOG, "ab")
    f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} aggiornamento avviato dal pannello ===\n".encode())
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(r / "AGGIORNA.ps1")]
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: console nascosta. Con DETACHED_PROCESS PowerShell 5 esce subito
        # con 0 senza eseguire lo script (provato sul PC il 05/10/2026: il pulsante diceva «avviato» e non faceva nulla)
        flags = 0x00000200 | 0x08000000
        p = subprocess.Popen(cmd, cwd=str(r), stdout=f, stderr=f, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        _riavvia_windows(p.pid)    # a fine aggiornamento il pannello si riavvia da solo (2026-10-05, l'utente)
    else:
        cmd = [sys.executable, str(r / "strumenti" / "aggiorna_jarvis.py"), "--applica"]
        subprocess.Popen(cmd, cwd=str(r), stdout=f, stderr=f, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    with _lock:
        _cache["quando"] = 0.0
    return {"avviato": True, "riavvio": True, "novita": s.get("novita", [])}


if __name__ == "__main__":
    import json
    segna_avvio()
    print(json.dumps(stato(True), ensure_ascii=False, indent=1))
