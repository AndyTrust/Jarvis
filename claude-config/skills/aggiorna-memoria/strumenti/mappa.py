#!/usr/bin/env python3
"""mappa.py — l'albero ASCII di una cartella. Deterministico, zero token.

Serve a far vedere una struttura senza che il modello debba scoprirla con
venti `ls` di fila: un albero costa qualche centinaio di token, venti `ls`
ne costano migliaia e a volte sbagliano strada.

    ./mappa.py .                          albero della cartella corrente
    ./mappa.py ~/Progetti/sito -p 3     fino a tre livelli
    ./mappa.py . --file                   mostra anche i file (di suo: solo cartelle)
    ./mappa.py . --json                   indice a macchina, per il grafo
    ./mappa.py . --out MAPPA.md           lo scrive in un file
"""
import argparse, json, os, sys
from pathlib import Path

SALTA = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next",
         "dist", "build", ".DS_Store", ".pytest_cache", ".mypy_cache",
         ".thumbnail", ".idea", ".vscode"}

def taglia(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024: return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.0f}TB"

def peso(d):
    t = 0
    for r, ds, fs in os.walk(d):
        ds[:] = [x for x in ds if x not in SALTA]
        for f in fs:
            try: t += (Path(r) / f).stat().st_size
            except OSError: pass
    return t

def conta(d):
    n = 0
    for r, ds, fs in os.walk(d):
        ds[:] = [x for x in ds if x not in SALTA]
        n += len([f for f in fs if f not in SALTA])
    return n

def albero(base, prof, mostra_file, righe, pref="", liv=0):
    if liv >= prof: return
    try:
        voci = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return
    voci = [v for v in voci if v.name not in SALTA]
    if not mostra_file:
        voci = [v for v in voci if v.is_dir()]
    for i, v in enumerate(voci):
        ultimo = i == len(voci) - 1
        gancio = "└── " if ultimo else "├── "
        if v.is_dir():
            righe.append(f"{pref}{gancio}{v.name}/  ({conta(v)} file · {taglia(peso(v))})")
            albero(v, prof, mostra_file, righe, pref + ("    " if ultimo else "│   "), liv + 1)
        else:
            try: s = taglia(v.stat().st_size)
            except OSError: s = "?"
            righe.append(f"{pref}{gancio}{v.name}  ({s})")

def indice(base):
    out = []
    for r, ds, fs in os.walk(base):
        ds[:] = [x for x in ds if x not in SALTA]
        for f in fs:
            if f in SALTA: continue
            p = Path(r) / f
            try: st = p.stat()
            except OSError: continue
            out.append({"percorso": str(p.relative_to(base)), "byte": st.st_size,
                        "modificato": int(st.st_mtime), "estensione": p.suffix.lower()})
    return out

def main():
    ap = argparse.ArgumentParser(description="albero ASCII di una cartella")
    ap.add_argument("cartella", nargs="?", default=".")
    ap.add_argument("-p", "--profondita", type=int, default=2)
    ap.add_argument("--file", action="store_true", help="mostra anche i file")
    ap.add_argument("--json", action="store_true", help="indice JSON invece dell'albero")
    ap.add_argument("--out", help="scrivi su file invece che a video")
    a = ap.parse_args()

    base = Path(a.cartella).expanduser().resolve()
    if not base.is_dir(): sys.exit(f"{base} non e' una cartella")

    if a.json:
        testo = json.dumps({"radice": str(base), "file": indice(base)}, ensure_ascii=False, indent=2)
    else:
        righe = [f"{base.name}/  ({conta(base)} file · {taglia(peso(base))})"]
        albero(base, a.profondita, a.file, righe)
        testo = "\n".join(righe)

    if a.out:
        Path(a.out).expanduser().write_text(testo + "\n", encoding="utf-8")
        print(f"✅ scritto in {a.out} ({len(testo)} caratteri, ~{len(testo)//4} token)")
    else:
        print(testo)

if __name__ == "__main__":
    main()
