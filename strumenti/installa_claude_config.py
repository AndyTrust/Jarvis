#!/usr/bin/env python3
"""Mette in ~/.claude quello che Jarvis si aspetta: ganci, agenti di casa e skill «aggiorna-memoria».
Non sovrascrive niente di tuo:
  - hooks/, agents/ e la skill: copia solo i file che mancano (con --aggiorna anche quelli diversi, dopo averne
    tenuto una copia .bak-AAAAMMGG);
  - settings.json: aggiunge i ganci di claude-config/settings.ganci.json che non ci sono già (stesso comando =
    già presente), dopo una copia di sicurezza settings.json.bak-AAAAMMGG-HHMM.
Le cartelle bozze/ e output/ della skill (memoria personale) non sono nel repository e non si toccano.

  python3 strumenti/installa_claude_config.py             installa
  python3 strumenti/installa_claude_config.py --prova     dice cosa farebbe, non scrive
  python3 strumenti/installa_claude_config.py --aggiorna  aggiorna anche i file già presenti ma diversi
Variabile HOME (o --home) per provarlo su una casa finta."""
import json
import shutil
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parents[1]
CONF = QUI / "claude-config"


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


HOME = Path(opzione("--home", str(Path.home()))).expanduser()
PROVA = "--prova" in sys.argv
AGGIORNA = "--aggiorna" in sys.argv
STAMPA = time.strftime("%Y%m%d")
fatti = []


def dichiara(cosa):
    fatti.append(cosa)
    print(("[prova] " if PROVA else "") + cosa)


def copia(src, dst):
    if dst.exists():
        if dst.read_bytes() == src.read_bytes():
            return
        if not AGGIORNA:
            # mai sovrascrivere alla cieca: il tuo resta, la versione di Jarvis va accanto per confrontarle
            accanto = dst.with_name(dst.name + f".nuovo-{STAMPA}")
            dichiara(f"lascio com'è il tuo {dst} (diverso da quello di Jarvis); la versione nuova va in {accanto.name}. "
                     "Con --aggiorna si sostituisce, dopo una copia .bak")
            if not PROVA:
                shutil.copy2(src, accanto)
            return
        if not PROVA:
            shutil.copy2(dst, dst.with_name(dst.name + f".bak-{STAMPA}"))
    dichiara(f"{'aggiorno' if dst.exists() else 'copio'}: {dst}")
    if not PROVA:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copia_albero(src_dir, dst_dir, salta=("__pycache__",)):
    for f in sorted(src_dir.rglob("*")):
        if f.is_file() and not any(p in f.parts for p in salta) and f.suffix != ".pyc":
            copia(f, dst_dir / f.relative_to(src_dir))


def unisci_ganci():
    modello = json.loads((CONF / "settings.ganci.json").read_text(encoding="utf-8").replace(
        "@@JARVIS@@", str(QUI)).replace("@@HOME@@", str(HOME)))
    file = HOME / ".claude" / "settings.json"
    try:
        attuale = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    except ValueError:
        sys.exit(f"{file} non è un JSON valido: lo lascio com'è, correggilo e rilancia")
    ganci = attuale.setdefault("hooks", {})
    aggiunti = 0
    for evento, voci in modello["hooks"].items():
        esistenti = ganci.setdefault(evento, [])
        comandi = {h.get("command") for v in esistenti for h in v.get("hooks", [])}
        for v in voci:
            nuovi = [h for h in v["hooks"] if h["command"] not in comandi]
            if nuovi:
                esistenti.append({**{k: x for k, x in v.items() if k != "hooks"}, "hooks": nuovi})
                aggiunti += len(nuovi)
    if not aggiunti:
        print("ganci: già tutti presenti in settings.json")
        return
    dichiara(f"aggiungo {aggiunti} ganci a {file} (copia di sicurezza prima)")
    if not PROVA:
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.exists():
            shutil.copy2(file, file.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M')}"))
        file.write_text(json.dumps(attuale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if not CONF.is_dir():
        sys.exit(f"manca {CONF}")
    copia_albero(CONF / "hooks", HOME / ".claude" / "hooks")
    copia_albero(CONF / "agents", HOME / ".claude" / "agents")
    copia_albero(CONF / "skills", HOME / ".claude" / "skills")
    copia_albero(CONF / "commands", HOME / ".claude" / "commands")     # /nuovo-progetto e /nuovo-agente ovunque
    unisci_ganci()
    # «Agenti di Jarvis» sulla lavagna è una cartella vera (agenti-casa) con un collegamento a ~/.claude/agents:
    # gli agenti di casa restano un file solo (spazi.json punta a ~/…/agenti-casa)
    casa_agenti = QUI / "agenti-casa" / ".claude" / "agents"
    if not casa_agenti.exists() and not casa_agenti.is_symlink():
        dichiara(f"collego {casa_agenti} → {HOME / '.claude' / 'agents'}")
        if not PROVA:
            casa_agenti.parent.mkdir(parents=True, exist_ok=True)
            casa_agenti.symlink_to(HOME / ".claude" / "agents")
            (QUI / "agenti-casa" / "LEGGIMI.md").write_text(
                "# Agenti di casa di Jarvis\n\nCartella collegata al gruppo «Agenti di Jarvis» del Command Center. "
                "`.claude/agents` è un collegamento a `~/.claude/agents` (creato da installa_claude_config.py).\n", encoding="utf-8")
    print(f"{'Da fare' if PROVA else 'Fatto'}: {len(fatti)} operazioni.")


if __name__ == "__main__":
    main()
