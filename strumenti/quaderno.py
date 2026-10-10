#!/usr/bin/env python3
"""Il quaderno di un agente: la sua memoria, scritta da lui (l'utente, 2026-10-04: «gli agenti devono essere
liberi di apprendere, imparare, cercare e auto-adattarsi»).

Un file per agente, nella memoria del suo progetto: <cartella>/.claude/memoria/agenti/<nome>.md
(per gli agenti di casa di Jarvis, ~/.claude/agents: ~/Jarvis/.claude/memoria/agenti/<nome>.md).
Sei sezioni: Imparato · Errori da non ripetere · Da verificare · Fonti · Proposte al profilo · Diario.
Ogni riga ha la data; le righe uguali non si ripetono; ogni sezione tiene al massimo 80 righe.
Il Diario (l'utente, 2026-10-05) ha una riga per lavoro concluso, che comincia con data e ora assolute (ISO con fuso,
es. 2026-10-05T13:02+02:00, perché Mac, PC e VPS stanno su fusi diversi): la scrive da solo il gancio
diario_agenti.py a fine lavoro, oppure `quaderno.py diario <agente> "cosa → esito"`.

  python3 ~/Jarvis/strumenti/quaderno.py dove <agente>                       # il file del quaderno
  python3 ~/Jarvis/strumenti/quaderno.py leggi <agente> [--righe 8]          # digesto da mettere nel compito
  python3 ~/Jarvis/strumenti/quaderno.py scrivi <agente> --fatto "…" --da_fare "…" --errore "…"   (il diario di fine lavoro)
          altre sezioni: --imparato "…" --verifica "…" --fonte "…" --proposta "…"   (tutte ripetibili)
  python3 ~/Jarvis/strumenti/quaderno.py raccogli <agente> --da <file del resoconto>   # legge le righe
        «DA SALVARE: …», «ERRORE DA SALVARE: …», «DA VERIFICARE: …», «FONTE: …», «PROPOSTA: …»
  python3 ~/Jarvis/strumenti/quaderno.py diario <agente> "cosa → esito" [--macchina PC]   # una riga di diario, ora di adesso
  python3 ~/Jarvis/strumenti/quaderno.py crea <agente>                                 # il quaderno vuoto, se non c'è
  python3 ~/Jarvis/strumenti/quaderno.py errori-ripetuti [--progetto <cartella>]      # lo stesso errore in 2+ giorni
  python3 ~/Jarvis/strumenti/quaderno.py elenco                                       # tutti i quaderni e quante righe
--cartella <cartella del progetto> forza il progetto quando lo stesso nome esiste in più progetti.
"""
import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
import time

def leggi_testo(p):
    """Legge un file; se OneDrive lo sta scaricando (EDEADLK, errno 11) riprova."""
    for tentativo in range(6):
        try:
            return Path(p).read_text(encoding="utf-8")
        except OSError as e:
            if e.errno != 11 or tentativo == 5:
                raise
            time.sleep(2 * (tentativo + 1))


HOME = Path.home()
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import percorsi_vault as _pv
    JARVIS = _pv.repo()
    OD = _pv.onedrive()
except Exception:  # noqa: BLE001
    JARVIS = Path(__file__).resolve().parents[1]
    OD = HOME / "OneDrive"
import os as _os
SPAZI_JSON = Path(_os.environ.get("JARVIS_SPAZI") or (Path(__file__).resolve().parents[1] / "command-center" / "spazi.json"))
CASA = HOME / ".claude" / "agents"            # agenti di casa: il quaderno sta nella memoria di Jarvis
MEMORIA_CASA = JARVIS / ".claude" / "memoria"
# Il diario di ogni agente: tre sezioni fisse in testa (FATTO, DA FARE, ERRORI COMMESSI DA NON RIPETERE), con data e ora;
# poi le sezioni di apprendimento. Le consegna l'agente a fine lavoro.
SEZIONI = [("fatto", "Fatto"), ("da_fare", "Da fare"), ("errore", "Errori commessi da non ripetere"),
           ("imparato", "Imparato"), ("verifica", "Da verificare"), ("fonte", "Fonti"),
           ("proposta", "Proposte al profilo"), ("diario", "Diario")]
TITOLI_VECCHI = {"Errori da non ripetere": "errore"}
MAX_RIGHE = 80
MARCHE = {"FATTO": "fatto", "DA FARE": "da_fare", "ERRORE COMMESSO": "errore", "ERRORI COMMESSI": "errore",
          "DA SALVARE": "imparato", "IMPARATO": "imparato", "ERRORE DA SALVARE": "errore", "ERRORE": "errore",
          "DA VERIFICARE": "verifica", "FONTE": "fonte", "PROPOSTA": "proposta", "PROPOSTA AL PROFILO": "proposta"}


def _percorso(v):
    v = str(v)
    if v.startswith("OD/"):
        return OD / v[3:]
    if v.startswith("~/"):
        return HOME / v[2:]
    return Path(v)


def cartelle_progetti():
    """(cartella del progetto, cartella della sua memoria) per ogni progetto con agenti."""
    out = []
    try:
        d = json.loads(leggi_testo(SPAZI_JSON))
    except (OSError, ValueError):
        d = []
    spazi = d if isinstance(d, list) else d.get("spazi", [])
    for s in spazi:
        for p in s.get("progetti", []):
            c = _percorso(p["cartella"])
            m = _percorso(p["memoria_propria"][0]) if p.get("memoria_propria") else c / ".claude" / "memoria"
            out.append((c, m))
    visti, unici = set(), []
    for c, m in out:
        if c not in visti and (c / ".claude" / "agents").is_dir():
            visti.add(c)
            unici.append((c, m))
    return unici


def trova(nome, cartella=None):
    """(file del profilo, file del quaderno). Con --cartella si cerca solo lì."""
    nome = nome.strip().lower()
    if cartella:
        c = Path(cartella).expanduser()
        prof = c / ".claude" / "agents" / f"{nome}.md"
        if not prof.exists():
            sys.exit(f"nessun agente «{nome}» in {c}")
        mem = next((m for cc, m in cartelle_progetti() if cc == c), c / ".claude" / "memoria")
        return prof, mem / "agenti" / f"{nome}.md"
    trovati = [(c / ".claude" / "agents" / f"{nome}.md", m) for c, m in cartelle_progetti()
               if (c / ".claude" / "agents" / f"{nome}.md").exists()]
    if (CASA / f"{nome}.md").exists():
        trovati.append((CASA / f"{nome}.md", MEMORIA_CASA))
    if not trovati:
        sys.exit(f"nessun agente «{nome}»: controlla il nome (python3 {sys.argv[0]} elenco)")
    if len(trovati) > 1:
        sys.exit(f"«{nome}» esiste in più progetti: " + ", ".join(str(p.parent.parent.parent) for p, _ in trovati)
                 + " — aggiungi --cartella")
    prof, mem = trovati[0]
    return prof, mem / "agenti" / f"{nome}.md"


def _norma(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def leggi_quaderno(f):
    """{chiave di sezione: [(data, testo), …]}"""
    sez = {k: [] for k, _ in SEZIONI}
    if not f.exists():
        return sez
    corrente = None
    titoli = {**TITOLI_VECCHI, **{t: k for k, t in SEZIONI}}
    for riga in leggi_testo(f).splitlines():
        if riga.startswith("## "):
            corrente = titoli.get(riga[3:].strip())
            continue
        m = re.match(r"^- (\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?) · (.+)$", riga)
        if m and corrente:
            sez[corrente].append((m.group(1), m.group(2).strip()))
    return sez


def scrivi_quaderno(f, nome, sez):
    f.parent.mkdir(parents=True, exist_ok=True)
    righe = [f"# Quaderno di {nome}", "",
             "*Lo scrive l'agente stesso, a fine lavoro (`quaderno.py scrivi`). Lo legge all'inizio del lavoro dopo.*", ""]
    for k, t in SEZIONI:
        righe.append(f"## {t}")
        for data, testo in sez[k][-MAX_RIGHE:]:
            righe.append(f"- {data} · {testo}")
        righe.append("")
    tmp = f.with_suffix(".tmp")
    tmp.write_text("\n".join(righe).rstrip("\n") + "\n", encoding="utf-8")
    tmp.replace(f)


def aggiungi(f, nome, voci):
    """voci: [(chiave, testo)]. Ritorna quante righe nuove (le ripetizioni si saltano)."""
    sez = leggi_quaderno(f)
    oggi = datetime.now().strftime("%Y-%m-%d %H:%M")
    nuove = 0
    for k, testo in voci:
        testo = " ".join(str(testo).split())
        if not testo:
            continue
        uguali = [d[:10] for d, t in sez[k] if _norma(t) == _norma(testo)]
        # un errore già scritto in un giorno diverso si riscrive: la ripetizione è il dato che serve a errori-ripetuti
        if uguali and (k != "errore" or oggi[:10] in uguali):
            continue
        sez[k].append((oggi, testo))
        nuove += 1
    if nuove or not f.exists():
        scrivi_quaderno(f, nome, sez)
    return nuove


def digesto(f, nome, righe=8):
    sez = leggi_quaderno(f)
    if not any(sez.values()):
        return (f"QUADERNO DI {nome}: ancora vuoto. Prima di chiudere scrivi FATTO, DA FARE ed ERRORI COMMESSI DA NON "
                f"RIPETERE: quaderno.py scrivi {nome} --fatto \"…\" --da_fare \"…\" --errore \"…\"")
    out = [f"QUADERNO DI {nome} (le ultime {righe} righe per sezione; il file intero: {f})"]
    for k, t in SEZIONI:
        if sez[k]:
            out.append(f"{t}:")
            out += [f"  - {d} · {x}" for d, x in sez[k][-righe:]]
    return "\n".join(out)


def ora_assoluta(adesso=None):
    """Data e ora con il fuso, al minuto: 2026-10-05T13:02+02:00 (uguale da leggere su Mac, PC e VPS)."""
    return (adesso or datetime.now().astimezone()).isoformat(timespec="minutes")


def riga_diario(testo, macchina="", adesso=None):
    """La riga del Diario: ora assoluta, macchina, cosa → esito."""
    testo = " ".join(str(testo).split())
    return f"{ora_assoluta(adesso)} {macchina.upper() + ' · ' if macchina else ''}{testo}"


def raccogli_da_testo(testo):
    voci = []
    for riga in testo.splitlines():
        r = riga.strip().lstrip("-*• ").strip()
        m = re.match(r"^\**([A-Z ]{4,25}?)\**\s*:\s*(.+)$", r)
        if not m:
            continue
        k = MARCHE.get(m.group(1).strip())
        if k:
            voci.append((k, m.group(2).strip().strip("*").strip()))
    return voci


def errori_ripetuti(cartella=None):
    out = []
    if cartella:
        c = Path(cartella).expanduser()
        coppie = [(c, next((m for cc, m in cartelle_progetti() if cc == c), c / ".claude" / "memoria"))]
    else:
        coppie = cartelle_progetti() + [(CASA.parent, MEMORIA_CASA)]
    for c, m in coppie:
        for f in sorted((m / "agenti").glob("*.md")) if (m / "agenti").is_dir() else []:
            sez = leggi_quaderno(f)
            per = {}
            for d, t in sez["errore"]:
                per.setdefault(_norma(t)[:120], []).append((d, t))
            for righe in per.values():
                giorni = sorted({d[:10] for d, _ in righe})
                if len(giorni) >= 2:
                    out.append((f.stem, str(c), giorni, righe[-1][1]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cosa", choices=["dove", "leggi", "scrivi", "raccogli", "diario", "crea", "errori-ripetuti", "elenco"])
    ap.add_argument("agente", nargs="?")
    ap.add_argument("testo", nargs="?", help="(diario) cosa → esito")
    ap.add_argument("--macchina", default="", help="(diario) MAC, nome del PC, VPS")
    ap.add_argument("--cartella", help="cartella del progetto, se il nome è in più progetti")
    ap.add_argument("--progetto", help="(errori-ripetuti) solo questa cartella")
    ap.add_argument("--righe", type=int, default=8)
    ap.add_argument("--da", help="(raccogli) file con il resoconto; senza, legge lo standard input")
    for k, _ in SEZIONI:
        ap.add_argument(f"--{k}", action="append", default=[])
    a = ap.parse_args()

    if a.cosa == "elenco":
        for c, m in cartelle_progetti() + [(CASA.parent, MEMORIA_CASA)]:
            agenti = sorted((c / ".claude" / "agents").glob("*.md")) if c != CASA.parent else sorted(CASA.glob("*.md"))
            for prof in agenti:
                if prof.name.startswith("LEGGIMI") or prof.name.startswith("_"):
                    continue
                q = m / "agenti" / f"{prof.stem}.md"
                n = sum(len(v) for v in leggi_quaderno(q).values()) if q.exists() else 0
                print(f"{prof.stem:32} {n:3} righe   {q}")
        return
    if a.cosa == "errori-ripetuti":
        rip = errori_ripetuti(a.progetto)
        if not rip:
            print("nessun errore ripetuto nei quaderni")
            return
        for nome, c, giorni, testo in rip:
            print(f"🔴 {nome} ({Path(c).name}): {len(giorni)} giorni ({giorni[0]} → {giorni[-1]}) · {testo}")
        sys.exit(3)
    if not a.agente:
        sys.exit("manca il nome dell'agente")
    prof, q = trova(a.agente, a.cartella)
    if a.cosa == "dove":
        print(q)
    elif a.cosa == "leggi":
        print(digesto(q, a.agente, a.righe))
    elif a.cosa == "scrivi":
        voci = [(k, riga_diario(t) if k == "diario" else t) for k, _ in SEZIONI for t in getattr(a, k)]
        if not voci:
            sys.exit("niente da scrivere: --fatto, --da_fare, --errore, --imparato, --verifica, --fonte, --proposta o --diario")
        n = aggiungi(q, a.agente, voci)
        print(f"{n} righe nuove in {q}" if n else f"niente di nuovo (già nel quaderno): {q}")
    elif a.cosa == "diario":
        if not (a.testo or "").strip():
            sys.exit("manca il testo: quaderno.py diario <agente> \"cosa → esito\"")
        n = aggiungi(q, a.agente, [("diario", riga_diario(a.testo, a.macchina))])
        print(f"{n} riga di diario in {q}")
    elif a.cosa == "crea":
        if q.exists():
            print(f"c'è già: {q}")
        else:
            aggiungi(q, a.agente, [])
            print(f"creato: {q}")
    elif a.cosa == "raccogli":
        testo = Path(a.da).read_text(encoding="utf-8") if a.da else sys.stdin.read()
        voci = raccogli_da_testo(testo)
        n = aggiungi(q, a.agente, voci) if voci else 0
        print(f"{len(voci)} righe trovate, {n} nuove in {q}")


if __name__ == "__main__":
    main()
