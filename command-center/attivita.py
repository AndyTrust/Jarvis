#!/usr/bin/env python3
"""Il registro delle attività degli agenti (proposta del 2026-10-02, audit della lavagna).

L'utente: «è importante vedere nella lavagna come stanno lavorando ogni singolo agente, come
richieste inviate e ricevute». Il bus .jarvis_status tiene solo gli ultimi 8 lanci e li
sovrascrive; registro.log delle missioni è testo da leggere, non un indice. Qui ogni
passaggio diventa una riga JSON, in un file al giorno, tenuto 14 giorni.

Chi scrive (sempre con registra()):
  ~/.claude/hooks → my-agent/.claude/hooks/jarvis_status.py   sessioni di Claude Code (fonte «hook»)
  command-center/missione.py                                  missioni del pannello  (fonte «missione»)
  command-center/server.py                                    chat del pannello      (fonte «chat»)
  command-center/incarichi_ponte.py                           coda incarichi VPS     (fonte «incarichi»)
  command-center/lavori_ponte.py                              strumenti/lavori.py    (fonte «lavori»)
  command-center/attivita_ponte.py                            copia Mac ⇄ VPS in DIR/remoti/ (righe intatte)
Chi legge: server.py, /api/agente-attivita e /api/agenti-attivita.

Una riga:
  {"v":1, "ts":1790926138.17, "ev":"richiesta", "id":"toolu_…", "da":"jarvis", "a":"crm:commercialista",
   "testo":"controlla le fatture", "fonte":"hook", "sessione":"…", "missione":"…", "cwd":"…",
   "modello":"sonnet", "sfondo":true, "durata_s":69.5, "esito":"…", "errore":"…"}
  ev: richiesta | partito | risposta | errore | rimandato
  id: lo stesso per la richiesta e per tutto quello che le succede dopo (tool_use_id).
  da / a: «utente», «jarvis», «sentinella», «<progetto>:<nome>», «<progetto>:orchestratore», oppure il solo
          nome quando chi scrive non sa il progetto: la chiave giusta la trova il server (risolvi()).

Scrittura: os.open con O_APPEND e una sola os.write di meno di 4096 byte, quindi atomica anche con
più processi che scrivono insieme (gancio, missioni, server). Niente lucchetti, niente riscritture.
"""
import json
import os
import re
import socket
import sys
import time
from datetime import date, timedelta
from pathlib import Path

WIN = sys.platform == "win32"
# Windows (unione del ramo windows, 02/10/2026): OneDrive sta in ~/OneDrive e Jarvis nella cartella di questo file
_OD = Path.home() / ("OneDrive" if WIN else "Library/CloudStorage/OneDrive")
# registro condiviso fra più macchine: solo se configurato (JARVIS_ATTIVITA_EXTRA), altrimenti spento
EXTRA = Path(os.environ.get("JARVIS_ATTIVITA_EXTRA") or (Path.home() / ".jarvis" / "registro-condiviso-non-configurato"))
DIR = Path(os.environ.get("JARVIS_ATTIVITA_DIR") or (
    Path(__file__).resolve().parents[1] / "backtalk" / "attivita" if WIN else Path.home() / "my-agent" / "backtalk" / "attivita"))
# Il PC Windows scrive ANCHE nel registro condiviso EXTRA/attivita-<NOME-PC>.jsonl (efae908 del ramo windows):
# append-only, una riga JSON per evento, un file per PC, mai il file di un altro PC. Il Mac lo legge (Lettore).
# JARVIS_ATTIVITA_CONDIVIDI=1 lo accende anche altrove (serve alle prove); =0 lo spegne.
CONDIVIDI = os.environ.get("JARVIS_ATTIVITA_CONDIVIDI", "1" if WIN else "0") == "1"
# 5ef1e8a del ramo windows: nel file condiviso vanno SOLO le richieste fra agenti. Le chat di chi usa il PC
# («utente»/«utente»), i rapporti della sentinella e le ricerche in memoria restano nello storico locale.
PRIVATI = {"utente", "utente", "sentinella", "memoria"}
CAMPI_CONDIVISI = ("v", "ts", "ev", "id", "da", "a", "testo", "esito", "errore", "durata_s", "modello", "sfondo")
GIORNI = 14
MAX_RIGA = 3800
EVENTI = ("richiesta", "partito", "risposta", "errore", "rimandato")


def _corto(testo, n):
    testo = " ".join(str(testo or "").split())
    return testo if len(testo) <= n else testo[:n - 1] + "…"


def nome_pc():
    return os.environ.get("COMPUTERNAME") or socket.gethostname().split(".")[0]


def file_condiviso():
    """Il file di QUESTO PC nella cartella condivisa, o None se la cartella non c'è (OneDrive scollegato)."""
    return EXTRA / f"attivita-{nome_pc()}.jsonl" if EXTRA.is_dir() else None


def _nome_breve(x):
    return str(x or "").split(":")[-1] or "?"


def riga_condivisa(riga):
    """La riga nel formato comune del registro condiviso, o None se è privata."""
    da, a = _nome_breve(riga.get("da")), _nome_breve(riga.get("a"))
    if {da.lower(), a.lower()} & PRIVATI:
        return None
    r = {k: riga[k] for k in CAMPI_CONDIVISI if k in riga}
    r.update(id="win:" + str(riga["id"]) if WIN else str(riga["id"]), da=da, a=a, fonte="windows" if WIN else riga.get("fonte", "?"),
             pc=nome_pc())
    return r


def _condividi(riga):
    f = file_condiviso()
    r = riga_condivisa(riga) if f else None
    if not r:
        return
    s = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
    if len(s.encode("utf-8")) > MAX_RIGA:
        r.pop("esito", None)
        r["testo"] = _corto(r.get("testo"), 80)
        s = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
    try:
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (s + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def file_del_giorno(giorno=None):
    return DIR / f"{(giorno or date.today()).isoformat()}.jsonl"


def cartella_remoti():
    return DIR / "remoti"


def file_remoti(giorni=3):
    """I file delle altre macchine degli ultimi `giorni` giorni (± uno: la VPS conta i giorni in UTC)."""
    c = cartella_remoti()
    if not c.is_dir():
        return []
    date_ok = {(date.today() - timedelta(days=i)).isoformat() for i in range(-1, giorni)}
    return sorted(f for f in c.glob("*.jsonl") if f.stem[-10:] in date_ok)


def registra(ev, id_, da, a, testo="", **altro):
    """Aggiunge un evento. Non solleva mai: un registro che non si scrive non deve fermare un agente."""
    if ev not in EVENTI or not id_:
        return
    riga = {"v": 1, "ts": round(time.time(), 3), "ev": ev, "id": str(id_), "da": str(da or "?"),
            "a": str(a or "?"), "testo": _corto(testo, 200)}
    for k, v in altro.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        riga[k] = _corto(v, 400) if isinstance(v, str) else v
    s = json.dumps(riga, ensure_ascii=False)
    if len(s.encode("utf-8")) > MAX_RIGA:
        for k in ("esito", "dettaglio", "cwd"):
            riga.pop(k, None)
        riga["testo"] = _corto(riga["testo"], 80)
        s = json.dumps(riga, ensure_ascii=False)
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(file_del_giorno(), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (s + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        _pota()
    except OSError:
        pass
    if CONDIVIDI:
        _condividi(riga)


def _pota():
    """Via i file più vecchi di GIORNI giorni, al massimo una volta all'ora (segno: .potato)."""
    segno = DIR / ".potato"
    try:
        if time.time() - segno.stat().st_mtime < 3600:
            return
    except OSError:
        pass
    try:
        segno.touch()
        limite = (date.today() - timedelta(days=GIORNI)).isoformat()
        for f in DIR.glob("*.jsonl"):
            if f.stem < limite:
                f.unlink()
        for f in cartella_remoti().glob("*.jsonl"):
            if f.stem[-10:] < limite:
                f.unlink()
    except OSError:
        pass


class Lettore:
    """Legge i file degli ultimi giorni una volta sola: dopo, solo le righe aggiunte (offset per file)."""

    def __init__(self, giorni=3):
        self.giorni = giorni
        self.offset = {}            # nome file -> byte letti
        self.righe = []

    def eventi(self):
        tieni = {file_del_giorno(date.today() - timedelta(days=i)).name for i in range(self.giorni)}
        if any(n not in tieni and not n.startswith(("extra:", "remoti:")) for n in self.offset):   # è passata la mezzanotte: si riparte
            self.offset, self.righe = {}, []
        # 02/10/2026: l'attività dei PC Windows (stesso formato, un file per PC) sta nella cartella condivisa del CRM
        extra = sorted(EXTRA.glob("attivita-*.jsonl")) if EXTRA.is_dir() else []
        if CONDIVIDI:       # il file di questo PC è una copia ridotta del registro locale: non si conta due volte
            extra = [x for x in extra if x.name != f"attivita-{nome_pc()}.jsonl"]
        # 2026-10-05 (lavagna viva): gli eventi delle altre macchine (Mac → VPS e VPS → Mac, attivita_ponte.py)
        # stanno in DIR/remoti/<origine>-<AAAA-MM-GG>.jsonl; si leggono quelli degli ultimi giorni
        remoti = file_remoti(self.giorni)
        for nome, f in [(n, DIR / n) for n in sorted(tieni)] + [("extra:" + x.name, x) for x in extra] \
                + [("remoti:" + x.name, x) for x in remoti]:
            try:
                dim = f.stat().st_size
            except OSError:
                continue
            da = self.offset.get(nome, 0)
            if dim < da:                                      # file rifatto a mano: si rilegge tutto
                self.offset, self.righe = {}, []
                return self.eventi()
            if dim == da:
                continue
            with open(f, "rb") as fh:
                fh.seek(da)
                pezzo = fh.read(dim - da)
            fine = pezzo.rfind(b"\n") + 1                     # una riga a metà si legge al prossimo giro
            for r in pezzo[:fine].splitlines():
                try:
                    self.righe.append(json.loads(r))
                except ValueError:
                    continue
            self.offset[nome] = da + fine
        return self.righe


def ricomponi(eventi, adesso=None, senza_risposta_s=1800):
    """Gli eventi con lo stesso id diventano una richiesta sola: chi, a chi, quando, come è finita."""
    adesso = adesso or time.time()
    per_id = {}
    for e in sorted(eventi, key=lambda x: x.get("ts", 0)):
        r = per_id.get(e["id"])
        if r is None:
            r = per_id[e["id"]] = {"id": e["id"], "da": e.get("da"), "a": e.get("a"), "testo": e.get("testo", ""),
                                   "inizio": e.get("ts"), "fine": None, "partito": None, "stato": "in corso",
                                   "durata_s": None, "esito": "", "errore": "", "rimandi": 0}
        for k in ("fonte", "sessione", "missione", "modello", "sfondo", "cwd"):
            if e.get(k) not in (None, "") and not r.get(k):
                r[k] = e[k]
        ev = e.get("ev")
        if ev == "richiesta":
            # la richiesta dice chi manda e a chi; un «partito» scritto prima (il gancio dell'SDK a volte
            # arriva prima del messaggio) aveva solo una stima
            r["da"], r["a"], r["testo"] = e.get("da"), e.get("a"), e.get("testo") or r["testo"]
            r["inizio"] = min(r["inizio"] or e.get("ts"), e.get("ts") or r["inizio"])
            if r["stato"] == "rimandato":
                r["stato"] = "in corso"           # rilanciato con lo stesso id
        elif ev == "partito":
            r["partito"] = e.get("ts")
            if r["stato"] in ("in corso", "rimandato"):
                r["stato"] = "al lavoro"
        elif ev == "rimandato":
            r["rimandi"] += 1
            r["stato"] = "rimandato"
            r["errore"] = e.get("errore") or e.get("testo") or "rimandato"
        elif ev in ("risposta", "errore"):
            r["fine"] = e.get("ts")
            # 2026-10-07: «codice di uscita 143/-15» è lo Stop dell'utente (SIGTERM), non un errore (anche le righe vecchie)
            fermato = ev == "errore" and re.search(r"codice di uscita (143|-15)\b", str(e.get("errore") or ""))
            r["stato"] = "errore" if ev == "errore" and not fermato else "finito"
            if fermato:
                r["esito"] = r["esito"] or "(fermato da te)"
            r["esito"] = e.get("esito") or r["esito"]
            if ev == "errore" and not fermato:
                r["errore"] = e.get("errore") or e.get("esito") or "errore"
            r["durata_s"] = e.get("durata_s") or (round(r["fine"] - r["inizio"], 1) if r["inizio"] else None)
    for r in per_id.values():
        if r["stato"] in ("in corso", "al lavoro") and adesso - (r["inizio"] or adesso) > senza_risposta_s:
            r["senza_risposta"] = True
    return sorted(per_id.values(), key=lambda r: r["inizio"] or 0, reverse=True)
