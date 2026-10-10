#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Crea la memoria condivisa di Jarvis e ci collega Claude Code e gli altri harness.

    python3 strumenti/collega_memoria.py                    dice cosa farebbe, non scrive niente
    python3 strumenti/collega_memoria.py --applica          lo fa
    python3 strumenti/collega_memoria.py --applica --solo-progetti   collega solo le memorie di progetto nuove
Opzioni: --memoria DIR (dove tenerla), --risposte FILE (default ~/.jarvis/risposte-avvio.json), --senza-claude-md,
         --senza-cache. La casa è $HOME: per provarlo su una casa finta, HOME=/tmp/casa python3 ...

Cosa fa con --applica. Non cancella mai niente: chi c'è già viene unito o spostato in <nome>.bak-AAAAMMGG.
  1. crea <memoria>/ con Comune/, Diario/, Report/, Sessioni/, Claude/projects/ (le cartelle degli spazi le crea
     crea_progetto.py quando nasce un progetto);
  2. ~/.claude/projects/<progetto>/memory → <memoria>/Claude/projects/<progetto>/memory (collegamento simbolico).
     Se nella memoria c'è già una cartella con lo stesso nome, i file si UNISCONO: quelli uguali si saltano,
     quelli diversi si copiano accanto con il suffisso .da-questo-mac-AAAAMMGG e si dichiarano;
  3. la cache: si collega SOLO ~/.claude/cache/pdf-testo (testo estratto dai PDF dal gancio pdf_a_testo.py,
     riutilizzabile). Il resto di ~/.claude/cache (changelog, catalogo dei modelli, issue) e le cartelle
     transitorie (paste-cache, file-history, session-env, shell-snapshots, debug, sessions, todos) NON si toccano:
     Claude Code le riscrive di continuo e su una cartella sincronizzata farebbero conflitti;
     le sessioni *.jsonl restano in ~/.claude/projects: sono grandi, scritte mentre lavori, e possono contenere
     quello che incolli (anche chiavi). Nella memoria va il loro riassunto (Sessioni/, scritto dai ganci);
  4. ~/.claude/CLAUDE.md: la sorgente unica diventa <memoria>/Comune/CLAUDE.md e ~/.claude/CLAUDE.md la indica
     con un collegamento. Se esistono tutti e due e sono diversi, nessuno si perde (copia .da-questo-mac);
  5. per gli altri harness scelti scrive i file di ingresso che rimandano alla stessa memoria:
     ~/.codex/AGENTS.md (Codex), ~/.gemini/GEMINI.md (Gemini CLI), <memoria>/Comune/ISTRUZIONI-HARNESS.md
     (da incollare in Cursor, Grok o altri che non leggono un file globale). Blocco tra marcatori, file con backup;
  6. scrive ~/.jarvis/percorsi.json (memoria, repo, progetti, collegamenti): lo leggono i ganci, la skill
     aggiorna-memoria e il Command Center.
Uscita: 0 tutto a posto, 1 qualcosa da guardare (righe 🔴).
"""
import filecmp
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
QUI = Path(__file__).resolve().parents[1]
OGGI = time.strftime("%Y%m%d")
ADESSO = time.strftime("%Y-%m-%d %H:%M")
MARCA_INIZIO = "<!-- jarvis-memoria:inizio -->"
MARCA_FINE = "<!-- jarvis-memoria:fine -->"
CARTELLE_BASE = ("Comune", "Diario", "Report", "Sessioni", "Claude/projects", "Claude/cache")
HARNESS_FILE = {"codex": ".codex/AGENTS.md", "gemini": ".gemini/GEMINI.md"}


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


APPLICA = "--applica" in sys.argv
righe = []


def di(segno, testo):
    righe.append(f"{segno} {testo}")


def fa(testo):
    di("🟢" if APPLICA else "·", ("" if APPLICA else "farei: ") + testo)


def leggi_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scrivi_json(p, dati):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + f".bak-{OGGI}"))
    p.write_text(json.dumps(dati, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def espandi(v):
    return Path(os.path.expanduser(str(v).replace("~", str(HOME), 1) if str(v).startswith("~") else str(v)))


def libero(p):
    """Un nome di backup che non esiste ancora: p.bak-AAAAMMGG, poi -2, -3..."""
    c = p.with_name(p.name + f".bak-{OGGI}")
    n = 2
    while c.exists() or c.is_symlink():
        c = p.with_name(p.name + f".bak-{OGGI}-{n}")
        n += 1
    return c


# ---------------------------------------------------------------- 1. la memoria
def scegli_memoria(risposte, percorsi):
    v = opzione("--memoria") or os.environ.get("JARVIS_MEMORIA") or risposte.get("memoria") or percorsi.get("memoria")
    return espandi(v) if v else HOME / "Jarvis-Memoria"


STATO = """---
spazio: {spazio}
aggiornato: {ora}
---
# Stato · {spazio}

_Aggiornato da Jarvis il {ora}. I ganci di Claude Code riscrivono la parte tra i marcatori a fine sessione._

<!-- stato-auto:inizio -->
## FATTO
- (ancora niente)

## DA FARE
- (ancora niente)

## ERRORI DA NON RIPETERE
- (ancora niente)
<!-- stato-auto:fine -->

## Note
Scrivi qui a mano: i ganci non toccano questa parte.
"""

PORTA = """---
aggiornato: {ora}
---
# Memoria di {assistente}

Porta d'ingresso della memoria condivisa. Ogni harness (Claude Code, Codex, Gemini, Cursor...) parte da qui.

- Profilo e preferenze: [[Profilo]] (il nome con cui chiamarti sta anche in `profilo-jarvis.md` di Jarvis)
- Regole di lavoro: [[Regole]]
- Progetti: ogni spazio ha `<spazio>/Stato.md` (elenco: `python3 strumenti/crea_progetto.py --elenco`). {spazi}
- Diario: `Diario/` · Report: `Report/` · Sessioni: `Sessioni/`
- Memoria automatica di Claude Code: `Claude/projects/`

Regola: una sola fonte. Si corregge quello che non è più vero, non si aggiungono doppioni. Nessun segreto qui dentro.
"""


def crea_struttura(mem, spazi, profilo):
    nuove = 0
    for c in list(CARTELLE_BASE) + [s for s in spazi]:
        d = mem / c
        if not d.is_dir():
            nuove += 1
            if APPLICA:
                d.mkdir(parents=True, exist_ok=True)
    if nuove:
        fa(f"creo {nuove} cartelle in {mem}")
    else:
        di("🟢", f"struttura della memoria già pronta in {mem}")
    for s in spazi:
        st = mem / s / "Stato.md"
        if not st.exists():
            fa(f"scrivo {st}")
            if APPLICA:
                st.write_text(STATO.format(spazio=s, ora=ADESSO), encoding="utf-8")
    porta = mem / "Comune" / "Memoria.md"
    if not porta.exists():
        fa(f"scrivo la porta d'ingresso {porta}")
        if APPLICA:
            porta.write_text(PORTA.format(ora=ADESSO, assistente=profilo.get("nome_assistente") or "Jarvis",
                                          spazi=", ".join(f"[[{s}/Stato|{s}]]" for s in spazi) or "Nessun progetto ancora: nascono quando li nomini."),
                             encoding="utf-8")
    for nome, testo in (("Profilo.md", profilo_md(profilo)), ("Regole.md", REGOLE)):
        f = mem / "Comune" / nome
        if not f.exists():
            fa(f"scrivo {f}")
            if APPLICA:
                f.write_text(testo, encoding="utf-8")


REGOLE = """# Regole di lavoro

- Prove, non ipotesi: è fatto solo quello che è stato controllato con un comando o un file.
- Conferma prima dell'irreversibile: cancellare, pubblicare, scrivere in produzione, mandare messaggi.
- Un segreto non entra mai nella memoria né in git: le chiavi stanno in ~/.env.jarvis.
- Data e ora sempre, dal sistema (AAAA-MM-GG HH:MM).
- Una domanda alla volta, poi ci si ferma ad aspettare.
"""


def profilo_md(p):
    return (f"---\naggiornato: {ADESSO}\n---\n# Profilo\n\n"
            f"- Come chiamarlo: {p.get('come_chiamarti') or '(da chiedere)'}\n"
            f"- Nome dell'assistente: {p.get('nome_assistente') or 'Jarvis'}\n"
            f"- Lingua: {p.get('lingua') or 'italiano'} · Tono: {p.get('tono') or 'semplice e diretto'}\n"
            f"- Fuso orario: {p.get('fuso_orario') or '(da chiedere)'}\n"
            f"- Lavoro: {p.get('lavoro') or '(da chiedere)'}\n"
            f"- Cose da non toccare mai: {', '.join(p.get('mai_toccare') or []) or '(nessuna indicata)'}\n")


# ---------------------------------------------------------------- 2. memoria di Claude Code
def unisci_cartelle(src, dst, rapporto):
    """Copia in dst i file di src che mancano; quelli diversi accanto, con suffisso. Non cancella niente."""
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        t = dst / rel
        if not t.exists():
            rapporto["copiati"] += 1
            if APPLICA:
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, t)
        elif filecmp.cmp(f, t, shallow=False):
            rapporto["uguali"] += 1
        else:
            alt = t.with_name(f"{t.stem}.da-{socket.gethostname().split('.')[0] or 'questo-mac'}-{OGGI}{t.suffix}")
            rapporto["diversi"].append(str(rel))
            if APPLICA:
                shutil.copy2(f, alt)


def collega_cartella(locale, condivisa, etichetta):
    """locale (dentro ~/.claude) diventa un collegamento a condivisa; il contenuto si unisce, l'originale resta in .bak."""
    if locale.is_symlink():
        try:
            if locale.resolve() == condivisa.resolve():
                di("🟢", f"{etichetta}: già collegata")
                return
        except OSError:
            pass
        di("🟡", f"{etichetta}: {locale} è un collegamento verso un altro posto ({os.readlink(locale)}): non lo tocco")
        return
    rapporto = {"copiati": 0, "uguali": 0, "diversi": []}
    if locale.is_dir():
        if condivisa.is_dir() and any(condivisa.iterdir()):
            unisci_cartelle(locale, condivisa, rapporto)
            fa(f"{etichetta}: unisco {locale} con la memoria che c'era già ({rapporto['copiati']} nuovi, "
               f"{rapporto['uguali']} uguali, {len(rapporto['diversi'])} diversi tenuti accanto)")
            for r in rapporto["diversi"]:
                di("🟡", f"   file diverso nei due posti, tenuti tutti e due: {r}")
        else:
            unisci_cartelle(locale, condivisa, rapporto)
            fa(f"{etichetta}: copio {rapporto['copiati']} file in {condivisa}")
        bak = libero(locale)
        fa(f"{etichetta}: l'originale resta in {bak.name}, poi {locale} → {condivisa}")
        if APPLICA:
            locale.rename(bak)
    else:
        fa(f"{etichetta}: collego {locale} → {condivisa}")
    if APPLICA:
        condivisa.mkdir(parents=True, exist_ok=True)
        locale.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(condivisa, locale, target_is_directory=True)


def collega_progetti(mem):
    base = HOME / ".claude" / "projects"
    fatti = []
    if not base.is_dir():
        di("🟢", "Claude Code non ha ancora progetti: i ganci collegheranno quelli nuovi a fine sessione")
        return fatti
    for p in sorted(base.iterdir()):
        m = p / "memory"
        if not p.is_dir() or not (m.exists() or m.is_symlink()):
            continue
        collega_cartella(m, mem / "Claude" / "projects" / p.name / "memory", f"memoria di Claude «{p.name}»")
        fatti.append(p.name)
    if not fatti:
        di("🟢", "nessuna memoria automatica di Claude Code da collegare, per ora")
    return fatti


def collega_cache(mem):
    pdf = HOME / ".claude" / "cache" / "pdf-testo"
    collega_cartella(pdf, mem / "Claude" / "cache" / "pdf-testo", "cache dei PDF")


# ---------------------------------------------------------------- 4. CLAUDE.md sorgente unica
CLAUDE_GLOBALE = """# Istruzioni globali di {assistente}

{MARCA_INIZIO}
Sei {assistente}, l'assistente di {chi}. Parli {lingua}, tono {tono}. Fuso orario: {fuso}.
Il nome con cui chiamare l'utente sta in `profilo-jarvis.md` di Jarvis e in `{mem}/Comune/Profilo.md`: usa quello.
La memoria è una sola: `{mem}`. Porta d'ingresso: `{mem}/Comune/Memoria.md`. Aprila per prima.
Lo stato di ogni spazio è in `{mem}/<spazio>/Stato.md`; i ganci lo aggiornano a fine sessione.
Questo file è un collegamento: la sorgente è `{mem}/Comune/CLAUDE.md`, la stessa per ogni harness.
Non toccare mai: {mai}.
{MARCA_FINE}
"""


def blocco(profilo, mem):
    return CLAUDE_GLOBALE.format(assistente=profilo.get("nome_assistente") or "Jarvis",
                                 chi=profilo.get("come_chiamarti") or "l'utente",
                                 lingua=profilo.get("lingua") or "italiano", tono=profilo.get("tono") or "semplice",
                                 fuso=profilo.get("fuso_orario") or "quello del sistema", mem=mem,
                                 mai=", ".join(profilo.get("mai_toccare") or []) or "niente di indicato",
                                 MARCA_INIZIO=MARCA_INIZIO, MARCA_FINE=MARCA_FINE)


def claude_md_unico(mem, profilo):
    sorgente = mem / "Comune" / "CLAUDE.md"
    locale = HOME / ".claude" / "CLAUDE.md"
    if locale.is_symlink():
        ok = False
        try:
            ok = locale.resolve() == sorgente.resolve()
        except OSError:
            pass
        di("🟢" if ok else "🟡", f"~/.claude/CLAUDE.md è già un collegamento ({'alla memoria' if ok else os.readlink(locale) + ': non lo tocco'})")
        return
    testo_locale = locale.read_text(encoding="utf-8") if locale.is_file() else ""
    if not sorgente.exists():
        nuovo = (testo_locale.rstrip() + "\n\n" if testo_locale else "") + (blocco(profilo, mem) if MARCA_INIZIO not in testo_locale else "")
        fa(f"la sorgente unica {sorgente} nasce " + ("dal tuo ~/.claude/CLAUDE.md, con in più il blocco della memoria" if testo_locale else "nuova"))
        if APPLICA:
            sorgente.parent.mkdir(parents=True, exist_ok=True)
            sorgente.write_text(nuovo, encoding="utf-8")
    elif testo_locale and testo_locale != sorgente.read_text(encoding="utf-8"):
        alt = sorgente.with_name(f"CLAUDE.da-{socket.gethostname().split('.')[0] or 'questo-mac'}-{OGGI}.md")
        fa(f"~/.claude/CLAUDE.md è diverso da quello nella memoria: lo tengo in {alt.name} da unire a mano")
        di("🟡", f"   da unire a mano: {alt}")
        if APPLICA:
            alt.write_text(testo_locale, encoding="utf-8")
    if locale.exists():
        bak = libero(locale)
        fa(f"~/.claude/CLAUDE.md resta in {bak.name}, poi diventa un collegamento a {sorgente}")
        if APPLICA:
            locale.rename(bak)
    else:
        fa(f"~/.claude/CLAUDE.md → {sorgente}")
    if APPLICA:
        locale.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(sorgente, locale)


# ---------------------------------------------------------------- 5. altri harness
def ingresso_harness(mem, harness):
    testo = (f"{MARCA_INIZIO}\n## Memoria condivisa di Jarvis\n"
             f"Le istruzioni comuni sono in `{mem}/Comune/CLAUDE.md` e la memoria in `{mem}`.\n"
             f"Leggi prima `{mem}/Comune/Memoria.md`, poi lo `Stato.md` dello spazio in cui lavori.\n"
             f"Scrivi lo stato dei progetti in `{mem}/<spazio>/Stato.md`, mai segreti.\n{MARCA_FINE}\n")
    for h in harness:
        h = h.lower().strip()
        if h in HARNESS_FILE:
            f = HOME / HARNESS_FILE[h]
            attuale = f.read_text(encoding="utf-8") if f.is_file() else ""
            if MARCA_INIZIO in attuale:
                di("🟢", f"{f} rimanda già alla memoria")
                continue
            fa(f"aggiungo a {f} il rimando alla memoria" + (" (copia .bak prima)" if attuale else ""))
            if APPLICA:
                f.parent.mkdir(parents=True, exist_ok=True)
                if attuale:
                    shutil.copy2(f, libero(f))
                f.write_text((attuale.rstrip() + "\n\n" if attuale else "") + testo, encoding="utf-8")
    altri = [h for h in harness if h.lower().strip() not in HARNESS_FILE and h.lower().strip() not in ("claude", "claude code", "claude-code")]
    f = mem / "Comune" / "ISTRUZIONI-HARNESS.md"
    if altri and not f.exists():
        fa(f"scrivo {f} da incollare nelle istruzioni di: {', '.join(altri)}")
        if APPLICA:
            f.write_text("# Da incollare nelle istruzioni personalizzate di Cursor, Grok o altri\n\n"
                         "Questi programmi non leggono un file globale da soli: incolla il blocco qui sotto nelle loro "
                         "impostazioni (Cursor: Settings → Rules → User Rules).\n\n" + testo, encoding="utf-8")


# ---------------------------------------------------------------- main
def main():
    risposte = leggi_json(opzione("--risposte") or HOME / ".jarvis" / "risposte-avvio.json")
    file_percorsi = HOME / ".jarvis" / "percorsi.json"
    percorsi = leggi_json(file_percorsi)
    mem = scegli_memoria(risposte, percorsi)
    # i progetti non stanno più qui: la fonte unica è command-center/spazi.json (crea_progetto.py), che crea da sé
    # la cartella <memoria>/<spazio>/ con Stato.md. Qui solo la struttura comune.
    spazi = []
    di("🟢", f"memoria condivisa: {mem}" + ("" if mem.exists() else " (da creare)"))
    if not "--solo-progetti" in sys.argv:
        crea_struttura(mem, spazi, risposte)
    collegati = collega_progetti(mem)
    if "--solo-progetti" not in sys.argv:
        if "--senza-cache" not in sys.argv:
            collega_cache(mem)
        if "--senza-claude-md" not in sys.argv:
            claude_md_unico(mem, risposte)
        ingresso_harness(mem, risposte.get("harness") or [])
    nuovi = {k: v for k, v in percorsi.items() if k != "spazi"}
    nuovi.update({"aggiornato": ADESSO, "memoria": str(mem), "vault": str(mem), "repo": str(QUI),
                  "progetti": percorsi.get("progetti") or str(HOME / "Progetti"),
                  "claude_progetti_collegati": collegati,
                  "claude_md": str(mem / "Comune" / "CLAUDE.md")})
    if {k: v for k, v in nuovi.items() if k != "aggiornato"} != {k: v for k, v in percorsi.items() if k != "aggiornato"}:
        fa(f"scrivo {file_percorsi}")
        if APPLICA:
            scrivi_json(file_percorsi, nuovi)
    print("\n".join(righe))
    if not APPLICA:
        print("\n(prova: niente è stato scritto. Rilancia con --applica.)")
    sys.exit(1 if any(r.startswith("🔴") for r in righe) else 0)


if __name__ == "__main__":
    main()
