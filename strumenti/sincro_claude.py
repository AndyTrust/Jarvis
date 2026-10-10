#!/usr/bin/env python3
"""Tiene allineati ~/.claude (quello che Claude Code carica davvero) e claude-config/ (la copia nel repository di Jarvis):
ganci (hooks/), agenti di casa (agents/) e skill «aggiorna-memoria». Senza allineamento Claude parte con agenti e ganci
vecchi e Jarvis si comporta in modo diverso da come è scritto (l'utente, 29/09/2026).
Regola: vince il file più recente (data di modifica). Mai cancella niente; di ogni file sostituito tiene una copia .bak-AAAAMMGG.
  python3 strumenti/sincro_claude.py                 mostra le differenze
  python3 strumenti/sincro_claude.py --applica       allinea in tutti e due i versi (il più recente vince)
  python3 strumenti/sincro_claude.py --verso-repo    solo ~/.claude → repository (lo usa il battito dei 30 minuti)
  python3 strumenti/sincro_claude.py --verso-casa    solo repository → ~/.claude (dopo un git pull)
Con --home CARTELLA si prova su una casa finta."""
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
LIVE = HOME / ".claude"
APPLICA = any(a in sys.argv for a in ("--applica", "--verso-repo", "--verso-casa"))
VERSO_REPO = "--verso-repo" in sys.argv or "--applica" in sys.argv
VERSO_CASA = "--verso-casa" in sys.argv or "--applica" in sys.argv
# (cartella in ~/.claude, cartella in claude-config, estensioni)
COPPIE = [("hooks", "hooks", {".py"}), ("agents", "agents", {".md"}),
          ("skills/aggiorna-memoria", "skills/aggiorna-memoria", {".py", ".md"})] + [
          # 2026-10-04 sera: le sei skill di Jarvis viaggiano con il repo (la VPS le aveva perse: menu «/» con 4 voci)
          (f"skills/{s}", f"skills/{s}", {".py", ".md"}) for s in
          ("brainstorming", "riunione-agenti", "systematic-debugging", "verification-before-completion",
           "writing-plans", "writing-skills")]
SALTA = ("bozze", "output", "__pycache__")
STAMPA = time.strftime("%Y%m%d")
fatti = []


def file_di(base: Path, estensioni):
    if not base.is_dir():
        return {}
    return {f.relative_to(base).as_posix(): f for f in base.rglob("*")
            if f.is_file() and f.suffix in estensioni and not any(s in f.parts for s in SALTA) and ".bak" not in f.name}


def copia(src: Path, dst: Path, verso: str):
    fatti.append(f"{verso}: {dst}")
    print(("" if APPLICA else "[prova] ") + f"{verso}: {dst.relative_to(dst.anchor) if False else dst}")
    if not APPLICA:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copy2(dst, dst.with_name(dst.name + f".bak-{STAMPA}"))
    shutil.copy2(src, dst)


def main():
    if not CONF.is_dir():
        sys.exit(f"manca {CONF}")
    for live_rel, repo_rel, est in COPPIE:
        a, b = file_di(LIVE / live_rel, est), file_di(CONF / repo_rel, est)
        for nome in sorted(set(a) | set(b)):
            fa, fb = a.get(nome), b.get(nome)
            if fa and fb and fa.read_bytes() == fb.read_bytes():
                continue
            if fa and not fb:
                if VERSO_REPO or not APPLICA:
                    copia(fa, CONF / repo_rel / nome, "→ repository (nuovo)")
            elif fb and not fa:
                if VERSO_CASA or not APPLICA:
                    copia(fb, LIVE / live_rel / nome, "→ ~/.claude (nuovo)")
            elif fa.stat().st_mtime >= fb.stat().st_mtime:
                if VERSO_REPO or not APPLICA:
                    copia(fa, fb, "→ repository (~/.claude è più recente)")
            else:
                if VERSO_CASA or not APPLICA:
                    copia(fb, fa, "→ ~/.claude (il repository è più recente)")
    print(f"{'Allineati' if APPLICA else 'Da allineare'}: {len(fatti)} file" if fatti else "~/.claude e claude-config sono allineati")


if __name__ == "__main__":
    main()
