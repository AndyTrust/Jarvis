#!/usr/bin/env python3
"""Per ogni gruppo di agenti: le azioni di lavoro normali (leggere il progetto, la memoria, scrivere nel progetto, comandi
comuni) passano dai paletti duri? Elenca le negate. Uso: prova_gruppi.py [--vecchio]"""
import os, sys, json, glob
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["CC_BADGE_DIR"] = "/tmp/prova-gruppi-badge"
import conformita as K
H = os.path.expanduser("~")
OD = H + "/Library/CloudStorage/OneDrive"
P = OD + "/Jarvis Brain/Progetti"
M = OD + "/Jarvis Brain/Memoria"
GRUPPI = {
    "Azienda Uno / CRM": P + "/Azienda Uno/CRM140-git",
    "Azienda Uno / Sito My": P + "/Azienda Uno/Sito Azienda Uno",
    "Azienda Due / AZD": P + "/Azienda Due/Azienda_Due",
    "Azienda Due / Social X": P + "/Azienda Due/Social X.com",
    "Vita personale / Jarvis": H + "/Jarvis",
    "Vita personale / Prodotto Uno": P + "/Vita personale/prodotto-uno-Ai-Business",
    "Patrimonio": P + "/Vita personale",
}
mem = glob.glob(H + "/.claude/projects/*/memory")
def azioni(c):
    a = [("Read", {"file_path": c + "/CLAUDE.md"}), ("Glob", {"pattern": "**/*.md", "path": c}), ("Grep", {"pattern": "def ", "path": c}),
         ("Write", {"file_path": c + "/_prova_agente.txt", "content": "x"}), ("Edit", {"file_path": c + "/_prova_agente.txt", "old_string": "x", "new_string": "y"}),
         ("Bash", {"command": f"cd '{c}' && ls -la && git status --short | head"}), ("Bash", {"command": f"cd '{c}' && python3 -c 'print(1)'"}),
         ("Bash", {"command": "python3 ~/Jarvis/strumenti/lavori.py chi"}), ("Bash", {"command": "python3 ~/Jarvis/strumenti/cerca_memoria.py 'prova'"}),
         ("Bash", {"command": f"cat '{M}/00 Comune/Memoria.md' | head -20"}), ("Read", {"file_path": M + "/00 Comune/Memoria.md"}),
         ("Bash", {"command": "ssh vps-tuo 'docker ps --format {{.Names}}; df -h /'"}),
         ("Bash", {"command": f"rm -f '{c}/_prova_agente.txt'"})]
    for m in mem[:1]:
        a += [("Read", {"file_path": m + "/MEMORY.md"}), ("Bash", {"command": f"ls '{m}'; cat '{m}/MEMORY.md' | head"})]
    a += [("Bash", {"command": "cat ~/Jarvis/VERSIONE 2>/dev/null; cat ~/.claude/settings.json | head -30"})]
    return a
tot = neg = 0
for g, c in GRUPPI.items():
    if not os.path.isdir(c): print(f"?? {g}: cartella assente"); continue
    for st, ing in azioni(c):
        tot += 1
        no, alza = K.paletti(st, ing, c)
        if no or alza:
            neg += bool(no)
            print(f"{'NEGA ' if no else 'alto '} {g:28} {st:5} {json.dumps(ing, ensure_ascii=False)[:95]}  -> {no or 'passa al modello (rischio alto)'}")
print(f"{tot} azioni provate, {neg} negate dai paletti duri")
