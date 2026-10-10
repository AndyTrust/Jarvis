#!/usr/bin/env python3
"""Il Registro (2026-10-03): l'elenco unico di ciò che Jarvis ha fatto o tentato, con l'esito e, per ogni
rifiuto, la regola che l'ha causato. Idea presa da OpenBot, decisione dell'utente del 2026-10-03.
Contratto: command-center/CONTRATTO-registro.md.

Fonti (tutte in sola lettura):
  approvazione  l'archivio delle schede (approvazioni.py): approvata, rifiutata, scaduta
  regola        registro/regole.jsonl: consenti e nega decisi da una regola (regole_permessi.py),
                più gli errori del file delle regole
  auto          stesso file, righe con fonte_decisione «auto»: autorizzati o negati da Jarvis (conformita.py, 2026-10-04)
  guardia       registro/guardia.jsonl: i comandi bloccati dalla guardia (~/.claude/hooks/guardia_comandi.py)
  ponte         /var/lib/cc-ponte/comandi.jsonl sulla VPS: i POST arrivati dal sito
  schermo       /var/lib/cc-ponte/schermo.jsonl sulla VPS: chi ha guardato lo schermo (raggruppato)
Le due fonti della VPS si leggono con UNA chiamata ssh (tail -n 500, timeout 10 s), tenuta in cache 30 s
e rifatta in un thread: una VPS che non risponde non rallenta la pagina, la fonte risulta
«non raggiungibile» e l'elenco continua con le altre.

Ogni testo passa da approvazioni.pulisci (righe con parole da segreto nascoste, token mascherati) ed è
troncato. Niente anteprime dei file, niente variabili d'ambiente, niente IP.
Solo libreria standard.
"""
import json
import os
import re
import shlex
import subprocess
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import approvazioni as A
import regole_permessi as R

FONTI = ("approvazione", "regola", "auto", "guardia", "ponte", "schermo")   # «auto» dal 2026-10-04: le decide Jarvis (conformita.py)
ESITI = ("permesso", "rifiutato", "fallito", "scaduto")
LIMITE_MAX = 500
RIGHE_LOCALI = 3000            # dalle code dei file locali
CACHE_VPS_S = 30
TIMEOUT_VPS_S = 10
ATTESA_PRIMA_S = 3             # la prima lettura della VPS aspetta al massimo questo, poi risponde senza
SOGLIA_PROPOSTE = 5
SEPARATORE = "@@CC-REGISTRO-SCHERMO@@"
# comando fisso, nessun pezzo viene dalla richiesta: niente iniezioni. Le prove lo cambiano con CC_REGISTRO_VPS_CMD.
COMANDO_VPS = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5", "vps-tuo",
               f"tail -n 500 /var/lib/cc-ponte/comandi.jsonl 2>/dev/null; echo {SEPARATORE}; "
               "tail -n 500 /var/lib/cc-ponte/schermo.jsonl 2>/dev/null; true"]


class RichiestaNonValida(ValueError):
    pass


def _corto(testo, n):
    return A.pulisci(testo, n).replace("\n", " ")


# ---------------------------------------------------------------- letture locali

def _coda_jsonl(f, n=RIGHE_LOCALI):
    """Le ultime n righe JSON valide di un file (le righe rotte si saltano)."""
    try:
        with open(f, "rb") as h:
            h.seek(0, os.SEEK_END)
            dim = h.tell()
            h.seek(max(0, dim - 2 * 1024 * 1024))
            righe = h.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return None
    out = []
    for r in righe:
        try:
            d = json.loads(r)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _ts(v):
    """epoch da un numero o da un'ora ISO (la VPS scrive in UTC con la Z: si conta sul tempo assoluto)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return int(d.timestamp())
        except ValueError:
            return None
    return None


def evento(ts, fonte, esito, azione, riepilogo, regola=None, dettagli=None):
    return {"ts": int(ts), "fonte": fonte, "esito": esito, "azione": _corto(azione, 60),
            "riepilogo": _corto(riepilogo, 160), "regola": _corto(regola, 80) if regola else None,
            "dettagli": {k: (_corto(v, 300) if isinstance(v, str) else v) for k, v in (dettagli or {}).items()
                         if v not in (None, "")}}


ESITO_APPROVAZIONE = {"approvata": "permesso", "rifiutata": "rifiutato", "scaduta": "scaduto"}


def da_approvazioni():
    tutte = A.tutte_pubbliche()
    out = []
    for a in tutte.values():
        esito = ESITO_APPROVAZIONE.get(a.get("stato"))
        if not esito:
            continue                     # in attesa: sta nelle schede, non nel registro
        d = a.get("dettagli") if isinstance(a.get("dettagli"), dict) else {}
        chi = a.get("deciso_da")
        dett = {"id": a.get("id"), "rischio": a.get("rischio"), "agente": a.get("agente"), "lavoro_id": a.get("lavoro_id"),
                "deciso_da": {"web": "L'utente dal sito", "mac": "L'utente dal Mac", "telegram": "L'utente da Telegram",
                              "nessuno": "nessuno (tempo scaduto)"}.get(chi, chi),
                "motivo": a.get("motivo"), "comando": d.get("comando"), "percorso": d.get("percorso"),
                "righe_aggiunte": d.get("righe_aggiunte"), "righe_tolte": d.get("righe_tolte")}
        out.append(evento(a.get("deciso") or a.get("creata") or 0, "approvazione", esito, a.get("strumento") or "",
                          a.get("riepilogo") or "", a.get("regola"), dett))
    return out


def da_regole():
    righe = _coda_jsonl(R.cartella_registro() / "regole.jsonl")
    if righe is None:
        return [], "vuota"
    out = []
    for r in righe:
        ts = _ts(r.get("ts"))
        if ts is None:
            continue
        if r.get("tipo") == "errore_file":
            out.append(evento(ts, "regola", "fallito", "file delle regole", r.get("riepilogo") or "file non valido", None,
                              {"in_uso": r.get("origine")}))
            continue
        esito = r.get("esito") if r.get("esito") in ("permesso", "rifiutato") else None
        if not esito:
            continue
        if r.get("fonte_decisione") == "auto":       # 2026-10-04: autorizzato o negato da Jarvis, senza scheda
            metodo = {"regola": "paletto o regola fissa", "modello": "controllo del modello",
                      "errore": "controllo non disponibile"}.get(r.get("metodo"), r.get("metodo"))
            out.append(evento(ts, "auto", esito, r.get("strumento") or "", r.get("riepilogo") or "", r.get("regola"),
                              {"rischio": r.get("rischio"), "agente": r.get("agente"), "lavoro_id": r.get("lavoro_id"),
                               "deciso_da": f"Jarvis ({metodo})", "motivo": r.get("motivo"), "metodo": r.get("metodo"),
                               "ms": r.get("ms")}))
            continue
        out.append(evento(ts, "regola", esito, r.get("strumento") or "", r.get("riepilogo") or "", r.get("regola"),
                          {"rischio": r.get("rischio"), "agente": r.get("agente"), "lavoro_id": r.get("lavoro_id"),
                           "deciso_da": "regola del file" if r.get("origine") == "file" else f"regola ({r.get('origine')})"}))
    return out, "ok"


def da_guardia():
    righe = _coda_jsonl(R.cartella_registro() / "guardia.jsonl")
    if righe is None:
        return [], "vuota"
    out = []
    for r in righe:
        ts = _ts(r.get("ts"))
        if ts is None:
            continue
        esito = "permesso" if r.get("esito") == "permesso" else "rifiutato"
        cmd = str(r.get("comando") or "")
        out.append(evento(ts, "guardia", esito, "Bash", ("Confermato dall'utente: " if esito == "permesso" else "Bloccato: ") + cmd,
                          "guardia: " + str(r.get("motivo") or ""),
                          {"comando": cmd, "cartella": A.breve_percorso(r.get("cwd") or ""),
                           "deciso_da": "L'utente (JARVIS_CONFERMATO=1)" if esito == "permesso" else "guardia dei comandi"}))
    return out, "ok"


# ---------------------------------------------------------------- la VPS (ponte e schermo)

def _esito_http(c):
    try:
        c = int(c)
    except (TypeError, ValueError):
        return "fallito"
    if 200 <= c < 300:
        return "permesso"
    if c >= 500:
        return "fallito"
    return "rifiutato"


REGOLA_PONTE = {401: "ponte: serve l'accesso", 403: "ponte: filtro del sito", 409: "ponte: modo della chat",
                400: "ponte: richiesta non valida", 413: "ponte: richiesta troppo grande", 415: "ponte: richiesta non valida",
                429: "ponte: troppe richieste insieme"}


def _ponte(righe):
    out = []
    for r in righe:
        ts = _ts(r.get("ts"))
        if ts is None:
            continue
        codice = r.get("esito")
        esito = _esito_http(codice)
        tipo = str(r.get("tipo") or "") or "(senza tipo)"
        pezzi = [f"Dal sito: {tipo}"]
        if r.get("cosa"):
            pezzi.append(str(r["cosa"]))
        if r.get("id"):
            pezzi.append(str(r["id"]))
        if r.get("decisione"):
            pezzi.append("decisione " + str(r["decisione"]))
        if r.get("testo"):
            pezzi.append("«" + str(r["testo"]) + "»")
        regola = REGOLA_PONTE.get(codice) if esito == "rifiutato" else None
        out.append(evento(ts, "ponte", esito, tipo, " · ".join(pezzi), regola,
                          {"codice": codice, "sessione": str(r.get("sessione") or "")[:10], "modo": r.get("modo"),
                           "durata_s": r.get("durata"), "percorso": r.get("percorso")}))
    return out


def _schermo(righe):
    """Lo schermo si chiede ogni 2 s: le richieste uguali e vicine (stessa sessione, stesso esito, meno di
    2 minuti l'una dall'altra) diventano un evento solo."""
    gruppi = []
    for r in sorted(righe, key=lambda x: _ts(x.get("ts")) or 0):
        ts = _ts(r.get("ts"))
        if ts is None:
            continue
        chiave = (str(r.get("sessione") or ""), str(r.get("percorso") or ""), _esito_http(r.get("esito")), r.get("esito"))
        g = gruppi[-1] if gruppi and gruppi[-1]["chiave"] == chiave and ts - gruppi[-1]["ultimo"] <= 120 else None
        if g:
            g["ultimo"], g["n"], g["byte"] = ts, g["n"] + 1, g["byte"] + int(r.get("byte") or 0)
        else:
            gruppi.append({"chiave": chiave, "primo": ts, "ultimo": ts, "n": 1, "byte": int(r.get("byte") or 0)})
    out = []
    for g in gruppi:
        sess, percorso, esito, codice = g["chiave"]
        cosa = "immagine dello schermo" if percorso == "schermo" else "stato del computer" if percorso == "stato" else percorso
        quante = f" ({g['n']} richieste in {max(1, round((g['ultimo'] - g['primo']) / 60))} min)" if g["n"] > 1 else ""
        out.append(evento(g["ultimo"], "schermo", esito, percorso or "schermo", f"Dal sito: {cosa}{quante}",
                          REGOLA_PONTE.get(codice) if esito == "rifiutato" and codice != 403 else
                          ("ponte: schermo spento o filtro" if codice == 403 else None),
                          {"codice": codice, "sessione": sess[:10], "richieste": g["n"], "dal": g["primo"],
                           "byte": g["byte"]}))
    return out


class LettoreVPS:
    """Cache di 30 s della lettura ssh, rifatta in un thread (una alla volta)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.dati = None            # (ponte, schermo) righe grezze
        self.letto = 0              # quando è finita l'ultima lettura (anche fallita)
        self.stato = "non ancora letta"
        self.thread = None

    def comando(self):
        altro = os.environ.get("CC_REGISTRO_VPS_CMD")
        if altro:
            try:
                c = json.loads(altro)
                if isinstance(c, list) and all(isinstance(x, str) for x in c):
                    return c
            except ValueError:
                pass
        return COMANDO_VPS

    def _leggi(self):
        try:
            r = subprocess.run(self.comando(), capture_output=True, timeout=TIMEOUT_VPS_S, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                raise OSError(f"uscita {r.returncode}")
            testo = r.stdout.decode("utf-8", "replace")
            if SEPARATORE not in testo:
                raise OSError("risposta inattesa")
            a, b = testo.split(SEPARATORE, 1)

            def righe(t):
                out = []
                for x in t.splitlines()[-500:]:
                    try:
                        d = json.loads(x)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        out.append(d)
                return out
            dati, stato = (righe(a), righe(b)), "ok"
        except subprocess.TimeoutExpired:
            dati, stato = None, "non raggiungibile (tempo scaduto)"
        except (OSError, ValueError) as e:
            dati, stato = None, f"non raggiungibile ({str(e)[:60]})"
        with self.lock:
            if dati is not None:
                self.dati = dati
            self.stato = stato
            self.letto = time.time()
            self.thread = None

    def leggi(self, attesa=None):
        """(dati|None, stato). Se la cache è vecchia rilegge in un thread; aspetta solo se non ha mai letto."""
        if os.environ.get("CC_REGISTRO_SENZA_VPS") == "1":
            return None, "spenta (CC_REGISTRO_SENZA_VPS)"
        with self.lock:
            vecchia = time.time() - self.letto > CACHE_VPS_S
            if vecchia and self.thread is None:
                self.thread = threading.Thread(target=self._leggi, daemon=True)
                self.thread.start()
            t = self.thread
            mai = self.letto == 0
        if t is not None and mai:
            t.join(ATTESA_PRIMA_S if attesa is None else attesa)
        with self.lock:
            if self.letto == 0:
                return None, "in lettura"
            stato = self.stato
            if self.dati is not None and stato != "ok":
                stato += "; mostro l'ultima lettura riuscita"
            return self.dati, stato


VPS = LettoreVPS()


# ---------------------------------------------------------------- l'elenco

def _intero(q, nome, minimo, massimo, default):
    v = (q.get(nome) or [None])[0] if isinstance(q.get(nome), list) else q.get(nome)
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise RichiestaNonValida(f"{nome}: serve un numero intero") from None
    if not minimo <= n <= massimo:
        raise RichiestaNonValida(f"{nome}: fra {minimo} e {massimo}")
    return n


def _scelta(q, nome, ammessi):
    v = (q.get(nome) or [None])[0] if isinstance(q.get(nome), list) else q.get(nome)
    if v in (None, ""):
        return None
    scelte = [x for x in str(v).split(",") if x]
    if not scelte or any(x not in ammessi for x in scelte):
        raise RichiestaNonValida(f"{nome}: uno fra {', '.join(ammessi)}")
    return set(scelte)


def elenco(fonte=None, esito=None, da=None, limite=200, testo=None):
    eventi, fonti = [], {}
    try:
        eventi += da_approvazioni()
        fonti["approvazione"] = "ok"
    except Exception as e:  # noqa: BLE001
        fonti["approvazione"] = f"errore ({type(e).__name__})"
    for nome, fn in (("regola", da_regole), ("guardia", da_guardia)):
        try:
            ev, st = fn()
            eventi += ev
            fonti[nome] = st
            if nome == "regola":
                fonti["auto"] = st                   # stesso file (registro/regole.jsonl)
        except Exception as e:  # noqa: BLE001
            fonti[nome] = f"errore ({type(e).__name__})"
            if nome == "regola":
                fonti["auto"] = fonti[nome]
    if fonte and not fonte & {"ponte", "schermo"}:
        fonti["ponte"] = fonti["schermo"] = "non chiesta"
    else:
        dati, stato = VPS.leggi()
        fonti["ponte"] = fonti["schermo"] = stato
        if dati is not None:
            try:
                eventi += _ponte(dati[0]) + _schermo(dati[1])
            except Exception as e:  # noqa: BLE001
                fonti["ponte"] = fonti["schermo"] = f"errore ({type(e).__name__})"
    if fonte:
        eventi = [e for e in eventi if e["fonte"] in fonte]
    if esito:
        eventi = [e for e in eventi if e["esito"] in esito]
    if da:
        eventi = [e for e in eventi if e["ts"] >= da]
    if testo:
        t = testo.lower()
        eventi = [e for e in eventi if t in (e["azione"] + " " + e["riepilogo"] + " " + (e["regola"] or "")).lower()]
    eventi.sort(key=lambda e: e["ts"], reverse=True)
    return {"eventi": eventi[:limite], "totale": len(eventi), "fonti": fonti, "ora": int(time.time())}


def elenco_da_query(q):
    """q come parse_qs. RichiestaNonValida per un parametro sbagliato (→ 400)."""
    t = (q.get("q") or [""])[0] if isinstance(q.get("q"), list) else (q.get("q") or "")
    if len(t) > 100:
        raise RichiestaNonValida("q: al massimo 100 caratteri")
    return elenco(fonte=_scelta(q, "fonte", FONTI), esito=_scelta(q, "esito", ESITI),
                  da=_intero(q, "da", 0, 10 ** 11, None), limite=_intero(q, "limite", 1, LIMITE_MAX, 200), testo=t or None)


# ---------------------------------------------------------------- proposte e regole (sola lettura)

def forma(strumento, a):
    """(chiave, regola proposta) per un'approvazione approvata, o None se non se ne può fare una regola sicura."""
    d = a.get("dettagli") if isinstance(a.get("dettagli"), dict) else {}
    if strumento == "Bash":
        cmd = str(d.get("comando") or "")
        if "[riga nascosta" in cmd or "…" in cmd or "«valore mascherato»" in cmd or d.get("troncato") or not R.bash_semplice(cmd):
            return None
        try:
            parti = shlex.split(cmd)
        except ValueError:
            return None
        # la forma: il programma più la prima parola che non è un'opzione (git commit, npm test, python3 x.py)
        base = parti[:1]
        for p in parti[1:]:
            if not p.startswith("-"):
                base.append(p)
                break
        prefisso = " ".join(shlex.quote(p) for p in base)
        return ("Bash", prefisso), {"strumento": "Bash", "corrispondenza": {"comando_inizia": prefisso}}
    if strumento in R.STRUMENTI_SCRIVONO or strumento in ("Read", "Glob", "Grep"):
        p = str(d.get("percorso") or "")
        if not p or A.e_file_segreto(p) or not (p.startswith("~/") or p.startswith("/")):
            return None
        cartella = p.rsplit("/", 1)[0]
        if cartella in ("", "~"):
            return None                       # mai «tutta la home»
        glob = cartella + "/*"
        return (strumento, glob), {"strumento": strumento, "corrispondenza": {"percorso_glob": glob}}
    if strumento == "WebFetch":
        host = R.url_sicuro(d.get("url"))
        if not host:
            return None
        return (strumento, host), {"strumento": strumento, "corrispondenza": {"url_dominio": host}}
    return None                   # WebSearch, agenti e strumenti MCP: niente proposte (revisione 2, F7)


def proposte(soglia=SOGLIA_PROPOSTE):
    """Le azioni approvate dall'utente almeno `soglia` volte con la stessa forma, che le regole di adesso non
    consentono già. SOLO suggerimenti: il testo della regola da copiare nel file, niente si crea da qui."""
    conta, esempio, ultima = Counter(), {}, {}
    for a in A.tutte_pubbliche().values():
        if a.get("stato") != "approvata":
            continue
        f = forma(a.get("strumento") or "", a)
        if not f:
            continue
        chiave, regola = f
        conta[chiave] += 1
        esempio.setdefault(chiave, regola)
        ultima[chiave] = max(ultima.get(chiave, 0), a.get("deciso") or 0)
    caricate = R.carica()
    out = []
    for chiave, n in conta.most_common():
        if n < soglia:
            continue
        regola = esempio[chiave]
        try:                          # solo proposte che il file delle regole accetterebbe (revisione 2, F7)
            R.valida({"regole": [{"id": "prova", "azione": "consenti", **regola}]})
        except R.RegoleNonValide:
            continue
        # già consentita da una regola? si prova con un esempio della forma
        prova = {"command": regola["corrispondenza"]["comando_inizia"]} if chiave[0] == "Bash" else \
            {"url": "https://" + chiave[1] + "/"} if chiave[0] == "WebFetch" else \
            {"file_path": os.path.expanduser(chiave[1].replace("/*", "/esempio"))} if chiave[1] else {}
        if R.valuta(chiave[0], prova, None, caricate)["azione"] == "consenti":
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", (chiave[0] + " " + chiave[1]).lower()).strip("-")[:40] or "proposta"
        testo = {"id": "proposta-" + slug, "descrizione": f"Approvata dall'utente {n} volte", **regola,
                 "azione": "consenti", "nota": f"Proposta dal Registro il {time.strftime('%Y-%m-%d')}: approvata {n} volte."}
        forma_testo = chiave[0] + (" " + chiave[1] if chiave[1] else "")
        out.append({"forma": _corto(forma_testo, 160), "volte": n, "ultima": ultima[chiave],
                    "testo_regola": json.dumps(testo, ensure_ascii=False, indent=2)})
    return out[:20]


def regole_e_proposte():
    d = R.descrivi()
    try:
        d["proposte"] = proposte()
    except Exception as e:  # noqa: BLE001
        d["proposte"] = []
        d["errore_proposte"] = type(e).__name__
    d["ora"] = int(time.time())
    return d


if __name__ == "__main__":
    import sys
    print(json.dumps(elenco(limite=int(sys.argv[1]) if len(sys.argv) > 1 else 20), ensure_ascii=False, indent=1))
