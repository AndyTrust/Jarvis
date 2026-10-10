#!/usr/bin/env python3
"""Allarme servizi: i siti e i servizi della VPS rispondono? (2026-10-05, programmatore-notifiche)

Prende il posto del workflow n8n «Jarvis · Allarme servizi (ogni 15 minuti)», che scriveva all'utente su Telegram.
Decisione dell'utente del 05/10/2026: gli avvisi arrivano nel filo «Notifiche Jarvis» del Command Center
(strumenti/notifica.py), Telegram solo di riserva.

Stessi controlli e stessa regola di n8n: GET con 15 s di tempo, giù = nessuna risposta, 404 o 5xx.
Differenza: avvisa al CAMBIO (un servizio cade, un servizio torna su), non ogni 15 minuti finché resta giù.
Stato in /root/.locale-onedrive/jarvis-cc/allarme-servizi.json (o ALLARME_SERVIZI_STATO).

    python3 strumenti/allarme_servizi.py            controlla e avvisa ai cambi (timer jarvis-allarme-servizi)
    python3 strumenti/allarme_servizi.py --prova    stampa soltanto
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVIZI = [("CRM Azienda Uno", "https://crm.esempio.it/web/login"),
           ("CRM Azienda Due", "https://crm2.esempio.it/web/login"),
           ("n8n Azienda Due", "https://n8n.esempio.it/healthz"),
           ("n8n Jarvis", "https://vps.esempio.it/healthz"),
           ("Licenze Jarvis", "https://vps.esempio.it/salute"),
           ("Ponte telefono", "https://vps.esempio.it/health")]
STATO = Path(os.environ.get("ALLARME_SERVIZI_STATO") or Path.home() / ".locale-onedrive" / "jarvis-cc" / "allarme-servizi.json")


def prova_uno(url):
    t0 = time.time()
    codice = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "jarvis-allarme"}), timeout=15) as r:
            codice = r.status
    except urllib.error.HTTPError as e:
        codice = e.code
    except Exception:  # noqa: BLE001
        codice = 0
    return codice, int((time.time() - t0) * 1000)


def main():
    prova = "--prova" in sys.argv
    esiti = []
    for nome, url in SERVIZI:
        codice, ms = prova_uno(url)
        esiti.append({"nome": nome, "codice": codice, "ms": ms, "ok": 0 < codice < 500 and codice != 404})
    righe = [f"{'🟢' if e['ok'] else '🔴'} {e['nome']}: {e['codice'] or 'nessuna risposta'} ({e['ms']} ms)" for e in esiti]
    if prova:
        print("\n".join(righe))
        return 0
    try:
        prima = json.loads(STATO.read_text())
    except (OSError, ValueError):
        prima = {}
    adesso = {e["nome"]: e["ok"] for e in esiti}
    caduti = [n for n, ok in adesso.items() if not ok and prima.get(n, True)]
    tornati = [n for n, ok in adesso.items() if ok and prima.get(n) is False]
    STATO.parent.mkdir(parents=True, exist_ok=True)
    STATO.write_text(json.dumps(adesso))
    if not caduti and not tornati:
        print("niente di nuovo: " + ", ".join(f"{n} {'ok' if ok else 'giù'}" for n, ok in adesso.items()))
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from notifica import notifica
    titolo = ("Servizio giù: " + ", ".join(caduti)) if caduti else ("Tornato su: " + ", ".join(tornati))
    esito = notifica("jarvis", titolo, "\n".join(righe), chiave=f"allarme-{time.strftime('%Y%m%d%H%M')}")
    print(titolo, "→", esito.get("dove"))
    return 0 if esito.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
