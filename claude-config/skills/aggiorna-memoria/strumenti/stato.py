#!/usr/bin/env python3
"""stato.py — a che punto siamo, in un colpo solo. Zero token.

Lo legge `/claude-md` all'apertura di una chat. Risponde a tre domande prima
che il modello debba fare un solo `ls`: il progetto è nuovo o no, dove eravamo
rimasti, e cosa è cambiato da allora.

    ./stato.py <cartella>          il quadro
    ./stato.py <cartella> --json
"""
import argparse, json, os, re, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

SALTA = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist",
         "build", ".codegraph", "graphify-out", "vendor", "target", "Pods"}

def sh(cmd, cwd):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=8)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""

def recenti(base: Path, giorni=7, quanti=12):
    limite = (datetime.now() - timedelta(days=giorni)).timestamp()
    out = []
    for r, ds, fs in os.walk(base):
        ds[:] = [d for d in ds if d not in SALTA and not d.startswith(".")]
        for f in fs:
            if f.startswith("."):
                continue
            p = Path(r) / f
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m > limite:
                out.append((m, str(p.relative_to(base))))
    out.sort(reverse=True)
    return [x[1] for x in out[:quanti]], len(out)


def pota_stato(stato, tenute_fatte=6):
    """Nel modo gancio lo stato va accorciato DOVE COSTA E NON SERVE.

    9/09/2026 — il gancio SessionStart stampava 15 KB a ogni apertura di chat,
    e 121 delle sue righe erano voci di «Fatto» degli ultimi due mesi: roba
    che il modello non deve decidere niente, ma che paga a ogni messaggio
    perche' entra nel contesto iniziale. E' il context bloat che questa skill
    esiste per combattere, prodotto dalla skill stessa.

    Cosa resta intero e perche':
      · «Errori da non ripetere» — TUTTI. Sono le righe che valgono di piu':
        senza, la sessione nuova ricommette lo stesso errore, e ricommetterlo
        costa mille volte quello che costa leggerlo.
      · «Da fare» — TUTTE. Sono decisioni aperte: tagliarne una vuol dire
        farla sparire.
      · «Fatto» — solo le ultime, che sono in fondo all'elenco perche' si
        accodano. Le vecchie restano in MEMORIA.md, a un `cat` di distanza.
    """
    out, sez, fatte = [], None, []
    for l in stato:
        t = l.strip()
        if t.lower().startswith("### "):
            if sez == "fatto":
                out.extend(fatte[-tenute_fatte:])
                if len(fatte) > tenute_fatte:
                    out.append(f"  …e altre {len(fatte)-tenute_fatte} in .claude/memoria/MEMORIA.md")
                fatte = []
            sez = t[4:].strip().lower()
            out.append(l); continue
        if sez == "fatto" and t.startswith("- "):
            fatte.append(l); continue
        out.append(l)
    if sez == "fatto":
        out.extend(fatte[-tenute_fatte:])
        if len(fatte) > tenute_fatte:
            out.append(f"  …e altre {len(fatte)-tenute_fatte} in .claude/memoria/MEMORIA.md")
    return out


def leggi_memoria(mem: Path):
    """MEMORIA.md: lo stato in cima, poi una riga per fatto"""
    f = mem / "MEMORIA.md"
    if not f.is_file():
        return None
    t = f.read_text(encoding="utf-8", errors="ignore")
    stato, righe, dentro = [], [], False
    for l in t.splitlines():
        if l.strip().lower().startswith("## a che punto siamo"):
            dentro = True; continue
        if dentro and l.startswith("## "):
            dentro = False
        if dentro and l.strip():
            stato.append(l.rstrip())
        if l.strip().startswith("- ["):
            righe.append(l.strip())
    return {"stato": stato, "fatti": righe,
            "file": sorted(p.name for p in mem.glob("*.md") if p.name != "MEMORIA.md"),
            "aggiornata": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}

def main():
    ap = argparse.ArgumentParser(description="a che punto siamo su questo progetto")
    ap.add_argument("cartella", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hook", action="store_true",
                    help="modo gancio: tace se non c'è niente da dire, e resta corto")
    a = ap.parse_args()

    base = Path(a.cartella).expanduser().resolve()
    if not base.is_dir():
        sys.exit(f"{base} non è una cartella")

    mem_locale = base / ".claude" / "memoria"
    m = leggi_memoria(mem_locale)
    # stesso slug di salva_brain.py: minuscole, tutto cio' che non e'
    # alfanumerico diventa un trattino. Prima cercava un nome mentre
    # salva_brain ne scriveva un altro, e l'indice risultava mancante.
    _s = __import__("re").sub(r"-+", "-",
        __import__("re").sub(r"[^a-z0-9]+", "-", base.name.lower().strip())).strip("-")
    generale = Path.home() / ".ai-memory" / "projects" / f"{_s}.md"
    if not generale.is_file():
        cand = list((Path.home() / ".ai-memory" / "projects").glob("*.md")) if (Path.home()/".ai-memory/projects").is_dir() else []
        generale = next((c for c in cand if c.stem.lower().replace("-", "") == base.name.lower().replace("-", "").replace("_", "").replace(" ", "")), None)

    cm = base / "CLAUDE.md"
    righe_cm = len(cm.read_text(encoding="utf-8", errors="ignore").splitlines()) if cm.is_file() else 0
    rec, n_rec = recenti(base)
    ramo = sh(["git", "branch", "--show-current"], base)
    sporco = sh(["git", "status", "--porcelain"], base)
    ultimo = sh(["git", "log", "-1", "--format=%ad · %s", "--date=short"], base)

    nuovo = m is None and righe_cm == 0

    # Modo gancio: in una cartella qualsiasi non deve dire niente.
    # Parla solo se il progetto è impiantato, e in poche righe.
    if a.hook:
        if nuovo or (m is None and righe_cm == 0):
            return
        out = [f"📁 {base.name}"]
        if m and m["stato"]:
            out += [l for l in pota_stato(m["stato"]) if l.strip()]
        if m and m["fatti"]:
            out.append(f"Già in memoria ({len(m['fatti'])}): "
                       + " · ".join(re.findall(r"\[([^\]]+)\]", " ".join(m["fatti"]))))
        elif m is None:
            out.append("Nessuna memoria: c'è il CLAUDE.md ma non la storia. "
                       "Alla fine della sessione usa /salva-brain.")
        if righe_cm > 200:
            out.append(f"⚠️ CLAUDE.md {righe_cm} righe: oltre le 200, va sfoltito.")
        print("\n".join(out))
        return

    if a.json:
        print(json.dumps({"progetto": base.name, "nuovo": nuovo, "memoria": m,
                          "claude_md_righe": righe_cm, "file_recenti": rec,
                          "git": {"ramo": ramo, "sporco": bool(sporco), "ultimo": ultimo}},
                         ensure_ascii=False, indent=2, default=str))
        return

    print(f"\n╭─ {base.name}")
    if nuovo:
        print("│  🆕 PROGETTO NUOVO — niente memoria, niente CLAUDE.md")
        print("│     impianta con:  ~/.claude/skills/aggiorna-memoria/strumenti/impianta.py . --conferma")
        print("╰─"); return

    if m:
        print(f"│  memoria: {len(m['file'])} fatti · aggiornata {m['aggiornata']}")
    else:
        print("│  ⚠️  nessuna memoria in .claude/memoria/ — c'è il CLAUDE.md ma non la storia")
    print(f"│  CLAUDE.md: {righe_cm} righe" + ("  🔴 oltre 200, va sfoltito" if righe_cm > 200 else ""))
    if ramo:
        print(f"│  git: {ramo}" + (" · modifiche non committate" if sporco else " · pulito"))
        if ultimo: print(f"│       ultimo commit {ultimo}")
    print("╰─")

    if m and m["stato"]:
        print("\nA CHE PUNTO SIAMO\n" + "─" * 58)
        for l in m["stato"]:
            print(l)

    if m and m["fatti"]:
        print("\nCOSA SAPPIAMO GIÀ (non riscoprirlo)\n" + "─" * 58)
        for l in m["fatti"]:
            print("  " + l)

    if rec:
        print(f"\nTOCCATO NEGLI ULTIMI 7 GIORNI ({n_rec} file)\n" + "─" * 58)
        for f in rec:
            print("  " + f)
        if n_rec > len(rec):
            print(f"  … e altri {n_rec - len(rec)}")

    if generale and generale.is_file():
        print(f"\nMemoria generale: {generale}")
    print("\nSe la richiesta riguarda cose già in memoria, leggi il file del fatto, "
          "non riesplorare la cartella.")

if __name__ == "__main__":
    main()
