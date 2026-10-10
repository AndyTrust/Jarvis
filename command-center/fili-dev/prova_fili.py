#!/usr/bin/env python3
"""Prove dell'archivio dei fili (2026-10-03, cc-fili-opus). Uso:

    python3 command-center/fili-dev/prova_fili.py                 # a, b, c (Chrome), senza claude vero
    python3 command-center/fili-dev/prova_fili.py --con-claude    # in più d: una domanda vera in «lettura»
    python3 command-center/fili-dev/prova_fili.py --senza-chrome  # salta c

Parti:
  a) unitarie su fili.py: id stabili, niente doppioni, versioni, nomi file sicuri, permessi, troncatura,
     segreti, limiti, riavvio, reset, concorrenza fra thread e fra processi, file rovinati;
  b) server.py con la patch fili-server.patch su una COPIA in una cartella temporanea: porta 7799,
     CC_PROVA=1, HOME temporanea, CC_FILI_DIR temporanea, un «claude» finto (claude_finto.py) che risponde
     senza rete. Endpoint, evento «fili» sul flusso, domanda e risposta nell'archivio, riavvio;
  c) Chrome headless vero (prova_fili_browser.js): due dispositivi (desktop 1440 sul Mac, iPhone 14
     attraverso una copia di cc_ponte.py), TUTTI i POST delle pagine abortiti;
  d) facoltativa: claude vero, una domanda semplice in «lettura», con la HOME vera ma l'archivio, i lavori
     e la configurazione nella cartella temporanea.

Non tocca il Command Center vero (7777) né i suoi file: tutto in cartelle temporanee. Ogni riga è PASS,
FAIL o SALTA; in fondo i totali e le righe non PASS.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEV = Path(__file__).resolve().parent
CC = DEV.parent
PONTE_DIR = CC.parent / "vps" / "cc-ponte"
PATCH = DEV / "fili-server.patch"
TMP = Path(tempfile.mkdtemp(prefix="prova-fili-"))
os.environ["CC_FILI_DIR"] = str(TMP / "fili-unit")
sys.path.insert(0, str(DEV))
import fili as F  # noqa: E402

RISULTATI = {"PASS": 0, "FAIL": 0, "SALTA": 0}
NON_PASS = []
U1 = "11111111-1111-4111-8111-111111111111"
U2 = "22222222-2222-4222-8222-222222222222"
U3 = "33333333-3333-4333-8333-333333333333"
ULET = "abcdefab-cdef-4abc-8def-abcdefabcdef"


def esito(nome, ok, dettaglio=""):
    tipo = "PASS" if ok else "FAIL"
    RISULTATI[tipo] += 1
    riga = f"{tipo}  {nome}" + (f"  — {str(dettaglio)[:300]}" if dettaglio and not ok else "")
    if not ok:
        NON_PASS.append(riga)
    print(riga, flush=True)
    return ok


def salta(nome, perche):
    RISULTATI["SALTA"] += 1
    riga = f"SALTA {nome}  — {perche}"
    NON_PASS.append(riga)
    print(riga, flush=True)


# ====================================================================== a) unitarie

def parte_a():
    print("\n== a) fili.py")
    avvisi = []
    F.AVVISA = avvisi.append
    r = F.domanda(U1, "jarvis", "Ciao, come va?", "190001-aaaa", ts=1000.0)
    esito("domanda: filo nuovo, versione 1, attesa sul lavoro", r["versione"] == 1 and r["attesa"] == "190001-aaaa"
          and r["messaggi"] == 1 and r["titolo"] == "Ciao, come va?", r)
    d = F.leggi(U1)
    esito("domanda: id stabile q-<lavoro>, chi io, ora", d["messaggi"][0]["id"] == "q-190001-aaaa"
          and d["messaggi"][0]["chi"] == "io" and d["messaggi"][0]["ora"], d["messaggi"][0])
    F.domanda(U1, "jarvis", "Ciao, come va?", "190001-aaaa", ts=1000.0)
    esito("domanda ripetuta con lo stesso lavoro = nessun doppione", len(F.leggi(U1)["messaggi"]) == 1)
    F.risposta(U1, "190001-aaaa", "Bene, l'utente.", True, motore="claude", ts=1005.0)
    d = F.leggi(U1)
    esito("risposta: a-<lavoro>, attesa finita, versione 3", [m["id"] for m in d["messaggi"]] == ["q-190001-aaaa", "a-190001-aaaa"]
          and d["in_attesa"] == [] and d["versione"] == 3 and d["messaggi"][1]["motore"] == "claude", d)
    F.risposta(U1, "190001-aaaa", "Bene, l'utente (corretta).", True, ts=1006.0)
    d = F.leggi(U1)
    esito("risposta ripetuta = sostituisce, non aggiunge (ora della prima resta)", len(d["messaggi"]) == 2
          and d["messaggi"][1]["testo"] == "Bene, l'utente (corretta)." and d["messaggi"][1]["ts"] == 1005.0)
    F.risposta(U1, "190002-bbbb", "", False, ts=1010.0)
    d = F.leggi(U1)
    esito("risposta vuota in errore = «(nessuna risposta)» con errore", d["messaggi"][-1]["testo"] == "(nessuna risposta)"
          and d["messaggi"][-1]["errore"] is True)
    esito("avviso a ogni scrittura con sessione e versione", [a["versione"] for a in avvisi] == [1, 2, 3, 4, 5]
          and all(a["sessione"] == U1 for a in avvisi), avvisi)

    # nomi file e id
    for cattivo in ("../etc/passwd", ULET.upper(), U1 + "x", "x.json", "", None, "11111111-1111-4111-8111-11111111111/"):
        try:
            F.domanda(cattivo, "jarvis", "x", "190003-cccc")
            esito(f"sessione non valida rifiutata: {cattivo!r}", False)
        except ValueError:
            esito(f"sessione non valida rifiutata: {cattivo!r}", True)
    esito("leggi() con nome strano = None, nessun file fuori cartella", F.leggi("../../etc/passwd") is None
          and F.leggi(ULET.upper()) is None)
    for cattivo in ("../x", "a b", "", "x" * 65, "a/b"):
        try:
            F.domanda(U2, "jarvis", "x", cattivo)
            esito(f"id lavoro non valido rifiutato: {cattivo!r}", False)
        except ValueError:
            esito(f"id lavoro non valido rifiutato: {cattivo!r}", True)
    esito("nessun file creato dai tentativi sbagliati", sorted(p.name for p in F.cartella().iterdir()
                                                               if not p.name.startswith(".")) == [f"{U1}.json"],
          [p.name for p in F.cartella().iterdir()])
    st_c = F.cartella().stat().st_mode & 0o777
    st_f = (F.cartella() / f"{U1}.json").stat().st_mode & 0o777
    esito("permessi: cartella 0700, file 0600", st_c == 0o700 and st_f == 0o600, f"{oct(st_c)} {oct(st_f)}")
    esito("nessun file temporaneo lasciato", not list(F.cartella().glob(".filo-*")))

    # troncatura e segreti
    r = F.risposta(U2, "190010-dddd", "a" * 50000, True, log_nome="2026-10-03_190010-dddd.log", interlocutore="jarvis")
    m = F.leggi(U2)["messaggi"][-1]
    esito("risposta enorme troncata a MAX_TESTO con il log indicato", len(m["testo"]) <= F.MAX_TESTO and m["troncato"]
          and m["log"] == "2026-10-03_190010-dddd.log" and "lavori/2026-10-03_190010-dddd.log" in m["testo"], len(m["testo"]))
    F.risposta(U2, "190011-eeee", "b" * 50000, True, log_nome="../../etc/passwd")
    m = F.leggi(U2)["messaggi"][-1]
    esito("nome di log non sicuro = non indicato", m["troncato"] and "log" in m and m["log"] == "" and "passwd" not in m["testo"])
    F.nascondi_anche("TOKEN-DELLA-PAGINA-123456")
    F.domanda(U2, "jarvis", "usa sk-ant-api03-ABCDEFGHIJKLMNOP, ghp_abcdefghijklmnopqrstuvwxyz12, "
                            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz e TOKEN-DELLA-PAGINA-123456 poi ciao", "190012-ffff")
    t = F.leggi(U2)["messaggi"][-1]["testo"]
    esito("segreti mascherati (sk-ant, ghp_, Bearer, token della pagina), il resto resta",
          "ABCDEFGHIJKLMNOP" not in t and "abcdefghijklmnopqrstuvwxyz12" not in t and "TOKEN-DELLA-PAGINA" not in t
          and "Bearer [nascosto]" in t and t.endswith("poi ciao"), t)
    testo_file = (F.cartella() / f"{U2}.json").read_text()
    esito("…e nemmeno nel file su disco", "ABCDEFGHIJKLMNOP" not in testo_file and "TOKEN-DELLA-PAGINA" not in testo_file)

    # elenco e cache
    el = F.elenco()
    esito("elenco: dal più recente, con riassunto", [f["sessione"] for f in el["fili"]] == [U2, U1]
          and el["fili"][1]["messaggi"] == 3 and el["fili"][1]["interlocutore"] == "jarvis" and isinstance(el["ora"], float), el)
    (F.cartella() / "non-un-filo.json").write_text("{}")
    (F.cartella() / f"{U3}.json").write_text("{rovinato")
    el = F.elenco()
    esito("elenco salta i file che non sono fili o sono rovinati", [f["sessione"] for f in el["fili"]] == [U2, U1])
    esito("leggi() su file rovinato = None", F.leggi(U3) is None)
    r = F.domanda(U3, "jarvis", "dopo il file rovinato", "190020-aaaa")
    esito("scrittura su file rovinato: il filo riparte pulito (versione 1)", r["versione"] == 1 and r["messaggi"] == 1)
    (F.cartella() / "non-un-filo.json").unlink()
    F.domanda(U1, "jarvis", "terza", "190030-aaaa")
    el = F.elenco()
    esito("cache dell'elenco: il filo riscritto risale in cima con i numeri nuovi",
          el["fili"][0]["sessione"] == U1 and el["fili"][0]["messaggi"] == 4)

    # reset e riavvio
    r = F.reset(U3.replace("3", "4"), "progetto:agente", "Nuova conversazione: il filo di prima è chiuso, riparto da zero.")
    d = F.leggi(U3.replace("3", "4"))
    esito("reset: filo nuovo con il messaggio r-…", d["messaggi"][0]["id"] == "r-44444444" and d["interlocutore"] == "progetto:agente")
    F.domanda(U1, "jarvis", "rimasta a metà", "190040-aaaa")
    n = F.riavvio()
    d = F.leggi(U1)
    ultimo = d["messaggi"][-1]
    esito("riavvio: l'attesa diventa «Risposta persa» (a-<lavoro>, errore) come nella pagina",
          n >= 1 and ultimo["id"] == "a-190040-aaaa" and ultimo["testo"] == F.PERSA and ultimo["errore"] and d["in_attesa"] == [], ultimo)
    esito("riavvio ripetuto: niente da fare", F.riavvio() == 0)

    # limiti
    vecchi = (F.MAX_MESSAGGI, F.MAX_BYTE_FILO, F.MAX_FILI)
    F.MAX_MESSAGGI = 10
    for i in range(15):
        F.domanda(U2, "jarvis", f"msg {i}", f"191000-{i:04d}")
    d = F.leggi(U2)
    esito("massimo di messaggi per filo: escono i più vecchi", len(d["messaggi"]) == 10 and d["messaggi"][-1]["testo"] == "msg 14")
    F.MAX_MESSAGGI = 400
    F.MAX_BYTE_FILO = 30000
    for i in range(10):
        F.risposta(U2, f"192000-{i:04d}", "z" * 9000, True)
    dim = (F.cartella() / f"{U2}.json").stat().st_size
    esito("massimo di byte per filo: il file resta sotto il tetto", dim <= 30000, dim)
    F.MAX_BYTE_FILO = vecchi[1]
    F.MAX_FILI = 5
    for i in range(8):
        F.domanda(f"aaaaaaaa-0000-4000-8000-{i:012d}", "jarvis", f"filo {i}", "193000-aaaa")
        time.sleep(0.01)
    fili = list(F.cartella().glob("*.json"))
    esito("massimo di fili: i meno recenti escono", len(fili) == 5 and (F.cartella() / "aaaaaaaa-0000-4000-8000-000000000007.json").exists(),
          len(fili))
    F.MAX_MESSAGGI, F.MAX_BYTE_FILO, F.MAX_FILI = vecchi

    # concorrenza fra thread
    U5 = "55555555-5555-4555-8555-555555555555"
    errori = []

    def scrivi(n):
        try:
            for i in range(25):
                F.domanda(U5, "jarvis", f"t{n}-{i}", f"t{n}-{i:03d}")
        except Exception as e:  # noqa: BLE001
            errori.append(repr(e))
    th = [threading.Thread(target=scrivi, args=(n,)) for n in range(8)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    d = F.leggi(U5)
    ids = [m["id"] for m in d["messaggi"]]
    esito("concorrenza (8 thread × 25): 200 messaggi, nessuno perso né doppio, versione 200",
          not errori and len(ids) == 200 and len(set(ids)) == 200 and d["versione"] == 200, f"{len(ids)} {d['versione']} {errori[:2]}")

    # concorrenza fra processi (flock)
    U6 = "66666666-6666-4666-8666-666666666666"
    codice = ("import sys; sys.path.insert(0, %r); import fili\n"
              "for i in range(20): fili.domanda(%r, 'jarvis', f'p{sys.argv[1]}-{i}', f'p{sys.argv[1]}-{i:03d}')") % (str(DEV), U6)
    procs = [subprocess.Popen([sys.executable, "-c", codice, str(n)], env=os.environ.copy()) for n in range(4)]
    codici = [p.wait(60) for p in procs]
    d = F.leggi(U6)
    ids = [m["id"] for m in d["messaggi"]]
    esito("concorrenza (4 processi × 20, lock su file): 80 messaggi, versione 80",
          codici == [0] * 4 and len(set(ids)) == 80 and d["versione"] == 80, f"{codici} {len(ids)} {d['versione']}")
    F.AVVISA = None


# ====================================================================== b) server con la patch

MODULI = ["server.py", "approvazioni.py", "approvazioni_mcp.py", "tecnico.py", "spazi.py", "conversazione.py",
          "senza_finestre.py", "attivita.py", "missione.py", "conferme.py", "aggiornamento.py", "repo_github.py"]


def http(metodo, url, corpo=None, intest=None, timeout=15):
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo, headers={"Content-Type": "application/json", **(intest or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def prepara_copia():
    copia = TMP / "cc"
    copia.mkdir()
    for n in MODULI:
        if (CC / n).exists():
            shutil.copy2(CC / n, copia / n)
    shutil.copy2(DEV / "fili.py", copia / "fili.py")
    r = subprocess.run(["patch", "-p0", "--dry-run", "-i", str(PATCH)], cwd=copia, capture_output=True, text=True)
    esito("la patch si applica (patch -p0 --dry-run) sul server.py attuale", r.returncode == 0
          and r.stdout.strip() == "patching file server.py", r.stdout + r.stderr)
    r = subprocess.run(["patch", "-p0", "-i", str(PATCH)], cwd=copia, capture_output=True, text=True)
    esito("patch applicata alla copia", r.returncode == 0, r.stdout + r.stderr)
    r = subprocess.run([sys.executable, "-m", "py_compile", str(copia / "server.py")], capture_output=True, text=True)
    esito("server.py con la patch compila", r.returncode == 0, r.stderr)
    casa = TMP / "casa"
    (casa / "my-agent").mkdir(parents=True)
    (casa / ".local" / "bin").mkdir(parents=True)
    shutil.copy2(DEV / "claude_finto.py", casa / ".local" / "bin" / "claude")
    os.chmod(casa / ".local" / "bin" / "claude", 0o755)
    # la pagina nuova (static-nuova) con fili.js, sopra i file statici di oggi (icone, sw.js)
    shutil.copytree(CC / "static", copia / "static")
    for f in (CC / "static-nuova").iterdir():
        if f.is_file():
            shutil.copy2(f, copia / "static" / f.name)
    pagina = (copia / "static" / "index.html").read_text(encoding="utf-8")
    if "/static/fili.js" not in pagina:
        pagina = pagina.replace("</body>", '<script src="/static/fili.js" defer></script>\n</body>', 1)
    (copia / "static" / "index.html").write_text(pagina, encoding="utf-8")
    (copia / "lavori").mkdir(exist_ok=True)
    (copia / "configurazione.json").write_text(json.dumps({
        "cartella_agente": str(casa / "my-agent"), "vault": "", "porta": 7799, "modo_chat": "lavoro"}))
    return copia, casa


class Server:
    def __init__(self, copia, casa, attesa="1"):
        self.copia, self.casa = copia, casa
        percorso = [str(casa / ".local" / "bin")] + [p for p in os.environ.get("PATH", "").split(":")
                                                     if p and ".local/bin" not in p]
        self.env = {**os.environ, "HOME": str(casa), "CC_PORTA": "7799", "CC_PROVA": "1",
                    "CC_FILI_DIR": str(TMP / "fili-server"), "CC_APPROVAZIONI_DIR": str(TMP / "approv-server"),
                    "PATH": ":".join(percorso), "FINTO_ATTESA": attesa}
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.base = "http://127.0.0.1:7799"
        self.log = open(TMP / "server-prova.log", "a")
        self.p = subprocess.Popen([sys.executable, str(copia / "server.py")], cwd=copia, env=self.env,
                                  stdout=self.log, stderr=subprocess.STDOUT)
        self.token = None
        for _ in range(80):
            try:
                c, b = http("GET", self.base + "/")
                if c == 200:
                    self.token = b.decode().split('window.CC_TOKEN = "')[1].split('"')[0]
                    break
            except (urllib.error.URLError, OSError, IndexError):
                pass
            time.sleep(0.5)
        self.H = {"X-Token": self.token or "", "Origin": self.base}

    def get(self, p, **k):
        c, b = http("GET", self.base + p, intest=self.H, **k)
        try:
            return c, json.loads(b)
        except ValueError:
            return c, b

    def post(self, corpo):
        c, b = http("POST", self.base + "/api/azione", corpo, self.H, timeout=40)
        try:
            return c, json.loads(b)
        except ValueError:
            return c, b

    def ferma(self):
        self.p.terminate()
        try:
            self.p.wait(8)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.log.flush()


def aspetta(fn, secondi=20, passo=0.25):
    fine = time.time() + secondi
    while time.time() < fine:
        v = fn()
        if v:
            return v
        time.sleep(passo)
    return fn()


def ascolta_sse(srv, eventi, ferma):
    try:
        with urllib.request.urlopen(srv.base + f"/api/flusso?token={srv.token}", timeout=60) as r:
            nome = None
            for riga in r:
                if ferma.is_set():
                    return
                riga = riga.decode().rstrip("\n")
                if riga.startswith("event: "):
                    nome = riga[7:]
                elif riga.startswith("data: "):
                    try:
                        eventi.append((nome or "message", json.loads(riga[6:]), time.time()))
                    except ValueError:
                        pass
                    nome = None
    except Exception:  # noqa: BLE001
        pass


def parte_b():
    print("\n== b) server.py con la patch (copia isolata, porta 7799, claude finto)")
    if not PATCH.exists():
        salta("server con la patch", f"manca {PATCH}")
        return None
    copia, casa = prepara_copia()
    srv = Server(copia, casa)
    fdir = TMP / "fili-server"
    ferma = threading.Event()
    try:
        if not esito("la copia parte sulla 7799 e dà il token", bool(srv.token)):
            return None
        c, d = srv.get("/api/fili")
        esito("GET /api/fili → elenco vuoto", c == 200 and d.get("fili") == [] and "ora" in d, d)
        c, _ = http("GET", srv.base + "/api/fili")
        esito("GET /api/fili senza token → 403", c == 403, c)
        c, _ = http("GET", srv.base + "/api/fili", intest={"X-Token": srv.token, "Host": "evil.example:7799"})
        esito("GET /api/fili con Host estraneo → 403", c == 403, c)
        for brutto in (f"/api/fili/{ULET.upper()}", "/api/fili/..%2f..%2fetc%2fpasswd", "/api/fili/x", f"/api/fili/{U1}x"):
            c, _ = srv.get(brutto)
            esito(f"GET {brutto[:40]} → 404", c == 404, c)
        eventi = []
        threading.Thread(target=ascolta_sse, args=(srv, eventi, ferma), daemon=True).start()
        time.sleep(1.2)
        S1 = "a1a1a1a1-0000-4000-8000-000000000001"
        t0 = time.time()
        c, r = srv.post({"tipo": "chiedi", "testo": "Prima domanda di prova", "sessione": S1, "continua": False,
                         "agente": "", "progetto": "", "motore": "claude"})
        lid = (r.get("lavoro") or {}).get("id") if isinstance(r, dict) else None
        esito("POST chiedi (dal programma di prova, non dal browser) → lavoro", c == 200 and lid, r)
        ev = aspetta(lambda: [e for e in eventi if e[0] == "fili" and e[1].get("sessione") == S1], 5)
        esito("evento «fili» sul flusso alla domanda, entro 2 s", bool(ev) and ev[0][2] - t0 < 2.0
              and ev[0][1].get("interlocutore") == "jarvis", [e[:2] for e in eventi if e[0] != "message"][:5])
        c, f = srv.get(f"/api/fili/{S1}")
        esito("GET /api/fili/<sessione>: la domanda c'è con l'id del lavoro e l'attesa", c == 200
              and f["messaggi"][0]["id"] == f"q-{lid}" and f["messaggi"][0]["testo"] == "Prima domanda di prova"
              and f["in_attesa"] == [lid], f)
        fine = aspetta(lambda: (srv.get(f"/api/fili/{S1}")[1].get("in_attesa") == []), 20)
        c, f = srv.get(f"/api/fili/{S1}")
        esito("a lavoro finito la risposta entra nel filo (a-<lavoro>), attesa vuota", fine and len(f["messaggi"]) == 2
              and f["messaggi"][1]["id"] == f"a-{lid}" and f["messaggi"][1]["testo"] == "Risposta finta a: Prima domanda di prova"
              and not f["messaggi"][1].get("errore") and f["messaggi"][1].get("motore") == "claude", f)
        c, lav = srv.get(f"/api/lavoro/{lid}")
        testo_pagina = lav["testo"].split("\n\n", 1)[1].strip() if lav["testo"].startswith("(cartella:") else lav["testo"].strip()
        esito("il testo nel filo è lo stesso che la pagina legge da /api/lavoro/<id>", testo_pagina == f["messaggi"][1]["testo"],
              testo_pagina[:100])
        conta = lambda: len([e for e in eventi if e[0] == "fili" and e[1].get("sessione") == S1])
        aspetta(lambda: conta() >= 2, 5)
        esito("eventi «fili»: uno alla domanda e uno alla risposta", conta() == 2, conta())
        c, el = srv.get("/api/fili")
        esito("GET /api/fili: il filo con titolo, interlocutore, numero messaggi, versione", c == 200
              and el["fili"][0]["sessione"] == S1 and el["fili"][0]["titolo"] == "Prima domanda di prova"
              and el["fili"][0]["messaggi"] == 2 and el["fili"][0]["versione"] == 2, el)
        # seconda domanda, risposta lunga, errore, segreto
        for testo in ("Seconda domanda LUNGA", "Terza domanda ERRORE", "Quarta con SEGRETO"):
            srv.post({"tipo": "chiedi", "testo": testo, "sessione": S1, "motore": "claude"})
        aspetta(lambda: len(srv.get(f"/api/fili/{S1}")[1].get("messaggi", [])) == 8 and
                srv.get(f"/api/fili/{S1}")[1].get("in_attesa") == [], 40)
        c, f = srv.get(f"/api/fili/{S1}")
        m = f["messaggi"]
        ids = [x["id"] for x in m]
        lids = [i[2:] for i in ids if i.startswith("q-")]
        # tre domande insieme (come da due dispositivi): il server le mette in fila, le risposte arrivano dopo
        esito("tre domande insieme nello stesso filo: ordine del tempo, risposte nell'ordine delle domande",
              len(m) == 8 and ids[2:] == [f"q-{x}" for x in lids[1:]] + [f"a-{x}" for x in lids[1:]], ids)
        per = {x["id"]: x for x in m}
        lunga, errata, segreta = (per.get(f"a-{x}", {}) for x in lids[1:4]) if len(lids) == 4 else ({}, {}, {})
        esito("risposta lunga troncata con il nome del log", len(lunga.get("testo", "")) <= F.MAX_TESTO and lunga.get("troncato")
              and lunga.get("log", "").endswith(".log") and lunga["log"] in lunga["testo"], len(lunga.get("testo", "")))
        esito("risposta in errore segnata errore", errata.get("errore") is True, errata)
        esito("segreto nella risposta mascherato nel filo", "ABCDEFGHIJKLMNOPQRSTUVWX" not in segreta.get("testo", "x")
              and "[nascosto]" in segreta.get("testo", ""), segreta.get("testo"))
        # reset
        c, r = srv.post({"tipo": "chiedi", "testo": "nuova conversazione", "sessione": S1, "motore": "claude"})
        nuova = r.get("sessione") if isinstance(r, dict) else None
        c, f = srv.get(f"/api/fili/{nuova}")
        esito("«nuova conversazione»: il filo nuovo esiste con il messaggio del server", r.get("reset") and c == 200
              and f["messaggi"][0]["id"].startswith("r-") and f["messaggi"][0]["testo"] == r.get("messaggio"), f)
        # un comando diretto non crea fili
        prima = len(srv.get("/api/fili")[1]["fili"])
        srv.post({"tipo": "comando_diretto", "nome": "lavori", "arg": ""})
        time.sleep(1.5)
        esito("un comando diretto «/lavori» non crea fili", len(srv.get("/api/fili")[1]["fili"]) == prima)
        # file sul disco
        tutti = "".join(p.read_text() for p in fdir.glob("*.json"))
        esito("archivio: cartella 0700, file 0600", (fdir.stat().st_mode & 0o777) == 0o700
              and all((p.stat().st_mode & 0o777) == 0o600 for p in fdir.glob("*.json")))
        esito("archivio: il token della pagina non c'è", srv.token not in tutti)
        # riavvio a metà risposta
        S2 = "b2b2b2b2-0000-4000-8000-000000000002"
        srv.ferma()
        srv = Server(copia, casa, attesa="30")
        srv.post({"tipo": "chiedi", "testo": "Domanda interrotta", "sessione": S2, "motore": "claude"})
        time.sleep(1.5)
        srv.ferma()
        srv = Server(copia, casa)
        c, f = srv.get(f"/api/fili/{S2}")
        esito("Command Center riavviato a metà: la risposta diventa «Risposta persa» (errore), attesa vuota",
              c == 200 and f["messaggi"][-1]["testo"] == F.PERSA and f["messaggi"][-1]["errore"] and f["in_attesa"] == [], f)
        return srv, copia, casa
    except BaseException:
        srv.ferma()
        raise
    finally:
        ferma.set()


# ====================================================================== c) Chrome con due dispositivi

SERVER_C = []


def parte_c(pronto):
    print("\n== c) Chrome headless: Mac (desktop 1440) e telefono (iPhone 14) attraverso il ponte")
    if "--senza-chrome" in sys.argv:
        salta("c) Chrome", "--senza-chrome")
        return
    if not pronto:
        salta("c) Chrome", "la copia del server non è partita")
        return
    vecchio, copia, casa = pronto
    vecchio.ferma()
    srv = Server(copia, casa, attesa="4")       # 4 s di lavoro: si vede «sta lavorando» sull'altro dispositivo
    SERVER_C.append(srv)
    if not shutil.which("node") or not (Path.home() / "Jarvis" / "node_modules" / "puppeteer-core").exists():
        salta("c) Chrome", "manca node o puppeteer-core in ~/Jarvis/node_modules")
        return
    sys.path.insert(0, str(PONTE_DIR))
    import base64
    import cc_ponte
    password = "prova-password-fili-123"
    seme = base64.b32encode(b"seme-prova-fili-20by").decode().rstrip("=")
    conf = TMP / "ponte-conf.json"
    conf.write_text(json.dumps({"pw_scrypt": cc_ponte.hash_password(password), "totp_seed_b32": seme,
                                "cookie_key_hex": os.urandom(32).hex()}))
    os.chmod(conf, 0o600)
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    env = {**os.environ, "CC_PONTE_CONF": str(conf), "CC_PONTE_BIND": "127.0.0.1", "CC_PONTE_PORT": str(porta),
           "CC_PONTE_UPSTREAM": srv.base, "CC_PONTE_UPSTREAM_HOST": "127.0.0.1:7799", "CC_PONTE_SECURE": "0",
           "CC_PONTE_STATO_DIR": "", "STATE_DIRECTORY": "", "CC_PONTE_COMANDI_OFF": str(TMP / "comandi-off-assente"),
           "CC_PONTE_SCHERMO_ON": str(TMP / "schermo-on-assente")}
    plog = open(TMP / "ponte.log", "w")
    ponte = subprocess.Popen([sys.executable, "-I", str(PONTE_DIR / "cc_ponte.py")], env=env, stdout=plog, stderr=subprocess.STDOUT)
    try:
        aspetta(lambda: _porta_aperta(porta), 10, 0.1)
        if time.time() % 30 > 25:
            time.sleep(30 - time.time() % 30 + 0.5)
        codice = cc_ponte.codice_totp(cc_ponte.seme_da_b32(seme), int(time.time() // 30))
        req = urllib.request.Request(f"http://127.0.0.1:{porta}/_ponte/entra", method="POST",
                                     data=f"password={password}&codice={codice}".encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
            intest = r.headers
        except urllib.error.HTTPError as e:
            intest = e.headers
        cookie = next((v.split(";")[0] for k, v in intest.items() if k.lower() == "set-cookie"), "")
        esito("accesso al ponte di prova (dal programma, non dal browser)", cookie.startswith("ccp="), cookie[:4])
        pannello = copia / "pannello.json"
        versione_prima = json.loads(pannello.read_text()).get("versione") if pannello.exists() else None
        vero = CC / "pannello.json"
        vero_prima = json.loads(vero.read_text()).get("versione") if vero.exists() else None
        r = subprocess.run(["node", str(DEV / "prova_fili_browser.js")], env={
            **os.environ, "FILI_BASE_MAC": srv.base, "FILI_BASE_PONTE": f"http://127.0.0.1:{porta}",
            "FILI_COOKIE": cookie, "FILI_SCHERMATE": str(Path.home() / ".locale-onedrive" / "cc-ponte" / "schermate-fili")},
            capture_output=True, text=True, timeout=400)
        for riga in (r.stdout or "").splitlines():
            if riga.startswith("PASS  "):
                esito("browser: " + riga[6:], True)
            elif riga.startswith("FAIL  "):
                esito("browser: " + riga[6:], False)
            else:
                print("      " + riga)
        if r.returncode not in (0, 1):
            esito("browser: il programma node finisce", False, (r.stderr or "")[-800:])
        versione_dopo = json.loads(pannello.read_text()).get("versione") if pannello.exists() else None
        esito("pannello.json della copia: versione invariata (nessun POST è arrivato)", versione_prima == versione_dopo,
              f"{versione_prima} → {versione_dopo}")
        vero_dopo = json.loads(vero.read_text()).get("versione") if vero.exists() else None
        esito("pannello.json VERO (7777): versione invariata", vero_prima == vero_dopo, f"{vero_prima} → {vero_dopo}")
    finally:
        ponte.terminate()
        ponte.wait(5)
        plog.close()


def _porta_aperta(porta):
    import socket
    try:
        socket.create_connection(("127.0.0.1", porta), timeout=0.2).close()
        return True
    except OSError:
        return False


# ====================================================================== d) claude vero

def parte_d():
    print("\n== d) claude vero: una domanda semplice in «lettura», archivio nella cartella temporanea")
    if "--con-claude" not in sys.argv:
        salta("d) claude vero", "serve --con-claude")
        return
    import importlib.util
    copia = TMP / "cc-d"
    copia.mkdir()
    for n in MODULI:
        if (CC / n).exists():
            shutil.copy2(CC / n, copia / n)
    shutil.copy2(DEV / "fili.py", copia / "fili.py")
    subprocess.run(["patch", "-p0", "-i", str(PATCH)], cwd=copia, capture_output=True, check=True)
    (copia / "lavori").mkdir()
    (TMP / "vuota").mkdir()
    (copia / "configurazione.json").write_text(json.dumps({"cartella_agente": str(TMP / "vuota"), "vault": "",
                                                            "porta": 7799, "modo_chat": "lettura"}))
    os.environ.update(CC_PORTA="7799", CC_PROVA="1", CC_FILI_DIR=str(TMP / "fili-claude"),
                      CC_APPROVAZIONI_DIR=str(TMP / "approv-claude"))
    sys.modules.pop("fili", None)
    spec = importlib.util.spec_from_file_location("server_prova", copia / "server.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    sess = str(__import__("uuid").uuid4())
    r = S.chiedi({"testo": "Rispondi solo con la parola: pronto", "sessione": sess, "motore": "claude"}, filo=True)
    lid = r["lavoro"]["id"]
    fine = aspetta(lambda: (S.lavoro_copia(lid) or {}).get("stato") in ("finito", "errore"), 180, 1)
    f = S.fili.leggi(sess)
    esito("claude vero: domanda e risposta nell'archivio", bool(fine) and f and [m["id"] for m in f["messaggi"]] == [f"q-{lid}", f"a-{lid}"]
          and f["in_attesa"] == [], f)
    if f and len(f["messaggi"]) == 2:
        print(f"      (risposta vera: {f['messaggi'][1]['testo'][:80]!r}, stato del lavoro {S.lavoro_copia(lid)['stato']})")
        esito("claude vero: risposta non vuota e senza errore", f["messaggi"][1]["testo"].strip() and not f["messaggi"][1].get("errore"))


def main():
    print(f"cartella temporanea: {TMP}  ·  {time.strftime('%Y-%m-%d %H:%M')}")
    parte_a()
    pronto = None
    try:
        pronto = parte_b()
        parte_c(pronto)
    finally:
        for x in ([pronto[0]] if pronto else []) + SERVER_C:
            x.ferma()
    parte_d()
    print(f"\nTOTALI  PASS {RISULTATI['PASS']}  FAIL {RISULTATI['FAIL']}  SALTA {RISULTATI['SALTA']}")
    for r in NON_PASS:
        print("  " + r)
    if "--tieni" not in sys.argv:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if RISULTATI["FAIL"] else 0)


if __name__ == "__main__":
    main()
