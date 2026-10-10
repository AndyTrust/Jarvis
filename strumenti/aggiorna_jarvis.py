#!/usr/bin/env python3
"""Aggiorna il SOFTWARE di Jarvis (codice, grafica, pagine, documentazione) dal repository da cui è stato scaricato, senza mai
toccare le cose tue: impostazioni, agenti, memoria, documenti, chiavi (l'utente, 29/09/2026: come un normale CRM che si aggiorna).

Cosa NON si tocca mai (PROTETTI): command-center/{configurazione,spazi,pannello,assistenza,...}.json, .env*, .claude/ (agenti, memoria,
impostazioni), profilo-jarvis.md, agenti-casa/, i lavori e le missioni, ogni file ignorato da git, e tutto ciò che sta fuori dal repository.
Se una tua modifica è dentro un file di codice, ne tiene una copia in .aggiornamenti/ prima di sostituirlo.

  python3 strumenti/aggiorna_jarvis.py               controlla: cosa cambierebbe (nessuna scrittura)
  python3 strumenti/aggiorna_jarvis.py --applica     aggiorna, poi ./installa.sh (idempotente) e la verifica
  python3 strumenti/aggiorna_jarvis.py --torna-indietro   rimette la versione di prima dell'ultimo aggiornamento
Opzioni: --ramo main (default: il ramo corrente) · --senza-riavvio · --home CARTELLA (casa finta, per provare)"""
import fnmatch
import subprocess
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parents[1]
DIR_AGG = QUI / ".aggiornamenti"
PROTETTI = [
    "command-center/configurazione.json", "command-center/spazi.json", "command-center/pannello.json", "command-center/assistenza.json",
    "command-center/assistenza-registro.json", "command-center/assistenza.log", "command-center/sessioni-nomi.json", "command-center/frequenti.json",
    "command-center/scadenze-chiuse.json", "command-center/gruppi-archiviati.json", "command-center/sessioni_motori.json",
    "command-center/modifiche-agenti.jsonl", "command-center/catena-stato.json", "command-center/missioni/*", "command-center/missioni_archivio/*",
    "command-center/lavori/*", "command-center/cache-profili/*", ".env", ".env.*", "*.env", ".claude/*", "profilo-jarvis.md", "agenti-casa/*",
    "strumenti/orb_posizione.json", "backtalk/backtalk.json", "sincro/copie/*", "sincro/ultimo.json", "VERSIONE.locale",
]


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


def git(*args, ok=False):
    r = subprocess.run(["git", "-C", str(QUI), *args], capture_output=True, text=True)
    if r.returncode and not ok:
        sys.exit(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def protetto(percorso: str) -> bool:
    return any(fnmatch.fnmatch(percorso, m) for m in PROTETTI)


def categoria(percorso: str) -> str:
    if percorso.startswith(("command-center/static/", "assets/")) or percorso.endswith((".css", ".png", ".svg", ".html")):
        return "grafica e pagine"
    if percorso.startswith(("docs/", "README")) or percorso.endswith(".md"):
        return "documentazione"
    return "codice"


def main():
    if not (QUI / ".git").exists():
        sys.exit("questa cartella non è un clone git: scarica Jarvis con git clone per poterlo aggiornare")
    if "--torna-indietro" in sys.argv:
        f = DIR_AGG / "ultimo-head"
        if not f.exists():
            sys.exit("nessun aggiornamento da annullare")
        vecchio = f.read_text().strip()
        git("reset", "--keep", vecchio)      # --keep: non tocca i file modificati da te
        print(f"Tornato alla versione {vecchio[:8]}. Le tue cose non sono state toccate.")
        return
    ramo = opzione("--ramo") or git("rev-parse", "--abbrev-ref", "HEAD")
    git("fetch", "--quiet", "origin", ramo)
    testa, nuova = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{ramo}")
    if testa == nuova:
        print("Jarvis è già all'ultima versione.")
        return
    cambi = [r.split("\t") for r in git("diff", "--name-status", f"HEAD..origin/{ramo}").splitlines() if r]
    da_applicare, saltati, tuoi_modificati = [], [], []
    sporchi = {r[3:] for r in git("status", "--porcelain", "--untracked-files=no").splitlines()}
    for c in cambi:
        p = c[-1]
        if protetto(p):
            saltati.append(p)
        else:
            da_applicare.append((c[0], p))
            if p in sporchi:
                tuoi_modificati.append(p)
    per_cat = {}
    for _, p in da_applicare:
        per_cat.setdefault(categoria(p), []).append(p)
    print(f"Aggiornamento disponibile: {testa[:8]} → {nuova[:8]}")
    for cat, lista in sorted(per_cat.items()):
        print(f"  {cat}: {len(lista)} file")
    if saltati:
        print(f"  protetti, lasciati com'erano: {len(saltati)} ({', '.join(saltati[:3])}{'…' if len(saltati) > 3 else ''})")
    if tuoi_modificati:
        print(f"  file di codice che avevi modificato (ne tengo una copia): {', '.join(tuoi_modificati[:4])}")
    print("  le tue impostazioni, i tuoi agenti, la memoria e i documenti: NON toccati")
    if "--applica" not in sys.argv:
        print("Per aggiornare: python3 strumenti/aggiorna_jarvis.py --applica")
        return
    DIR_AGG.mkdir(exist_ok=True)
    cartella = DIR_AGG / time.strftime("copia-%Y%m%d-%H%M")
    for p in tuoi_modificati:
        dst = cartella / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((QUI / p).read_bytes())
        git("checkout", "--", p)
    (DIR_AGG / "ultimo-head").write_text(testa + "\n")
    # se l'aggiornamento porterebbe un file dove tu hai già un file tuo non tracciato, non lo si sovrascrive
    for stato, p in da_applicare:
        if stato.startswith("A") and (QUI / p).exists() and not git("ls-files", "--", p):
            sys.exit(f"{p} esiste già ed è tuo: lo lascio, l'aggiornamento si ferma. Spostalo e rilancia.")
    r = subprocess.run(["git", "-C", str(QUI), "merge", "--ff-only", f"origin/{ramo}"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("aggiornamento non applicabile in modo lineare: " + (r.stderr or r.stdout).strip()[:200])
    print("Codice aggiornato. Ora ./installa.sh (non tocca i tuoi file) e la verifica…")
    casa = ["--home", opzione("--home")] if opzione("--home") else []
    subprocess.run(["bash", str(QUI / "installa.sh"), "--si", "--senza-brew", "--senza-voce", *casa], check=False)
    v = subprocess.run([sys.executable, str(QUI / "strumenti" / "verifica_installazione.py"), "--veloce", *casa]).returncode
    if v:
        print(f"La verifica ha trovato errori: torna indietro con  python3 strumenti/aggiorna_jarvis.py --torna-indietro")
    elif "--senza-riavvio" not in sys.argv and sys.platform == "darwin":
        uid = subprocess.run(["id", "-u"], capture_output=True, text=True).stdout.strip()
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/com.jarvis.command-center"], capture_output=True)
        print("Command Center riavviato: ricarica la pagina.")
    print("Fatto. Tornare indietro: python3 strumenti/aggiorna_jarvis.py --torna-indietro")


if __name__ == "__main__":
    main()
