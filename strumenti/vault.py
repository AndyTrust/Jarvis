#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Gli agenti e il Vault: usare una voce senza mai vederla. Guida: docs/wiki/Vault.md.

Dove funziona: macOS (con "uso_agenti": true e "browser" nel config.json del Vault) e modo VPS (Linux, avanzato).
Su Windows NON c'è: il Vault di Windows si usa solo dalla pagina, a mano.

  vault.py usa "NOME DELLA VOCE" [--campo password|utente|mail] [--browser <nome>] [--selettore CSS] [--invio]
           [--attendi 330] [--chi <agente>]
  manda al Command Center di questa macchina SOLO il nome: il valore resta lì e finisce nel campo del browser
  (Chrome con la porta DevTools scritta in «browser») senza passare di qui. Il proprietario deve premere «Consenti»
  nella pagina Vault entro 5 minuti (nel modo VPS le voci di classe «servizio» passano subito); una richiesta alla
  volta. Il dominio ammesso lo decide la voce (Domini, Link): su un sito diverso non si scrive niente.
  Stampa solo l'esito (compilata, negata, scaduta, rifiutata, errore): mai il valore.
  Il campo password si compila solo in un <input type=password>. Sulle pagine di accesso di Google, Apple,
  Microsoft... (strumenti/vault-provider.json) solo una voce di quel dominio esatto, sempre con il «Consenti».
  Se dopo --invio il sito chiede verifica in due passaggi, passkey o captcha: esce con codice 6 e il messaggio
  «FERMATI»: l'agente si ferma e avvisa il proprietario.

  vault.py codice "NOME DELLA VOCE" [--selettore CSS] [--browser <nome>] [--invio] [--chi <agente>]
  il codice di verifica arrivato per MAIL (serve strumenti/posta.py con le tue caselle): il Command Center legge la
  casella scritta nella voce, solo mail degli ultimi 5 minuti dal dominio del sito, e lo scrive nel campo. Il codice
  non passa di qui. Aspetta il codice fino a 2,5 minuti.

LE CARTE NON SI USANO MAI: il Vault rifiuta ogni richiesta su una voce di tipo Carta. Un pagamento passa da un
servizio di pagamento, con la conferma del proprietario.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CC_URL = os.environ.get("JARVIS_CC_URL", "http://127.0.0.1:7777")
TOKEN_CC = Path(os.environ.get("JARVIS_CC_TOKEN_FILE") or (Path.home() / ".locale-onedrive" / "jarvis-cc" / "token-locale"))


def _cc(metodo, percorso, corpo=None):
    """Chiamata al Command Center locale (solo nomi ed esiti: le rotte dell'uso non restituiscono mai valori)."""
    dati = json.dumps(corpo).encode() if corpo is not None else None
    try:
        token = TOKEN_CC.read_text().strip()
    except OSError:
        sys.exit("Command Center spento o mai avviato su questa macchina (manca il token locale).")
    req = urllib.request.Request(CC_URL + percorso, data=dati, method=metodo, headers={
        "Content-Type": "application/json", "X-Token": token,
        "Host": CC_URL.split("//", 1)[-1].split("/", 1)[0]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"errore": f"risposta {e.code}"}


def usa(a, campo_fisso=None):
    if not a or a[0].startswith("--"):
        sys.exit("uso: vault.py usa \"NOME DELLA VOCE\" [--campo password] [--browser <nome>] [--selettore CSS] [--invio]")

    def opz(nome, predefinito=None):
        return a[a.index(nome) + 1] if nome in a and a.index(nome) + 1 < len(a) else predefinito
    corpo = {"nome": a[0], "campo": campo_fisso or opz("--campo", "password"), "browser": opz("--browser", ""),
             "selettore": opz("--selettore", ""), "invio": "--invio" in a, "chi": opz("--chi", "agente")}
    attendi = float(opz("--attendi", "500" if corpo["campo"] == "codice" else "330"))
    try:
        codice, r = _cc("POST", "/api/vault/uso/richiedi", corpo)
    except OSError as e:
        sys.exit(f"Command Center non raggiungibile ({type(e).__name__})")
    if codice != 200:
        sys.exit(f"rifiutato ({codice}): {r.get('errore', '')}")
    fine = time.time() + attendi
    avvisato = False
    while r.get("stato") in ("attesa", "in corso") and time.time() < fine:
        if r.get("stato") == "attesa" and not avvisato:
            print(f"in attesa del «Consenti» del proprietario (scade fra {r.get('scade_s', 0)} s)…", flush=True)
            avvisato = True
        if r.get("stato") == "in corso" and corpo["campo"] == "codice" and not avvisato:
            print("cerco il codice nella casella della voce…", flush=True)
            avvisato = True
        time.sleep(2)
        codice, r = _cc("GET", f"/api/vault/uso/stato?id={r['id']}")
        if codice != 200:
            sys.exit(f"stato non leggibile ({codice}): {r.get('errore', '')}")
    s = r.get("stato")
    if s == "compilata":
        print(f"compilata: «{r.get('nome')}» ({r.get('campo')}) su {r.get('host')}"
              f"{'' if r.get('verificato') else ' (lunghezza del campo non confermata)'}")
        if r.get("verifica"):
            cosa = {"due passaggi": "la verifica in due passaggi", "captcha": "un captcha (non sono un robot)",
                    "passkey": "una passkey"}.get(r["verifica"], r["verifica"])
            print(f"FERMATI: dopo l'invio il sito chiede {cosa}. Non aggirarlo: avvisa il proprietario.", flush=True)
            sys.exit(6)
        return
    sys.exit(f"{s}: {r.get('motivo') or 'nessun dettaglio'}")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "aiuto"):
        print(__doc__)
        return
    if sys.platform == "win32":
        sys.exit("Su Windows gli agenti non usano il Vault: apri la pagina Vault del Command Center e copia tu il valore.")
    if a[0] == "usa":
        usa(a[1:])
    elif a[0] == "codice":
        usa(a[1:], campo_fisso="codice")
    else:
        sys.exit("comando sconosciuto: " + a[0] + " (usa | codice)")


if __name__ == "__main__":
    main()
