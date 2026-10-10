#!/usr/bin/env python3
"""Aggiornamento mensile degli agenti: chi è scaduto, l'incarico per il ricercatore, la risposta nel profilo.

Una volta al mese ogni specialista deve rimettersi in pari sulla sua materia (norme,
strumenti, API, pratiche) e sul progetto su cui lavora. Il risultato finisce nel suo
profilo, sezione «## Aggiornamento della materia», così alla chiamata dopo parte già
aggiornato.

Questo programma non chiama nessun modello e non apre internet: conta i giorni, scrive
l'incarico e incolla la risposta. A cercare è il `ricercatore-web`, lanciato da Jarvis
con l'incarico preparato qui.

Uso:
  python3 strumenti/aggiorna_agenti.py elenco            chi è scaduto e chi no
  python3 strumenti/aggiorna_agenti.py elenco --json     lo stesso, per il Command Center
  python3 strumenti/aggiorna_agenti.py prepara           un incarico per ogni scaduto
  python3 strumenti/aggiorna_agenti.py prepara <nome>    solo per quell'agente
  python3 strumenti/aggiorna_agenti.py prepara --tutti   anche per quelli ancora in corso
  python3 strumenti/aggiorna_agenti.py applica <nome|percorso> <risposta.md>
  python3 strumenti/aggiorna_agenti.py avviso            una riga sola, muto se va tutto bene

`elenco` esce 1 se c'è almeno un agente scaduto, 0 altrimenti. `avviso` esce sempre 0:
lo chiama il gancio di sessione e non deve mai fermare l'apertura di una chat.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

HOME = Path.home()
MY_AGENT = Path(__file__).resolve().parent.parent
INDICE_PROGETTI = HOME / ".ai-memory/global/projects-index.md"
LAVORO = MY_AGENT / "strumenti/aggiornamenti-agenti"
STORICO = LAVORO / "storico"
SEZIONE = "## Aggiornamento della materia"
GIORNI = 30


# ---------------------------------------------------------------- lettura

def cartelle_progetti():
    """Le cartelle dei progetti: da command-center/spazi.json, la stessa fonte del Command
    Center e della mappa degli agenti. L'indice vecchio solo se spazi.json non c'è."""
    try:
        sys.path.insert(0, str(MY_AGENT / "command-center"))
        import spazi as spazi_mod
        dentro = [(p["nome"], Path(p["cartella"])) for s in spazi_mod.carica()
                  for p in s["progetti"] if p.get("esiste")]
        if dentro:
            return dentro
    except Exception:
        pass
    fuori = []
    if not INDICE_PROGETTI.exists():
        return fuori
    for riga in INDICE_PROGETTI.read_text(encoding="utf-8").splitlines():
        if not riga.startswith("|") or "`" not in riga:
            continue
        celle = [c.strip() for c in riga.strip("|").split("|")]
        if len(celle) < 2:
            continue
        percorsi = re.findall(r"`([^`]+)`", celle[1])
        if not percorsi:
            continue
        nome = re.sub(r"\*\*|\(.*?\)", "", celle[0]).strip()
        fuori.append((nome, Path(percorsi[0].strip().rstrip("/").replace("~", str(HOME), 1))))
    return fuori


def frontmatter(testo):
    """Il blocco fra i due `---` in cima, come dizionario chiave: valore."""
    if not testo.startswith("---"):
        return {}, testo
    fine = testo.find("\n---", 3)
    if fine == -1:
        return {}, testo
    campi = {}
    for riga in testo[3:fine].splitlines():
        if ":" in riga and not riga.startswith(" "):
            k, _, v = riga.partition(":")
            campi[k.strip()] = v.strip()
    return campi, testo[fine + 4:]


def leggi_profilo(percorso, progetto):
    testo = percorso.read_text(encoding="utf-8")
    campi, corpo = frontmatter(testo)
    quando = campi.get("aggiornato-il", "").strip()
    try:
        data = dt.date.fromisoformat(quando) if quando else None
    except ValueError:
        data = None
    oggi = dt.date.today()
    eta = (oggi - data).days if data else None
    return {
        # una skill si chiama come la sua cartella: `SKILL` non direbbe niente
        "nome": campi.get("name") or (percorso.parent.name if percorso.name == "SKILL.md" else percorso.stem),
        "file": str(percorso),
        "progetto": progetto,
        "modello": campi.get("model", "—"),
        "descrizione": campi.get("description", "").strip(),
        "aggiornato_il": quando or None,
        "giorni": eta,
        "scaduto": eta is None or eta > GIORNI,
        "corpo": corpo,
    }


def file_profilo(cartella):
    """I profili di una cartella `.claude/agents/`, più le skill `azd-*` di Azienda Due, che
    stanno in `.claude/skills/<nome>/SKILL.md` e fanno lo stesso mestiere degli specialisti."""
    file = sorted(cartella.glob("*.md"))
    skill = cartella.parent / "skills"
    if skill.is_dir():
        file += sorted(s / "SKILL.md" for s in skill.iterdir()
                       if s.is_dir() and (s / "SKILL.md").exists())
    return file


def tutti_gli_agenti():
    """Tutti i profili: quelli di my-agent e quelli di ogni progetto dell'indice."""
    fonti = [("Jarvis", MY_AGENT / ".claude/agents")]
    fonti += [(nome, c / ".claude/agents") for nome, c in cartelle_progetti()]
    agenti, visti, cartelle_viste = [], {}, set()
    for progetto, cartella in fonti:
        if not cartella.is_dir() or cartella.resolve() in cartelle_viste:
            continue            # ~/Jarvis e ~/my-agent sono la stessa cartella: una volta sola
        cartelle_viste.add(cartella.resolve())
        for f in file_profilo(cartella):
            a = leggi_profilo(f, progetto)
            if not a["descrizione"]:
                continue        # LEGGIMI e simili: non sono agenti
            if a["nome"] in visti:  # due progetti con lo stesso nome: si distinguono
                a["nome"] = f"{a['nome']}__{cartella.parent.parent.name}"
            visti[a["nome"]] = True
            agenti.append(a)
    return agenti


def trova(agenti, chi):
    """L'agente col nome dato, o il profilo al percorso dato (serve per le prove)."""
    p = Path(chi).expanduser()
    if p.suffix == ".md" and p.is_file():
        return leggi_profilo(p.resolve(), "(percorso diretto)")
    for a in agenti:
        if a["nome"] == chi or Path(a["file"]).stem == chi:
            return a
    return None


# ---------------------------------------------------------------- elenco

def comando_elenco(agenti, come_json):
    if come_json:
        print(json.dumps({
            "oggi": dt.date.today().isoformat(),
            "soglia_giorni": GIORNI,
            "totale": len(agenti),
            "scaduti": sum(1 for a in agenti if a["scaduto"]),
            "agenti": [{k: a[k] for k in
                        ("nome", "progetto", "modello", "aggiornato_il", "giorni", "scaduto", "file")}
                       for a in agenti],
        }, ensure_ascii=False, indent=1))
        return 1 if any(a["scaduto"] for a in agenti) else 0

    largo = max([len(a["nome"]) for a in agenti], default=10)
    progetto = None
    for a in sorted(agenti, key=lambda a: (a["progetto"], a["nome"])):
        if a["progetto"] != progetto:
            progetto = a["progetto"]
            print(f"\n{progetto}")
        if a["aggiornato_il"] is None:
            stato = "mai aggiornato"
        elif a["scaduto"]:
            stato = f"scaduto da {a['giorni'] - GIORNI} g (ultimo {a['aggiornato_il']})"
        else:
            stato = f"a posto, {GIORNI - a['giorni']} g alla scadenza"
        print(f"  {'✗' if a['scaduto'] else '✓'} {a['nome']:<{largo}}  {a['modello']:<7} {stato}")

    scaduti = sum(1 for a in agenti if a["scaduto"])
    print(f"\n{len(agenti)} agenti, {scaduti} da aggiornare (soglia {GIORNI} giorni, oggi {dt.date.today()}).")
    if scaduti:
        print("Incarichi per il ricercatore: python3 strumenti/aggiorna_agenti.py prepara")
    return 1 if scaduti else 0


def comando_avviso(agenti):
    """Una riga per il gancio di sessione. Muto quando non c'è niente da dire."""
    scaduti = [a for a in agenti if a["scaduto"]]
    if scaduti:
        nomi = ", ".join(a["nome"] for a in scaduti[:4])
        resto = f" e altri {len(scaduti) - 4}" if len(scaduti) > 4 else ""
        print(f"🗓 Aggiornamento mensile: {len(scaduti)} agenti da rimettere in pari ({nomi}{resto}). "
              f"Elenco: python3 strumenti/aggiorna_agenti.py elenco")
    return 0


# ---------------------------------------------------------------- prepara

def materiale_del_progetto(a):
    """Dove l'agente deve guardare dentro il progetto: memoria e file toccati di recente."""
    percorso = Path(a["file"])
    radice = percorso.parent.parent.parent  # <progetto>/.claude/agents/x.md -> <progetto>
    if percorso.name == "SKILL.md":       # <progetto>/.claude/skills/<nome>/SKILL.md
        radice = percorso.parent.parent.parent.parent
    righe = []
    memoria = radice / ".claude/memoria"
    if (memoria / "MEMORIA.md").exists():
        righe.append(f"- indice della memoria: `{memoria / 'MEMORIA.md'}`")
        recenti = sorted(memoria.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:6]
        for f in recenti:
            if f.name == "MEMORIA.md":
                continue
            quando = dt.date.fromtimestamp(f.stat().st_mtime)
            righe.append(f"  - `{f.name}` (toccato il {quando})")
    claude_md = radice / "CLAUDE.md"
    if claude_md.exists():
        righe.append(f"- istruzioni del progetto: `{claude_md}`")
    if not righe:
        righe.append(f"- il progetto non ha una `.claude/memoria/`: guarda i file di `{radice}`")
    return radice, righe


def testo_incarico(a):
    radice, materiale = materiale_del_progetto(a)
    da_quando = a["aggiornato_il"] or "mai (è il primo aggiornamento)"
    periodo = (f"dal {a['aggiornato_il']} a oggi" if a["aggiornato_il"]
               else "negli ultimi dodici mesi (è il primo aggiornamento)")
    ruolo = a["corpo"].strip().split("\n\n")[0].strip() if a["corpo"].strip() else ""
    return f"""# Incarico: aggiorna «{a['nome']}»

*Preparato il {dt.datetime.now():%Y-%m-%d %H:%M} da `strumenti/aggiorna_agenti.py`.*

Per il `ricercatore-web`. Lo lancia Jarvis. Non modificare nessun file: torna solo il
testo della sezione, nel formato in fondo. Lo incolla `aggiorna_agenti.py applica`.

## Chi è

- Nome: `{a['nome']}`
- Progetto: {a['progetto']}
- Profilo: `{a['file']}`
- Modello: {a['modello']}
- Ultimo aggiornamento della materia: {da_quando}

## Di cosa si occupa

{a['descrizione'] or '(il profilo non ha una descrizione)'}

{ruolo}

## Cosa devi cercare

**Fuori.** Cosa è cambiato nella sua materia {periodo}: norme e scadenze
italiane o europee che lo riguardano, versioni nuove degli strumenti e delle API che
usa, pratiche o modi di lavorare che sono cambiati, cose che ha smesso di funzionare.
Fonti primarie: il sito dell'ente, la Gazzetta Ufficiale, Normattiva, Agenzia delle
Entrate, INPS, la documentazione ufficiale del prodotto. Ogni riga porta il link e la
data in cui l'hai letta. Se in un campo non è cambiato niente, lo scrivi.

**Dentro.** Cosa è cambiato nel progetto su cui lavora:

{chr(10).join(materiale)}

Cartella del progetto: `{radice}`

Cerca le decisioni prese, gli errori da non ripetere e i file nuovi che cambiano il suo
lavoro. Leggi, non riassumere a memoria.

## Cosa restituisci

Solo questo, massimo 25 righe, senza cappello e senza saluti:

```markdown
### Fuori
- <cosa è cambiato, in una riga> · <link> · letto il {dt.date.today()}

### Nel progetto
- <cosa è cambiato> · `<file>`

### Cosa cambia per lui
- <cosa deve fare di diverso alla prossima chiamata>
```

Niente frasi da AI, verbo «è», fatto verificabile. Se una sezione è vuota, scrivi
«niente di nuovo» e basta.

Il testo lo metti nella risposta finale, non in un file: il `ricercatore-web` non ha lo
strumento per scrivere. A salvarlo e ad applicarlo con `aggiorna_agenti.py applica` è
Jarvis.
"""


def comando_prepara(agenti, chi, tutti):
    if chi:
        a = trova(agenti, chi)
        if not a:
            print(f"Agente «{chi}» non trovato. Prova con: elenco", file=sys.stderr)
            return 2
        scelti = [a]
    else:
        scelti = agenti if tutti else [a for a in agenti if a["scaduto"]]
    if not scelti:
        print("Nessun agente scaduto: niente da preparare.")
        return 0
    LAVORO.mkdir(parents=True, exist_ok=True)
    for a in scelti:
        f = LAVORO / f"{a['nome']}.md"
        f.write_text(testo_incarico(a), encoding="utf-8")
        print(f"scritto  {f}")
    print(f"\n{len(scelti)} {'incarico' if len(scelti) == 1 else 'incarichi'} in {LAVORO}. Si lanciano con il `ricercatore-web`, uno per volta.")
    return 0


# ---------------------------------------------------------------- applica

def metti_sezione(corpo, contenuto, oggi):
    """Rimpiazza «## Aggiornamento della materia» o la aggiunge in fondo."""
    nuova = f"{SEZIONE}\n\n*Rimesso in pari il {oggi}.*\n\n{contenuto.strip()}\n"
    righe = corpo.splitlines(keepends=True)
    inizio = next((i for i, r in enumerate(righe) if r.strip() == SEZIONE), None)
    if inizio is None:
        return corpo.rstrip("\n") + "\n\n" + nuova
    fine = len(righe)
    for i in range(inizio + 1, len(righe)):
        if righe[i].startswith("## "):
            fine = i
            break
    return "".join(righe[:inizio]) + nuova + ("\n" + "".join(righe[fine:]) if fine < len(righe) else "")


def metti_data(campi_testo, oggi):
    """Aggiorna o aggiunge `aggiornato-il:` nel frontmatter."""
    righe = campi_testo.splitlines()
    for i, r in enumerate(righe):
        if r.startswith("aggiornato-il:"):
            righe[i] = f"aggiornato-il: {oggi}"
            return "\n".join(righe)
    return "\n".join(righe + [f"aggiornato-il: {oggi}"])


def comando_applica(agenti, chi, risposta):
    a = trova(agenti, chi)
    if not a:
        print(f"Agente «{chi}» non trovato.", file=sys.stderr)
        return 2
    f_risposta = Path(risposta).expanduser()
    if not f_risposta.is_file():
        print(f"File della risposta non trovato: {f_risposta}", file=sys.stderr)
        return 2
    contenuto = f_risposta.read_text(encoding="utf-8").strip()
    if not contenuto:
        print("La risposta è vuota: non applico niente.", file=sys.stderr)
        return 2

    profilo = Path(a["file"])
    testo = profilo.read_text(encoding="utf-8")
    oggi = dt.date.today().isoformat()

    STORICO.mkdir(parents=True, exist_ok=True)
    copia = STORICO / f"{a['nome']}-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    # 🔴 shutil.copy2 porta con sé la data del profilo originale: «ls -lt» sullo
    # storico metteva in cima i file sbagliati, e la data vera restava solo nel
    # nome. La copia deve avere la data di quando è stata fatta.
    shutil.copy(profilo, copia)

    fine = testo.find("\n---", 3) if testo.startswith("---") else -1
    if fine == -1:
        print("Il profilo non ha il frontmatter: non lo tocco.", file=sys.stderr)
        return 2
    testa, corpo = testo[3:fine], testo[fine + 4:]
    nuovo = "---" + metti_data(testa, oggi) + "\n---\n" + metti_sezione(corpo, contenuto, oggi)
    profilo.write_text(nuovo, encoding="utf-8")

    print(f"profilo  {profilo}")
    print(f"copia    {copia}")
    print(f"data     aggiornato-il: {oggi}")

    # 🔴 Questo script cambia i profili e non tocca .claude/memoria/. Dopo il
    # giro del 19-20/09/2026 la memoria di Azienda Due è rimasta indietro di 14
    # ore e il controllo di sincronia ha segnalato «qualcuno ha lavorato e non
    # ha salvato». Non si vedeva perché lo script rispondeva bene e i profili
    # erano davvero aggiornati: mancava solo il salvataggio.
    # la cartella del progetto è quella che contiene il «.claude» del profilo,
    # sia per gli agenti (.claude/agents/x.md) sia per le skill (.claude/skills/x/SKILL.md)
    cartella = next((p.parent for p in profilo.parents if p.name == ".claude"), None)
    if cartella:
        print()
        print("⚠ la memoria del progetto NON è stata toccata. A fine giro:")
        print(f'  python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py "{cartella}" \\')
        print('    --salva --stato "..." --completato "..." --dafare "..."')
        print("  (senza, il battito dei 30 minuti segnerà il progetto come indietro)")
    return 0


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    e = sub.add_parser("elenco", help="chi è scaduto e chi no")
    e.add_argument("--json", action="store_true")
    pr = sub.add_parser("prepara", help="scrive gli incarichi per il ricercatore")
    pr.add_argument("agente", nargs="?")
    pr.add_argument("--tutti", action="store_true", help="anche quelli non ancora scaduti")
    ap = sub.add_parser("applica", help="mette la risposta nel profilo")
    ap.add_argument("agente")
    ap.add_argument("risposta")
    sub.add_parser("avviso", help="una riga per il gancio di sessione")
    a = p.parse_args()

    agenti = tutti_gli_agenti()
    if not agenti and a.comando != "applica":
        print("Nessun profilo trovato in .claude/agents/.", file=sys.stderr)
        return 0 if a.comando == "avviso" else 2
    if a.comando == "elenco":
        return comando_elenco(agenti, a.json)
    if a.comando == "avviso":
        return comando_avviso(agenti)
    if a.comando == "prepara":
        return comando_prepara(agenti, a.agente, a.tutti)
    return comando_applica(agenti, a.agente, a.risposta)


if __name__ == "__main__":
    sys.exit(main())
