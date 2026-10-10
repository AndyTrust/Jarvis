#!/usr/bin/env python3
"""impianta.py — mette un progetto nelle condizioni di costare poco. Zero token.

Misura la cartella, decide il decidibile e prepara l'impianto: gli strumenti
deterministici, il gancio dei PDF, lo scheletro dei CLAUDE.md, i grafi se
convengono. Quello che resta è il giudizio, e lo scrive un umano (o il modello,
guidato da SKILL.md).

    ./impianta.py <cartella>                # misura e dice cosa farebbe
    ./impianta.py <cartella> --conferma     # lo fa
    ./impianta.py <cartella> --solo-misura  # solo il quadro, non tocca niente
"""
import argparse, json, os, shutil, subprocess, sys
from collections import Counter
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SALTA_DIR = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist",
             "build", ".pytest_cache", ".mypy_cache", ".idea", ".vscode", ".codegraph",
             "graphify-out", "vendor", ".terraform", "target", "Pods"}
CODICE = {".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".rb", ".go", ".rs", ".java",
          ".kt", ".swift", ".c", ".cpp", ".cs", ".sh", ".sql", ".vue", ".svelte"}
TESTO = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css"}
GROSSI = {".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".mp4", ".mov", ".pdf",
          ".psd", ".ai", ".webp", ".heic", ".tgz"}
SOGLIA_GRAFO = 500      # sotto, un grafo costa più di quanto fa risparmiare

def cammina(base: Path):
    for r, ds, fs in os.walk(base):
        ds[:] = [d for d in ds if d not in SALTA_DIR and not d.startswith(".")]
        for f in fs:
            if f.startswith("."):
                continue
            yield Path(r) / f

def misura(base: Path):
    est, peso_ext, n, peso = Counter(), Counter(), 0, 0
    vecchie = []
    for p in cammina(base):
        try:
            s = p.stat().st_size
        except OSError:
            continue
        e = p.suffix.lower()
        est[e] += 1; peso_ext[e] += s; n += 1; peso += s
    for d in base.rglob("*"):
        if d.is_dir() and d.name.lower() in ("_to_delete", "_prova", "_old", "_vecchio", "backup"):
            k = sum(1 for _ in d.rglob("*") if _.is_file())
            if k: vecchie.append((d.relative_to(base), k))
    codice = sum(v for k, v in est.items() if k in CODICE)
    testo = sum(v for k, v in est.items() if k in TESTO)
    return {"file": n, "byte": peso, "codice": codice, "testo": testo,
            "indicizzabili": codice + testo,
            "linguaggi": [k for k, _ in est.most_common() if k in CODICE][:6],
            "pdf": est.get(".pdf", 0),
            "zavorra": sorted(((k, v, peso_ext[k]) for k, v in est.items() if k in GROSSI),
                              key=lambda x: -x[2])[:5],
            "cartelle_vecchie": vecchie,
            "cartelle_cima": sorted([d.name for d in base.iterdir()
                                     if d.is_dir() and d.name not in SALTA_DIR
                                     and not d.name.startswith(".")])}

def taglia(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024: return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} TB"

IGNORA = """# generati e pesanti: fuori dai grafi e dagli indici
node_modules/
__pycache__/
.venv/
dist/
build/
.codegraph/
graphify-out/
.DS_Store
*.zip
*.tar.gz
*.png
*.jpg
*.jpeg
*.mp4
*.webp
"""

def scheletro(nome, m):
    lingue = ", ".join(m["linguaggi"]) or "—"
    righe = [f"# {nome} — indice", "",
        "Questo file è un **indice**, non un manuale: viene riletto a ogni",
        "messaggio. Il dettaglio sta nei `CLAUDE.md` delle sottocartelle, che",
        "vengono letti solo quando si entra davvero lì.",
        "", "⚠️ **Tenerlo sotto le 200 righe.** Un `CLAUDE.md` da 4.000 token",
        "brucia 32.000 token dopo otto messaggi.", "",
        f"<!-- impiantato il {__import__('datetime').date.today()} · "
        f"{m['file']} file · {taglia(m['byte'])} · {lingue} -->", "",
        "## Dove sta cosa", "", "| Cartella | Contiene | Dettaglio in |", "|---|---|---|"]
    for d in m["cartelle_cima"][:12]:
        righe.append(f"| `{d}/` | DA SCRIVERE | `{d}/CLAUDE.md` |")
    righe += ["", "## Le regole che rompono qualcosa", "",
        "DA SCRIVERE: le tre o quattro cose che, se sbagliate, rompono il progetto.",
        "Non «usa nomi chiari»: cose come «dopo aver copiato un modulo rimetti i",
        "permessi, altrimenti salta in silenzio».", "",
        "## Strumenti: prima il codice, poi il modello", "",
        "Il giudizio al modello, l'esecuzione ripetibile al codice.", "", "```bash",
        "strumenti/pdf_testo.py <file.pdf>   # PDF → testo (gancio attivo)",
        "strumenti/mappa.py . -p 2           # albero ASCII della cartella", "```", "",
        "**Prima di generare HTML/CSS/React, mostra un diagramma ASCII del layout",
        "e aspetta l'ok.** Correggere un disegno costa niente; rigenerare",
        "trecento righe perché un pulsante va spostato costa migliaia di token.", ""]
    return "\n".join(righe) + "\n"

def main():
    ap = argparse.ArgumentParser(description="prepara un progetto a costare poco")
    ap.add_argument("cartella", nargs="?", default=".")
    ap.add_argument("--conferma", action="store_true")
    ap.add_argument("--solo-misura", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    base = Path(a.cartella).expanduser().resolve()
    if not base.is_dir(): sys.exit(f"{base} non è una cartella")
    m = misura(base)
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2, default=str)); return

    fai = a.conferma and not a.solo_misura
    print(f"\n╭─ {base.name}")
    print(f"│  {m['file']} file · {taglia(m['byte'])}")
    print(f"│  {m['codice']} di codice · {m['testo']} di testo · "
          f"{m['indicizzabili']} indicizzabili")
    print(f"│  linguaggi: {', '.join(m['linguaggi']) or '—'}")
    print("╰─")

    print("\nCOSA SERVE\n" + "─" * 58)
    fatti = []

    # 1. strumenti
    dest = base / "strumenti"
    if (base / "AZD-AZD" / "strumenti").is_dir(): dest = base / "AZD-AZD" / "strumenti"
    esistono = dest.is_dir() and any(dest.glob("*.py"))
    print(f"{'✓' if esistono else '+'} strumenti deterministici → {dest.relative_to(base)}/")
    if fai and not esistono:
        dest.mkdir(parents=True, exist_ok=True)
        for f in (SKILL / "strumenti").glob("*.py"):
            if f.name != "impianta.py":
                shutil.copy2(f, dest / f.name); os.chmod(dest / f.name, 0o755)
        fatti.append(f"strumenti in {dest.relative_to(base)}/")

    # 1bis. memoria di progetto — dentro il progetto, viaggia con lui
    mem = base / ".claude" / "memoria"
    c_e = (mem / "MEMORIA.md").is_file()
    print(f"{'✓' if c_e else '+'} memoria di progetto → .claude/memoria/")
    if fai and not c_e:
        subprocess.run([sys.executable, str(SKILL/"strumenti"/"salva_brain.py"), str(base),
                        "--stato", "Progetto appena impiantato. Da scrivere: che cos'è, "
                        "a che punto è, cosa è aperto."], capture_output=True)
        fatti.append(".claude/memoria/")

    # 2. gancio PDF
    gancio = Path.home() / ".claude/hooks/pdf_a_testo.py"
    attivo = gancio.is_file()
    print(f"{'✓' if attivo else '!'} gancio PDF{'' if attivo else ' — MANCA, vedi SKILL.md'}"
          f"   ({m['pdf']} PDF nel progetto)")

    # 3. CLAUDE.md
    cm = base / "CLAUDE.md"
    if cm.exists():
        n = len(cm.read_text(encoding='utf-8', errors='ignore').splitlines())
        print(f"{'✓' if n <= 200 else '!'} CLAUDE.md esiste — {n} righe"
              f"{'' if n <= 200 else '  🔴 OLTRE 200: va sfoltito'}")
    else:
        print("+ CLAUDE.md da scrivere (scheletro pronto, il contenuto è giudizio)")
        if fai: cm.write_text(scheletro(base.name, m), encoding="utf-8"); fatti.append("CLAUDE.md")

    # 4. ignore
    for nome in (".gitignore", ".codegraphignore"):
        f = base / nome
        print(f"{'✓' if f.exists() else '+'} {nome}")
        if fai and not f.exists(): f.write_text(IGNORA, encoding="utf-8"); fatti.append(nome)

    # 5. grafi
    n = m["indicizzabili"]
    if n >= SOGLIA_GRAFO:
        pronto = (base / ".codegraph").is_dir()
        print(f"{'✓' if pronto else '+'} grafi: {n} file indicizzabili ≥ {SOGLIA_GRAFO} → convengono")
        if fai and not pronto:
            for cmd, ok in (("codegraph init .", "codegraph"), ("graphify update . --no-cluster", "graphify")):
                if shutil.which(ok):
                    print(f"   … {cmd}")
                    subprocess.run(cmd.split(), cwd=base, capture_output=True)
                    fatti.append(cmd)
                else:
                    print(f"   ⚠️  {ok} non installato")
    else:
        print(f"– grafi: solo {n} file indicizzabili (< {SOGLIA_GRAFO}) → "
              f"costerebbero più di quanto farebbero risparmiare")

    # 6. zavorra
    if m["cartelle_vecchie"]:
        tot = sum(k for _, k in m["cartelle_vecchie"])
        print(f"! {tot} file in cartelle di scarto: "
              + ", ".join(f"{d} ({k})" for d, k in m["cartelle_vecchie"][:4]))
        print("   verifica che siano superati, POI cancella (mai al contrario)")
    if m["zavorra"]:
        print("  pesi morti: " + " · ".join(f"{e} ×{c} = {taglia(b)}" for e, c, b in m["zavorra"]))

    print("─" * 58)
    if fai:
        print(f"\n✅ fatto: {', '.join(fatti) if fatti else 'niente da fare, era già a posto'}")
        print("Adesso il giudizio: riempi le tabelle «DA SCRIVERE» del CLAUDE.md.")
    elif not a.solo_misura:
        print("\nProva a vuoto. Aggiungi --conferma per farlo davvero.")

if __name__ == "__main__":
    main()
