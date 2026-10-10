#!/usr/bin/env python3
"""Un nome assegnato dentro do_POST/do_GET di server.py non deve coincidere con un nome globale usato nello stesso metodo.
Il 2026-10-04 una variabile locale `azione` ha nascosto la funzione `azione()` e ha rotto /api/azione (le azioni della pagina,
compresi i permessi) per circa un'ora: Python considera locale un nome assegnato ovunque nella funzione."""
import ast
import sys
from pathlib import Path

src = (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
tree = ast.parse(src)
glob = set()
for n in tree.body:
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        glob.add(n.name)
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            glob |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
    elif isinstance(n, (ast.Import, ast.ImportFrom)):
        glob |= {(a.asname or a.name).split(".")[0] for a in n.names}
errori = []
for c in ast.walk(tree):
    if isinstance(c, ast.ClassDef):
        for f in c.body:
            if isinstance(f, ast.FunctionDef) and f.name in ("do_GET", "do_POST", "do_PUT", "do_DELETE"):
                assegnati, usati = set(), set()
                for x in ast.walk(f):
                    if isinstance(x, ast.Name):
                        (assegnati if isinstance(x.ctx, (ast.Store, ast.Del)) else usati).add(x.id)
                    elif isinstance(x, (ast.Import, ast.ImportFrom)):
                        assegnati |= {(a.asname or a.name).split(".")[0] for a in x.names}
                errori += [f"{c.name}.{f.name}: «{n}» è assegnato e anche usato come nome globale" for n in sorted(assegnati & glob & usati)]
for e in errori:
    print("ERRORE", e)
print("ok: nessun nome nascosto" if not errori else f"{len(errori)} errori")
sys.exit(1 if errori else 0)
