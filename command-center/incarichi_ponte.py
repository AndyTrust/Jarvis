#!/usr/bin/env python3
"""Dalla coda degli incarichi (VPS) agli eventi della lavagna (2026-10-04, agente «dots-vivi»).

L'utente: «devono vedersi avanzare ogni avatar Dots mentre le richieste passano da un agente all'altro».
La coda (~/Jarvis/strumenti/incarichi.py, contratto in docs/incarichi-contratto.md) sta sulla VPS; la
lavagna legge il registro delle attività (attivita.py). Qui un thread solo, ogni 8 s, legge
incarichi.stato_pubblico() (sul Mac via ssh, con la connessione riusata) e scrive nel registro i CAMBI:

    nuovo     → richiesta                    (da «jarvis-utente» → «jarvis», a «revisore» → «<progetto>:revisore»)
    preso     → partito
    fatto     → risposta  con durata_s       (dalla presa, o dalla creazione, alla risposta)
    fallito   → errore
    annullato → errore «annullato da …»
    scaduto   → errore «scaduto senza risposta»

Un incarico visto per la prima volta già avanti (nuovo e preso fra due giri) riceve anche i passi saltati,
in ordine: richiesta, partito, poi la fine. Mai due eventi uguali per lo stesso (id, passo): i passi già
scritti si tengono in memoria e, all'avvio, si rileggono dal registro di oggi (id «inc:…»).
Al primo giro lo storico NON si rigioca: gli incarichi che ci sono già contano come visti, salvo quelli
nati negli ultimi 2 minuti. Se la VPS non risponde: niente eventi, niente eccezioni, si riprova al giro
dopo, con una riga su stderr al massimo ogni 5 minuti.

Prova:  python3 incarichi_ponte.py prova     (finta coda, registro in una cartella temporanea)
"""
import os
import sys
import threading
import time
from pathlib import Path

OGNI_S = 8
NUOVI_S = 120             # al primo giro si raccontano solo gli incarichi nati negli ultimi 2 minuti
LOG_OGNI_S = 300
FONTE = "incarichi"
# 2026-10-10 (Jarvis da zero): nessun elenco scritto qui. Un nome della coda è un agente di progetto se ha la sua
# scheda in <cartella>/.claude/agents/ di un progetto di spazi.json: sulla lavagna è «<progetto>:<nome>».
AGENTI_PROVA = None        # solo per prova(): {nome: progetto}


def _agenti_progetti():
    if AGENTI_PROVA is not None:
        return AGENTI_PROVA
    out = {}
    try:
        import spazi
        for s in spazi.carica():
            for p in s["progetti"]:
                if p.get("esiste"):
                    for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                        out.setdefault(a["nome"], p["id"])
    except Exception:  # noqa: BLE001
        pass
    return out


FINE = {"fatto": "risposta", "fallito": "errore", "annullato": "errore", "scaduto": "errore"}

_THREAD = None
_LOCK = threading.Lock()


def chiave(nome):
    """Il nome di agente della coda → la chiave che risolvi_chiave() di server.py riconosce."""
    n = str(nome or "").strip().lower()
    if n in ("jarvis-utente", "jarvis"):
        return "jarvis"
    pid = _agenti_progetti().get(n)
    if pid:
        return f"{pid}:{n}"
    return n or "?"       # un nome che non è sulla lavagna: il server lo segna «?:nome» (richiesta senza destinatario)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Ponte:
    def __init__(self, fonte, registra, adesso=time.time, log=None):
        self.fonte = fonte                      # una funzione che torna il dict di stato_pubblico()
        self.registra = registra                # attivita.registra
        self.adesso = adesso
        self.log = log or (lambda t: print(t, file=sys.stderr, flush=True))
        self.fatti = {}                         # id incarico -> set dei passi scritti: richiesta, partito, fine
        self.primo = True
        self.ultimo_log = 0.0

    # ------------------------------------------------------------ registro di oggi (dopo un riavvio)
    def ricorda(self, eventi):
        """I passi già scritti nel registro (righe con id «inc:…»): non si riscrivono."""
        for e in eventi or ():
            id_ = str(e.get("id") or "")
            if not id_.startswith("inc:"):
                continue
            ev = e.get("ev")
            passo = "fine" if ev in ("risposta", "errore") else ev
            # un passo scritto vale anche per quelli prima (che al primo giro potevano essere «storico» non scritto)
            prima = {"richiesta": ["richiesta"], "partito": ["richiesta", "partito"],
                     "fine": ["richiesta", "partito", "fine"]}.get(passo)
            if prima:
                self.fatti.setdefault(id_[4:], set()).update(prima)

    # ------------------------------------------------------------ un giro
    def giro(self):
        """Legge la coda e scrive gli eventi nuovi. Torna quanti ne ha scritti (None se la coda non risponde)."""
        try:
            stato = self.fonte()
            incarichi = list((stato or {}).get("incarichi") or [])
        except Exception as e:  # noqa: BLE001 — VPS spenta, ssh caduto, JSON rotto: si riprova fra 8 s
            t = self.adesso()
            if t - self.ultimo_log >= LOG_OGNI_S:
                self.ultimo_log = t
                self.log(f"incarichi_ponte: coda non letta ({type(e).__name__}: {str(e)[:160]}), riprovo ogni {OGNI_S} s")
            return None
        adesso = self.adesso()
        scritti = 0
        for inc in sorted(incarichi, key=lambda d: d.get("creato") or 0):
            id_ = str(inc.get("id") or "")
            stato_inc = inc.get("stato")
            if not id_ or stato_inc not in ("nuovo", "preso") + tuple(FINE):
                continue
            fatti = self.fatti.setdefault(id_, set())
            if self.primo and adesso - (_num(inc.get("creato")) or 0) > NUOVI_S:
                fatti.update(self._passi(stato_inc))          # storico: visto, non raccontato
                continue
            for passo in self._passi(stato_inc):
                if passo in fatti:
                    continue
                fatti.add(passo)
                self._scrivi(passo, inc)
                scritti += 1
        self.primo = False
        # la coda tiene gli ultimi 50: chi ne è uscito non serve più ricordarlo
        vivi = {str(d.get("id")) for d in incarichi}
        if len(self.fatti) > 500:
            for k in [k for k in self.fatti if k not in vivi]:
                del self.fatti[k]
        return scritti

    @staticmethod
    def _passi(stato):
        return {"nuovo": ["richiesta"], "preso": ["richiesta", "partito"]}.get(
            stato, ["richiesta", "partito", "fine"] if stato in ("fatto", "fallito") else ["richiesta", "fine"])

    def _scrivi(self, passo, inc):
        id_, da, a = "inc:" + str(inc["id"]), chiave(inc.get("da")), chiave(inc.get("a"))
        testo = inc.get("testo") or ""
        comuni = {"fonte": FONTE, "tipo": inc.get("tipo")}
        if passo == "richiesta":
            self.registra("richiesta", id_, da, a, testo, **comuni)
        elif passo == "partito":
            self.registra("partito", id_, da, a, testo, preso_da=inc.get("preso_da"), **comuni)
        else:
            stato = inc.get("stato")
            r = inc.get("risposta") or {}
            inizio = _num(inc.get("preso_il")) or _num(inc.get("creato"))
            fine = _num(r.get("il")) or _num(inc.get("annullato_il")) or self.adesso()
            durata = round(max(0.0, fine - inizio), 1) if inizio else None
            if stato == "fatto" and r.get("esito", "ok") == "ok":
                self.registra("risposta", id_, da, a, testo, durata_s=durata, esito=r.get("testo") or "fatto",
                              token_stimati=r.get("token_stimati"), **comuni)
                return
            if stato == "annullato":
                errore = f"annullato da {inc.get('annullato_da') or '?'}"
            elif stato == "scaduto":
                errore = "scaduto senza risposta"
            else:
                errore = r.get("testo") or "fallito"
            self.registra("errore", id_, da, a, testo, errore=errore, esito=stato,
                          durata_s=durata if stato in ("fatto", "fallito") else None, **comuni)


# ------------------------------------------------------------ il thread del Command Center

def _strumenti():
    p = str(Path(__file__).resolve().parents[1] / "strumenti")
    if p not in sys.path:
        sys.path.insert(0, p)
    import incarichi  # noqa: E402
    return incarichi


def _ciclo(ponte):
    while True:
        try:
            ponte.giro()
        except Exception as e:  # noqa: BLE001 — il thread non deve morire per un incarico strano
            ponte.log(f"incarichi_ponte: giro fallito ({type(e).__name__}: {str(e)[:160]})")
        time.sleep(OGNI_S)


def avvia():
    """Fa partire UN thread demone (le chiamate dopo la prima non fanno niente). Torna il thread."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return _THREAD
        import attivita
        incarichi = _strumenti()
        ponte = Ponte(incarichi.stato_pubblico, attivita.registra)
        try:
            righe = attivita.Lettore(giorni=2).eventi()
            ponte.ricorda(righe)
        except Exception:  # noqa: BLE001
            pass
        _THREAD = threading.Thread(target=_ciclo, args=(ponte,), name="incarichi_ponte", daemon=True)
        _THREAD.start()
        return _THREAD


# ------------------------------------------------------------ prova

def prova():
    global AGENTI_PROVA
    AGENTI_PROVA = {n: "progetto-a" for n in ("progetto-a-ceo", "commercialista", "garante-dati")}
    import json
    import shutil
    import tempfile
    cartella = Path(tempfile.mkdtemp(prefix="prova-ponte-"))
    os.environ["JARVIS_ATTIVITA_DIR"] = str(cartella)
    os.environ["JARVIS_ATTIVITA_EXTRA"] = str(cartella / "nessuna")
    os.environ["JARVIS_ATTIVITA_CONDIVIDI"] = "0"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attivita
    attivita.DIR = cartella
    esiti = []

    def v(nome, cond):
        esiti.append(bool(cond))
        print(("  ok   " if cond else "  NO   ") + nome)

    def righe():
        f = attivita.file_del_giorno()
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    ora = [1_800_000_000.0]
    coda = {"incarichi": []}
    giu = [False]

    def finta():
        if giu[0]:
            raise OSError("ssh vps-tuo: nessuna risposta in 60 s")
        return json.loads(json.dumps(coda))

    log = []
    p = Ponte(finta, attivita.registra, adesso=lambda: ora[0], log=log.append)

    def inc(id_, stato, creato, a="garante-dati", **k):
        d = {"id": id_, "da": "jarvis-utente", "a": a, "tipo": "domanda", "testo": f"prova {id_}", "creato": creato,
             "scade": creato + 86400, "stato": stato, "preso_da": None, "preso_il": None, "risposta": None}
        d.update(k)
        return d

    try:
        # storico: uno vecchio fatto, uno vecchio preso, uno nato 30 s fa
        coda["incarichi"] = [inc("in_00000001", "fatto", ora[0] - 3600, preso_il=ora[0] - 3500,
                                 risposta={"testo": "ok", "esito": "ok", "il": ora[0] - 3400}),
                             inc("in_00000002", "preso", ora[0] - 900, preso_da="garante-dati", preso_il=ora[0] - 800),
                             inc("in_00000003", "nuovo", ora[0] - 30, a="commercialista")]
        n = p.giro()
        r = righe()
        v("primo giro: lo storico non si rigioca, il nato da 30 s sì (1 evento)", n == 1 and len(r) == 1)
        v("richiesta: id inc:, da jarvis, a progetto-a:commercialista, fonte incarichi",
          r and r[0]["ev"] == "richiesta" and r[0]["id"] == "inc:in_00000003" and r[0]["da"] == "jarvis"
          and r[0]["a"] == "progetto-a:commercialista" and r[0]["fonte"] == "incarichi")
        v("secondo giro senza cambi: nessun evento", p.giro() == 0 and len(righe()) == 1)
        # avanzano: 3 preso, 2 fatto (vecchio ma cambiato dopo l'avvio: si racconta)
        ora[0] += 8
        coda["incarichi"][2].update(stato="preso", preso_da="commercialista", preso_il=ora[0] - 2)
        coda["incarichi"][1].update(stato="fatto", risposta={"testo": "fatto bene", "esito": "ok", "il": ora[0] - 1,
                                                             "token_stimati": 12})
        p.giro()
        r = righe()
        v("preso → partito", any(x["ev"] == "partito" and x["id"] == "inc:in_00000003" for x in r))
        risp = [x for x in r if x["ev"] == "risposta" and x["id"] == "inc:in_00000002"]
        v("fatto → risposta con durata_s (dalla presa)", len(risp) == 1 and risp[0]["durata_s"] == round(ora[0] - 1 - (ora[0] - 8 - 800), 1))
        v("nessuna richiesta riscritta per lo storico", not any(x["ev"] == "richiesta" and x["id"] == "inc:in_00000002" for x in r))
        # uno nuovo che passa da nuovo a fatto fra due giri: richiesta, partito, risposta in ordine
        ora[0] += 8
        coda["incarichi"].append(inc("in_00000004", "fatto", ora[0] - 6, a="progetto-a-ceo", preso_da="progetto-a-ceo", preso_il=ora[0] - 5,
                                     risposta={"testo": "sì", "esito": "ok", "il": ora[0] - 1}))
        coda["incarichi"].append(inc("in_00000005", "fallito", ora[0] - 6, preso_da="garante-dati", preso_il=ora[0] - 5,
                                     risposta={"testo": "timeout di 600 s", "esito": "fallito", "il": ora[0] - 1}))
        coda["incarichi"].append(inc("in_00000006", "annullato", ora[0] - 6, annullato_da="jarvis-utente", annullato_il=ora[0] - 2))
        coda["incarichi"].append(inc("in_00000007", "scaduto", ora[0] - 7))
        coda["incarichi"].append(inc("in_00000008", "nuovo", ora[0] - 3, a="sconosciuto-x"))
        p.giro()
        r = righe()
        quattro = [x["ev"] for x in r if x["id"] == "inc:in_00000004"]
        v("saltato tutto fra due giri: richiesta, partito, risposta in ordine", quattro == ["richiesta", "partito", "risposta"])
        cinque = [x for x in r if x["id"] == "inc:in_00000005"]
        v("fallito → errore con il motivo", [x["ev"] for x in cinque] == ["richiesta", "partito", "errore"]
          and cinque[-1]["errore"] == "timeout di 600 s")
        sei = [x for x in r if x["id"] == "inc:in_00000006"]
        v("annullato → errore «annullato da jarvis-utente»", [x["ev"] for x in sei] == ["richiesta", "errore"]
          and sei[-1]["errore"] == "annullato da jarvis-utente")
        sette = [x for x in r if x["id"] == "inc:in_00000007"]
        v("scaduto → errore «scaduto senza risposta»", sette[-1]["ev"] == "errore" and sette[-1]["errore"] == "scaduto senza risposta")
        otto = [x for x in r if x["id"] == "inc:in_00000008"]
        v("destinatario fuori dalla lavagna: il nome resta (il server lo segna «?:»)", otto and otto[0]["a"] == "sconosciuto-x")
        # mai due eventi uguali per lo stesso (id, ev)
        coppie = [(x["id"], x["ev"]) for x in righe()]
        v(f"mai due eventi uguali per (id, ev) ({len(coppie)} righe)", len(coppie) == len(set(coppie)))
        # VPS giù: niente eventi, niente eccezioni, un log solo in 5 minuti
        giu[0] = True
        prima = len(righe())
        esiti_giu = []
        for _ in range(10):
            ora[0] += 8
            esiti_giu.append(p.giro())
        v("VPS giù: nessun evento, nessuna eccezione", all(x is None for x in esiti_giu) and len(righe()) == prima)
        v(f"VPS giù: una riga di log in 80 s ({len(log)})", len(log) == 1)
        ora[0] += 300
        p.giro()
        v("VPS giù: un'altra riga dopo 5 minuti", len(log) == 2)
        giu[0] = False
        coda["incarichi"][-1].update(stato="preso", preso_da="x", preso_il=ora[0])
        ora[0] += 8
        v("VPS di nuovo su: riprende (partito dell'ultimo)", p.giro() == 1)
        # riavvio del Command Center: un ponte nuovo che rilegge il registro non ripete niente
        q = Ponte(finta, attivita.registra, adesso=lambda: ora[0], log=log.append)
        q.ricorda(attivita.Lettore(giorni=1).eventi())
        prima = len(righe())
        coda["incarichi"].append(inc("in_00000009", "nuovo", ora[0] - 5))
        q.giro()
        nuove = righe()[prima:]
        v("dopo un riavvio: solo l'incarico nuovo, niente doppioni dei recenti",
          [(x["id"], x["ev"]) for x in nuove] == [("inc:in_00000009", "richiesta")])
        v("le chiavi: jarvis-utente→jarvis, garante-dati→progetto-a:garante-dati, altro invariato",
          chiave("jarvis-utente") == "jarvis" and chiave("garante-dati") == "progetto-a:garante-dati" and chiave("jarvis-giuseppe") == "jarvis-giuseppe")
        # avvia(): un thread solo
        global _THREAD
        _THREAD = None
        import types
        finto_mod = types.SimpleNamespace(stato_pubblico=finta)
        vero = globals()["_strumenti"]
        globals()["_strumenti"] = lambda: finto_mod
        try:
            t1, t2 = avvia(), avvia()
            v("avvia(): un thread demone solo", t1 is t2 and t1.daemon and t1.is_alive()
              and sum(1 for t in threading.enumerate() if t.name == "incarichi_ponte") == 1)
        finally:
            globals()["_strumenti"] = vero
    finally:
        shutil.rmtree(cartella, ignore_errors=True)
    print("tutto ok" if all(esiti) else f"{esiti.count(False)} prove fallite")
    return 0 if all(esiti) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["prova"]:
        sys.exit(prova())
    print(__doc__)
