#!/usr/bin/env python3
"""Prova ripetibile delle notifiche di Jarvis e del Postino (2026-10-05, programmatore-notifiche) su un'istanza ISOLATA.

    python3 command-center/prova_notifiche.py [--porta 7797] [--tieni]      esito 0 = tutto passa

Copia questa cartella in una cartella temporanea (senza stato vero), HOME finta, CC_FILI_DIR finto, avvia
`CC_PORTA=<porta> CC_PROVA=1 python3 server.py` e prova: fili.notifica (chiave, prova, togli), POST /api/notifica
(mittente sbagliato, dati, togli_prove), GET /api/fili, il contesto che va a Jarvis per una risposta nel filo,
la conversione HTML→testo di strumenti/notifica.py e che in prova notifica.py non tocchi mai Telegram.
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
import time
import urllib.error
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--porta", type=int, default=7797)
ap.add_argument("--tieni", action="store_true")
ARG = ap.parse_args()
BASE = f"http://127.0.0.1:{ARG.porta}"
esiti = []


def ok(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("✅" if cond else "❌"), nome, ("· " + str(dettaglio)) if dettaglio and not cond else "")


with socket.socket() as s:
    if s.connect_ex(("127.0.0.1", ARG.porta)) == 0:
        print(f"❌ la porta {ARG.porta} è occupata")
        sys.exit(1)

TMP = Path(tempfile.mkdtemp(prefix="prova-notifiche-"))
CC = TMP / "command-center"
HOME = TMP / "home"
FILI = TMP / "fili"
HOME.mkdir()
STATO_VERO = {"spazi.json", "pannello.json", "gruppi-archiviati.json", "agenti-tolti.json", "modifiche-agenti.jsonl",
              "conversazioni.json", "assistenza.json", "sessioni_motori.json", "catena-stato.json"}
shutil.copytree(QUI, CC, ignore=lambda d, nomi: [n for n in nomi if n in STATO_VERO or n in (
    "missioni", "missioni_archivio", "cache-profili", "__pycache__", "pannello-storia", "lavori", ".DS_Store",
    "static-nuova", "registro-dev", "perf-dev", "fili-dev") or n.startswith("static-backup") or ".prima-" in n
    or n.startswith("pannello.json.bak")])
(CC / "spazi.json").write_text(json.dumps({"spazi": []}))
(CC / "pannello.json").write_text(json.dumps({"versione": 1, "aspetto": {}, "gruppi": [], "lavagne": {}}))

# --- 1. fili.py da solo
os.environ["CC_FILI_DIR"] = str(TMP / "fili-unita")
sys.path.insert(0, str(CC))
import fili  # noqa: E402

r = fili.notifica("postino", "Report posta", "1. booking@ · richiesta volo", dati={"voci": [{"numero": 1, "bozza": {"testo": "Gentile"}}]},
                  prova=True, chiave="prova-1")
r2 = fili.notifica("postino", "Report posta", "rifatto", prova=True, chiave="prova-1")
ok("stessa chiave = stesso messaggio, stesso filo", r2["sessione"] == r["sessione"] and r2["messaggi"] == 1)
ok("interlocutore del postino", r["interlocutore"] == "postino")
rj = fili.notifica("jarvis", "Pranzo", "Sede Uno 2.880 €")
ok("jarvis → notifiche-jarvis", rj["interlocutore"] == "notifiche-jarvis")
tel = json.loads(fili.file_telefono().read_text())
ok("lista del telefono con le due notifiche", {v["k"] for v in tel} == {"postino", "notifiche-jarvis"})
ok("contesto del filo", fili.contesto_notifiche(r["sessione"])[-1]["testo"] == "rifatto")
ok("togli solo le prove", fili.togli_notifiche() == 1 and len(fili.leggi(rj["sessione"])["messaggi"]) == 1)
try:
    fili.notifica("altro", "x", "y")
    ok("mittente sconosciuto rifiutato", False)
except ValueError:
    ok("mittente sconosciuto rifiutato", True)
remoto = fili.leggi(rj["sessione"])
remoto["messaggi"].append({"id": "n-x", "chi": "lui", "testo": "nuovo", "ts": remoto["messaggi"][0]["ts"] + 1, "notifica": True})
ok("specchio: unisce e poi non cambia più", fili.specchia(remoto) and not fili.specchia(remoto))

# --- 2. notifica.py: HTML → testo, e in prova niente Telegram anche se il Command Center non risponde
sys.path.insert(0, str(QUI.parent / "strumenti"))
import notifica  # noqa: E402

ok("da_html", notifica.da_html("<b>Pranzo</b> &amp; cena<br>riga <a href='https://x.it'>link</a>") == "**Pranzo** & cena\nriga link (https://x.it)")
chiamate = []
notifica.telegram = lambda *a, **k: chiamate.append(a) or True
notifica.su_vps = lambda: True
notifica.CC_URL = "http://127.0.0.1:9"          # nessuno ascolta
notifica.TOKEN_FILE = TMP / "token-finto"
notifica.TOKEN_FILE.write_text("x")
e = notifica.notifica("jarvis", "prova", "prova notifiche", prova=True)
ok("in prova, CC giù: niente Telegram", e["ok"] is False and not chiamate, e)
e = notifica.notifica("jarvis", "vero", "CC giù")
ok("fuori prova, CC giù: riserva Telegram", e["dove"] == "telegram" and len(chiamate) == 1, e)

# --- 3. server isolato
env = {**os.environ, "HOME": str(HOME), "CC_PORTA": str(ARG.porta), "CC_PROVA": "1", "CC_FILI_DIR": str(FILI),
       "JARVIS_ATTIVITA_DIR": str(TMP / "attivita")}
LOG = TMP / "server.log"
SRV = subprocess.Popen([sys.executable, "server.py"], cwd=CC, env=env, stdout=open(LOG, "w"), stderr=subprocess.STDOUT,
                       start_new_session=True)
TOKEN = None
for _ in range(60):
    try:
        html = urllib.request.urlopen(BASE + "/", timeout=2).read().decode()
        TOKEN = re.search(r'CC_TOKEN = "([^"]+)"', html).group(1)
        break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)


def post(percorso, corpo):
    req = urllib.request.Request(BASE + percorso, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(percorso):
    req = urllib.request.Request(BASE + percorso, headers={"X-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


try:
    ok("server partito", TOKEN, LOG.read_text()[-400:] if LOG.exists() else "")
    if TOKEN:
        ok("la pagina carica notifiche.js e notifiche.css", "notifiche.js" in html and "notifiche.css" in html)
        c, d = post("/api/notifica", {"chi": "postino", "titolo": "prova notifiche 05/10", "testo": "1. prova",
                                     "dati": {"voci": [{"numero": 1, "bozza": {"destinatario": "a@b.it", "testo": "ciao"}}]},
                                     "prova": True})
        ok("POST /api/notifica", c == 200 and d.get("ok") and d.get("interlocutore") == "postino", (c, d))
        ok("telegram_copia spento di default", d.get("telegram_copia") is False, d)
        c2, d2 = post("/api/notifica", {"chi": "nessuno", "testo": "x"})
        ok("mittente sbagliato → 400", c2 == 400, (c2, d2))
        el = get("/api/fili")
        f = next((x for x in el["fili"] if x["interlocutore"] == "postino"), None)
        ok("il filo del Postino è in /api/fili", f and f["messaggi"] == 1, el)
        filo = get("/api/fili/" + d["sessione"])
        m = filo["messaggi"][-1]
        ok("il messaggio ha mittente, titolo, dati e prova", m.get("mittente") == "Postino" and m.get("titolo")
           and m.get("dati", {}).get("voci") and m.get("prova"), m)
        sys.path.insert(0, str(CC))
        ctx = subprocess.run([sys.executable, "-c", "import server,sys;print(server.contesto_notifiche(sys.argv[1],'postino'))",
                              d["sessione"]], cwd=CC, env=env, capture_output=True, text=True, timeout=60)
        ok("il contesto della risposta porta il report e la regola dell'invio",
           "prova notifiche 05/10" in ctx.stdout and "invia" in ctx.stdout and "Cestino" in ctx.stdout, ctx.stderr[-300:])
        c3, d3 = post("/api/notifica", {"togli_prove": True})
        ok("togli_prove", c3 == 200 and d3.get("tolti") == 1, d3)
finally:
    if SRV.poll() is None:
        try:
            os.killpg(SRV.pid, signal.SIGTERM)
            SRV.wait(10)
        except Exception:  # noqa: BLE001
            os.killpg(SRV.pid, signal.SIGKILL)
    if not ARG.tieni:
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("cartella:", TMP)

print(f"\n{sum(esiti)}/{len(esiti)} prove passate")
sys.exit(0 if all(esiti) else 1)
