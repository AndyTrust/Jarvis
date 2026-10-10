#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Pulizia e unione di quello che Claude Code salva da solo in ~/.claude, senza perdere niente.

Regole (in quest'ordine):
  1. projects/*/memory (l'auto-memoria di Claude Code): MAI cancellata. Si UNISCE alla memoria condivisa con
     strumenti/collega_memoria.py --solo-progetti (collegamento a <memoria>/Claude/projects/<progetto>; i file diversi
     restano tutti e due, l'originale va in memory.bak-AAAAMMGG).
  2. projects/*/*.jsonl (le trascrizioni delle chat) più vecchie di --giorni-chat (30): prima il riassunto nel diario
     del giorno della chat (<memoria>/Diario/AAAA-MM-GG.md, sezione «Chat archiviate»: cartella, prima richiesta,
     ultima risposta), poi la chat (con la sua cartella di sotto-agenti) va compressa in
     ~/.jarvis/archivio-chat/AAAAMMGG-HHMM.tar.gz e solo dopo esce da ~/.claude. Gli archivi si tengono --giorni-archivio (180).
  3. transitori, oltre la soglia: shell-snapshots (3 giorni), session-env (3), debug (7), paste-cache (7),
     cache/pdf-testo (14), file-history (30), todos (30), backups/.claude.json.backup.* (tiene gli ultimi 3).
     Il resto della cache (catalogo dei modelli, changelog) non si tocca.
  4. Mai: le sessioni aperte, i file toccati nelle ultime 24 ore, settings.json, .credentials.json, agents/, skills/,
     hooks/, commands/, plugins/. Le cose strane (ganci doppi in settings.json) si segnalano soltanto.

    python3 strumenti/pulisci_claude.py --prova            dice cosa farebbe (è anche il comportamento senza opzioni)
    python3 strumenti/pulisci_claude.py --applica [--giorni-chat 30] [--quiet]
Variabile CLAUDE_HOME (o --home) per provarlo su una casa finta. Scrive ~/.claude/pulizia-jarvis.log.
La pianificano launchd (com.jarvis.pulizia-claude, ogni giorno) e il comando /aggiorna.
"""
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path


def opzione(nome, predefinito):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


HOME = Path(opzione("--home", os.environ.get("CLAUDE_HOME") or os.environ.get("HOME") or str(Path.home()))).expanduser()
CLAUDE = HOME / ".claude"
J = HOME / ".jarvis"
QUI = Path(__file__).resolve().parents[1]
APPLICA = "--applica" in sys.argv and "--prova" not in sys.argv
QUIET = "--quiet" in sys.argv
G_CHAT = float(opzione("--giorni-chat", 30))
G_ARCHIVIO = float(opzione("--giorni-archivio", 180))
ADESSO = time.time()
GIORNO = 86400
TRANSITORI = [("shell-snapshots", 3, "snapshot della shell"), ("session-env", 3, "ambiente di sessione"),
              ("debug", 7, "log di debug"), ("paste-cache", 7, "testo incollato"), ("cache/pdf-testo", 14, "testo dei PDF"),
              ("file-history", 30, "cronologia dei file"), ("todos", 30, "elenco di cose da fare")]
righe, tot = [], {"file": 0, "byte": 0}


def peso(p):
    try:
        return p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def ultimo_tocco(p):
    try:
        m = p.lstat().st_mtime
    except OSError:
        return ADESSO                       # non si sa: «appena toccato», quindi non si toglie
    if p.is_dir() and not p.is_symlink():
        for f in p.rglob("*"):
            try:
                m = max(m, f.lstat().st_mtime)
            except OSError:
                pass
    return m


def memoria():
    try:
        v = json.loads((J / "percorsi.json").read_text(encoding="utf-8")).get("memoria")
    except (OSError, ValueError):
        v = None
    return Path(os.path.expanduser(v)) if v else HOME / "Jarvis-Memoria"


def sessioni_aperte():
    """Le chat da non toccare: quelle con un processo claude vivo (registro di sessioni.py e, su Linux, /proc)."""
    vive = set()
    try:
        reg = json.loads((J / "sessioni.json").read_text(encoding="utf-8"))
        for sid, s in (reg.items() if isinstance(reg, dict) else []):
            try:
                if s.get("stato") == "aperta" and s.get("pid"):
                    os.kill(int(s["pid"]), 0)
                    vive.add(sid)
            except (OSError, ValueError, AttributeError):
                pass
    except (OSError, ValueError):
        pass
    proc = Path("/proc")
    if proc.is_dir():
        for d in proc.iterdir():
            if not d.name.isdigit():
                continue
            try:
                argv = (d / "cmdline").read_bytes().split(b"\0")
                if not any(b"claude" in a for a in argv[:3]):
                    continue
                cwd = os.readlink(d / "cwd")
            except (OSError, IndexError):
                continue
            c = CLAUDE / "projects" / "".join("-" if ch in "/._" else ch for ch in cwd)
            for f in sorted(c.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)[:3] if c.is_dir() else []:
                vive.add(f.stem)
    return vive


# ---------------------------------------------------------------- 1. memory/ -> memoria condivisa
def unisci_memory():
    cm = QUI / "strumenti" / "collega_memoria.py"
    sole = [m for m in (CLAUDE / "projects").glob("*/memory") if m.is_dir() and not m.is_symlink()] \
        if (CLAUDE / "projects").is_dir() else []
    if not sole:
        righe.append("memory dei progetti: già tutte unite alla memoria condivisa")
        return
    righe.append(f"memory dei progetti da unire alla memoria condivisa: {len(sole)} ({', '.join(m.parent.name for m in sole[:4])}…)")
    if APPLICA and cm.is_file():
        r = subprocess.run([sys.executable, str(cm), "--applica", "--solo-progetti"], capture_output=True, text=True,
                           timeout=120, env={**os.environ, "HOME": str(HOME)})
        righe.append(f"  collega_memoria.py --solo-progetti: esito {r.returncode}")


# ---------------------------------------------------------------- 2. trascrizioni vecchie
def riassunto(f):
    """(ora d'inizio, cartella, prima richiesta, ultima risposta) da una trascrizione .jsonl."""
    inizio, cwd, prima, ultima = None, "", "", ""
    try:
        with open(f, encoding="utf-8", errors="ignore") as h:
            for riga in h:
                try:
                    d = json.loads(riga)
                except ValueError:
                    continue
                inizio = inizio or d.get("timestamp")
                cwd = cwd or d.get("cwd") or ""
                m = d.get("message") or {}
                c = m.get("content")
                testo = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")
                testo = " ".join(str(testo).split())
                if not testo:
                    continue
                if d.get("type") == "user" and not prima and not testo.startswith("<"):
                    prima = testo
                elif d.get("type") == "assistant":
                    ultima = testo
    except OSError:
        pass
    return inizio, cwd, prima[:200], ultima[:240]


def scrivi_riassunto(f, tar):
    inizio, cwd, prima, ultima = riassunto(f)
    giorno = (inizio or time.strftime("%Y-%m-%d", time.localtime(f.stat().st_mtime)))[:10]
    ora = (inizio or "")[11:16]
    diario = memoria() / "Diario" / f"{giorno}.md"
    riga = (f"- {ora or '--:--'} · `{f.stem[:8]}` · {cwd.replace(str(HOME), '~') or f.parent.name} · prima richiesta: «{prima or '-'}» "
            f"· ultima risposta: «{ultima or '-'}» · archivio: `{tar.name}`")
    testo = diario.read_text(encoding="utf-8") if diario.is_file() else f"# Diario · {giorno}\n"
    if f"`{f.stem[:8]}`" in testo:
        return
    if "## Chat archiviate" not in testo:
        testo = testo.rstrip("\n") + "\n\n## Chat archiviate\n"
    testo = testo.rstrip("\n") + "\n" + riga + "\n"
    diario.parent.mkdir(parents=True, exist_ok=True)
    diario.write_text(testo, encoding="utf-8")


def chat_vecchie():
    progetti = CLAUDE / "projects"
    if not progetti.is_dir():
        return
    aperte = sessioni_aperte()
    vecchie = []
    for cartella in sorted(p for p in progetti.iterdir() if p.is_dir()):
        for f in sorted(cartella.glob("*.jsonl")):
            eta = ADESSO - ultimo_tocco(f)
            if f.stem in aperte or eta < GIORNO or eta < G_CHAT * GIORNO:
                continue
            vecchie.append(f)
    if not vecchie:
        righe.append(f"chat più vecchie di {G_CHAT:g} giorni: nessuna")
        return
    b = sum(peso(f) + peso(f.parent / f.stem) for f in vecchie)
    tot["file"] += len(vecchie)
    tot["byte"] += b
    righe.append(f"chat più vecchie di {G_CHAT:g} giorni: {len(vecchie)} ({b // 1024} KB) → riassunto nel diario, "
                 f"archivio compresso in {J / 'archivio-chat'}, poi via da ~/.claude")
    if not APPLICA:
        return
    dest = J / "archivio-chat"
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    tar = dest / f"{time.strftime('%Y%m%d-%H%M')}.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:              # prima l'archivio: se fallisce, non si toglie niente
        for f in vecchie:
            tf.add(f, arcname=str(f.relative_to(CLAUDE)))
            if (f.parent / f.stem).is_dir():
                tf.add(f.parent / f.stem, arcname=str((f.parent / f.stem).relative_to(CLAUDE)))
    with tarfile.open(tar, "r:gz") as tf:              # e si controlla che ci siano tutte
        dentro = set(tf.getnames())
    if not all(str(f.relative_to(CLAUDE)) in dentro for f in vecchie):
        righe.append(f"  ERRORE: l'archivio {tar} non contiene tutte le chat: non tolgo niente")
        return
    for f in vecchie:
        try:
            scrivi_riassunto(f, tar)
        except OSError as e:
            righe.append(f"  riassunto non scritto per {f.name}: {e}")
    import shutil
    for f in vecchie:
        f.unlink(missing_ok=True)
        if (f.parent / f.stem).is_dir():
            shutil.rmtree(f.parent / f.stem, ignore_errors=True)
    for vecchio in dest.glob("*.tar.gz"):
        if ADESSO - vecchio.stat().st_mtime > G_ARCHIVIO * GIORNO:
            vecchio.unlink(missing_ok=True)
    righe.append(f"  archivio: {tar}")


# ---------------------------------------------------------------- 3. transitori
def transitori():
    import shutil
    aperte = sessioni_aperte()
    for nome, giorni, etichetta in TRANSITORI:
        d = CLAUDE / nome
        if not d.is_dir():
            continue
        via = [x for x in sorted(d.iterdir()) if x.name not in aperte and not x.is_symlink()
               and ADESSO - ultimo_tocco(x) > max(giorni * GIORNO, GIORNO)]
        if not via:
            continue
        b = sum(peso(x) for x in via)
        tot["file"] += len(via)
        tot["byte"] += b
        righe.append(f"{etichetta} (> {giorni:g} giorni): {len(via)} elementi, {b // 1024} KB in {nome}/")
        if APPLICA:
            for x in via:
                shutil.rmtree(x, ignore_errors=True) if x.is_dir() else x.unlink(missing_ok=True)
    bk = CLAUDE / "backups"
    if bk.is_dir():
        copie = sorted(bk.glob(".claude.json.backup.*"), key=lambda x: x.stat().st_mtime, reverse=True)[3:]
        copie = [x for x in copie if ADESSO - x.stat().st_mtime > GIORNO]
        if copie:
            righe.append(f"copie vecchie di .claude.json: {len(copie)} (tengo le ultime 3)")
            tot["file"] += len(copie)
            if APPLICA:
                for x in copie:
                    x.unlink(missing_ok=True)


def segnala_ganci():
    try:
        d = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    visti, doppi, assenti = set(), [], []
    for ev, gruppi in (d.get("hooks") or {}).items():
        for g in gruppi:
            for h in g.get("hooks", []):
                cmd = h.get("command") or ""
                k = (ev, g.get("matcher", ""), cmd)
                if k in visti:
                    doppi.append(f"{ev}: {cmd[-50:]}")
                visti.add(k)
                for pezzo in cmd.replace('"', " ").split():
                    if pezzo.endswith(".py") and pezzo.startswith("/") and not Path(pezzo).exists():
                        assenti.append(f"{ev}: {pezzo}")
    if doppi:
        righe.append(f"da guardare (non tocco): ganci registrati due volte in settings.json: {' | '.join(doppi[:5])}")
    if assenti:
        righe.append(f"da guardare (non tocco): ganci che puntano a file inesistenti: {' | '.join(sorted(set(assenti))[:5])}")


def main():
    if not CLAUDE.is_dir():
        print(f"{CLAUDE} non c'è: niente da fare")
        return 0
    unisci_memory()
    chat_vecchie()
    transitori()
    segnala_ganci()
    esito = (f"{'Fatto' if APPLICA else 'Prova (niente scritto)'}: {tot['file']} elementi, {tot['byte'] / 1048576:.1f} MB "
             f"· {time.strftime('%Y-%m-%d %H:%M')}")
    if not QUIET:
        print("\n".join(righe))
    print(esito)
    if APPLICA:
        try:
            with open(CLAUDE / "pulizia-jarvis.log", "a", encoding="utf-8") as lg:
                lg.write(esito + "\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
