#!/usr/bin/env python3
"""Fase 0 della skill aggiorna-memoria: fotografa lo stato, non tocca nulla.

Scrive un report markdown in output/inventario-<data>.md con:
- sessioni Claude Code per cartella-progetto (~/.claude/projects)
- file di auto-memoria tecnica di Claude Code (tutti sotto lo slug home)
- note già presenti nel vault Obsidian (memoria condivisa)
- piani in .claude/plans (possibili doppioni da rivedere a mano)
- file .bak-* dentro .claude/skills
"""
import os
import re
import sys
from pathlib import Path
from datetime import datetime

HOME = Path.home()
CLAUDE_PROJECTS = HOME / ".claude" / "projects"
CLAUDE_PLANS = HOME / ".claude" / "plans"
CLAUDE_SKILLS = HOME / ".claude" / "skills"
AUTO_MEMORY = CLAUDE_PROJECTS / "-Users-tu" / "memory"
sys.path.insert(0, str(Path(__file__).parent))
from percorsi import memoria as _memoria
VAULT_MEMORIA = _memoria()

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def du(path):
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def parse_frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


def scan_projects():
    rows = []
    if not CLAUDE_PROJECTS.exists():
        return rows
    for d in sorted(CLAUDE_PROJECTS.iterdir()):
        if not d.is_dir():
            continue
        jsonl_files = list(d.rglob("*.jsonl"))
        size = du(d)
        if jsonl_files:
            mtimes = [f.stat().st_mtime for f in jsonl_files]
            oldest, newest = min(mtimes), max(mtimes)
        else:
            oldest = newest = d.stat().st_mtime
        rows.append({
            "cartella": d.name,
            "size_bytes": size,
            "n_sessioni": len(jsonl_files),
            "piu_vecchia": datetime.fromtimestamp(oldest).strftime("%Y-%m-%d"),
            "piu_recente": datetime.fromtimestamp(newest).strftime("%Y-%m-%d"),
        })
    return rows


def scan_auto_memory():
    rows = []
    if not AUTO_MEMORY.exists():
        return rows
    for f in sorted(AUTO_MEMORY.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        rows.append({
            "file": f.name,
            "name": fm.get("name", ""),
            "type": fm.get("type", ""),
            "description": fm.get("description", ""),
        })
    return rows


def scan_vault():
    rows = []
    if not VAULT_MEMORIA.exists():
        return rows
    for f in sorted(VAULT_MEMORIA.rglob("*.md")):
        rel = f.relative_to(VAULT_MEMORIA)
        rows.append({
            "path": str(rel),
            "size_bytes": f.stat().st_size,
            "modificato": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"),
        })
    return rows


def scan_plans():
    rows = []
    if not CLAUDE_PLANS.exists():
        return rows
    for f in sorted(CLAUDE_PLANS.glob("*.md")):
        rows.append({
            "file": f.name,
            "size_bytes": f.stat().st_size,
            "modificato": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return rows


def scan_bak():
    rows = []
    if not CLAUDE_SKILLS.exists():
        return rows
    for f in CLAUDE_SKILLS.rglob("*.bak-*"):
        rows.append({
            "file": str(f.relative_to(CLAUDE_SKILLS)),
            "size_bytes": f.stat().st_size,
            "modificato": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"),
        })
    return sorted(rows, key=lambda r: r["file"])


def table(headers, rows, keys):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(r[k]) for k in keys) + " |")
    return "\n".join(out)


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    progetti = scan_projects()
    auto_mem = scan_auto_memory()
    vault = scan_vault()
    piani = scan_plans()
    bak = scan_bak()

    tot_size = sum(r["size_bytes"] for r in progetti)
    tot_sessioni = sum(r["n_sessioni"] for r in progetti)

    parts = []
    parts.append(f"# Inventario memoria — {now}")
    parts.append("")
    parts.append("Fase 0 della skill aggiorna-memoria. Sola lettura, nessun file toccato.")
    parts.append("")
    parts.append(f"## Sessioni Claude Code (~/.claude/projects) — {human(tot_size)} totali, "
                  f"{len(progetti)} cartelle, {tot_sessioni} sessioni")
    parts.append("")
    parts.append(table(
        ["Cartella", "Dimensione", "N. sessioni", "Più vecchia", "Più recente"],
        [{**r, "size_bytes": human(r["size_bytes"])} for r in sorted(progetti, key=lambda r: -r["size_bytes"])],
        ["cartella", "size_bytes", "n_sessioni", "piu_vecchia", "piu_recente"],
    ))
    parts.append("")
    parts.append(f"## Auto-memoria tecnica di Claude Code — {len(auto_mem)} file")
    parts.append("")
    parts.append("Tutti sotto lo slug «home» (`-Users-tu`), non nel progetto/spazio "
                  "giusto — bug noto, vedi `brain/SKILL.md`. Da smistare per spazio (fase 2).")
    parts.append("")
    parts.append(table(
        ["File", "type", "description"],
        auto_mem,
        ["file", "type", "description"],
    ))
    parts.append("")
    parts.append(f"## Note nel vault (memoria condivisa) — {len(vault)} file")
    parts.append("")
    parts.append(table(
        ["Percorso", "Dimensione", "Modificato"],
        [{**r, "size_bytes": human(r["size_bytes"])} for r in vault],
        ["path", "size_bytes", "modificato"],
    ))
    parts.append("")
    parts.append(f"## Piani in .claude/plans — {len(piani)} file (possibili doppioni, da rivedere a mano)")
    parts.append("")
    parts.append(table(
        ["File", "Dimensione", "Modificato"],
        [{**r, "size_bytes": human(r["size_bytes"])} for r in piani],
        ["file", "size_bytes", "modificato"],
    ))
    parts.append("")
    parts.append(f"## File .bak-* dentro .claude/skills — {len(bak)} file")
    parts.append("")
    parts.append(table(
        ["File", "Dimensione", "Modificato"],
        [{**r, "size_bytes": human(r["size_bytes"])} for r in bak],
        ["file", "size_bytes", "modificato"],
    ))
    parts.append("")

    out_dir = Path(__file__).resolve().parent.parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"inventario-{datetime.now().strftime('%Y%m%d-%H%M')}.md"
    out_path.write_text("\n".join(parts), encoding="utf-8")

    print(f"Scritto: {out_path}")
    print(f"Sessioni Claude Code: {human(tot_size)} in {len(progetti)} cartelle, {tot_sessioni} sessioni totali")
    print(f"Auto-memoria tecnica: {len(auto_mem)} file (tutti da smistare)")
    print(f"Note nel vault: {len(vault)}")
    print(f"Piani: {len(piani)} file")
    print(f"File .bak-* in skills: {len(bak)} file")


if __name__ == "__main__":
    main()
