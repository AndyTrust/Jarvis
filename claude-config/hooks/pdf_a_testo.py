#!/usr/bin/env python3
"""Gancio PreToolUse: nessun PDF entra intero nel contesto.

Un PDF letto come PDF costa 1.500-3.000 token a pagina. Questo gancio
intercetta Read su un .pdf, lancia l'estrattore deterministico, scrive il
testo in una cache e dice al modello di leggere quello. Risparmio 3-4x.

Se l'estrattore non c'e' o il PDF e' una scansione senza testo, lascia
passare la lettura originale: meglio un PDF caro che un buco silenzioso.
"""
import hashlib, json, os, subprocess, sys
from pathlib import Path

# canonico nella skill: vale per OGNI progetto, non solo per quello dove nacque
ESTRATTORE = Path.home() / ".claude/skills/aggiorna-memoria/strumenti/pdf_testo.py"
CACHE = Path.home() / ".claude/cache/pdf-testo"

def lascia_passare(perche=""):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow",
        "permissionDecisionReason": perche}} if perche else {}))
    sys.exit(0)

def main():
    try:
        dati = json.load(sys.stdin)
    except Exception:
        lascia_passare()
    if dati.get("tool_name") != "Read":
        lascia_passare()
    p = (dati.get("tool_input") or {}).get("file_path") or ""
    if not p.lower().endswith(".pdf"):
        lascia_passare()
    pdf = Path(p).expanduser()
    if not pdf.is_file() or not ESTRATTORE.is_file():
        lascia_passare()

    st = pdf.stat()
    chiave = hashlib.sha1(f"{pdf}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    txt = CACHE / f"{pdf.stem}-{chiave}.txt"

    if not txt.exists():
        r = subprocess.run([sys.executable, str(ESTRATTORE), str(pdf), "--out", str(txt)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not txt.exists():
            lascia_passare()
    corpo = txt.read_text(encoding="utf-8", errors="ignore")
    if len(corpo.strip()) < 40:          # scansione senza testo: serve l'OCR
        lascia_passare("PDF senza testo estraibile (scansione): letto come immagine.")

    pagine = max(1, corpo.count("--- pagina "))
    prima_token = pagine * 2000          # costo reale di un PDF nativo: 1.500-3.000 a pagina
    dopo_token = max(1, len(corpo) // 4)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason":
            f"Il testo di questo PDF e' gia' stato estratto in modo deterministico.\n"
            f"Leggi questo file al posto del PDF:\n\n    {txt}\n\n"
            f"({pagine} pagine · ~{dopo_token} token invece di ~{prima_token}, "
            f"{prima_token/dopo_token:.1f}x in meno). "
            f"Se ti serve davvero il PDF impaginato (grafica, firme, tabelle "
            f"che il testo perde), dillo e si riapre l'originale."}}))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        lascia_passare()
