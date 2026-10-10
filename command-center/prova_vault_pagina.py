#!/usr/bin/env python3
"""Pannello di prova del Vault: la pagina #vault da sola, su una porta libera, con una CASA FINTA.

    python3 command-center/prova_vault_pagina.py [--porta 7811] [--casa /percorso/finto]

Serve static/vault.js e vault.css dentro una pagina minima con la stessa struttura del Command Center (menu .schede.menu,
<main>, sezioni .vista, app.css e temi.css per i colori veri) e passa /api/vault/* a vault_cc.py. Così si prova la pagina
con il browser senza riavviare il Command Center vero e senza toccare la casa vera; ed è anche la prova che i tre file
del Vault funzionano da soli (Vault vuoto).
Prima di partire imposta HOME, USERPROFILE, APPDATA, XDG_* e tutti i JARVIS_VAULT_* dentro la casa finta; su macOS crea un
portachiavi usa-e-getta (mai il Portachiavi di login). Rifiuta di partire se la casa finta sta nella casa vera.
Porta vietata: 7777 (il Command Center vero).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

QUI = Path(__file__).resolve().parent
VIETATE = {7777}

a = argparse.ArgumentParser()
a.add_argument("--porta", type=int, default=7811)
a.add_argument("--casa", default="")
a.add_argument("--file-vero", default="", help="un file .env FINTO da mostrare come «file vero» (sola lettura)")
a.add_argument("--file-prova", default="", help="la copia di prova (dati finti), scrivibile")
a.add_argument("--google-finto", type=int, default=0, help="porta dell'emittente OIDC finto (prova_vault_google.py)")
arg = a.parse_args()
if arg.porta in VIETATE:
    sys.exit(f"porta {arg.porta} vietata: è di un servizio vero")
casa_vera = Path(os.path.expanduser("~")).resolve()
casa = Path(arg.casa or tempfile.mkdtemp(prefix="vault-pagina-")).resolve()
if casa == casa_vera or casa_vera in casa.parents:
    sys.exit("la casa finta non può stare dentro la casa vera")
casa.mkdir(parents=True, exist_ok=True)
os.environ.update({"HOME": str(casa), "USERPROFILE": str(casa), "APPDATA": str(casa / "AppData" / "Roaming"),
                   "LOCALAPPDATA": str(casa / "AppData" / "Local"), "XDG_CONFIG_HOME": str(casa / ".config"),
                   "XDG_DATA_HOME": str(casa / ".local" / "share"), "XDG_CACHE_HOME": str(casa / ".cache"),
                   "XDG_STATE_HOME": str(casa / ".local" / "state"),
                   "JARVIS_VAULT_DIR": str(casa / "dati" / "vault"),
                   "JARVIS_VAULT_ENV_VERO": arg.file_vero or str(casa / ".env.jarvis"),
                   "JARVIS_VAULT_ENV_PROVA": arg.file_prova or str(casa / "prova" / "env.jarvis.prova"),
                   "JARVIS_VAULT_PROFILO": str(QUI.parent / "profilo-jarvis.md")})
if Path.home().resolve() != casa:
    sys.exit("Path.home() non è la casa finta: mi fermo")
if arg.google_finto:
    os.environ.update({"JARVIS_VAULT_PROVA": "1", "JARVIS_VAULT_OIDC_EMITTENTE": f"http://127.0.0.1:{arg.google_finto}"})
if sys.platform == "darwin":
    kc = casa / "prova.keychain-db"
    if not kc.exists():
        subprocess.run(["security", "create-keychain", "-p", "prova-vault", str(kc)], check=True, capture_output=True)
        subprocess.run(["security", "set-keychain-settings", str(kc)], check=True, capture_output=True)
    subprocess.run(["security", "unlock-keychain", "-p", "prova-vault", str(kc)], check=True, capture_output=True)
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = str(kc)
else:
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = "file"

sys.path.insert(0, str(QUI))
import vault_cc as vault  # noqa: E402

TOKEN = "prova-pagina"
PAGINA = """<!doctype html>
<html lang="it" data-tema="scuro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vault · prova</title>
<link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/static/vault.css"><link rel="stylesheet" href="/static/temi.css">
<style>body{display:flex;flex-direction:column;background:var(--fondo);color:var(--testo)} .schede.menu{flex:none;display:flex;gap:8px;padding:8px 16px;align-items:center;flex-wrap:wrap}
.schede.menu a{color:inherit} #prova-temi{margin-left:auto;display:flex;gap:6px} #prova-temi button{min-height:32px}</style>
<script>window.CC_TOKEN = "__TOKEN__";</script></head>
<body><nav class="schede menu"><a href="#chat" data-vista="chat">Chat</a>
<span id="prova-temi"><button type="button" data-t="chiaro">Chiaro</button><button type="button" data-t="scuro">Scuro</button></span></nav>
<main><section class="vista" data-vista="chat"><p style="padding:16px">Pannello di prova del Vault. Apri «Vault».</p></section></main>
<script>
const TITOLI = { chat: "Chat" };
function mostraVista() { const b = (location.hash || "#chat").slice(1).split("/")[0];
  for (const s of document.querySelectorAll(".vista")) s.classList.toggle("attiva", s.dataset.vista === b);
  for (const a of document.querySelectorAll(".menu a")) a.classList.toggle("attiva", a.dataset.vista === b); }
window.addEventListener("hashchange", mostraVista); document.addEventListener("DOMContentLoaded", mostraVista);
document.querySelectorAll("#prova-temi button").forEach((b) => b.addEventListener("click", () => document.documentElement.dataset.tema = b.dataset.t));
</script>
<script src="/static/vault.js" defer></script>
</body></html>"""
TIPI = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}


class Gestore(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):      # solo metodo, percorso senza query, codice: mai corpi né valori
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def _invia(self, codice, corpo, tipo="application/json; charset=utf-8"):
        dati = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._invia(200, PAGINA.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            f = (QUI / "static" / p[8:]).resolve()
            if (QUI / "static") in f.parents and f.is_file() and f.suffix in TIPI:
                return self._invia(200, f.read_bytes(), TIPI[f.suffix])
            return self._invia(404, {"errore": "non trovato"})
        if p.startswith("/api/vault/"):
            if self.headers.get("X-Token") != TOKEN and p != "/api/vault/google/callback":
                return self._invia(403, {"errore": "token"})
            return self._invia(*vault.gestisci("GET", p, parse_qs(urlsplit(self.path).query), {}, self.headers))
        return self._invia(404, {"errore": "non trovato"})

    def do_POST(self):
        p = self.path.split("?")[0]
        if not p.startswith("/api/vault/") or self.headers.get("X-Token") != TOKEN:
            return self._invia(403, {"errore": "non ammesso"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._invia(400, {"errore": "JSON non valido"})
        return self._invia(*vault.gestisci("POST", p, {}, corpo, self.headers))


print(f"Vault di prova su http://127.0.0.1:{arg.porta}/#vault · casa finta {casa}", flush=True)
ThreadingHTTPServer(("127.0.0.1", arg.porta), Gestore).serve_forever()
