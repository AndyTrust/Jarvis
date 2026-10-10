#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Aggiorna da solo lo stato di avanzamento dei progetti nella memoria condivisa.

Gancio di Claude Code per gli eventi Stop, PreCompact e SessionEnd (JSON su stdin, campi comuni
session_id, transcript_path, cwd, hook_event_name; PreCompact ha anche trigger, SessionEnd reason).
Lo installa strumenti/installa_claude_config.py in ~/.claude/settings.json.

Cosa scrive (solo parte meccanica, il giudizio resta alla skill aggiorna-memoria):
  - <memoria>/<spazio>/Stato.md, tra <!-- stato-auto:inizio --> e <!-- stato-auto:fine -->: per ogni progetto
    dello spazio FATTO / DA FARE / ERRORI letti da <progetto>/.claude/memoria/MEMORIA.md (formato di salva_brain.py),
    i file toccati nella sessione, l'ultimo commit e la data-ora. Il resto del file (le note a mano) non si tocca;
  - <memoria>/Sessioni/AAAA-MM.md: una riga per evento (data-ora, evento, spazio/progetto, sessione, file toccati);
  - a SessionEnd collega le memorie di Claude Code dei progetti nuovi (collega_memoria.py --solo-progetti).
Stop scatta a ogni risposta: scrive al massimo una volta ogni 10 minuti per sessione.
Esce sempre 0 e non stampa niente: un gancio non deve mai fermare Claude. Gli errori vanno in ~/.jarvis/ganci.log.
La memoria viene da ~/.jarvis/percorsi.json, i progetti da command-center/spazi.json (fonte unica). Una cartella fuori dagli spazi lascia solo la riga in Sessioni/.

Scrive anche il diario del giorno, <memoria>/Diario/AAAA-MM-GG.md (FATTO / DA FARE / ERRORI con l'ora), solo se c'è
qualcosa di nuovo. A comando (ganci git, /aggiorna, conferme): stato_avanzamento.py --giro --evento <nome> --cwd <cartella>.

Prova a mano:  echo '{"hook_event_name":"SessionEnd","cwd":"'$PWD'","session_id":"prova"}' | python3 stato_avanzamento.py
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
J = HOME / ".jarvis"
INIZIO, FINE = "<!-- stato-auto:inizio -->", "<!-- stato-auto:fine -->"
PAUSA_STOP = 600


def adesso():
    return time.strftime("%Y-%m-%d %H:%M")


def leggi_json(p, vuoto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if vuoto is None else vuoto


def scrivi_json(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def log(testo):
    try:
        J.mkdir(parents=True, exist_ok=True)
        with open(J / "ganci.log", "a", encoding="utf-8") as f:
            f.write(f"{adesso()} {testo}\n")
    except OSError:
        pass


def esp(v):
    return Path(os.path.expanduser(str(v)))


def spazi_json(percorsi):
    """Gli spazi di command-center/spazi.json (la fonte unica dei progetti, scritta da crea_progetto.py e dal
    Command Center), nella forma [{"nome", "cartella_memoria", "progetti": [(nome, cartella)]}]. In più, per chi
    ha installato una versione vecchia, gli «spazi» di percorsi.json."""
    out = []
    f = os.environ.get("JARVIS_SPAZI") or (esp(percorsi.get("repo") or HOME / "Jarvis") / "command-center" / "spazi.json")
    d = leggi_json(f)
    for s in (d.get("spazi") if isinstance(d, dict) else d) or []:
        if not isinstance(s, dict) or not s.get("nome"):
            continue
        mem_nome = s.get("cartella_nome") or (esp(s["memoria"]).parent.name if s.get("memoria") else s["nome"])
        out.append({"nome": s["nome"], "cartella_memoria": mem_nome,
                    "progetti": [(p.get("nome") or esp(p["cartella"]).name, esp(p["cartella"]))
                                 for p in s.get("progetti") or [] if p.get("cartella")]})
    for s in percorsi.get("spazi") or []:
        if isinstance(s, dict) and s.get("nome") and not any(x["nome"] == s["nome"] for x in out):
            out.append({"nome": s["nome"], "cartella_memoria": s["nome"],
                        "progetti": [(esp(c).name, esp(c)) for c in s.get("cartelle") or []]})
    return out


def trova_spazio(cwd, percorsi):
    """(spazio, nome del progetto, cartella del progetto) per la cartella di lavoro, o (None, None, None)."""
    try:
        c = Path(cwd).resolve()
    except OSError:
        return None, None, None
    for s in spazi_json(percorsi):
        for nome, d in s["progetti"]:
            try:
                d = d.resolve()
            except OSError:
                continue
            if c == d or d in c.parents:
                return s, nome, d
    return None, None, None


def sezione(testo, titolo):
    """Le righe «- ...» sotto «### titolo» (formato di salva_brain.py)."""
    out, dentro = [], False
    for r in testo.splitlines():
        s = r.strip()
        if s.startswith("### "):
            dentro = s[4:].lower().startswith(titolo.lower())
            continue
        if s.startswith("## ") and dentro:
            break
        if dentro and s.startswith("- "):
            out.append(s[2:])
    return out[:12]


def memoria_progetto(cartella):
    t = ""
    f = cartella / ".claude" / "memoria" / "MEMORIA.md"
    if f.is_file():
        try:
            t = f.read_text(encoding="utf-8")
        except OSError:
            pass
    return {"fatto": sezione(t, "Fatto"), "da_fare": sezione(t, "Da fare"), "errori": sezione(t, "Errori")}


def giro(evento, cwd):
    """Il giro a comando (ganci git post-commit e pre-push, /aggiorna, conferme dell'utente): Stato.md dello spazio,
    diario del giorno, riga in Sessioni/. Senza installazione o fuori dai progetti non fa niente. Muto."""
    percorsi = leggi_json(J / "percorsi.json")
    if not percorsi.get("memoria"):
        return
    s, progetto, cartella = trova_spazio(cwd, percorsi)
    if s:
        aggiorna_spazio(percorsi, s, evento, progetto, None, diario=True)


def _righe_diario(testo, titoli):
    """{chiave: [(data-ora, testo)]} dalle sezioni del diario (formato di strumenti/quaderno.py)."""
    out, corrente = {k: [] for k in set(titoli.values())}, None
    for r in testo.splitlines():
        if r.startswith("## "):
            corrente = titoli.get(r[3:].strip())
            continue
        m = re.match(r"^- (\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?) · (.+)$", r)
        if m and corrente:
            out[corrente].append((m.group(1), m.group(2).strip()))
    return out


def azioni(cartella, quante=6):
    """Le ultime azioni registrate sul progetto (.claude/memoria/azioni.jsonl, scritto da crea_progetto.registra_azione)."""
    out = []
    try:
        with open(cartella / ".claude" / "memoria" / "azioni.jsonl", encoding="utf-8") as h:
            for riga in h.readlines()[-quante:]:
                try:
                    out.append(json.loads(riga))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


TITOLI_DIARIO = {"Fatto": "fatto", "Da fare": "da_fare", "Errori commessi da non ripetere": "errore",
                 "Errori da non ripetere": "errore"}


def diari(cartella):
    """I diari degli agenti del progetto: [(agente, {fatto, da_fare, errore}, [errori ripetuti])].
    Un errore è ripetuto se la stessa frase compare in due giorni diversi."""
    out = []
    d = cartella / ".claude" / "memoria" / "agenti"
    attivi = {f.stem for f in (cartella / ".claude" / "agents").glob("*.md")}
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        if f.stem not in attivi:
            continue
        try:
            sez = _righe_diario(f.read_text(encoding="utf-8"), TITOLI_DIARIO)
        except OSError:
            continue
        per = {}
        for data, testo in sez["errore"]:
            per.setdefault(re.sub(r"\W+", " ", testo.lower()).strip()[:120], set()).add(data[:10])
        ripetuti = [k for k, giorni in per.items() if len(giorni) >= 2]
        out.append((f.stem, sez, ripetuti))
    return out


def file_toccati(transcript, cartella):
    """I file scritti o modificati nella sessione (Edit, Write, MultiEdit, NotebookEdit), dagli ultimi 2 MB del trascritto."""
    out = []
    try:
        p = Path(transcript)
        with open(p, "rb") as f:
            f.seek(max(0, p.stat().st_size - 2_000_000))
            coda = f.read().decode("utf-8", "ignore")
    except (OSError, TypeError):
        return out
    for riga in coda.splitlines():
        if '"tool_use"' not in riga:
            continue
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        for b in (d.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                fp = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                if fp:
                    try:
                        fp = str(Path(fp).resolve().relative_to(cartella))
                    except (ValueError, OSError):
                        fp = Path(fp).name
                    if fp not in out:
                        out.append(fp)
    return out[-15:]


def git(cartella, *args):
    try:
        r = subprocess.run(["git", "-C", str(cartella), *args], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def blocco_progetto(nome, info):
    righe = [f"### {nome}", f"_Ultimo aggiornamento: {info['ora']} ({info['evento']})_", ""]
    for titolo, chiave in (("FATTO", "fatto"), ("DA FARE", "da_fare"), ("ERRORI DA NON RIPETERE", "errori")):
        righe.append(f"**{titolo}**")
        righe += [f"- {x}" for x in info.get(chiave) or []] or ["- (niente scritto nella memoria del progetto)"]
        righe.append("")
    if info.get("toccati"):
        righe.append("**File toccati nell'ultima sessione:** " + ", ".join(f"`{x}`" for x in info["toccati"]))
    if info.get("commit"):
        righe.append(f"**Ultimo commit:** {info['commit']}")
    if info.get("modifiche"):
        righe.append(f"**Modifiche non salvate in git:** {info['modifiche']} file")
    if info.get("azioni"):
        righe.append("**Ultime azioni:**")
        righe += [f"- {a.get('ora', '')} · {a.get('testo', '')}" for a in info["azioni"]]
        righe.append("")
    if info.get("diari"):
        righe.append("**Diari degli agenti** (le ultime righe di FATTO / DA FARE / ERRORI):")
        for agente, sez, _ in info["diari"]:
            pezzi = []
            for titolo, k in (("fatto", "fatto"), ("da fare", "da_fare"), ("errori", "errore")):
                if sez.get(k):
                    pezzi.append(f"{titolo}: " + "; ".join(f"{t} ({d})" for d, t in sez[k][-3:]))
            righe.append(f"- `{agente}` · " + (" · ".join(pezzi) if pezzi else "diario ancora vuoto"))
        rip = [(a, r) for a, _, rr in info["diari"] for r in rr]
        if rip:
            righe.append("")
            righe.append("**⚠ ERRORI RIPETUTI (da segnalare al proprietario):** "
                         + "; ".join(f"`{a}`: {r}" for a, r in rip))
    righe.append("")
    return "\n".join(righe)


def aggiorna_stato(mem, spazio, progetti):
    """Riscrive la parte automatica di <memoria>/<spazio>/Stato.md. Torna True se è cambiata."""
    f = mem / spazio / "Stato.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    t = f.read_text(encoding="utf-8") if f.is_file() else f"# Stato · {spazio}\n\n{INIZIO}\n{FINE}\n\n## Note\n"
    if INIZIO not in t:
        t = t.rstrip() + f"\n\n{INIZIO}\n{FINE}\n"
    corpo = "\n".join(blocco_progetto(n, i) for n, i in sorted(progetti.items()))
    nuovo = re.sub(re.escape(INIZIO) + r".*?" + re.escape(FINE), lambda m: f"{INIZIO}\n{corpo}\n{FINE}", t, flags=re.S)
    if nuovo == t:
        return False
    nuovo = re.sub(r"(?m)^aggiornato: .*$", f"aggiornato: {adesso()}", nuovo, count=1)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(nuovo, encoding="utf-8")
    tmp.replace(f)
    return True


def _norma(x):
    return re.sub(r"\W+", " ", str(x).lower()).strip()


def scrivi_diario(mem, s, nome, info, evento):
    """Il diario del giorno, <memoria>/Diario/AAAA-MM-GG.md: un blocco «HH:MM · spazio / progetto · evento» con
    FATTO, DA FARE ed ERRORI DA NON RIPETERE, solo con le voci che oggi non sono ancora scritte (idempotente e muto
    se non c'è niente di nuovo). Voci dalla memoria del progetto e dai diari degli agenti. Torna True se ha scritto."""
    f = mem / "Diario" / f"{time.strftime('%Y-%m-%d')}.md"
    try:
        vecchio = f.read_text(encoding="utf-8") if f.is_file() else ""
    except OSError:
        vecchio = ""
    gia = {_norma(r[2:]) for r in vecchio.splitlines() if r.startswith("- ")}
    voci = {"fatto": list(info.get("fatto") or []), "da_fare": list(info.get("da_fare") or []),
            "errori": list(info.get("errori") or [])}
    for agente, sez, _ in info.get("diari") or []:
        for k_d, k in (("fatto", "fatto"), ("da_fare", "da_fare"), ("errore", "errori")):
            voci[k] += [f"{agente}: {testo}" for _, testo in (sez.get(k_d) or [])[-5:]]
    nuove = {k: [v for v in vs if _norma(v) and _norma(v) not in gia] for k, vs in voci.items()}
    for k in nuove:                                    # niente doppioni dentro lo stesso blocco
        visti, uniche = set(), []
        for v in nuove[k]:
            if _norma(v) not in visti:
                visti.add(_norma(v))
                uniche.append(v)
        nuove[k] = uniche
    if not any(nuove.values()):
        return False
    righe = [f"## {time.strftime('%H:%M')} · {s['nome']} / {nome} · {evento}", ""]
    for titolo, k in (("FATTO", "fatto"), ("DA FARE", "da_fare"), ("ERRORI DA NON RIPETERE", "errori")):
        if nuove[k]:
            righe += [f"**{titolo}**"] + [f"- {v}" for v in nuove[k]] + [""]
    f.parent.mkdir(parents=True, exist_ok=True)
    testa = "" if vecchio else f"# Diario · {time.strftime('%Y-%m-%d')}\n\nLo scrivono da soli i ganci (fine risposta, compattazione, fine sessione, commit, conferme).\n\n"
    with open(f, "a", encoding="utf-8") as h:
        h.write(testa + "\n".join(righe) + "\n")
    return True


def aggiorna_spazio(percorsi, s, evento, progetto_attivo=None, toccati=None, diario=False):
    """Ricalcola lo Stato.md di uno spazio: per ogni progetto FATTO/DA FARE/ERRORI dalla sua memoria, i diari degli
    agenti e gli errori ripetuti. Il progetto della sessione (progetto_attivo) prende anche evento, ora, file toccati
    e git; gli altri tengono quelli dell'ultima volta (~/.jarvis/stato-progetti.json). Lo chiama anche il Command
    Center quando cambiano spazi.json, le schede, i diari o i file caricati."""
    mem = esp(percorsi["memoria"])
    tutti = leggi_json(J / "stato-progetti.json")
    cache = tutti.setdefault(s["nome"], {})
    progetti = {}
    for nome, cart in s["progetti"]:
        info = memoria_progetto(cart)
        vecchio = cache.get(nome, {})
        if nome == progetto_attivo:
            vecchio = {"ora": adesso(), "evento": evento, "toccati": toccati or vecchio.get("toccati", []),
                       "commit": git(cart, "log", "-1", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M"),
                       "modifiche": len([r for r in git(cart, "status", "--porcelain").splitlines() if r.strip()])}
            cache[nome] = vecchio
        info.update({"ora": vecchio.get("ora") or "nessuna sessione ancora", "evento": vecchio.get("evento") or "creato",
                     "toccati": vecchio.get("toccati", []), "commit": vecchio.get("commit", ""),
                     "modifiche": vecchio.get("modifiche", 0), "diari": diari(cart), "azioni": azioni(cart)})
        progetti[nome] = info
        if diario and nome == progetto_attivo:
            scrivi_diario(mem, s, nome, info, evento)
    if progetto_attivo:
        scrivi_json(J / "stato-progetti.json", tutti)
    return aggiorna_stato(mem, s["cartella_memoria"], progetti)


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        log("stato_avanzamento: ingresso non JSON, ignorato")
        return
    evento = ev.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "manuale")
    cwd = ev.get("cwd") or os.getcwd()
    sid = str(ev.get("session_id") or "senza-id")
    if evento == "Stop" and ev.get("stop_hook_active"):
        return
    percorsi = leggi_json(J / "percorsi.json")
    if not percorsi.get("memoria"):
        return                                   # Jarvis non ancora installato: niente da fare
    mem = esp(percorsi["memoria"])
    stato_ganci = leggi_json(J / "stato-ganci.json")
    if evento == "Stop" and time.time() - stato_ganci.get(sid, 0) < PAUSA_STOP:
        return
    stato_ganci[sid] = time.time()
    stato_ganci = dict(sorted(stato_ganci.items(), key=lambda kv: kv[1])[-200:])
    scrivi_json(J / "stato-ganci.json", stato_ganci)

    s, progetto, cartella = trova_spazio(cwd, percorsi)
    toccati = file_toccati(ev.get("transcript_path"), cartella or Path(cwd))
    progetto = progetto or Path(cwd).name
    if s:
        ev_testo = evento + (f"/{ev.get('trigger') or ev.get('reason')}" if ev.get("trigger") or ev.get("reason") else "")
        aggiorna_spazio(percorsi, s, ev_testo, progetto, toccati, diario=True)
    ses = mem / "Sessioni" / f"{time.strftime('%Y-%m')}.md"
    ses.parent.mkdir(parents=True, exist_ok=True)
    nuovo_file = not ses.exists()
    with open(ses, "a", encoding="utf-8") as f:
        if nuovo_file:
            f.write(f"# Sessioni · {time.strftime('%Y-%m')}\n\n")
        f.write(f"- {adesso()} · {evento} · {s['nome'] if s else 'fuori dagli spazi'}/{progetto} · `{sid[:8]}`"
                + (f" · {len(toccati)} file toccati" if toccati else "") + "\n")
    if evento == "SessionEnd":
        cm = esp(percorsi.get("repo") or HOME / "Jarvis") / "strumenti" / "collega_memoria.py"
        if cm.is_file():
            subprocess.run([sys.executable, str(cm), "--applica", "--solo-progetti"], capture_output=True, timeout=20)


if __name__ == "__main__":
    try:
        if "--giro" in sys.argv:            # a comando: --giro --evento <nome> --cwd <cartella>
            a = sys.argv
            giro(a[a.index("--evento") + 1] if "--evento" in a else "a comando",
                 a[a.index("--cwd") + 1] if "--cwd" in a else os.getcwd())
        else:
            main()
    except Exception as e:  # un gancio non ferma mai Claude
        log(f"stato_avanzamento: {type(e).__name__}: {e}")
    sys.exit(0)
