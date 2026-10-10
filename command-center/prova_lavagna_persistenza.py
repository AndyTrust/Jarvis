#!/usr/bin/env python3
"""Prova ripetibile della persistenza della lavagna del Command Center (audit 2026-10-02).

Lavora SOLO contro una copia isolata del Command Center (di default http://127.0.0.1:7792, avviata
con `CC_PORTA=7792 CC_PROVA=1 python3 server.py` dentro la copia). Non tocca mai il pannello vero:
se la porta è 7777 si rifiuta di partire.

Cosa prova (le stesse chiamate della pagina, salvaPannello() in static/app.js):
  R1  spostare una scheda: POST /api/pannello con {…PAN, versione} → rilettura, posizione e versione
  R2  due schede del browser, schede DIVERSE spostate: la seconda non deve perdere il suo spostamento
  R3  la stessa scheda del browser, due salvataggi in volo con la stessa versione (debounce 500 ms
      + risposta lenta): il secondo non deve andare perso
  R4  tempo reale: /api/flusso deve mandare un evento con la chiave «pannello» entro 3 s
  R5  un POST senza «versione» (pagina che non ha letto il pannello) non deve poter svuotare la lavagna
  R6  coordinate e limiti: quello che si salva deve tornare uguale (niente tagli silenziosi)
  R7  merge per scheda (endpoint proposto POST /api/pannello/modifica): se esiste, deve
      applicare solo le schede mandate

Esito: 0 se tutti i requisiti R1-R7 passano, 1 se almeno uno è un DIFETTO. Alla fine rimette il
pannello della copia com'era.

Uso:  python3 prova_lavagna_persistenza.py [--porta 7792]
"""
import argparse
import copy
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--porta", type=int, default=7792)
ARG = ap.parse_args()
if ARG.porta == 7777:
    sys.exit("rifiuto: 7777 è il Command Center vero. Usa la copia di prova.")
BASE = f"http://127.0.0.1:{ARG.porta}"

ESITI = []          # (codice, ok, testo)


def segna(codice, ok, testo):
    ESITI.append((codice, ok, testo))
    print(f"[{'OK      ' if ok else 'DIFETTO '}] {codice} {testo}")


def token():
    html = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
    m = re.search(r"CC_TOKEN\s*=\s*[\"']([^\"']+)", html)
    if not m:
        sys.exit("token non trovato nella pagina")
    return m.group(1)


TOK = token()


def chiama(metodo, percorso, corpo=None, intestazioni=None):
    h = {"X-Token": TOK, "Content-Type": "application/json", "Origin": BASE}
    h.update(intestazioni or {})
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(BASE + percorso, data=dati, method=metodo, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}"), time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read() or b"{}")
        except ValueError:
            d = {}
        return e.code, d, time.time() - t0


def leggi():
    c, d, _ = chiama("GET", "/api/pannello")
    assert c == 200, (c, d)
    return d


def salva(pan, versione="dalla-pagina"):
    """Come salvaPannello(): l'intero PAN più la versione letta (None = la pagina non la manda)."""
    corpo = {"gruppi": pan.get("gruppi", []), "aspetto": pan.get("aspetto", {}), "lavagne": pan.get("lavagne", {})}
    if versione == "dalla-pagina":
        versione = pan.get("versione")
    if versione is not None:
        corpo["versione"] = versione
    return chiama("POST", "/api/pannello", corpo)


def ha_merge():
    """Il server ha l'endpoint proposto POST /api/pannello/modifica? (404 = no; 400 su ops vuote = sì)"""
    return chiama("POST", "/api/pannello/modifica", {"ops": []})[0] != 404


def ops_da(prima, dopo):
    """Lo stesso diff per scheda di diffPannello() proposto per app.js (solo nodi e fili: basta alle prove)."""
    ops = []
    for k, L in dopo["lavagne"].items():
        A = prima["lavagne"].get(k, {"nodi": [], "fili": []})
        pa = {n["id"]: n for n in A["nodi"]}
        cambiati = [n for n in L["nodi"] if pa.get(n["id"]) != n]
        if cambiati:
            ops.append({"op": "nodi", "lavagna": k, "nodi": cambiati})
    return ops


def salva_come_pagina(prima, dopo):
    """Come salva la pagina: oggi tutto il PAN con la versione letta; con la patch, solo le schede cambiate."""
    if MERGE:
        return chiama("POST", "/api/pannello/modifica", {"base": prima.get("versione"), "ops": ops_da(prima, dopo)})
    return salva(dopo)


def lavagna_con_due_nodi(pan):
    for k, L in pan["lavagne"].items():
        if len(L.get("nodi") or []) >= 2:
            return k
    pan["lavagne"].setdefault("generale", {"nodi": [], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}})
    pan["lavagne"]["generale"]["nodi"] += [
        {"id": "prova-a", "tipo": "nota", "agente": "", "testo": "A", "x": 0, "y": 0},
        {"id": "prova-b", "tipo": "nota", "agente": "", "testo": "B", "x": 300, "y": 0}]
    return "generale"


def nodo(pan, lav, i):
    return pan["lavagne"][lav]["nodi"][i]


ORIGINALE = leggi()
MERGE = ha_merge()
print(f"         server {'CON' if MERGE else 'senza'} il salvataggio per scheda (/api/pannello/modifica)")
try:
    # ------------------------------------------------------------------ R1
    p = leggi()
    lav = lavagna_con_due_nodi(p)
    if p["lavagne"][lav]["nodi"][0]["id"].startswith("prova-"):
        c, d, _ = salva(p)
        p = leggi()
    v0 = p["versione"]
    n0 = nodo(p, lav, 0)
    nuovo_x, nuovo_y = n0["x"] + 37, n0["y"] - 19
    n0["x"], n0["y"] = nuovo_x, nuovo_y
    tempi = []
    c, d, t = salva(p)
    tempi.append(t)
    r = leggi()
    rn = next(n for n in r["lavagne"][lav]["nodi"] if n["id"] == n0["id"])
    segna("R1", c == 200 and d.get("versione") == v0 + 1 and r["versione"] == v0 + 1
          and (rn["x"], rn["y"]) == (nuovo_x, nuovo_y),
          f"spostamento salvato: HTTP {c}, versione {v0}→{r['versione']}, posizione su disco {rn['x']},{rn['y']}"
          f" (attesa {nuovo_x},{nuovo_y})")

    # tempi del POST (il debounce della pagina è 500 ms: se un POST dura di più, R3 succede davvero)
    for _ in range(15):
        q = leggi()
        c, d, t = salva(q)
        tempi.append(t)
    tempi.sort()
    print(f"         tempi POST /api/pannello su {len(tempi)} prove: mediana {tempi[len(tempi)//2]*1000:.0f} ms,"
          f" massimo {tempi[-1]*1000:.0f} ms")

    # ------------------------------------------------------------------ R2
    base = leggi()
    scheda_a = copy.deepcopy(base)          # scheda del browser A
    scheda_b = copy.deepcopy(base)          # scheda del browser B, aperta insieme
    ida, idb = nodo(base, lav, 0)["id"], nodo(base, lav, 1)["id"]
    nodo(scheda_a, lav, 0)["x"] += 111
    nodo(scheda_b, lav, 1)["y"] += 222
    ca, da, _ = salva_come_pagina(base, scheda_a)
    cb, db, _ = salva_come_pagina(base, scheda_b)   # oggi: 409, la pagina B ricarica e perde il suo spostamento
    fine = leggi()
    xa = next(n for n in fine["lavagne"][lav]["nodi"] if n["id"] == ida)["x"]
    yb = next(n for n in fine["lavagne"][lav]["nodi"] if n["id"] == idb)["y"]
    ok_a = xa == nodo(scheda_a, lav, 0)["x"]
    ok_b = yb == nodo(scheda_b, lav, 1)["y"]
    segna("R2", ok_a and ok_b,
          f"due schede del browser, schede diverse: A HTTP {ca}, B HTTP {cb}"
          f"{' (409 conflitto: la pagina B ricarica e scarta)' if cb == 409 else ''};"
          f" su disco A {'c’è' if ok_a else 'PERSO'}, B {'c’è' if ok_b else 'PERSO'}")

    # ------------------------------------------------------------------ R3
    base = leggi()
    pan = copy.deepcopy(base)
    nodo(pan, lav, 0)["x"] += 5
    primo = copy.deepcopy(pan)              # salvataggio 1 in volo, PAN_VER ancora quello vecchio
    nodo(pan, lav, 0)["y"] += 7             # la mossa dopo, 500 ms più tardi, con lo stesso PAN_VER
    secondo = copy.deepcopy(pan)
    risultati = {}
    barriera = threading.Barrier(2)

    def manda(nome, corpo):
        barriera.wait()
        if nome == "2":
            time.sleep(0.02)                # il primo arriva un filo prima
        risultati[nome] = salva_come_pagina(base, corpo)[0]

    th = [threading.Thread(target=manda, args=("1", primo)), threading.Thread(target=manda, args=("2", secondo))]
    [x.start() for x in th]
    [x.join() for x in th]
    fine = leggi()
    n = next(z for z in fine["lavagne"][lav]["nodi"] if z["id"] == ida)
    ok = (n["x"], n["y"]) == (nodo(secondo, lav, 0)["x"], nodo(secondo, lav, 0)["y"])
    segna("R3", ok, f"stessa scheda del browser, due POST in volo con la stessa versione: HTTP {risultati.get('1')}/"
          f"{risultati.get('2')}; ultima mossa su disco: {'sì' if ok else 'NO, persa'}")

    # ------------------------------------------------------------------ R4
    eventi = []

    def ascolta():
        try:
            r = urllib.request.urlopen(f"{BASE}/api/flusso?token={TOK}", timeout=6)
            fino = time.time() + 5
            while time.time() < fino:
                riga = r.readline().decode().strip()
                if riga.startswith("data:"):
                    eventi.append(json.loads(riga[5:]))
                    if "pannello" in eventi[-1].get("chiavi", []):
                        return
        except Exception as e:  # noqa: BLE001
            eventi.append({"errore": str(e)})

    t = threading.Thread(target=ascolta)
    t.start()
    time.sleep(0.8)
    q = leggi()
    salva(q)
    t.join(7)
    arrivato = any("pannello" in e.get("chiavi", []) for e in eventi)
    segna("R4", arrivato, f"/api/flusso: evento «pannello» {'arrivato' if arrivato else 'NON arrivato'}"
          f" ({len(eventi)} messaggi). NB: la pagina su «pannello» chiama solo aggiornaAllineamento(),"
          " non ricarica PAN: la seconda scheda non vede lo spostamento (vedi report)")

    # ------------------------------------------------------------------ R5
    vuoto = {"gruppi": [], "aspetto": {}, "lavagne": {"generale": {"nodi": [], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}}}}
    prima = leggi()
    nodi_prima = sum(len(L["nodi"]) for L in prima["lavagne"].values())
    c, d, _ = salva(vuoto, versione=None)
    dopo = leggi()
    nodi_dopo = sum(len(L["nodi"]) for L in dopo["lavagne"].values())
    segna("R5", c != 200 or nodi_dopo == nodi_prima,
          f"POST senza versione con PAN vuoto (pagina che non è riuscita a leggere il pannello): HTTP {c},"
          f" schede {nodi_prima}→{nodi_dopo}")
    # rimetto com'era prima di R5
    prima_v = dopo["versione"]
    salva(prima, versione=prima_v)

    # ------------------------------------------------------------------ R6
    p = leggi()
    n = nodo(p, lav, 0)
    n["x"], n["y"] = 9500, -9100
    n["w"], n["colore"] = 260, "#ff0000"        # campi che una scheda ridimensionabile/colorata userebbe
    p["lavagne"][lav]["titolo"] = "Titolo lavagna"
    c, d, _ = salva(p)
    r = leggi()
    rn = next(z for z in r["lavagne"][lav]["nodi"] if z["id"] == n["id"])
    tagli = []
    if (rn["x"], rn["y"]) != (9500, -9100):
        tagli.append(f"x,y {9500},{-9100}→{rn['x']},{rn['y']}")
    for k in ("w", "colore"):
        if k not in rn:      # oggi la pagina non li usa: solo un avviso, non un difetto
            print(f"         nota: nodo.{k} scartato da pulisci_pannello() (oggi la pagina non lo usa)")
    if "titolo" not in r["lavagne"][lav]:
        tagli.append("lavagna.titolo scartato (il titolo vive solo nel localStorage)")
    # 61 lavagne: la 61ª sparisce?
    p = leggi()
    for i in range(61 - len(p["lavagne"])):
        p["lavagne"][f"prova-limite-{i:02d}"] = {"nodi": [], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}}
    c, d, _ = salva(p)
    r = leggi()
    if len(r["lavagne"]) < len(p["lavagne"]):
        tagli.append(f"lavagne {len(p['lavagne'])}→{len(r['lavagne'])} (oltre 60 si perdono le più nuove, in silenzio)")
    segna("R6", not tagli, "valori salvati = valori riletti" + ("" if not tagli else ": " + "; ".join(tagli)))

    # ------------------------------------------------------------------ R7
    c, d, _ = chiama("POST", "/api/pannello/modifica", {"base": 0, "ops": [
        {"op": "nodi", "lavagna": lav, "nodi": [{"id": ida, "x": 1, "y": 2}]}]})
    if c == 404:
        segna("R7", False, "POST /api/pannello/modifica (merge per scheda) non esiste: ogni salvataggio riscrive tutto il pannello")
    else:
        r = leggi()
        n = next(z for z in r["lavagne"][lav]["nodi"] if z["id"] == ida)
        segna("R7", c == 200 and (n["x"], n["y"]) == (1, 2), f"merge per scheda: HTTP {c}, nodo {n['x']},{n['y']}")
finally:
    # la copia torna com'era (con la versione attuale, così il controllo passa)
    attuale = leggi()
    c, d, _ = salva(ORIGINALE, versione=attuale["versione"])
    print(f"         pannello della copia ripristinato: HTTP {c}")

difetti = [e for e in ESITI if not e[1]]
print(f"\n{len(ESITI) - len(difetti)}/{len(ESITI)} requisiti OK, {len(difetti)} difetti")
sys.exit(1 if difetti else 0)
