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
La memoria e gli spazi vengono da ~/.jarvis/percorsi.json. Una cartella fuori dagli spazi lascia solo la riga in Sessioni/.

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


def trova_spazio(cwd, percorsi):
    c = Path(cwd).resolve()
    for s in percorsi.get("spazi") or []:
        for d in s.get("cartelle") or []:
            try:
                d = esp(d).resolve()
            except OSError:
                continue
            if c == d or d in c.parents:
                return s.get("nome"), d
    return None, None


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
    righe.append("")
    return "\n".join(righe)


def aggiorna_stato(mem, spazio, progetti):
    f = mem / spazio / "Stato.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    t = f.read_text(encoding="utf-8") if f.is_file() else f"# Stato · {spazio}\n\n{INIZIO}\n{FINE}\n\n## Note\n"
    if INIZIO not in t:
        t = t.rstrip() + f"\n\n{INIZIO}\n{FINE}\n"
    corpo = "\n".join(blocco_progetto(n, i) for n, i in sorted(progetti.items()))
    nuovo = re.sub(re.escape(INIZIO) + r".*?" + re.escape(FINE), lambda m: f"{INIZIO}\n{corpo}\n{FINE}", t, flags=re.S)
    nuovo = re.sub(r"(?m)^aggiornato: .*$", f"aggiornato: {adesso()}", nuovo, count=1)
    if nuovo != t:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(nuovo, encoding="utf-8")
        tmp.replace(f)


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

    spazio, cartella = trova_spazio(cwd, percorsi)
    toccati = file_toccati(ev.get("transcript_path"), cartella or Path(cwd))
    progetto = cartella.name if cartella else Path(cwd).name
    if spazio:
        tutti = leggi_json(J / "stato-progetti.json")
        info = memoria_progetto(cartella)
        info.update({"ora": adesso(), "evento": evento + (f"/{ev.get('trigger') or ev.get('reason')}" if ev.get("trigger") or ev.get("reason") else ""),
                     "toccati": toccati or tutti.get(spazio, {}).get(progetto, {}).get("toccati", []),
                     "commit": git(cartella, "log", "-1", "--format=%h %ad %s", "--date=format:%Y-%m-%d %H:%M"),
                     "modifiche": len([r for r in git(cartella, "status", "--porcelain").splitlines() if r.strip()])})
        tutti.setdefault(spazio, {})[progetto] = info
        scrivi_json(J / "stato-progetti.json", tutti)
        aggiorna_stato(mem, spazio, tutti[spazio])
    ses = mem / "Sessioni" / f"{time.strftime('%Y-%m')}.md"
    ses.parent.mkdir(parents=True, exist_ok=True)
    nuovo_file = not ses.exists()
    with open(ses, "a", encoding="utf-8") as f:
        if nuovo_file:
            f.write(f"# Sessioni · {time.strftime('%Y-%m')}\n\n")
        f.write(f"- {adesso()} · {evento} · {spazio or 'fuori dagli spazi'}/{progetto} · `{sid[:8]}`"
                + (f" · {len(toccati)} file toccati" if toccati else "") + "\n")
    if evento == "SessionEnd":
        cm = esp(percorsi.get("repo") or HOME / "Jarvis") / "strumenti" / "collega_memoria.py"
        if cm.is_file():
            subprocess.run([sys.executable, str(cm), "--applica", "--solo-progetti"], capture_output=True, timeout=20)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # un gancio non ferma mai Claude
        log(f"stato_avanzamento: {type(e).__name__}: {e}")
    sys.exit(0)
