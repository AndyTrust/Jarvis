#!/usr/bin/env python3
"""pdf_testo.py — estrae il testo grezzo da un PDF. Zero token.

Un PDF passato intero al modello costa 1.500–3.000 token a pagina.
Lo stesso PDF ridotto a testo ne costa 300–600. Su un fascicolo di 300
pagine sono 600.000 token contro 150.000.

    ./pdf_testo.py fattura.pdf                  -> stampa il testo
    ./pdf_testo.py fattura.pdf --out testo.txt  -> lo scrive su file
    ./pdf_testo.py cartella/ --out estratti/    -> tutta una cartella
    ./pdf_testo.py f.pdf --pagine 1-5           -> solo alcune pagine
    ./pdf_testo.py f.pdf --json                 -> {pagine:[...], meta:{...}}

Usa pdftotext (poppler) se c'e', altrimenti PyMuPDF. Se il PDF e' una
scansione senza testo lo dice invece di restituire il vuoto in silenzio.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

def _range(spec, n):
    if not spec:
        return list(range(1, n + 1))
    out = []
    for pezzo in spec.split(","):
        pezzo = pezzo.strip()
        if "-" in pezzo:
            a, b = pezzo.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(pezzo))
    return [p for p in out if 1 <= p <= n]

def con_pymupdf(path, pagine_spec):
    import fitz
    doc = fitz.open(path)
    nums = _range(pagine_spec, doc.page_count)
    pagine = [{"n": p, "testo": doc[p - 1].get_text("text").strip()} for p in nums]
    meta = {"pagine_totali": doc.page_count, "motore": "pymupdf",
            "titolo": (doc.metadata or {}).get("title") or ""}
    doc.close()
    return pagine, meta

def con_pdftotext(path, pagine_spec):
    import fitz
    n = fitz.open(path).page_count
    nums = _range(pagine_spec, n)
    pagine = []
    for p in nums:
        r = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), path, "-"],
                           capture_output=True, text=True)
        pagine.append({"n": p, "testo": r.stdout.strip()})
    return pagine, {"pagine_totali": n, "motore": "pdftotext -layout", "titolo": ""}

def estrai(path, pagine_spec=None):
    path = str(path)
    try:
        if shutil.which("pdftotext"):
            return con_pdftotext(path, pagine_spec)
    except Exception:
        pass
    return con_pymupdf(path, pagine_spec)

def main():
    ap = argparse.ArgumentParser(description="PDF -> testo grezzo, senza far leggere il PDF al modello")
    ap.add_argument("sorgente", help="un .pdf o una cartella di .pdf")
    ap.add_argument("--out", help="file o cartella di destinazione (senza: stampa a video)")
    ap.add_argument("--pagine", help="es. 1-5 oppure 1,3,7-9")
    ap.add_argument("--json", action="store_true", help="esce in JSON con i metadati")
    a = ap.parse_args()

    src = Path(a.sorgente).expanduser()
    files = sorted(src.rglob("*.pdf")) if src.is_dir() else [src]
    if not files:
        sys.exit(f"nessun PDF in {src}")

    for f in files:
        try:
            pagine, meta = estrai(f, a.pagine)
        except Exception as e:
            print(f"⚠️  {f.name}: {e}", file=sys.stderr)
            continue
        vuote = sum(1 for p in pagine if not p["testo"])
        if vuote == len(pagine):
            print(f"⚠️  {f.name}: nessun testo estraibile — e' una scansione, "
                  f"serve l'OCR (ocrmypdf).", file=sys.stderr)
        corpo = (json.dumps({"file": str(f), "meta": meta, "pagine": pagine},
                            ensure_ascii=False, indent=2) if a.json
                 else "\n\n".join(f"--- pagina {p['n']} ---\n{p['testo']}" for p in pagine))
        if a.out:
            dest = Path(a.out).expanduser()
            if len(files) > 1 or dest.is_dir() or a.sorgente.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
                dest = dest / (f.stem + (".json" if a.json else ".txt"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(corpo, encoding="utf-8")
            prima, dopo = f.stat().st_size, dest.stat().st_size
            print(f"✅ {f.name} -> {dest}  ({prima//1024} kB -> {dopo//1024} kB, "
                  f"~{max(1, dopo//4)} token invece di ~{meta['pagine_totali']*2000})")
        else:
            print(corpo)

if __name__ == "__main__":
    main()
