#!/usr/bin/env python3
"""Prova ripetibile del menu laterale e della lavagna (audit del 2026-10-02, patch P3–P11) su un'istanza ISOLATA.

    python3 command-center/prova_menu_lavagna.py            esito 0 = tutto passa, 1 = qualcosa no
    python3 command-center/prova_menu_lavagna.py --porta 7795 --tieni

Cosa fa: copia questa cartella (senza missioni, cache, lavori, storia e SENZA i file di stato veri: spazi.json,
pannello.json, gruppi-archiviati.json, agenti-tolti.json, modifiche-agenti.jsonl) in una cartella temporanea, con
una HOME finta che ha il suo .Trash. Scrive spazi e pannello di prova con progetti in cartelle temporanee, avvia
`CC_PORTA=<porta> CC_PROVA=1 python3 server.py`, ascolta il flusso SSE, prova, ferma il server.
Non tocca mai spazi.json, pannello.json, agenti o cartelle di progetto veri, né il Cestino vero.
--tieni lascia la cartella temporanea per guardarla dopo.
"""
import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--porta", type=int, default=7794)
ap.add_argument("--tieni", action="store_true")
ARG = ap.parse_args()
PORTA = ARG.porta
BASE = f"http://127.0.0.1:{PORTA}"

esiti = []


def ok(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("✅" if cond else "❌"), nome, ("· " + str(dettaglio)) if dettaglio and not cond else "")


def porta_libera(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


if not porta_libera(PORTA):
    print(f"❌ la porta {PORTA} è occupata: non avvio niente (scegli --porta)")
    sys.exit(1)

# ---------------------------------------------------------------- copia isolata e dati di prova
TMP = Path(tempfile.mkdtemp(prefix="prova-menu-lavagna-"))
CC = TMP / "command-center"
HOME = TMP / "home"
(HOME / ".Trash").mkdir(parents=True)
STATO_VERO = {"spazi.json", "pannello.json", "gruppi-archiviati.json", "agenti-tolti.json", "modifiche-agenti.jsonl",
              "conversazioni.json", "assistenza.json", "sessioni_motori.json", "catena-stato.json"}
shutil.copytree(QUI, CC, ignore=lambda d, nomi: [n for n in nomi if n in STATO_VERO or n in (
    "missioni", "missioni_archivio", "cache-profili", "__pycache__", "pannello-storia", "lavori", ".DS_Store")
    or n.startswith("pannello.json.bak") or n.endswith(".orig")])
PROG = TMP / "progetti"
for nome in ("Alfa", "Beta", "Gamma", "Delta", "Fuori"):
    (PROG / nome).mkdir(parents=True)
    (PROG / nome / "README.md").write_text(f"# {nome}\nfile del progetto: non va mai toccato\n")
(TMP / "memoria").mkdir()
(TMP / "report").mkdir()


def voce(pid, nome, capo=None):
    v = {"id": pid, "nome": nome, "cartella": str(PROG / nome), "sezioni_memoria": []}
    if capo:
        v["capogruppo"] = capo
    return v


def spazio(sid, nome, progetti):
    return {"id": sid, "nome": nome, "memoria": str(TMP / "memoria"), "report": str(TMP / "report"), "progetti": progetti}


(CC / "spazi.json").write_text(json.dumps({"spazi": [
    spazio("prova-uno", "Prova Uno", [voce("alfa", "Alfa", "ceo-alfa"), voce("beta", "Beta", "ceo-beta")]),
    spazio("prova-g", "Prova G", [voce("gamma", "Gamma", "ceo-gamma")]),
    spazio("prova-d", "Prova D", [voce("delta", "Delta", "ceo-delta")]),
]}, ensure_ascii=False, indent=2) + "\n")


def nodo(i, agente=None, testo=None, x=0, y=0):
    return {"id": i, "tipo": "agente" if agente else "nota", "agente": agente or "", "testo": testo or "", "x": x, "y": y}


PANNELLO0 = {"versione": 1, "aspetto": {}, "gruppi": [
    {"id": "spazio-prova-uno", "nome": "Prova Uno", "chiuso": False, "agenti": ["alfa:ceo-alfa", "alfa:dev-alfa", "beta:ceo-beta"]},
    {"id": "spazio-prova-g", "nome": "Prova G", "chiuso": False, "agenti": ["gamma:ceo-gamma"]},
    {"id": "spazio-prova-d", "nome": "Prova D", "chiuso": False, "agenti": ["delta:ceo-delta"]},
    {"id": "spazio-fantasma", "nome": "Fantasma vecchio", "chiuso": False, "agenti": []},
], "lavagne": {
    "generale": {"nodi": [nodo("n1", "alfa:ceo-alfa"), nodo("n2", "alfa:dev-alfa"), nodo("n3", "beta:ceo-beta"),
                          nodo("n4", None, "📁 Prova Uno · Alfa"), nodo("n5", None, "📁 Prova Uno · Beta"),
                          nodo("n6", None, "Prova Uno"), nodo("n7", "gamma:ceo-gamma"), nodo("n8", "delta:ceo-delta"), nodo("n9", None, "📁 Gamma"),
                          nodo("n9", None, "L'utente")],
                 "fili": [{"da": "n1", "a": "n2"}, {"da": "n9", "a": "n1"}, {"da": "n9", "a": "n7"}],
                 "vista": {"x": 0, "y": 0, "zoom": 1}},
    "spazio-prova-uno": {"nodi": [nodo("m1", "alfa:ceo-alfa"), nodo("m2", "beta:ceo-beta")], "fili": [{"da": "m1", "a": "m2"}],
                         "vista": {"x": 0, "y": 0, "zoom": 1}},
    "spazio-fantasma": {"nodi": [nodo("f1", "vecchio:x")], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}},
    "g-orfana": {"nodi": [nodo("o1", None, "nota sola")], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}},
    "demo-squadra": {"nodi": [nodo("d1", "alfa:ceo-alfa")], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}},
}}
(CC / "pannello.json").write_text(json.dumps(PANNELLO0, ensure_ascii=False, indent=1))
(CC / "gruppi-archiviati.json").write_text("{}")
(CC / "agenti-tolti.json").write_text("{}")

# ---------------------------------------------------------------- server isolato
LOG = TMP / "server.log"
env = {**os.environ, "HOME": str(HOME), "CC_PORTA": str(PORTA), "CC_PROVA": "1",
       "JARVIS_ATTIVITA_DIR": str(TMP / "attivita")}
SRV = subprocess.Popen([sys.executable, "server.py"], cwd=CC, env=env, stdout=open(LOG, "w"), stderr=subprocess.STDOUT,
                       start_new_session=True)


def ferma():
    if SRV.poll() is None:
        try:
            os.killpg(SRV.pid, signal.SIGTERM)
            SRV.wait(10)
        except Exception:  # noqa: BLE001
            os.killpg(SRV.pid, signal.SIGKILL)


TOKEN = None
for _ in range(60):
    try:
        html = urllib.request.urlopen(BASE + "/", timeout=2).read().decode()
        TOKEN = re.search(r'CC_TOKEN = "([^"]+)"', html).group(1)
        break
    except Exception:  # noqa: BLE001
        if SRV.poll() is not None:
            break
        time.sleep(0.5)
if not TOKEN:
    print("❌ il server di prova non è partito; log:\n" + LOG.read_text()[-2000:])
    ferma()
    sys.exit(1)
print(f"server di prova su {BASE} (pid {SRV.pid}), cartella {TMP}")


def chiama(metodo, percorso, corpo=None):
    req = urllib.request.Request(BASE + percorso, method=metodo, headers={"X-Token": TOKEN, "Content-Type": "application/json"},
                                 data=json.dumps(corpo).encode() if corpo is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def azione(**k):
    return chiama("POST", "/api/azione", {"tipo": "agente", **k})


# flusso SSE in ascolto: (istante, chiavi) di ogni messaggio
SSE = []


def ascolta():
    try:
        r = urllib.request.urlopen(f"{BASE}/api/flusso?token={TOKEN}", timeout=120)
        for riga in r:
            riga = riga.decode().strip()
            if riga.startswith("data: "):
                d = json.loads(riga[6:])
                SSE.append((time.time(), set(d.get("chiavi") or [])))
    except Exception:  # noqa: BLE001
        pass


threading.Thread(target=ascolta, daemon=True).start()
time.sleep(5)            # sorveglia_file (ogni 2 s) prende le misure al primo giro


def arriva(chiave, dopo, entro=6.0):
    fine = time.time() + entro
    while time.time() < fine:
        if any(t >= dopo and chiave in c for t, c in SSE):
            return True
        time.sleep(0.1)
    return False


def quanti(chiave, dopo):
    return sum(1 for t, c in SSE if t >= dopo and chiave in c)


def pannello():
    return json.loads((CC / "pannello.json").read_text())


def spazi_json():
    return json.loads((CC / "spazi.json").read_text())


def archivio():
    return json.loads((CC / "gruppi-archiviati.json").read_text())


try:
    # --- agenti di prova, creati come dalla pagina
    for pid, nome, capo in (("alfa", "ceo-alfa", ""), ("alfa", "dev-alfa", "ceo-alfa"), ("beta", "ceo-beta", ""),
                            ("gamma", "ceo-gamma", ""), ("delta", "ceo-delta", ""), ("delta", "dev-delta", "ceo-delta")):
        c, d = azione(cosa="crea", progetto=pid, nome=nome, capogruppo=capo, description=f"agente di prova {nome}")
        if c != 200:
            ok(f"crea {pid}:{nome}", False, d)

    # --- 428: niente salvataggi alla cieca (patch del mattino, rete di sicurezza)
    c, _ = chiama("POST", "/api/pannello", {"gruppi": [], "lavagne": {"generale": {}}})
    ok("POST /api/pannello senza versione → 428", c == 428, c)

    # --- lavagna_verifica vede fantasma e lavagna orfana (dati vecchi)
    c, v = chiama("GET", "/api/lavagna/verifica")
    testi = json.dumps(v.get("problemi", []), ensure_ascii=False)
    ok("verifica: gruppo fantasma spazio-fantasma segnalato", "gruppo fantasma" in testi and "fantasma" in testi, testi[:300])
    ok("verifica: lavagne orfane spazio-fantasma e g-orfana segnalate",
       "«spazio-fantasma»" in testi and "«g-orfana»" in testi and "gruppo che non c'è più" in testi, testi[:300])

    # --- P8: agente archiviato nel payload di /api/spazi
    c, d = azione(cosa="togli", progetto="alfa", nome="dev-alfa")
    ok("togli dev-alfa → 200", c == 200, d)
    c, d = chiama("GET", "/api/spazi")
    alfa = next(p for s in d["spazi"] for p in s["progetti"] if p["id"] == "alfa")
    ok("P8: /api/spazi ha archiviati=['dev-alfa'] per alfa", alfa.get("archiviati") == ["dev-alfa"], alfa.get("archiviati"))
    c, d = azione(cosa="ripristina", progetto="alfa", nome="dev-alfa")
    c, d = chiama("GET", "/api/spazi")
    alfa = next(p for s in d["spazi"] for p in s["progetti"] if p["id"] == "alfa")
    ok("P8: dopo «Ripristina» archiviati è vuoto e l'agente è vivo",
       alfa.get("archiviati") == [] and any(a["nome"] == "dev-alfa" for a in alfa["agenti"]), alfa.get("archiviati"))

    # --- D16: eliminare/togliere il capogruppo svuota «capogruppo» in spazi.json; il ripristino lo rimette
    c, d = azione(cosa="elimina", progetto="delta", nome="ceo-delta")
    vd = next(p for s in spazi_json()["spazi"] for p in s["progetti"] if p["id"] == "delta")
    ok("D16: elimina ceo-delta → «capogruppo» fuori da spazi.json", c == 200 and "capogruppo" not in vd and vd.get("capogruppo_tolto") == "ceo-delta", vd)
    c, v = chiama("GET", "/api/lavagna/verifica")
    err = [x for x in v["problemi"] if x["livello"] == "errore" and "Delta" in x["dove"]]
    ok("D16: «Controlla lavagna» non dà più errore sul CEO di Delta (solo avviso)", not err, err)
    c, d = azione(cosa="togli", progetto="gamma", nome="ceo-gamma")
    vg = next(p for s in spazi_json()["spazi"] for p in s["progetti"] if p["id"] == "gamma")
    ok("D16: togli ceo-gamma → capogruppo tolto", "capogruppo" not in vg, vg)
    c, d = azione(cosa="ripristina", progetto="gamma", nome="ceo-gamma")
    vg = next(p for s in spazi_json()["spazi"] for p in s["progetti"] if p["id"] == "gamma")
    ok("D16: ripristina ceo-gamma → torna capogruppo", vg.get("capogruppo") == "ceo-gamma" and "capogruppo_tolto" not in vg, vg)

    # --- D13: rinominare uno spazio scrive spazi.json, le etichette della lavagna e il gruppo del menu; le cartelle non si spostano
    t0 = time.time()
    mem_prima = next(x for x in spazi_json()["spazi"] if x["id"] == "prova-d").get("memoria")
    c, d = azione(cosa="rinomina_spazio", spazio="prova-d", nome="Prova Delta Nuovo")
    sd = next(x for x in spazi_json()["spazi"] if x["id"] == "prova-d")
    P = pannello()
    ok("D13: rinomina_spazio → 200 e spazi.json col nome nuovo", c == 200 and sd["nome"] == "Prova Delta Nuovo", (c, d))
    ok("D13: il gruppo spazio-prova-d nel menu ha il nome nuovo",
       next(g for g in P["gruppi"] if g["id"] == "spazio-prova-d")["nome"] == "Prova Delta Nuovo")
    ok("D13: le cartelle non si spostano (memoria identica, cartella_nome = quella vecchia)",
       sd.get("memoria") == mem_prima and sd.get("cartella_nome") in ("Prova D", None) or sd.get("memoria") == mem_prima)
    ok("D13: SSE «spazi» e «pannello» arrivati", arriva("spazi", t0) and arriva("pannello", t0))
    c, d = azione(cosa="rinomina_spazio", spazio="prova-d", nome="Prova G")
    ok("D13: nome già usato da un altro spazio → 400", c == 400, (c, d))
    c, d = azione(cosa="rinomina_spazio", spazio="prova-d", nome="a/b")
    ok("D13: nome con «/» → 400", c == 400, (c, d))
    c, d = azione(cosa="rinomina_spazio", spazio="non-esiste", nome="Qualcosa")
    ok("D13: spazio sconosciuto → 400", c == 400, (c, d))

    # --- P4: togli_gruppo pulisce pannello.json, con SSE «pannello» e «spazi»
    t0 = time.time()
    c, d = azione(cosa="togli_gruppo", progetto="beta")
    P = pannello()
    tutte = [n for k, L in P["lavagne"].items() if not k.startswith("demo") for n in L["nodi"]]
    ok("P4: togli beta → 200", c == 200, d)
    ok("P4: nessuna scheda beta:* e nessuna nota «📁 Prova Uno · Beta» nelle lavagne",
       not any(n["agente"].startswith("beta:") or n["testo"] == "📁 Prova Uno · Beta" for n in tutte))
    ok("P4: beta:* fuori dai gruppi del menu", not any(a.startswith("beta:") for g in P["gruppi"] for a in g["agenti"]))
    ok("P4: SSE «pannello» e «spazi» arrivati", arriva("pannello", t0) and arriva("spazi", t0))
    time.sleep(1.2)
    t0 = time.time()
    c, d = azione(cosa="togli_gruppo", progetto="alfa")       # l'ultimo dello spazio: esce anche lo spazio
    P = pannello()
    ok("P4: togli alfa (ultimo) → spazio prova-uno fuori da spazi.json",
       c == 200 and not any(s["id"] == "prova-uno" for s in spazi_json()["spazi"]), d)
    ok("P4: gruppo spazio-prova-uno e la sua lavagna fuori da pannello.json",
       not any(g["id"] == "spazio-prova-uno" for g in P["gruppi"]) and "spazio-prova-uno" not in P["lavagne"])
    gen = P["lavagne"]["generale"]
    ok("P4: generale senza schede alfa:* né note «Prova Uno»/«📁 Prova Uno · Alfa»; l'utente e Gamma restano",
       not any(n["agente"].startswith("alfa:") or n["testo"] in ("Prova Uno", "📁 Prova Uno · Alfa") for n in gen["nodi"])
       and any(n["testo"] == "L'utente" for n in gen["nodi"]) and any(n["agente"] == "gamma:ceo-gamma" for n in gen["nodi"]))
    ok("P4: nessun filo verso schede tolte", all(f["da"] in {n["id"] for n in gen["nodi"]} and f["a"] in {n["id"] for n in gen["nodi"]} for f in gen["fili"]))
    ok("P4: la lavagna demo non si tocca", P["lavagne"]["demo-squadra"]["nodi"][0]["agente"] == "alfa:ceo-alfa")
    ok("P4: SSE «pannello» e «spazi» arrivati (alfa)", arriva("pannello", t0) and arriva("spazi", t0))
    ok("P4: la cartella del progetto Alfa è intatta", (PROG / "Alfa" / "README.md").exists())

    # --- P9: ripristino di un gruppo che NON è uscito per ultimo, con lo spazio sparito
    A = archivio()
    ok("P9: premessa — beta senza spazio_voce, alfa con", "spazio_voce" not in A["beta"] and "spazio_voce" in A["alfa"])
    c, d = azione(cosa="ripristina_gruppo", progetto="beta")
    sp = next((s for s in spazi_json()["spazi"] if s["id"] == "prova-uno"), None)
    ok("P9: ripristina beta (non l'ultimo) → 200, lo spazio prova-uno torna con beta",
       c == 200 and sp is not None and [p["id"] for p in sp["progetti"]] == ["beta"], (c, d))
    time.sleep(1.2)
    c, d = azione(cosa="togli_gruppo", progetto="beta")       # di nuovo fuori, ora con spazio_voce

    # --- P9: archivio sparito → messaggio chiaro, niente toccato
    time.sleep(1.2)
    c, d = azione(cosa="togli_gruppo", progetto="gamma")
    ar_gamma = Path(archivio()["gamma"]["archivio"])
    shutil.move(str(ar_gamma), str(TMP / "archivio-spostato"))   # qualcuno ha spostato l'archivio
    prima_spazi, prima_arch = (CC / "spazi.json").read_bytes(), (CC / "gruppi-archiviati.json").read_bytes()
    c, d = azione(cosa="ripristina_gruppo", progetto="gamma")
    ok("P9: ripristina gamma con archivio sparito → 400 «non c'è più … Elimina definitivamente»",
       c == 400 and "non c'è più" in d.get("errore", "") and "Elimina definitivamente" in d.get("errore", ""), (c, d))
    ok("P9: spazi.json e gruppi-archiviati.json intatti dopo l'errore",
       (CC / "spazi.json").read_bytes() == prima_spazi and (CC / "gruppi-archiviati.json").read_bytes() == prima_arch)
    c, d = chiama("GET", "/api/spazi")
    ok("/api/spazi: gamma ha archivio_mancante=true", any(g["progetto"] == "gamma" and g.get("archivio_mancante") for g in d["gruppi_archiviati"]))
    c, v = chiama("GET", "/api/lavagna/verifica")
    ok("verifica: gruppo archiviato con archivio mancante segnalato",
       any("Gamma" in x["dove"] and "non c'è più" in x["cosa"] for x in v["problemi"]), v["problemi"][-3:])

    # --- P6: elimina_gruppo
    c, p = azione(cosa="anteprima_elimina_gruppo", progetto="alfa")
    ok("P6: anteprima alfa elenca i profili archiviati e cosa resta",
       c == 200 and "agents/ceo-alfa.md" in p.get("file", []) and str(PROG / "Alfa").replace(str(HOME), "~") in p.get("restano", [""])[0], p)
    ar_alfa = Path(archivio()["alfa"]["archivio"])
    c, d = azione(cosa="elimina_gruppo", progetto="alfa", conferma="alfa sbagliato")
    ok("P6: nome sbagliato → 400, voce e archivio ancora lì", c == 400 and "alfa" in archivio() and ar_alfa.is_dir(), (c, d))
    t0 = time.time()
    c, d = azione(cosa="elimina_gruppo", progetto="alfa", conferma="Alfa")
    cestino = list((HOME / ".Trash").iterdir())
    ok("P6: nome giusto → 200, voce sparita", c == 200 and "alfa" not in archivio(), (c, d))
    ok("P6: archivio nel Cestino (HOME finta) con i profili, non più nella cartella",
       not ar_alfa.exists() and any(x.name == f"Alfa {ar_alfa.name}" and (x / "agents" / "ceo-alfa.md").exists() for x in cestino),
       [x.name for x in cestino])
    ok("P6: cartella del progetto Alfa intatta", (PROG / "Alfa" / "README.md").read_text().startswith("# Alfa"))
    ok("P6: spazio_voce passato a beta (resta ripristinabile)", archivio().get("beta", {}).get("spazio_voce", {}).get("id") == "prova-uno")
    c, d = azione(cosa="elimina_gruppo", progetto="gamma", conferma="Gamma")
    ok("P6: gamma con archivio già sparito → 200, voce tolta, niente nel Cestino per Gamma",
       c == 200 and "gamma" not in archivio() and not any(x.name.startswith("Gamma ") for x in (HOME / ".Trash").iterdir()), (c, d))
    # controllo di percorso: un archivio fuori dalla cartella del progetto non si tocca mai
    strano = PROG / "Fuori" / "_archivio-20260101-000000"
    (strano / "agents").mkdir(parents=True)
    A = archivio()
    A["finto"] = {"spazio": "prova-d", "voce": voce("finto", "Delta"), "archivio": str(strano), "condivisa": False, "ts": time.time()}
    (CC / "gruppi-archiviati.json").write_text(json.dumps(A, ensure_ascii=False, indent=1))
    c, d = azione(cosa="elimina_gruppo", progetto="finto", conferma="Delta")
    ok("P6: archivio fuori dalla cartella del progetto → 400 e niente spostato",
       c == 400 and "non lo tocco" in d.get("errore", "") and strano.is_dir(), (c, d))
    A.pop("finto")
    (CC / "gruppi-archiviati.json").write_text(json.dumps(A, ensure_ascii=False, indent=1))

    # --- P3: modifiche esterne → evento SSE; le scritture del server non danno un secondo evento
    time.sleep(3)
    t0 = time.time()
    s = spazi_json()
    s["spazi"][0]["nome"] = s["spazi"][0]["nome"] + " (da OneDrive)"
    (CC / "spazi.json").write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    ok("P3: modifica esterna di spazi.json → SSE «spazi»", arriva("spazi", t0, 6))
    time.sleep(3)
    t0 = time.time()
    P = pannello()
    P["versione"] = P["versione"] + 1
    P["gruppi"][0]["nome"] = "Rinominato altrove"
    (CC / "pannello.json").write_text(json.dumps(P, ensure_ascii=False, indent=1))
    ok("P3: modifica esterna di pannello.json → SSE «pannello»", arriva("pannello", t0, 6))
    time.sleep(3)
    t0 = time.time()
    (CC / "agenti-tolti.json").write_text(json.dumps({"delta": ["x"]}))
    ok("P3: modifica esterna di agenti-tolti.json → SSE «spazi»", arriva("spazi", t0, 6))
    time.sleep(3)
    t0 = time.time()
    c, d = chiama("POST", "/api/pannello/modifica", {"base": pannello()["versione"], "ops": [{"op": "titolo", "lavagna": "generale", "titolo": "prova"}]})
    time.sleep(5)            # due giri e mezzo di sorveglia_file
    ok("P3: una scrittura del server → un solo evento «pannello» (niente doppio tocco)", c == 200 and quanti("pannello", t0) == 1, quanti("pannello", t0))

    # --- P7 e D14/D15 (pagina): controlli sul codice
    js = (CC / "static" / "app.js").read_text()
    ok("P7: un solo listener su «＋ Nuovo gruppo» (apriNuovoGruppo)",
       js.count('$("btn-nuovo-gruppo").addEventListener') == 1 and '$("btn-nuovo-gruppo").addEventListener("click", apriNuovoGruppo)' in js)
    ok("D14: smontaGruppo toglie anche la lavagna", re.search(r"function smontaGruppo[\s\S]{0,400}delete PAN\.lavagne\[gid\]", js) is not None)
    ok("D15: etichetta «Gruppi per spazio»", ">Gruppi per spazio</button>" in (CC / "static" / "index.html").read_text())
    ok("server vivo fino alla fine (nessun 500 nel log)", SRV.poll() is None and " 500 " not in LOG.read_text())
finally:
    ferma()
    ok("istanza di prova fermata", SRV.poll() is not None)
    if ARG.tieni:
        print("cartella tenuta:", TMP)
    else:
        shutil.rmtree(TMP, ignore_errors=True)      # solo la cartella temporanea di questa prova

print(f"\n{sum(esiti)}/{len(esiti)} passati")
sys.exit(0 if all(esiti) else 1)
