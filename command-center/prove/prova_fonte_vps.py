#!/usr/bin/env python3
"""Prova della fonte unica sulla VPS (fonte_vps.py, 2026-10-05) su due copie ISOLATE del Command Center.

    python3 command-center/prove/prova_fonte_vps.py            esito 0 = tutto passa
    python3 command-center/prove/prova_fonte_vps.py --tieni    lascia la cartella temporanea

a) fusione a tre vie (fondi): modifiche diverse si sommano, stessa scheda toccata da tutte e due vince la VPS,
   una scheda tolta dal Mac esce, una aggiunta resta.
b) due server di prova: «VPS» (porta 7811) e «Mac» (porta 7812, con la fonte accesa e un «ssh» che è una shell
   locale). Una nota scritta sulla VPS compare sul Mac; una nota scritta sul Mac compare sulla VPS; con la VPS
   spenta il Mac risponde lo stesso e salva in locale; riaccesa la VPS, la nota fatta col VPS spento arriva là
   insieme a quella scritta sulla VPS nel frattempo. Fili: un filo del Mac si vede sulla VPS e viceversa.
   Aspetto: il tema scelto sul Mac è quello della VPS.
Non tocca mai i file veri: HOME finte, cartelle temporanee, porte di prova.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QUI))
import fonte_vps  # noqa: E402

TIENI = "--tieni" in sys.argv
esiti = []


def esito(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + nome + (f"  · {dettaglio}" if dettaglio and not cond else ""))


def nodo(i, testo="", x=0, y=0, agente=""):
    return {"id": i, "tipo": "agente" if agente else "nota", "agente": agente, "testo": testo, "x": x, "y": y}


# ---------------------------------------------------------------- a) fusione
BASE = {"versione": 5, "aspetto": {}, "gruppi": [{"id": "g1", "nome": "Uno", "chiuso": False, "agenti": ["a:x"]}],
        "lavagne": {"generale": {"nodi": [nodo("n1", "uno"), nodo("n2", "due"), nodo("n3", "tre")],
                                 "fili": [{"da": "n1", "a": "n2"}], "vista": {"x": 0, "y": 0, "zoom": 1}}}}
loc = json.loads(json.dumps(BASE))
rem = json.loads(json.dumps(BASE))
loc["lavagne"]["generale"]["nodi"][0]["x"] = 100          # Mac sposta n1
loc["lavagne"]["generale"]["nodi"][1]["x"] = 7            # Mac sposta n2 ...
rem["lavagne"]["generale"]["nodi"][1]["x"] = 9            # ... e anche la VPS: vince la VPS
loc["lavagne"]["generale"]["nodi"] = [n for n in loc["lavagne"]["generale"]["nodi"] if n["id"] != "n3"]  # Mac toglie n3
loc["lavagne"]["generale"]["nodi"].append(nodo("m1", "nota del Mac"))
rem["lavagne"]["generale"]["nodi"].append(nodo("v1", "nota della VPS"))
rem["gruppi"].append({"id": "g2", "nome": "Due", "chiuso": False, "agenti": []})
F = fonte_vps.fondi(BASE, loc, rem)
per = {n["id"]: n for n in F["lavagne"]["generale"]["nodi"]}
esito("fusione: spostamento del Mac entra", per.get("n1", {}).get("x") == 100)
esito("fusione: stessa scheda toccata da tutte e due, vince la VPS", per.get("n2", {}).get("x") == 9)
esito("fusione: scheda tolta dal Mac esce", "n3" not in per)
esito("fusione: nota nuova del Mac e nota nuova della VPS ci sono tutte e due", "m1" in per and "v1" in per)
esito("fusione: gruppo nuovo della VPS resta", [g["id"] for g in F["gruppi"]] == ["g1", "g2"])
esito("fusione: filo n1→n2 resta", {"da": "n1", "a": "n2"} in F["lavagne"]["generale"]["fili"])
esito("fusione: niente cambi = la VPS così com'è", fonte_vps.impronta(fonte_vps.fondi(BASE, BASE, rem)) == fonte_vps.impronta(rem))

# ---------------------------------------------------------------- b) due server
P_VPS, P_MAC = 7811, 7812


def libera(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


if not (libera(P_VPS) and libera(P_MAC)):
    print(f"FAIL porte {P_VPS}/{P_MAC} occupate: non avvio niente")
    sys.exit(1)

TMP = Path(tempfile.mkdtemp(prefix="prova-fonte-vps-"))
STATO = {"spazi.json", "pannello.json", "gruppi-archiviati.json", "agenti-tolti.json", "modifiche-agenti.jsonl",
         "conversazioni.json", "assistenza.json", "sessioni_motori.json", "catena-stato.json"}


def copia(nome):
    cc = TMP / nome / "command-center"
    shutil.copytree(QUI, cc, ignore=lambda d, nomi: [n for n in nomi if n in STATO or n in (
        "missioni", "missioni_archivio", "cache-profili", "__pycache__", "pannello-storia", "lavori", ".DS_Store",
        "static-backup-20261003-1626", "static-backup-20261003-2021", "static-backup-20261004-0320", "perf-dev")
        or n.startswith("pannello.json.") or n.endswith(".orig")])
    (cc / "spazi.json").write_text(json.dumps({"spazi": []}))
    (cc / "pannello.json").write_text(json.dumps(BASE, ensure_ascii=False))
    casa = TMP / nome / "home"
    (casa / ".locale-onedrive" / "jarvis-cc").mkdir(parents=True)
    return cc, casa


CC_V, CASA_V = copia("vps")
CC_M, CASA_M = copia("mac")
# il Mac parte già allineato alla VPS (come dopo la fusione iniziale)
st = CASA_M / ".locale-onedrive" / "jarvis-cc"
(st / "pannello-base-vps.json").write_text(json.dumps(BASE))
(st / "fonte-vps.json").write_text(json.dumps({"impronta": fonte_vps.impronta(BASE)}))
FILI_REMOTI_VPS = CASA_V / ".locale-onedrive" / "jarvis-cc" / "fili-remoti" / "mac"
TOKEN_CMD = (f"curl -s -H 'Host: 127.0.0.1:{P_VPS}' http://127.0.0.1:{P_VPS}/ | "
             "python3 -c 'import re,sys; print(re.search(r\"CC_TOKEN = \\\"([^\\\"]+)\", sys.stdin.read()).group(1))'")
PROCESSI = {}


def avvia(nome):
    cc, casa = (CC_V, CASA_V) if nome == "vps" else (CC_M, CASA_M)
    env = {**os.environ, "HOME": str(casa), "CC_PROVA": "1", "CC_PORTA": str(P_VPS if nome == "vps" else P_MAC),
           "PYTHONUNBUFFERED": "1"}
    if nome == "mac":
        env.update({"CC_FONTE_VPS": "1", "CC_FONTE_PORTA": str(P_VPS), "CC_FONTE_PORTA_VPS": str(P_VPS),
                    "CC_FONTE_SSH_LOCALE": "1", "CC_FONTE_TOKEN_CMD": TOKEN_CMD,
                    "CC_FONTE_FILI_REMOTI": str(FILI_REMOTI_VPS)})
    else:
        env["CC_FONTE_VPS"] = "0"
    log = open(TMP / f"{nome}.log", "a")
    PROCESSI[nome] = subprocess.Popen([sys.executable, "server.py"], cwd=cc, env=env, stdout=log, stderr=log)
    porta = P_VPS if nome == "vps" else P_MAC
    for _ in range(80):
        if not libera(porta):
            return True
        time.sleep(0.25)
    return False


def ferma(nome):
    p = PROCESSI.pop(nome, None)
    if p:
        p.terminate()
        try:
            p.wait(8)
        except subprocess.TimeoutExpired:
            p.kill()


def token(porta):
    req = urllib.request.Request(f"http://127.0.0.1:{porta}/", headers={"Host": f"127.0.0.1:{porta}"})
    html = urllib.request.urlopen(req, timeout=5).read().decode()
    return html.split('CC_TOKEN = "')[1].split('"')[0]


def api(porta, percorso, corpo=None, timeout=15):
    t = token(porta)
    h = {"Host": f"127.0.0.1:{porta}", "X-Token": t, "Content-Type": "application/json"}
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{percorso}", headers=h, method="POST" if corpo is not None else "GET",
                                 data=json.dumps(corpo).encode() if corpo is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def testi(porta):
    d = api(porta, "/api/pannello")
    return {n.get("testo") for n in d["lavagne"]["generale"]["nodi"]}


def aspetta(cond, secondi=12):
    fine = time.time() + secondi
    while time.time() < fine:
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def nota(porta, i, testo):
    return api(porta, "/api/pannello/modifica", {"ops": [{"op": "nodi", "lavagna": "generale", "nodi": [nodo(i, testo, 50, 50)]}]})


def filo(cartella, interlocutore, testo):
    s = str(uuid.uuid4())
    cartella.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    (cartella / f"{s}.json").write_text(json.dumps({
        "formato": 1, "sessione": s, "interlocutore": interlocutore, "titolo": testo, "creato": ts, "aggiornato": ts,
        "versione": 1, "in_attesa": [], "messaggi": [{"id": "q-1", "chi": "utente", "testo": testo, "ts": ts, "ora": "12:00"}]}))
    return s


try:
    esito("server «VPS» acceso", avvia("vps"))
    esito("server «Mac» acceso (fonte unica)", avvia("mac"))
    esito("nota scritta sulla VPS compare sul Mac", aspetta(lambda: "dalla VPS" in testi(P_MAC)) if nota(P_VPS, "v10", "dalla VPS") else False)
    t0 = time.time()
    nota(P_MAC, "m10", "dal Mac")
    esito("nota scritta sul Mac è subito sulla VPS", "dal Mac" in testi(P_VPS), f"{time.time() - t0:.1f} s")
    vm, vv = api(P_MAC, "/api/pannello").get("versione"), api(P_VPS, "/api/pannello").get("versione")
    esito("stessa versione sul Mac e sulla VPS", vm == vv, f"mac {vm} vps {vv}")

    s_mac = filo(CASA_M / ".locale-onedrive" / "jarvis-cc" / "fili", "Jarvis", "filo nato sul Mac")
    s_vps = filo(CASA_V / ".locale-onedrive" / "jarvis-cc" / "fili", "Jarvis", "filo nato sulla VPS")
    esito("filo del Mac visibile sulla VPS (origine mac)",
          aspetta(lambda: any(r["sessione"] == s_mac and r.get("origine") == "mac" for r in api(P_VPS, "/api/fili")["fili"])))
    esito("filo della VPS visibile sul Mac (origine vps)",
          aspetta(lambda: any(r["sessione"] == s_vps and r.get("origine") == "vps" for r in api(P_MAC, "/api/fili")["fili"])))
    esito("filo della VPS leggibile intero dal Mac", (api(P_MAC, f"/api/fili/{s_vps}").get("messaggi") or [{}])[0].get("testo") == "filo nato sulla VPS")

    api(P_MAC, "/api/aspetto", {"tema": "chiaro"})
    esito("tema scelto sul Mac = tema della VPS", api(P_VPS, "/api/aspetto").get("tema") == "chiaro")

    ferma("vps")
    t0 = time.time()
    try:
        nota(P_MAC, "m11", "col VPS spento")
        ok_spento = "col VPS spento" in testi(P_MAC)
    except Exception as e:  # noqa: BLE001
        ok_spento = False
        print("   ", e)
    esito("VPS spenta: il Mac salva lo stesso, senza bloccarsi", ok_spento and time.time() - t0 < 12, f"{time.time() - t0:.1f} s")
    esito("VPS spenta: la pagina del Mac legge la lavagna", "dal Mac" in testi(P_MAC))
    time.sleep(5)                      # almeno due giri della lavagna con la VPS spenta
    esito("VPS riaccesa", avvia("vps"))
    nota(P_VPS, "v11", "VPS dopo il ritorno")
    esito("al ritorno: la nota fatta col VPS spento arriva sulla VPS",
          aspetta(lambda: {"col VPS spento", "VPS dopo il ritorno"} <= testi(P_VPS), 20), testi(P_VPS))
    esito("al ritorno: il Mac ha anche la nota scritta sulla VPS",
          aspetta(lambda: {"col VPS spento", "VPS dopo il ritorno"} <= testi(P_MAC), 20), testi(P_MAC))
    ev = (CASA_M / ".locale-onedrive" / "jarvis-cc" / "fonte-vps.log").read_text(encoding="utf-8")
    esito("avviso all'utente: VPS giù e poi di nuovo raggiungibile", "la VPS non risponde" in ev and "risponde di nuovo" in ev, ev[:300])
finally:
    ferma("mac")
    ferma("vps")
    if TIENI:
        print("cartella:", TMP)
    else:
        shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{sum(esiti)} PASS, {len(esiti) - sum(esiti)} FAIL")
sys.exit(0 if all(esiti) else 1)
