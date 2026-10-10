#!/usr/bin/env python3
"""Chi sta lavorando davvero, e chi gira a vuoto.

Per «chi tiene quale risorsa condivisa» c'è `strumenti/portiere.py`: stessa
fonte (i recapiti in /tmp/cc-socks), domanda diversa.

    python3 strumenti/agenti.py                 l'elenco, con quanto lavorano davvero
    python3 strumenti/agenti.py --secondi 10    guarda più a lungo prima di giudicare
    python3 strumenti/agenti.py --fermi         solo quelli da chiudere
    python3 strumenti/agenti.py --chiudi <pid>  chiude quella sessione (chiede conferma)
    python3 strumenti/agenti.py --chiudi-fermi  chiude quelle ferme da più di 4 ore (chiede conferma)
    python3 strumenti/agenti.py --pulisci-orfane  cancella i recapiti senza processo
    python3 strumenti/agenti.py --si            con --chiudi-fermi: non chiede (per la sentinella)
    python3 strumenti/agenti.py --json          l'elenco in JSON

Perché esiste: il 20/09/2026 un agente ha girato sette ore dopo aver già consegnato
tre volte, e me ne sono accorto per caso. Chiedere a ogni sessione «stai lavorando?»
costa un giro di messaggi e la risposta è un'opinione. Qui si guarda il sistema
operativo, che non ha opinioni: quanto tempo di processore ha consumato la sessione
in una finestra di qualche secondo.

Come si legge il verdetto:
  LAVORA   consuma processore adesso: sta macinando davvero
  FERMA    zero processore nella finestra: aspetta te, o è rimasta appesa
  ASCOLTO  è un servizio che aspetta apposta: Telegram, il telefono (Remote
           Control), la voce, la sessione Cloud. Ferma è il suo stato normale:
           non si chiude, si controlla e si riavvia se cade (l'utente, 26/09/2026)
  ORFANA   c'è il recapito ma il processo è morto: residuo, si può cancellare

Attenzione: FERMA non vuol dire «da buttare». Una sessione in chat che aspetta una
tua risposta è ferma ed è giusto che lo sia. Il tempo passato dall'avvio dice quanto
vale la pena guardarla: una ferma da otto ore quasi sempre è stata dimenticata.
Prima di chiudere si chiede sempre.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import processi  # noqa: E402

RECAPITI = Path("/tmp/cc-socks")
FERME_DOPO_ORE = 4     # una ferma da più di tante ore, se non è in ascolto, si può chiudere

# Chi è «in ascolto»: si riconosce dal comando, suo o del padre, non dal pid (che
# cambia a ogni riavvio). Ordine: la prima che combacia vince.
IN_ASCOLTO = (
    ("--channels plugin:telegram", "Telegram (Mac)"),
    ("--channels", "Canale in ascolto"),
    ("remote-control", "Telefono → PC (Remote Control)"),
    ("--sdk-url", "Telefono → PC (Remote Control)"),
    ("--append-system-prompt VOICE", "Voce (backtalk)"),
    ("backtalk.main", "Voce (backtalk)"),
    ("--teleport", "Cloud Chat"),
)


def campo(pid, formato):
    if processi.WIN:          # niente ps: tabella dei processi di Windows
        p = next((x for x in processi.elenco() if x["pid"] == int(pid)), None)
        if not p:
            return ""
        return {"command=": p["cmd"], "ppid=": str(p["ppid"]),
                "etime=": processi.acceso_da(pid)}.get(formato, "")
    r = subprocess.run(["ps", "-o", formato, "-p", str(pid)],
                       capture_output=True, text=True, errors="replace")
    righe = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    return righe[-1] if len(righe) > 1 or (righe and "=" in formato) else (righe[0] if righe else "")


def secondi_cpu(pid):
    """Tempo di processore consumato finora, in secondi. None se il processo non c'è."""
    if processi.WIN:
        return processi.cpu_secondi(pid)
    r = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True, errors="replace")
    t = r.stdout.strip()
    if not t:
        return None
    pezzi = t.replace("-", ":").split(":")
    try:
        n = [float(p) for p in pezzi]
    except ValueError:
        return None
    tot = 0.0
    for v in n:
        tot = tot * 60 + v
    return tot


def cartella(pid):
    if processi.WIN:          # la cartella di lavoro di un processo altrui non si legge senza strumenti in più
        return ""
    r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                       capture_output=True, text=True, errors="replace")
    for riga in r.stdout.splitlines():
        if riga.startswith("n"):
            return riga[1:]
    return ""


def comando(pid):
    if processi.WIN:
        return "claude"
    c = campo(pid, "command=")
    for pezzo in c.split():
        if pezzo.endswith("/claude") or pezzo.endswith("claude"):
            return "claude"
    return (c.split("/")[-1] if c else "")[:40]


def in_ascolto(pid):
    """Il nome del servizio se la sessione è un ascoltatore, altrimenti ''. Guarda il
    comando della sessione e quello del padre (il Remote Control lancia un figlio
    --sdk-url, la voce di backtalk lancia il claude dell'SDK)."""
    comandi = [campo(pid, "command=")]
    padre = campo(pid, "ppid=")
    if padre.isdigit() and int(padre) > 1:
        comandi.append(campo(padre, "command="))
    for pezzo, nome in IN_ASCOLTO:
        if any(pezzo in c for c in comandi):
            return nome
    return ""


def del_pannello(pid):
    """La sessione l'ha lanciata il Command Center (chat, sentinella, missione): il padre è `server.py`
    o `missione.py`. Non è una sessione «aperta e non registrata»: è un lavoro del pannello."""
    padre = campo(pid, "ppid=")
    if not padre.isdigit() or int(padre) <= 1:
        return False
    c = campo(padre, "command=")
    return "server.py" in c or "missione.py" in c


def durata(testo):
    """«01-01:15:28» -> ore, per dire se vale la pena guardarla."""
    try:
        pezzi = testo.replace("-", ":").split(":")
        n = [float(p) for p in pezzi]
        tot = 0.0
        for v in n:
            tot = tot * 60 + v
        return tot / 3600
    except Exception:
        return 0.0


def guarda(secondi):
    pid_vivi, orfani = [], []
    if processi.WIN:          # nessun recapito: le sessioni sono i claude.exe di Claude Code
        pid_vivi = processi.sessioni_claude()
    elif not RECAPITI.is_dir():
        return [], []
    else:
        for s in sorted(RECAPITI.glob("*.sock")):
            try:
                pid = int(s.stem)
            except ValueError:
                continue
            if secondi_cpu(pid) is None:
                orfani.append((pid, s))
            else:
                pid_vivi.append(pid)

    prima = {p: secondi_cpu(p) for p in pid_vivi}
    time.sleep(secondi)
    righe = []
    for p in pid_vivi:
        dopo = secondi_cpu(p)
        if dopo is None:
            continue
        usato = max(0.0, dopo - (prima.get(p) or 0.0))
        acceso = campo(p, "etime=")
        # Il 5% del tempo guardato. Sotto è il battito di chi aspetta: una sessione
        # appesa consuma qualche centesimo anche senza fare niente, e chiamarla
        # «lavora» nasconderebbe proprio quelle da chiudere.
        righe.append({
            "pid": p,
            "lavora": usato > secondi * 0.05,
            "cpu": usato,
            "acceso": acceso,
            "ore": durata(acceso),
            "dove": cartella(p),
            "cosa": comando(p),
            "ascolto": in_ascolto(p),
        })
    righe.sort(key=lambda r: (bool(r["ascolto"]), r["lavora"], -r["ore"]))
    return righe, orfani


def stato_di(r):
    return "ASCOLTO" if r.get("ascolto") else ("LAVORA" if r["lavora"] else "FERMA")


def da_chiudere(righe):
    """Le ferme da più di FERME_DOPO_ORE che non sono in ascolto."""
    return [r for r in righe if not r["lavora"] and not r["ascolto"] and r["ore"] >= FERME_DOPO_ORE]


def pulisci_orfane(orfani):
    """Cancella i recapiti senza processo. Torna quanti ne ha tolti."""
    tolti = 0
    for _pid, s in orfani:
        try:
            s.unlink()
            tolti += 1
        except FileNotFoundError:
            pass
    return tolti


def stampa(righe, orfani, solo_fermi):
    if not righe and not orfani:
        print("Nessuna sessione di Claude aperta.")
        return
    print(f"{'pid':>7}  {'stato':<7} {'accesa da':>12}  {'processore':>10}  dove")
    for r in righe:
        if solo_fermi and (r["lavora"] or r["ascolto"]):
            continue
        dove = r["dove"].replace(str(Path.home()), "~") or r["cosa"]
        if r["ascolto"]:
            dove = f"{r['ascolto']} · {dove}"
        print(f"{r['pid']:>7}  {stato_di(r):<7} {r['acceso']:>12}  {r['cpu']:>9.2f}s  {dove}")
    for pid, s in orfani:
        print(f"{pid:>7}  {'ORFANA':<7} {'-':>12}  {'-':>10}  recapito senza processo: {s}")

    fermi_vecchi = da_chiudere(righe)
    if fermi_vecchi:
        print()
        print(f"{len(fermi_vecchi)} ferme da più di {FERME_DOPO_ORE} ore (le sessioni in ascolto non contano): "
              + ", ".join(str(r["pid"]) for r in fermi_vecchi))
        print("Se aspettano una risposta dell'utente vanno lasciate stare. Se no:")
        print("  python3 strumenti/agenti.py --chiudi-fermi")
    if orfani:
        print(f"\n{len(orfani)} recapiti orfani: python3 strumenti/agenti.py --pulisci-orfane")


def chiudi(pid, chiedi=True):
    if chiedi:
        r = input(f"Chiudo la sessione {pid}? Il lavoro non salvato si perde. [s/N] ")
        if r.strip().lower() not in ("s", "si", "sì"):
            print("   lasciata aperta")
            return False
    try:
        os.kill(pid, 15)   # gentile: la sessione può salvare
    except ProcessLookupError:
        print(f"   {pid} non c'è già più")
        return False
    except PermissionError:
        print(f"   {pid}: non ho il permesso di chiuderla")
        return False
    for _ in range(20):
        time.sleep(0.5)
        if secondi_cpu(pid) is None:
            print(f"   {pid} chiusa")
            return True
    print(f"   {pid} non si è chiusa in dieci secondi: guardala a mano prima di insistere")
    return False


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--secondi", type=float, default=4)
    p.add_argument("--fermi", action="store_true")
    p.add_argument("--chiudi", type=int)
    p.add_argument("--chiudi-fermi", action="store_true")
    p.add_argument("--pulisci-orfane", action="store_true")
    p.add_argument("--si", action="store_true", help="non chiedere conferma (sentinella)")
    p.add_argument("--json", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    a = p.parse_args()
    if a.help:
        print(__doc__)
        return 0
    if a.chiudi:
        return 0 if chiudi(a.chiudi, chiedi=not a.si) else 1

    righe, orfani = guarda(a.secondi)
    if a.json:
        import json
        print(json.dumps({"sessioni": [{**r, "stato": stato_di(r)} for r in righe],
                          "orfane": [str(s) for _p, s in orfani]}, ensure_ascii=False, indent=1))
    else:
        stampa(righe, orfani, a.fermi)

    if a.pulisci_orfane:
        print(f"\nrecapiti orfani tolti: {pulisci_orfane(orfani)}")
    if a.chiudi_fermi:
        lista = da_chiudere(righe)
        if not lista:
            print(f"\nNiente da chiudere: nessuna ferma da più di {FERME_DOPO_ORE} ore fuori dagli ascoltatori.")
            return 0
        print()
        for r in lista:
            chiudi(r["pid"], chiedi=not a.si)
    return 0


if __name__ == "__main__":
    sys.exit(main())
