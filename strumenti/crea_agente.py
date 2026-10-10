#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Crea uno specialista dentro un progetto, dal modello unico (command-center/modelli/agente.md).

Lo usa il capogruppo del progetto (o l'assistente, o il comando /nuovo-agente), uno alla volta:

    python3 strumenti/crea_agente.py "<progetto>" "<ruolo>" --missione "<cosa fa, in una frase>"
            [--modello haiku|sonnet|opus] [--strumenti "Read, Grep, Bash"] [--limiti "<cosa non fa>"]
            [--riporta-a <agente>] [--nome <nome-file>] [--programma] [--prova] [--json]
    python3 strumenti/crea_agente.py "<progetto>" "<nome>" --modifica [--missione …] [--modello …] [--strumenti …] [--limiti …]
    python3 strumenti/crea_agente.py "<progetto>" "<nome>" --togli        la scheda va in .claude/agents/_archivio/

Regole (controllate qui, non solo scritte):
  - un progetto ha sempre un capogruppo: senza, si rifiuta e dice di lanciare prima crea_progetto.py;
  - nessun agente senza missione chiara: almeno 25 caratteri e diversa dal ruolo;
  - modelli: haiku esegue, sonnet ricerca/testi/verifica (predefinito), opus solo programmazione
    (serve --programma oppure una missione che parla di codice);
  - idempotente: se l'agente c'è già con la stessa missione non si tocca; ogni scheda cambiata ha una copia .bak.
Scrive <cartella>/.claude/agents/<nome>.md, il quaderno <cartella>/.claude/memoria/agenti/<nome>.md e aggiunge
il nuovo nome alla riga «comunica» di chi lo coordina. Il Command Center se ne accorge da solo in 2 secondi.
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
REPO = QUI.parent
CC = REPO / "command-center"
sys.path.insert(0, str(QUI))
sys.path.insert(0, str(CC))
import crea_progetto as cp  # noqa: E402
import spazi as sp_mod  # noqa: E402

MODELLO = CC / "modelli" / "agente.md"
SEZIONE_CAPO = CC / "modelli" / "capogruppo-sezione.md"
NOME_OK = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PAROLE_CODICE = re.compile(r"programm|codice|sviluppa|script|refactor|debug|bug|software|app\b|api\b", re.I)
import quaderno  # noqa: E402
SEZIONI_QUADERNO = [titolo for _, titolo in quaderno.SEZIONI]


def componi(nome, missione, modello, progetto, spazio, capogruppo="", strumenti="", limiti="", ceo=False,
            tono=None, umorismo=None, serieta=None):
    """Il testo della scheda. progetto e spazio sono le voci di spazi.json."""
    cartella = cp._esp(progetto["cartella"])
    memoria = spazio.get("memoria") or ""
    memoria = str(Path(cp._esp(memoria)).parent / "Stato.md") if memoria else "Stato.md dello spazio"
    strumenti = " ".join(str(strumenti or "").split())
    limiti = " ".join(str(limiti or "").split())
    tono = tono or "diretto, chiaro"
    testo = MODELLO.read_text(encoding="utf-8").format(
        name=nome, description=missione, description_yaml=sp_mod.valore_yaml(missione), model=modello,
        tools=f" {strumenti}" if strumenti else "", tools_testo=strumenti or "tutti quelli della sessione",
        tono_yaml=sp_mod.valore_yaml(tono), umorismo=1 if umorismo is None else umorismo,
        serieta=2 if serieta is None else serieta, capogruppo=capogruppo or "l'assistente",
        limiti_yaml=sp_mod.valore_yaml(limiti) if limiti else '""', limiti=f"- {limiti}" if limiti else "- nessun limite in più oltre a quelli qui sotto",
        progetto=progetto["nome"], cartella=cp.corto(cartella), memoria=cp.corto(memoria) if memoria.startswith("/") else memoria,
        repo=cp.corto(REPO), creato=time.strftime("%Y-%m-%d %H:%M"))
    if not capogruppo:                       # il capogruppo non riporta a nessuno del progetto
        testo = testo.replace("comunica: l'assistente\nriporta_a: l'assistente\n", "comunica:\nriporta_a:\n")
        testo = re.sub(r"<!-- comunica-con:inizio.*?<!-- comunica-con:fine -->",
                       "<!-- comunica-con:inizio (scritto dalla lavagna del Command Center, non toccare a mano) -->\n"
                       "## Comunica con\n\nNessun collegamento ancora: crea gli specialisti e la lavagna li collega.\n"
                       "<!-- comunica-con:fine -->", testo, flags=re.S)
    if ceo:
        sez = SEZIONE_CAPO.read_text(encoding="utf-8").format(progetto=progetto["nome"], cartella=cp.corto(cartella),
                                                              repo=cp.corto(REPO))
        segno = "<!-- comunica-con:inizio"
        testo = testo.replace(segno, sez.lstrip("\n") + "\n" + segno, 1)
    return sp_mod.con_come_parla(testo)


def testo_quaderno(nome):
    righe = [f"# Quaderno di {nome}", "",
             "*Il diario dell'agente: lo legge all'avvio e lo aggiorna prima di chiudere (FATTO, DA FARE, ERRORI COMMESSI "
             "DA NON RIPETERE, una riga per voce con data e ora: `quaderno.py scrivi`). Si modifica anche dalla lavagna.*", ""]
    for t in SEZIONI_QUADERNO:
        righe += [f"## {t}", ""]
    return "\n".join(righe).rstrip("\n") + "\n"


def scrivi_agente(L, progetto, spazio, nome, missione, modello="sonnet", capogruppo="", ceo=False, strumenti="",
                  limiti=""):
    cartella = cp._esp(progetto["cartella"])
    agenti = cartella / ".claude" / "agents"
    f = agenti / f"{nome}.md"
    q = cartella / ".claude" / "memoria" / "agenti" / f"{nome}.md"
    if f.is_file():
        L.saltate.append(f"c'è già: {f}")
    else:
        L.scrivi(f, componi(nome, missione, modello, progetto, spazio, capogruppo, strumenti, limiti, ceo))
    L.scrivi(q, testo_quaderno(nome))
    if capogruppo:                           # chi coordina sa di averlo sotto (riga «comunica»)
        cf = agenti / f"{capogruppo}.md"
        if cf.is_file():
            t = cf.read_text(encoding="utf-8")
            campi, corpo = sp_mod.frontmatter(t)
            attuali = sp_mod.comunica_di(campi, "")
            if nome not in attuali:
                nuovi = attuali + [nome]
                t2, _ = sp_mod.aggiorna_frontmatter(t, {"comunica": ", ".join(nuovi)})
                t2 = re.sub(r"(<!-- comunica-con:inizio[^\n]*-->\n).*?(<!-- comunica-con:fine -->)",
                            lambda m: m.group(1) + "## Comunica con\n\nL'utente ha collegato questo agente ad altri nella "
                            f"lavagna del Command Center: comunica con {', '.join(nuovi)}.\n" + m.group(2), t2, flags=re.S)
                L.scrivi(cf, t2, sovrascrivi=True)
    return f


def _progetto(chi):
    d = cp.carica_spazi()
    s, p = cp.trova_progetto(d, chi)
    if not p:
        nomi = ", ".join(x["nome"] for y in d["spazi"] for x in y.get("progetti", [])) or "nessuno"
        raise SystemExit(f"progetto «{chi}» non trovato (progetti: {nomi}). Crealo con crea_progetto.py")
    return s, p


def controlla_missione(ruolo, missione):
    m = " ".join(str(missione or "").split())
    if len(m) < 25 or cp.slug(m) == cp.slug(ruolo):
        raise SystemExit("serve una missione chiara (almeno 25 caratteri, diversa dal ruolo): "
                         "cosa fa questo agente, su quali file, cosa consegna")
    return m


def controlla_modello(modello, missione, programma):
    if modello not in cp.MODELLI:
        raise SystemExit("modello: haiku, sonnet o opus")
    if modello == "opus" and not (programma or PAROLE_CODICE.search(missione)):
        raise SystemExit("opus si usa solo per programmare: aggiungi --programma se la missione è scrivere codice, "
                         "altrimenti usa sonnet")


def crea(progetto_chi, ruolo, missione, modello="sonnet", strumenti="", limiti="", riporta_a=None, nome=None,
         programma=False, prova=False):
    s, p = _progetto(progetto_chi)
    cartella = cp._esp(p["cartella"])
    capo = p.get("capogruppo")
    if not capo or not (cartella / ".claude" / "agents" / f"{capo}.md").is_file():
        raise SystemExit(f"«{p['nome']}» non ha un capogruppo: rilancia crea_progetto.py \"{p['nome']}\" (lo ricrea)")
    nome = cp.slug(nome or ruolo)
    if not NOME_OK.fullmatch(nome):
        raise SystemExit("nome dell'agente non valido")
    missione = controlla_missione(ruolo, missione)
    controlla_modello(modello, missione, programma)
    sopra = riporta_a or capo
    if not (cartella / ".claude" / "agents" / f"{sopra}.md").is_file():
        raise SystemExit(f"«{sopra}» non è un agente di {p['nome']}")
    tombe = cp.CC / "agenti-tolti.json"
    try:
        if nome in json.loads(tombe.read_text(encoding="utf-8")).get(p["id"], []):
            print(f"attenzione: «{nome}» era stato tolto dal proprietario; lo ricreo perché lo chiedi a mano")
    except (OSError, ValueError):
        pass
    L = cp.Lavoro(prova)
    f = cartella / ".claude" / "agents" / f"{nome}.md"
    if f.is_file():
        campi, _ = sp_mod.frontmatter(f.read_text(encoding="utf-8"))
        if " ".join(campi.get("description", "").split()) != missione:
            raise SystemExit(f"«{nome}» esiste già in {p['nome']} con un'altra missione: usa --modifica per cambiarla")
    scrivi_agente(L, p, s, nome, missione, modello, capogruppo=sopra, strumenti=strumenti, limiti=limiti)
    if L.fatte and not prova:
        cp.registra_azione(p["id"], f"agente creato: {nome} ({modello}, riporta a {sopra}) · missione: {missione[:120]}")
    return {"agente": nome, "progetto": p["nome"], "file": str(f), "modello": modello, "riporta_a": sopra,
            "fatte": L.fatte, "saltate": L.saltate, "prova": prova}


def modifica(progetto_chi, nome, missione=None, modello=None, strumenti=None, limiti=None, programma=False, prova=False):
    s, p = _progetto(progetto_chi)
    f = cp._esp(p["cartella"]) / ".claude" / "agents" / f"{cp.slug(nome)}.md"
    if not f.is_file():
        raise SystemExit(f"nessun agente «{nome}» in {p['nome']}")
    t = f.read_text(encoding="utf-8")
    campi, _ = sp_mod.frontmatter(t)
    if missione is not None:
        missione = controlla_missione(nome, missione)
    controlla_modello(modello or campi.get("model", "sonnet"), missione or campi.get("description", ""), programma)
    nuovo, cambiate = sp_mod.aggiorna_frontmatter(t, {"description": missione, "model": modello, "tools": strumenti,
                                                       "limiti": limiti})
    if missione is not None:                 # la missione sta anche nel corpo, sotto «## Missione»
        nuovo = re.sub(r"(## (?:Missione|Compito)\n\n).*?(\n\n)", lambda m: m.group(1) + missione + m.group(2), nuovo,
                       count=1, flags=re.S)
    if limiti is not None:
        nuovo = re.sub(r"(## Limiti\n\n)- .*?(\n)", lambda m: m.group(1) + f"- {limiti}" + m.group(2), nuovo, count=1)
    L = cp.Lavoro(prova)
    L.scrivi(f, nuovo, sovrascrivi=True)
    if L.fatte and not prova:
        cp.registra_azione(p["id"], f"agente modificato: {f.stem} ({', '.join(cambiate) or 'corpo'})")
    return {"agente": f.stem, "cambiate": cambiate, "fatte": L.fatte, "prova": prova}


def togli(progetto_chi, nome, prova=False):
    s, p = _progetto(progetto_chi)
    nome = cp.slug(nome)
    if nome == p.get("capogruppo"):
        raise SystemExit("il capogruppo non si toglie: un progetto ha sempre un capogruppo (archivia il progetto)")
    d = cp._esp(p["cartella"]) / ".claude" / "agents"
    f = d / f"{nome}.md"
    if not f.is_file():
        raise SystemExit(f"nessun agente «{nome}» in {p['nome']}")
    dst = d / "_archivio" / f"{nome}.md"
    if dst.exists():
        dst = dst.with_name(f"{nome}.{time.strftime('%Y%m%d-%H%M%S')}.md")
    if not prova:
        dst.parent.mkdir(exist_ok=True)
        shutil.move(str(f), str(dst))
        cp.registra_azione(p["id"], f"agente tolto: {nome} (scheda in .claude/agents/_archivio/)")
    return {"agente": nome, "fatte": [f"sposta {f} → {dst}"], "prova": prova}


def _opz(a, nome, predefinito=None):
    if nome in a:
        i = a.index(nome)
        if i + 1 >= len(a):
            raise SystemExit(f"{nome} vuole un valore")
        return a[i + 1]
    return predefinito


def main():
    a = sys.argv[1:]
    if len(a) < 2 or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    con_valore = {"--missione", "--modello", "--strumenti", "--limiti", "--riporta-a", "--nome"}
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in con_valore)]
    if len(pos) < 2:
        raise SystemExit("uso: crea_agente.py <progetto> <ruolo> --missione \"…\"")
    prova = "--prova" in a
    if "--togli" in a:
        r = togli(pos[0], pos[1], prova)
    elif "--modifica" in a:
        r = modifica(pos[0], pos[1], _opz(a, "--missione"), _opz(a, "--modello"), _opz(a, "--strumenti"),
                     _opz(a, "--limiti"), "--programma" in a, prova)
    else:
        r = crea(pos[0], pos[1], _opz(a, "--missione"), _opz(a, "--modello", "sonnet"), _opz(a, "--strumenti", ""),
                 _opz(a, "--limiti", ""), _opz(a, "--riporta-a"), _opz(a, "--nome"), "--programma" in a, prova)
    if "--json" in a:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"Agente «{r['agente']}» · {time.strftime('%Y-%m-%d %H:%M')}" + (" · PROVA: non scrivo niente" if prova else ""))
    for x in r.get("fatte", []):
        print(("  farei: " if prova else "  fatto: ") + x)
    if not r.get("fatte"):
        print("  niente da fare: è già tutto a posto")


if __name__ == "__main__":
    main()
