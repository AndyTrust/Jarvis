#!/usr/bin/env python3
"""Controlla i link del vault dopo il riordino: [[wikilink]], file:/// e obsidian://open (2026-10-02).

    python3 vault_link_check.py [--ripara]   # --ripara riscrive i prefissi vecchi noti (elenco RIPARA)
"""
import re, sys, collections
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crea_progetto as _cp  # noqa: E402

B = _cp.memoria()                         # la memoria condivisa (~/.jarvis/percorsi.json)
M = B
stems = collections.defaultdict(list)
for p in B.rglob("*") if B.is_dir() else []:
    if p.suffix in (".md", ".pdf", ".txt", ".png", ".jpg") and "_da_cancellare" not in p.parts:
        stems[p.stem].append(p); stems[p.name].append(p)
RIPARA = []                               # prefissi vecchi da riscrivere dopo uno spostamento: (vecchio, nuovo)
rotti = collections.Counter(); esempi = collections.defaultdict(list); riparati = 0
ripara = "--ripara" in sys.argv
for p in sorted(M.rglob("*.md")) if M.is_dir() else []:
    if ".claude" in p.parts or "_archivio" in p.parts:
        continue
    t = p.read_text(encoding="utf-8", errors="ignore")
    orig = t
    if ripara:
        for a, b in RIPARA:
            t = t.replace(a, b)
        if t != orig:
            p.write_text(t, encoding="utf-8"); riparati += 1
    for m in re.finditer(r"\[\[([^\]|#]+)", t):
        n = m.group(1).strip().rstrip("\\")
        if n and not (stems.get(n) or stems.get(Path(n).stem) or (B / n).exists() or (M / n).exists() or (B / (n + ".md")).exists() or (M / (n + ".md")).exists()):
            rotti["wikilink"] += 1; esempi["wikilink"].append((p.name, n))
    for m in re.finditer(r"\(file://([^)\s]+)\)", t):
        q = Path(unquote(m.group(1)))
        if not q.exists():
            rotti["file://"] += 1; esempi["file://"].append((p.name, str(q)[-90:]))
    for m in re.finditer(r"obsidian://open\?vault=[^&]+&file=([^)\s\"]+)", t):
        f = unquote(m.group(1))
        if not ((B / f).exists() or (B / (f + ".md")).exists()):
            rotti["obsidian://"] += 1; esempi["obsidian://"].append((p.name, f[-90:]))
print("riparati", riparati, "file;" , "link rotti:", dict(rotti))
for k, v in esempi.items():
    c = collections.Counter(x[1] for x in v)
    print(f"-- {k}: {len(v)} (primi 12 diversi)")
    for n, q in c.most_common(12):
        print("   ", q, " ×", n)
