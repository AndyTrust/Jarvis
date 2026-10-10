#!/usr/bin/env python3
"""Prova vera degli interruttori Volto e Mani del Command Center (deve essere acceso).

    python3 command-center/prova_interruttori.py

Per ognuno: acceso dal pannello → la scheda si apre; chiudo la scheda a mano (come l'utente)
→ il pannello spegne server e interruttore; riacceso → spento dal pannello → scheda chiusa
e server fermo. Più: l'interruttore della voce apre e chiude la finestra di Jarvis a voce.
Apre e chiude davvero le schede in Chrome; Mani accende la webcam per qualche secondo.
"""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7777"
PEZZI = {"volto": 8790, "mani": 8794}
esiti = []


TOKEN = None


def api(metodo, percorso, dati=None):
    req = urllib.request.Request(BASE + percorso, method=metodo, data=json.dumps(dati).encode() if dati else None,
                                 headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def stato(nome):
    return bool(api("GET", "/api/stato")[1].get("locale", {}).get(nome))


def schede(porta):
    out = subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to get URL of every tab of every window'],
                         capture_output=True, text=True).stdout
    return len(re.findall(rf"https?://(?:127\.0\.0\.1|localhost):{porta}\b", out))


def server(porta):
    return bool(subprocess.run(["lsof", "-ti", f"tcp:{porta}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.strip())


def chiudi_come_utente(porta):
    subprocess.run(["osascript", "-e", 'tell application "Google Chrome"\n repeat with w in windows\n'
                    f'  close (every tab of w whose URL starts with "http://127.0.0.1:{porta}")\n end repeat\nend tell'])


def aspetta(cond, secondi):
    fine = time.time() + secondi
    while time.time() < fine:
        if cond():
            return True
        time.sleep(1)
    return cond()


def prova(nome, ok, dettaglio=""):
    esiti.append(ok)
    print(f"{'ok     ' if ok else 'FALLITA'} {nome}" + (f" — {dettaglio}" if dettaglio and not ok else ""), flush=True)


def main():
    global TOKEN
    html = urllib.request.urlopen(BASE + "/", timeout=5).read().decode()
    m = re.search(r"TOKEN\s*=\s*[\"']([^\"']+)", html)
    if not m:
        sys.exit("Non trovo il token nella pagina del Command Center")
    TOKEN = m.group(1)
    for nome, porta in PEZZI.items():
        c, r = api("POST", "/api/azione", {"tipo": "interruttore", "nome": nome, "acceso": True})
        prova(f"{nome}: acceso dal pannello", c == 200, str(r))
        prova(f"{nome}: si apre UNA scheda", aspetta(lambda: schede(porta) == 1, 15), f"schede {schede(porta)}")
        prova(f"{nome}: interruttore acceso", aspetta(lambda: stato(nome), 10))
        chiudi_come_utente(porta)
        if nome == "volto":
            # dal 22/09/2026 il volto e il grafo sinapsi stanno DENTRO il pannello (iframe):
            # chiudere la scheda non deve spegnerli, se no il grafo della Home cade
            time.sleep(30)
            prova(f"{nome}: scheda chiusa a mano → resta acceso (grafo nel pannello)", stato(nome))
            prova(f"{nome}: … e il server resta vivo", server(porta))
        else:
            # dal 26/09/2026 si spegne dopo 3 letture certe di fila senza la scheda, una ogni 15 s
            prova(f"{nome}: scheda chiusa a mano → interruttore spento",
                  aspetta(lambda: not stato(nome), 75))
            prova(f"{nome}: … e server fermato", aspetta(lambda: not server(porta), 10))
        c, r = api("POST", "/api/azione", {"tipo": "interruttore", "nome": nome, "acceso": True})
        aspetta(lambda: schede(porta) == 1 and stato(nome), 15)
        c, r = api("POST", "/api/azione", {"tipo": "interruttore", "nome": nome, "acceso": False})
        prova(f"{nome}: spento dal pannello", c == 200, str(r))
        prova(f"{nome}: … scheda chiusa", aspetta(lambda: schede(porta) == 0, 10), f"schede {schede(porta)}")
        prova(f"{nome}: … server fermato", aspetta(lambda: not server(porta), 10))
        prova(f"{nome}: … interruttore spento", aspetta(lambda: not stato(nome), 10))
    # La voce è tornata per decisione dell'utente del 19/09/2026 22:09: l'interruttore deve
    # funzionare, non dare errore. Si accende e si rispegne, per non lasciare finestre aperte.
    def backtalk_vivo():
        return bool(subprocess.run(["pgrep", "-f", "backtalk.main"], capture_output=True, text=True).stdout.strip())

    c, r = api("POST", "/api/azione", {"tipo": "interruttore", "nome": "voce", "acceso": True})
    prova("voce: l'interruttore la accende", c == 200 and "voce" in str(r.get("messaggio", "")).lower(), str(r))
    # Si aspetta che sia DAVVERO partita prima di spegnere: apre un Terminale e poi «uv run»,
    # e ci mette qualche secondo. Spegnendo subito non c'era ancora niente da chiudere e la
    # prova accusava il pannello di un difetto che non ha.
    partita = aspetta(backtalk_vivo, 45)
    prova("voce: backtalk parte davvero", partita, "non si è vista partire in 45 secondi")
    c, r = api("POST", "/api/azione", {"tipo": "interruttore", "nome": "voce", "acceso": False})
    prova("voce: e la rispegne", c == 200 and "spenta" in str(r.get("messaggio", "")).lower(), str(r))
    if partita:
        prova("voce: non resta backtalk acceso", aspetta(lambda: not backtalk_vivo(), 20))
    # il volto serve al grafo sinapsi della Home: la prova lo lascia acceso com'era
    api("POST", "/api/azione", {"tipo": "interruttore", "nome": "volto", "acceso": True})
    print(f"\n{sum(esiti)}/{len(esiti)} prove passate")
    sys.exit(0 if all(esiti) else 1)


if __name__ == "__main__":
    main()
