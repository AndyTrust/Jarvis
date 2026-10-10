#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Prova del Vault sul Command Center VERO, in una CASA FINTA COMPLETA, su una porta libera.

    python3 command-center/prova_vault_server.py [--porta 0] [--resta] [--casa /percorso/finto]

Avvia command-center/server.py con lo stesso Python di questo comando, come copia di prova (CC_PROVA=1), con HOME,
USERPROFILE, APPDATA, LOCALAPPDATA e XDG_* dentro una cartella temporanea (controlla prima che Path.home() del server
sia la casa finta). Su macOS la chiave del dispositivo va in un portachiavi usa-e-getta, mai nel Portachiavi di login.
Poi controlla: GET /api/vault/stato (200, Vault non creato, stato vuoto), crea con password corta (400), voci senza
sessione (401), Google senza client (503 con la spiegazione), ritorno di Google senza token (pagina «non valido»).
Con --resta lascia il server acceso e stampa l'indirizzo (per provare la pagina nel browser); Ctrl+C lo ferma.
Porta vietata: 7777 (il Command Center vero). La casa finta si toglie alla fine (non con --casa).
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parent
a = argparse.ArgumentParser()
a.add_argument("--porta", type=int, default=0)
a.add_argument("--resta", action="store_true")
a.add_argument("--casa", default="")
arg = a.parse_args()
if arg.porta == 7777:
    sys.exit("porta 7777 vietata: è il Command Center vero")
if not arg.porta:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        arg.porta = so.getsockname()[1]

casa_vera = Path(os.path.expanduser("~")).resolve()
casa = Path(arg.casa or tempfile.mkdtemp(prefix="vault-server-")).resolve()
if casa == casa_vera or casa_vera in casa.parents:
    sys.exit("la casa finta non può stare dentro la casa vera")
casa.mkdir(parents=True, exist_ok=True)
env = {**os.environ, "HOME": str(casa), "USERPROFILE": str(casa), "APPDATA": str(casa / "AppData" / "Roaming"),
       "LOCALAPPDATA": str(casa / "AppData" / "Local"), "XDG_CONFIG_HOME": str(casa / ".config"),
       "XDG_DATA_HOME": str(casa / ".local" / "share"), "XDG_CACHE_HOME": str(casa / ".cache"),
       "XDG_STATE_HOME": str(casa / ".local" / "state"), "CC_PORTA": str(arg.porta), "CC_PROVA": "1",
       "JARVIS_VAULT_PROFILO": str(casa / "profilo-finto.md"), "PYTHONDONTWRITEBYTECODE": "1"}
(casa / "profilo-finto.md").write_text("---\nname: jarvis\nnome_assistente: Aiutante\nchiamami: Capo Finto\n---\n")
for nome in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
    Path(env[nome]).mkdir(parents=True, exist_ok=True)
casa_server = subprocess.run([sys.executable, "-c", "from pathlib import Path; print(Path.home().resolve())"],
                             env=env, capture_output=True, text=True).stdout.strip()
if Path(casa_server) != casa:
    sys.exit(f"Path.home() del server non è la casa finta ({casa_server}): mi fermo")
# la libreria di cifratura come la vedrà il server (anche dall'ambiente dedicato ~/.jarvis/vault-venv
# della casa finta); se non c'è, si prendono in sola lettura i pacchetti utente veri (PYTHONUSERBASE), senza scriverci.
critto = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(QUI)!r}); import vault_cc; print(vault_cc.CRITTO_OK)"],
                        env=env, capture_output=True, text=True, cwd=str(casa)).stdout.strip()
if critto != "True":
    import site
    env["PYTHONUSERBASE"] = site.getuserbase()
    print("cryptography non c'è nella casa finta: uso i pacchetti utente veri in sola lettura (PYTHONUSERBASE)")
else:
    print("cryptography: trovata come la troverà il server")
if sys.platform == "darwin":
    kc = casa / "prova.keychain-db"
    if not kc.exists():
        subprocess.run(["security", "create-keychain", "-p", "prova-vault", str(kc)], check=True, capture_output=True)
        subprocess.run(["security", "set-keychain-settings", str(kc)], check=True, capture_output=True)
    subprocess.run(["security", "unlock-keychain", "-p", "prova-vault", str(kc)], check=True, capture_output=True)
    env["JARVIS_VAULT_PORTACHIAVI"] = str(kc)
elif sys.platform != "win32":
    env["JARVIS_VAULT_PORTACHIAVI"] = "file"

log = casa / "server.log"
# il server di prova può scrivere qualche file di stato accanto a sé (conversazioni, progetti visti): alla fine si
# tolgono solo quelli che prima non c'erano
prima = {f for f in QUI.iterdir() if f.is_file()}
p = subprocess.Popen([sys.executable, "server.py"], cwd=str(QUI), env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
esito = 1
base = f"http://127.0.0.1:{arg.porta}"
try:
    html = None
    for _ in range(120):
        try:
            html = urllib.request.urlopen(base + "/", timeout=2).read().decode()
            break
        except OSError:
            if p.poll() is not None:
                raise SystemExit("il server si è fermato: " + log.read_text(errors="ignore")[-600:])
            time.sleep(0.5)
    if html is None:
        raise SystemExit("il server non risponde")
    token = re.search(r'CC_TOKEN = "([^"]+)"', html).group(1)

    def chiama(metodo, percorso, corpo=None):
        r = urllib.request.Request(base + percorso, method=metodo, headers={"X-Token": token, "Content-Type": "application/json"},
                                   data=json.dumps(corpo).encode() if corpo is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=30) as x:
                return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    c, d = chiama("GET", "/api/vault/stato")
    print("GET /api/vault/stato ->", c, json.dumps({k: d.get(k) for k in ("creato", "sbloccato", "cifratura", "posto_ok",
                                                                          "assistente", "proprietario", "portachiavi", "errore")}, ensure_ascii=False))
    ok1 = c == 200 and d.get("cifratura") is True and d.get("creato") is False and d.get("assistente") == "Aiutante"
    c2, d2 = chiama("POST", "/api/vault/crea", {"email": "prova@esempio.invalid", "password": "corta"})
    print("POST /api/vault/crea (password corta) ->", c2, d2.get("errore"))
    ok2 = c2 == 400 and "12 caratteri" in (d2.get("errore") or "")
    c3, d3 = chiama("GET", "/api/vault/voci")
    print("GET /api/vault/voci senza sessione ->", c3, d3.get("errore"))
    ok3 = c3 == 401
    c4, d4 = chiama("GET", "/api/vault/google/inizio")
    print("GET /api/vault/google/inizio senza client ->", c4, d4.get("errore"))
    ok4 = c4 == 503 and d4.get("manca_client") and "docs/wiki/Vault.md" in (d4.get("errore") or "")
    r5 = urllib.request.urlopen(base + "/api/vault/google/callback?state=inventato&code=x", timeout=10)
    corpo5 = r5.read().decode()
    print("GET /api/vault/google/callback (senza token, state inventato) ->", r5.status, "|", re.sub("<[^>]+>", "", corpo5).strip()[:60])
    ok5 = r5.status == 200 and "non valido" in corpo5
    r6 = urllib.request.Request(base + "/api/vault/stato", headers={"X-Token": token, "X-CC-Ponte": "1"})
    try:
        urllib.request.urlopen(r6, timeout=10)
        ok6 = False
    except urllib.error.HTTPError as e:
        ok6 = e.code == 403
    print("GET /api/vault/stato da un ponte internet (X-CC-Ponte) ->", "403" if ok6 else "NON rifiutato")
    esito = 0 if (ok1 and ok2 and ok3 and ok4 and ok5 and ok6) else 1
    print("ESITO:", "ok" if esito == 0 else "FALLITA")
    if arg.resta:
        print(f"\nServer di prova acceso: {base}/#vault  (casa finta {casa}) · Ctrl+C per fermarlo", flush=True)
        p.wait()
finally:
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
    errori = [r for r in log.read_text(errors="ignore").splitlines() if "vault" in r.lower() and ("Error" in r or "errore" in r)]
    if errori:
        print("righe del log con errori del Vault:", *errori[:5], sep="\n  ")
    for f in QUI.iterdir():
        if f.is_file() and f not in prima and f.suffix in (".json", ".jsonl", ".lock", ".log"):
            f.unlink()
    if not arg.casa:
        shutil.rmtree(casa, ignore_errors=True)
sys.exit(esito)
