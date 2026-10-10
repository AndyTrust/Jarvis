#!/usr/bin/env python3
"""Prova del riquadro «Chiavi e da guardare» del Command Center (scheda Squadra).

    python3 prova_chiavi.py        esce con 1 se qualcosa non torna

Non apre il browser e non accende niente: guarda i tre file della pagina e il
dato che il server manda. Quello che deve restare vero:

  1. il riquadro c'è, dentro la Squadra (#agenti), con i quattro posti che la pagina riempie;
  2. app.js li riempie davvero, da s.portiere del server nuovo o, col server
     vecchio, dal battito (memoria.battito.portiere);
  3. **nessun bottone toglie una chiave a chi lavora**: dal 26/09/2026 (richiesta
     dell'utente) il riquadro ha «Chiedi a Jarvis: chi è?» e «Ritira i fantasmi», e
     basta. Il ritiro vale solo per le prese dei processi già morti (FANTASMA):
     toglierla a un agente vivo gli romperebbe il lavoro, e quella resta una
     decisione di Jarvis, non di un clic;
  4. il dato arriva sul serio — `battito()` di server.py restituisce tutto
     `sincro/ultimo.json`, chiave «portiere» compresa.
"""
import json
import re
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
AGENTE = QUI.parent
HTML = (QUI / "static/index.html").read_text()
JS = (QUI / "static/app.js").read_text()
CSS = (QUI / "static/app.css").read_text()

sbagli = []


def prova(nome, vero):
    print(("ok      " if vero else "SBAGLIATO ") + nome)
    if not vero:
        sbagli.append(nome)


# ── 1. il riquadro è nella pagina, dentro la Squadra ────────────────────────
vista = re.search(r'<section class="vista" data-vista="agenti">(.*?)\n    </section>', HTML, re.S)
prova("la vista «agenti» (Squadra) esiste", bool(vista))
riquadro = re.search(r'<section class="pannello chiavi-riq"[^>]*>(.*?)</section>',
                     vista.group(1) if vista else "", re.S)
prova("il riquadro «Chiavi» è dentro la Squadra", bool(riquadro))
dentro = riquadro.group(1) if riquadro else ""

for posto in ("chiavi-quando", "chiavi-giro", "chiavi-guardare", "chiavi-note"):
    prova(f"c'è il posto {posto}", f'id="{posto}"' in dentro)

# ── 2. app.js lo riempie, dal portiere o dal battito ────────────────────────
prova("app.js ha disegnaChiavi", "function disegnaChiavi(" in JS)
prova("disegnaChiavi viene chiamata col portiere", "disegnaChiavi(portiere" in JS)
prova("legge s.portiere (server nuovo)", "s.portiere" in JS)
prova("legge la chiave «portiere» del battito (server vecchio)", "b.portiere" in JS)
for posto in ("chiavi-quando", "chiavi-giro", "chiavi-guardare", "chiavi-note"):
    prova(f"app.js riempie {posto}", f'$("{posto}")' in JS)
prova("il CSS del riquadro c'è", ".chiavi-note" in CSS and ".chiavi-riq" in CSS)

# ── 3. nessun bottone toglie una chiave a chi lavora ────────────────────────
for vietato in ("<form", "<input", "<select", 'class="switch"'):
    prova(f"nel riquadro non c'è {vietato}", vietato not in dentro)
prova("nel riquadro l'unico bottone fisso è «Chiedi a Jarvis»",
      all("data-chiedi=" in b for b in re.findall(r"<button[^>]*>", dentro)))
funzione = re.search(r"function disegnaChiavi\(p, perche\) \{(.*?)\n\}", JS, re.S)
prova("disegnaChiavi si legge tutta", bool(funzione))
corpo = funzione.group(1) if funzione else ""
for vietato in ("azione(", "api(", "onclick", "addEventListener"):
    prova(f"disegnaChiavi non usa {vietato}", vietato not in corpo)
prova("«Ritira i fantasmi» compare solo sulle righe FANTASMA", 'tipo === "FANTASMA" ? el("button"' in corpo)
azioni_portiere = re.findall(r'tipo: "portiere", cosa: "(\w+)"', JS)
prova("l'unica azione del portiere è ritira_fantasmi", azioni_portiere == ["ritira_fantasmi"])

# ── 4. il dato esiste davvero ───────────────────────────────────────────────
# server.py non è stato toccato: `battito()` restituisce tutto ultimo.json, e
# «portiere» è già dentro. Se un giorno qualcuno lo filtrasse, il riquadro
# resterebbe muto e nessuno se ne accorgerebbe: meglio che lo dica una prova.
SERVER = (QUI / "server.py").read_text()
prova("server.py restituisce tutto ultimo.json nel battito",
      'leggi_json(AGENTE / "sincro/ultimo.json"' in SERVER)
ultimo = AGENTE / "sincro/ultimo.json"
if ultimo.exists():
    d = json.loads(ultimo.read_text())
    p = d.get("portiere")
    prova("ultimo.json ha la chiave «portiere»", isinstance(p, dict))
    if isinstance(p, dict):
        prova("«portiere» ha chiavi, da_guardare e note",
              {"chiavi", "da_guardare", "note"} <= set(p))
else:
    print("saltata  ultimo.json non c'è ancora (il battito non è mai passato)")

print(f"\nprove: {len(sbagli)} sbagliate" if sbagli else "\n✅ tutte passate")
sys.exit(1 if sbagli else 0)
