#!/usr/bin/env python3
"""Rende i lavori automatici di Jarvis (launchd, solo Mac) dai modelli di launchd/*.plist.
I modelli hanno @@JARVIS@@ (la cartella di Jarvis) e @@HOME@@ (la tua casa). Per default scrive solo i file in
~/Library/LaunchAgents e NON li carica: si accendono con --attiva. Non sovrascrive un lavoro già presente e
diverso (lo lascia com'è e lo dice).

  python3 strumenti/installa_launchd.py --lista             i lavori e cosa fanno
  python3 strumenti/installa_launchd.py                     scrive i lavori «generici» (pannello, sentinella, sincronia, sveglio)
  python3 strumenti/installa_launchd.py --tutti --attiva    anche i tuoi lavori personali (DI_TITOLARE) e li carica
  python3 strumenti/installa_launchd.py --prova             cosa farebbe, senza scrivere
Con --home CARTELLA si prova su una casa finta."""
import os
import subprocess
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parents[1]
MODELLI = QUI / "launchd"
GENERICI = {
    "com.jarvis.command-center": "il Command Center sempre acceso (porta 7777)",
    "com.jarvis.sentinella15": "la sentinella: pulizia e rapporto ogni 15 minuti",
    "com.jarvis.sincronia30": "la sincronia della memoria ogni 30 minuti",
    "com.jarvis.stai-sveglio": "tiene sveglio il Mac finché è alimentato (caffeinate)",
    "com.jarvis.pulizia-claude": "pulizia e unione di ~/.claude nella memoria condivisa, ogni giorno alle 6:20",
    "com.jarvis.giro-apprendimento": "i diari degli agenti nella memoria, ogni giorno alle 6:40 (nessun gruppo = niente)",
}
# lavori personali: li aggiungi tu (un modello in launchd/ e una riga qui). Si accendono con --tutti.
DI_TITOLARE = {}


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


HOME = Path(opzione("--home", str(Path.home()))).expanduser()
PROVA, ATTIVA, TUTTI = "--prova" in sys.argv, "--attiva" in sys.argv, "--tutti" in sys.argv


def main():
    if "--lista" in sys.argv:
        for k, v in {**GENERICI, **DI_TITOLARE}.items():
            print(f"{k:38} {'generico' if k in GENERICI else 'dell’utente':10} {v}")
        return
    if sys.platform != "darwin" and not opzione("--home"):
        sys.exit("launchd esiste solo sul Mac")
    destinazione = HOME / "Library" / "LaunchAgents"
    if not PROVA:
        (HOME / ".jarvis" / "log").mkdir(parents=True, exist_ok=True)     # launchd non crea la cartella dei log
    scelti = dict(GENERICI, **(DI_TITOLARE if TUTTI else {}))
    for label, cosa in scelti.items():
        modello = MODELLI / f"{label}.plist"
        if not modello.is_file():
            print(f"manca il modello {modello.name}: salto")
            continue
        testo = modello.read_text(encoding="utf-8").replace("@@JARVIS@@", str(QUI)).replace("@@HOME@@", str(HOME))
        dest = destinazione / f"{label}.plist"
        if dest.exists() and dest.read_text(encoding="utf-8") != testo:
            print(f"lascio com'è (già presente e diverso): {dest.name}")
            continue
        print(("[prova] " if PROVA else "") + f"{'già a posto' if dest.exists() else 'scrivo'}: {dest.name}  ({cosa})")
        if PROVA:
            continue
        destinazione.mkdir(parents=True, exist_ok=True)
        dest.write_text(testo, encoding="utf-8")
        if ATTIVA and sys.platform == "darwin":
            uid = os.getuid()
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
            r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dest)], capture_output=True, text=True)
            print(f"   attivo: {'sì' if r.returncode == 0 else 'NO — ' + r.stderr.strip()}")
    if not ATTIVA:
        print("Scritti, non caricati. Per accenderli: rilancia con --attiva.")


if __name__ == "__main__":
    main()
