#!/usr/bin/env python3
"""Dal registro dei lavori (strumenti/lavori.py) agli eventi della lavagna (2026-10-05, «lavagna viva»).

L'utente: «come mai non vedo nella lavagna gli agenti e le riunioni lavorare?». Ogni agente, prima di toccare
qualcosa, fa `lavori.py prendo "<progetto>" "<cosa>" --agente <nome>` e alla fine `finito "<esito>"`: è la
fonte più affidabile di «chi lavora adesso», da qualunque sessione o macchina. Qui un thread solo, ogni 2 s,
guarda le prese del registro (sulla VPS dal 2026-10-05; sul Mac la sua copia ~/.cache/jarvis-lavori/attivi) e scrive nel registro delle attività (attivita.py) i cambi:

    file nuovo (prendo)          → richiesta + partito   da «jarvis» (riunione: «<progetto>:capogruppo»)
                                                          a «<progetto>:<agente>» (lo risolve il server)
    file sparito (finito)        → risposta con l'esito della riga di storico, o errore se «chiusa male»
    file rinominato «.fantasma»  → errore «sessione morta»

Solo le prese di QUESTA macchina (campo «macchina»): quelle delle altre arrivano già come eventi dalla loro
macchina (attivita_ponte.py), e il registro su OneDrive arriva alla VPS con minuti di ritardo.
Un lavoro già raccontato dal gancio di Claude Code (una richiesta aperta verso lo stesso agente, fonte «hook»)
non si racconta due volte: `coperto(chiave)` lo dice.
Al primo giro le prese più vecchie di 2 minuti contano come viste (stato, non storia).

Prova:  python3 lavori_ponte.py prova
"""
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

OGNI_S = 2
NUOVI_S = 120
MORTA_S = 45 * 60         # come lavori.py: senza battito da 45 minuti la presa è morta, non si racconta
FONTE = "lavori"
_THREAD = None
_LOCK = threading.Lock()


def _slug(t):
    import re
    t = str(t or "").lower().replace("'", " ")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "senza-nome"


class Ponte:
    def __init__(self, attivi, storico, macchina, registra, coperto=None, adesso=time.time, log=None):
        self.attivi = Path(attivi)
        self.storico = Path(storico)
        self.macchina = macchina
        self.registra = registra
        self.coperto = coperto or (lambda chiave: False)
        self.adesso = adesso
        self.log = log or (lambda t: print(t, file=sys.stderr, flush=True))
        self.visti = {}          # nome file -> {"d": presa, "raccontato": bool, "ts": inizio}
        self.primo = True

    def _leggi(self):
        fuori = {}
        try:
            nomi = list(self.attivi.iterdir())
        except OSError:
            return None
        for f in nomi:
            if f.suffix != ".json":
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict) or d.get("macchina") != self.macchina or not d.get("agente"):
                continue
            try:
                d["_mtime"] = f.stat().st_mtime
            except OSError:
                d["_mtime"] = None
            fuori[f.name] = d
        return fuori

    @staticmethod
    def chiavi(d):
        """(da, a) per il registro: il server le risolve in «progetto:nome» (o «?:nome»)."""
        prog, agente = str(d.get("progetto") or "").strip(), str(d.get("agente") or "").strip()
        a = f"{_slug(prog)}:{agente}" if prog else agente
        da = "jarvis"
        if str(d.get("cosa") or "").lower().startswith("riunione") and prog and not agente.endswith("-ceo"):   # il capogruppo si chiama <progetto>-ceo
            da = f"{_slug(prog)}:capogruppo"
        return da, a

    def _esito(self, d):
        """L'esito scritto da `finito` nello storico di questa macchina (ultima riga con agente e cosa)."""
        f = self.storico / f"{datetime.now().strftime('%Y-%m')}__{_slug(self.macchina)}.md"
        try:
            with open(f, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 20000))
                righe = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return None
        pulisci = lambda t: str(t or "").replace("|", "/").replace("\n", " ").strip()
        for r in reversed(righe):
            celle = [c.strip() for c in r.strip().strip("|").split("|")]
            if len(celle) >= 5 and celle[2] == pulisci(d.get("agente")) and celle[3] == pulisci(d.get("cosa")):
                return celle[4]
        return None

    def giro(self):
        ora = self._leggi()
        if ora is None:
            return None
        adesso = self.adesso()
        scritti = 0
        for nome, d in sorted(ora.items(), key=lambda x: x[1].get("ts") or 0):
            if nome in self.visti:
                self.visti[nome]["d"] = d
                continue
            # le prese vecchie senza «ts» (settembre) hanno solo la data del file: mai «adesso»
            inizio = float(d.get("ts") or d.get("_mtime") or adesso)
            vivo = float(d.get("ts_battito") or d.get("_mtime") or inizio)
            v = self.visti[nome] = {"d": d, "raccontato": False, "ts": inizio}
            if (self.primo and adesso - inizio > NUOVI_S) or adesso - vivo > MORTA_S:
                continue
            da, a = self.chiavi(d)
            if self.coperto(a):
                continue
            # lo stesso file torna a ogni presa della stessa sessione e agente: l'inizio fa l'id unico
            id_ = v["id"] = f"lav:{nome[:-5]}:{int(inizio)}"
            testo = d.get("cosa") or ""
            self.registra("richiesta", id_, da, a, testo, fonte=FONTE, pc=self.macchina)
            self.registra("partito", id_, da, a, testo, fonte=FONTE, pc=self.macchina)
            v["raccontato"] = True
            scritti += 2
        for nome in [n for n in self.visti if n not in ora]:
            v = self.visti.pop(nome)
            if not v["raccontato"]:
                continue
            d = v["d"]
            da, a = self.chiavi(d)
            id_ = v["id"]
            durata = round(max(0.0, adesso - v["ts"]), 1)
            fantasma = any(x.name.startswith(nome + ".fantasma") for x in self.attivi.glob(nome + ".fantasma*"))
            esito = self._esito(d)
            if fantasma or (esito or "").lower().startswith("chiusa male"):
                self.registra("errore", id_, a, da, d.get("cosa") or "", fonte=FONTE, durata_s=durata,
                              errore=esito or "sessione morta senza «finito»", pc=self.macchina)
            else:
                self.registra("risposta", id_, a, da, d.get("cosa") or "", fonte=FONTE, durata_s=durata,
                              esito=esito or "finito", pc=self.macchina)
            scritti += 1
        self.primo = False
        return scritti


def _ciclo(ponte, aggiorna=None):
    while True:
        try:
            if aggiorna:
                aggiorna()   # dal 2026-10-05 il registro sta sulla VPS: sul Mac si legge la sua copia
            ponte.giro()
        except Exception as e:  # noqa: BLE001 — il thread non deve morire per un file strano
            ponte.log(f"lavori_ponte: giro fallito ({type(e).__name__}: {str(e)[:160]})")
        time.sleep(OGNI_S)


def avvia(coperto=None):
    """Un thread demone solo. `coperto(chiave)`: True se il gancio di Claude Code sta già raccontando quell'agente."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return _THREAD
        import attivita
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
        import lavori  # noqa: E402
        ponte = Ponte(lavori.ATTIVI, lavori.STORICO, lavori.macchina(), attivita.registra, coperto=coperto)
        aggiorna = lavori.aggiorna_specchio if getattr(lavori, "CLIENTE", False) else None
        _THREAD = threading.Thread(target=_ciclo, args=(ponte, aggiorna), name="lavori_ponte", daemon=True)
        _THREAD.start()
        return _THREAD


def prova():
    import shutil
    import tempfile
    c = Path(tempfile.mkdtemp(prefix="prova-lavori-ponte-"))
    att, sto = c / "attivi", c / "storico"
    att.mkdir()
    sto.mkdir()
    eventi, esiti = [], []
    ora = [1_800_000_000.0]

    def v(nome, cond):
        esiti.append(bool(cond))
        print(("  ok   " if cond else "  NO   ") + nome)

    def reg(ev, id_, da, a, testo="", **k):
        eventi.append({"ev": ev, "id": id_, "da": da, "a": a, "testo": testo, **k})

    def presa(nome, agente, progetto, cosa, ts, macchina="Mac"):
        (att / nome).write_text(json.dumps({"progetto": progetto, "agente": agente, "cosa": cosa, "macchina": macchina,
                                            "ts": ts}))
        os.utime(att / nome, (ts, ts))
    coperti = set()
    p = Ponte(att, sto, "Mac", reg, coperto=lambda k: k in coperti, adesso=lambda: ora[0])
    try:
        presa("mac__s__vecchio__x.json", "gb-posta", "Gruppo B", "vecchio", ora[0] - 3600)
        (att / "mac__s__senzats__x.json").write_text(json.dumps({"progetto": "Jarvis", "agente": "vecchio", "cosa": "settembre",
                                                                "macchina": "Mac"}))
        os.utime(att / "mac__s__senzats__x.json", (ora[0] - 86400 * 15,) * 2)
        presa("mac__s__nuovo__x.json", "gb-gestionale", "Gruppo B", "riunione: posizione", ora[0] - 5)
        presa("pc__s__altro__x.json", "commercialista", "Gruppo A", "altro", ora[0] - 5, macchina="PC")
        p.giro()
        v("primo giro: solo la presa recente di questa macchina (richiesta+partito)",
          [(e["ev"], e["id"]) for e in eventi] == [("richiesta", f"lav:mac__s__nuovo__x:{int(ora[0] - 5)}"),
                                                    ("partito", f"lav:mac__s__nuovo__x:{int(ora[0] - 5)}")])
        v("riunione: da gruppo-b:capogruppo a gruppo-b:gb-gestionale",
          eventi[0]["da"] == "gruppo-b:capogruppo" and eventi[0]["a"] == "gruppo-b:gb-gestionale" and eventi[0]["fonte"] == "lavori")
        v("secondo giro senza cambi: niente", p.giro() == 0)
        # finito con esito nello storico
        f = sto / f"{datetime.now().strftime('%Y-%m')}__mac.md"
        f.write_text("| Finito | Progetto | Agente | Cosa | Esito | File |\n|---|---|---|---|---|---|\n"
                     "| 2026-10-05 10:46 | Gruppo B | gb-gestionale | riunione: posizione | posizione scritta | — |\n")
        (att / "mac__s__nuovo__x.json").unlink()
        ora[0] += 30
        p.giro()
        r = eventi[-1]
        v("finito → risposta con l'esito e la durata, verso inverso",
          r["ev"] == "risposta" and r["esito"] == "posizione scritta" and r["da"] == "gruppo-b:gb-gestionale"
          and r["a"] == "gruppo-b:capogruppo" and r["durata_s"] == 35.0)
        v("la presa vecchia sparita (mai raccontata) non scrive niente", (att / "mac__s__vecchio__x.json").unlink() or p.giro() == 0)
        # dopo un riavvio: una presa senza «ts» e ferma da settimane non è «nuova»
        q = Ponte(att, sto, "Mac", reg, adesso=lambda: ora[0] + 10)
        n = len(eventi)
        q.giro()
        v("presa senza ts, ferma da settimane: non si racconta", len(eventi) == n)
        # coperto dal gancio
        coperti.add("jarvis:programmatore-x")
        presa("mac__s__prog__jarvis.json", "programmatore-x", "Jarvis", "lavagna", ora[0])
        n = len(eventi)
        p.giro()
        v("coperto dal gancio: niente doppioni", len(eventi) == n)
        # fantasma
        presa("mac__s__morto__x.json", "analista", "Gruppo C", "analisi", ora[0])
        p.giro()
        (att / "mac__s__morto__x.json").rename(att / "mac__s__morto__x.json.fantasma-pid1-morto")
        p.giro()
        v("presa diventata fantasma → errore", eventi[-1]["ev"] == "errore" and eventi[-1]["a"] == "jarvis"
          and eventi[-1]["da"] == "gruppo-c:analista")
        # chiusa male
        presa("mac__s__male__x.json", "gruppo-d-ceo", "Gruppo D", "riunione: verdetto", ora[0])
        p.giro()
        v("capogruppo in riunione: da jarvis", eventi[-2]["da"] == "jarvis")
        with f.open("a") as fh:
            fh.write("| 2026-10-05 11:00 | Gruppo D | gruppo-d-ceo | riunione: verdetto | chiusa male: nessun battito | — |\n")
        (att / "mac__s__male__x.json").unlink()
        p.giro()
        v("«chiusa male» nello storico → errore", eventi[-1]["ev"] == "errore" and "chiusa male" in eventi[-1]["errore"])
        # stessa sessione e agente, seconda presa: stesso file, id nuovo
        primo_id = eventi[-1]["id"]
        ora[0] += 60
        presa("mac__s__male__x.json", "gruppo-d-ceo", "Gruppo D", "di nuovo", ora[0])
        p.giro()
        v("seconda presa con lo stesso file: id diverso", eventi[-1]["ev"] == "partito" and eventi[-1]["id"] != primo_id)
    finally:
        shutil.rmtree(c, ignore_errors=True)
    print("tutto ok" if all(esiti) else f"{esiti.count(False)} prove fallite")
    return 0 if all(esiti) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["prova"]:
        sys.exit(prova())
    print(__doc__)
