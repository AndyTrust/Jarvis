#!/usr/bin/env python3
"""Il giro standard di «aggiorna memoria» (2026-10-02): vault e memoria di Claude, parte meccanica.

    python3 giro_memoria.py            # a secco: mostra cosa troverebbe e correggerebbe
    python3 giro_memoria.py --applica  # applica le correzioni sicure

Fa, in ordine:
 1. vault: cartellini mancanti (vault_cartellini), Stato di ogni progetto e Stato generale (stato_vault), link rotti (vault_link_check);
 2. memoria di Claude (~/.claude/projects/*/memory): indice MEMORY.md allineato ai file (righe verso file spariti, note orfane),
    `modified: AAAA-MM-GG HH:MM` su ogni nota, percorsi vecchi (Report, Postino-Report, 01 Diario, VAULT-INDEX, ~/my-agent),
    link [[…]] rotti, note ferme da oltre 60 giorni, cartelle di progetto che non esistono più.
Il giudizio (doppioni col vault, unioni, riscritture) NON è meccanico: lo fa un agente sonnet a partire dal report di questo script,
e quello che esce di scena si SPOSTA in ~/.locale-onedrive/backup-vault-AAAAMMGG/memoria-claude/, non si cancella.
"""
import os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
PROG = HOME / ".claude/projects"
VECCHI = []   # percorsi superati da segnalare: li aggiunge chi riordina la propria memoria


def _percorsi():
    """Vault e repo da strumenti/percorsi_vault.py (Mac e VPS, 04/10/2026); se manca, i percorsi del Mac."""
    for r in (os.environ.get("JARVIS_REPO", ""), str(HOME / "Jarvis"), "/root/jarvis"):
        if r and (Path(os.path.expanduser(r)) / "strumenti/percorsi_vault.py").is_file():
            sys.path.insert(0, str(Path(os.path.expanduser(r)) / "strumenti"))
            try:
                import percorsi_vault as pv
                return pv.vault(), pv.repo()
            except Exception:
                break
            finally:
                sys.path.pop(0)
    sys.path.insert(0, str(Path(__file__).parent))
    from percorsi import memoria, repo
    return memoria(), repo()


VAULT, REPO = _percorsi()
STRUM = REPO / "strumenti"


def esegui(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def fm(testo):
    m = re.match(r"---\n(.*?)\n---\n?", testo, re.S)
    return (m.group(1), testo[m.end():]) if m else (None, testo)


def main(applica):
    print("== 1. Vault")
    for s, a in (("vault_cartellini.py", ["--applica"] if applica else []), ("stato_vault.py", [] if applica else ["--prova"]),
                 ("vault_link_check.py", [])):
        out = esegui(["python3", str(STRUM / s), *a])
        print(f"- {s}: " + out.splitlines()[0] if out else f"- {s}: nessuna uscita")
    print("\n== 2. Memoria di Claude")
    tot = {"orfane": 0, "righe_morte": 0, "senza_data": 0, "vecchi": 0, "ferme": 0, "cartella_morta": 0}
    adesso = datetime.now()
    for mem in sorted(PROG.glob("*/memory")):
        note = [p for p in mem.glob("*.md") if p.name != "MEMORY.md"]
        if not note and not (mem / "MEMORY.md").exists():
            continue
        slug = mem.parent.name
        idx = mem / "MEMORY.md"
        testo_idx = idx.read_text(encoding="utf-8") if idx.exists() else ""
        # cartella di progetto sparita (lo slug usa «-» per «/», quindi si prova solo se il percorso ricostruito esiste)
        cand = Path("/" + slug.lstrip("-").replace("-", "/"))
        morta = len(note) > 0 and not any(Path("/" + "/".join(slug.lstrip("-").split("-")[:i])).exists() for i in range(3, 6))
        if morta:
            tot["cartella_morta"] += 1
            print(f"- {slug[-60:]}: la cartella del progetto sembra non esistere più ({len(note)} note, non si caricano)")
        righe = testo_idx.splitlines()
        nuove = []
        for r in righe:
            m = re.search(r"\]\(([^)]+\.md)\)", r)
            if m and not (mem / m.group(1)).exists():
                tot["righe_morte"] += 1
                print(f"- {slug[-50:]}: riga di indice verso file che non c'è: {m.group(1)}")
                continue
            nuove.append(r)
        citati = set(re.findall(r"\]\(([^)]+\.md)\)", testo_idx))
        for p in note:
            if p.name not in citati:
                tot["orfane"] += 1
                print(f"- {slug[-50:]}: nota fuori dall'indice: {p.name}")
                if applica:
                    campi, _ = fm(p.read_text(encoding="utf-8"))
                    d = re.search(r"^description:\s*(.+)$", campi or "", re.M)
                    nuove.append(f"- [{p.stem}]({p.name}) — {(d.group(1) if d else p.stem)[:140]}")
            t = p.read_text(encoding="utf-8")
            campi, corpo = fm(t)
            if campi is None or "modified:" not in campi:
                tot["senza_data"] += 1
                if applica:
                    ora = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    if campi is None:
                        t = f"---\nname: {p.stem}\ndescription: {p.stem}\nmetadata:\n  modified: {ora}\n---\n{t}"
                    elif "metadata:" in campi:
                        t = t.replace("metadata:\n", f"metadata:\n  modified: {ora}\n", 1)
                    else:
                        t = t.replace("\n---\n", f"\nmetadata:\n  modified: {ora}\n---\n", 1)
                    p.write_text(t, encoding="utf-8")
            if "obsole" not in p.name and any(v in t for v in VECCHI):
                tot["vecchi"] += 1
                print(f"- {slug[-50:]}: {p.name} cita nomi vecchi: " + ", ".join(v for v in VECCHI if v in t))
            if (adesso - datetime.fromtimestamp(p.stat().st_mtime)).days > 60:
                tot["ferme"] += 1
        if applica and nuove != righe:
            idx.write_text("\n".join(nuove) + "\n", encoding="utf-8")
    print("\n== 3. Regole obsolete nei file vivi (obsoleti.json)")
    import json
    reg = json.loads((Path(__file__).resolve().parents[1] / "obsoleti.json").read_text(encoding="utf-8"))
    radici = [VAULT / "Memoria", HOME / ".claude/CLAUDE.md", HOME / ".claude/agents",
              REPO / "CLAUDE.md", HOME / "CLAUDE.md"] + list(PROG.glob("*/memory"))
    saltare = ("schema-archivio-storico-rinominato", "feedback_cose_obsolete", "_archivio", "/Diario/", "/Report/", "/Sessioni/", "_da_cancellare", ".bak", "Controllo comprensione", "Decisioni/2026-10-02")
    for v in reg["voci"]:
        rx = re.compile(v["termine"], re.I)
        trovati = []
        for r in radici:
            for f in ([r] if r.is_file() else (r.rglob("*.md") if r.exists() else [])):
                if any(x in str(f) for x in saltare) or f.name == "MEMORY.md" and "memory" in f.parts:
                    pass
                if any(x in str(f) for x in saltare):
                    continue
                try:
                    t = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for e in v.get("eccezioni", []):
                    t = t.replace(e, "")
                n = len(rx.findall(t))
                if n:
                    trovati.append((n, str(f).replace(str(HOME), "~")[-110:]))
        print(f"- «{v['termine'][:40]}» (dal {v['da']}): {len(trovati)} file" + (" — " + v["perche"][:90] if trovati else ""))
        for n, f in sorted(trovati, reverse=True)[:8]:
            print(f"    {n}× {f}")
    print("\n== 4. Storico di Claude Code: chat, snapshot, backup, hook (Mac e VPS)")
    # l'utente, 2026-10-04: «quando lanciamo aggiorna memoria deve cancellare tutto lo storico passato e obsoleto», anche sulla VPS.
    # Le chat tolte finiscono prima in un archivio compresso (si tiene 30 giorni); mai chat toccate nelle ultime 24 ore o di un processo vivo.
    pul = STRUM / "pulisci_claude.py"
    flag = ["--applica", "--archivia", str(HOME / ".locale-onedrive/backup-claude-storico")] if applica else []
    for riga in [r for r in esegui(["python3", str(pul), *flag]).splitlines() if r.startswith(("Tolti", "Da togliere", "archivio", "hook"))][:6]:
        print(f"- Mac: {riga[:220]}")
    for casa in ("/root", "/home/jarvis"):
        cmd = f"python3 /root/jarvis/strumenti/pulisci_claude.py --home {casa}" + (" --applica --archivia /root/backup-claude-storico" if applica else "")
        try:
            out = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "vps-tuo", cmd], capture_output=True, text=True, timeout=180)
            testo = (out.stdout + out.stderr).strip().splitlines()
        except (subprocess.SubprocessError, OSError) as e:
            testo = [f"VPS non raggiungibile ({type(e).__name__})"]
        for riga in [r for r in testo if r.startswith(("Tolti", "Da togliere", "archivio", "hook", "VPS"))][:6]:
            print(f"- VPS {casa}: {riga[:200]}")
    print("\nRiepilogo:", tot)
    print("Giudizio (doppioni col vault, unioni, riscritture): lo fa un agente sonnet su questo report; i file che escono di scena si SPOSTANO nel backup.")


if __name__ == "__main__":
    main("--applica" in sys.argv)
