#!/usr/bin/env python3
"""Prove di «Aggiorna ora» (aggiornamento.py, 2026-10-05). Repository finti in una cartella temporanea: niente rete,
niente riavvii veri (applica(prova=True) fa tutto tranne il riavvio).

  python3 command-center/prove/prova_aggiornamento.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SORGENTE = Path(__file__).resolve().parents[1] / "aggiornamento.py"
ESITI = []


def git(cartella, *a):
    p = subprocess.run(["git", "-C", str(cartella), *a], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {a}: {p.stderr}")
    return p.stdout.strip()


def commit(cartella, nome, testo):
    (cartella / nome).write_text(testo)
    git(cartella, "add", nome)
    git(cartella, "commit", "-q", "-m", f"cambia {nome}")


def controlla(nome, cond, dettaglio=""):
    ESITI.append(cond)
    print(("OK    " if cond else "ERRORE") + f" {nome}" + (f"  ({dettaglio})" if not cond and dettaglio else ""))


def carica(clone):
    """Un aggiornamento.py fresco dentro clone/command-center (QUI = quella cartella)."""
    dst = clone / "command-center" / "aggiornamento.py"
    shutil.copy(SORGENTE, dst)
    spec = importlib.util.spec_from_file_location(f"agg_{id(dst)}", dst)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    tmp = Path(tempfile.mkdtemp(prefix="prova-agg-"))
    os.environ.update(GIT_AUTHOR_NAME="p", GIT_AUTHOR_EMAIL="p@p", GIT_COMMITTER_NAME="p", GIT_COMMITTER_EMAIL="p@p")
    try:
        origine = tmp / "origine.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origine)], check=True)
        clone, altro = tmp / "clone", tmp / "altro"
        subprocess.run(["git", "clone", "-q", str(origine), str(clone)], check=True, capture_output=True)
        (clone / "command-center").mkdir()
        (clone / ".gitignore").write_text("command-center/aggiornamento.py\ncommand-center/lavori/\n__pycache__/\n")
        commit(clone, "a.txt", "uno\n")
        git(clone, "push", "-q", "-u", "origin", "main")
        subprocess.run(["git", "clone", "-q", str(origine), str(altro)], check=True, capture_output=True)

        m = carica(clone)
        avvio = m.segna_avvio()
        controlla("versione di avvio letta", avvio == git(clone, "rev-parse", "HEAD"))
        s = m.stato(True)
        controlla("tutto allineato: niente riquadro", s["attivo"] and not s["disponibile"], s)
        r = m.applica(prova=True)
        controlla("Aggiorna ora senza novità: dice che è già aggiornato", not r["avviato"] and "aggiornato" in r["motivo"], r)

        # GitHub avanti (VPS / copie): avanti veloce
        commit(altro, "b.txt", "due\n")
        git(altro, "push", "-q", "origin", "main")
        s = m.stato(True)
        controlla("GitHub avanti: riquadro con 1 modifica da scaricare",
                  s["disponibile"] and s["da_scaricare"] and s["indietro"] == 1 and s["novita"] == ["cambia b.txt"], s)
        r = m.applica(occupato=["chat: domanda lunga"], prova=True)
        controlla("chat in corso: chiede conferma e non tocca niente",
                  r.get("chiede_conferma") and git(clone, "rev-parse", "HEAD") == avvio, r)
        r = m.applica(forza=True, occupato=["chat: domanda lunga"], prova=True)
        controlla("con «riavvia lo stesso»: avanti veloce fatto",
                  r["avviato"] and r["scaricato"] and git(clone, "rev-parse", "HEAD") == git(clone, "rev-parse", "@{u}"), r)
        s = m.stato(True)
        controlla("dopo il download, prima del riavvio: resta «da riavviare»", s["disponibile"] and s["da_riavviare"] and not s["da_scaricare"], s)

        # pannello ripartito: avvio = HEAD, il riquadro sparisce
        m = carica(clone)
        m.segna_avvio()
        controlla("dopo il riavvio il riquadro sparisce", not m.stato(True)["disponibile"])

        # Mac: commit locale dopo l'avvio (pubblicato o no) = serve solo riavviare
        commit(clone, "c.txt", "tre\n")
        s = m.stato(True)
        controlla("commit locale dopo l'avvio: «da riavviare» anche con GitHub indietro",
                  s["disponibile"] and s["da_riavviare"] and s["avanti"] == 1 and s["novita"] == ["cambia c.txt"], s)
        r = m.applica(prova=True)
        controlla("Aggiorna ora con solo riavvio: avviato, niente download", r["avviato"] and not r["scaricato"], r)
        git(clone, "push", "-q", "origin", "main")

        # file modificato qui che l'aggiornamento cambierebbe: git rifiuta, niente reset né stash
        m = carica(clone)
        m.segna_avvio()
        git(altro, "pull", "-q", "--ff-only")
        commit(altro, "a.txt", "uno cambiato su GitHub\n")
        git(altro, "push", "-q", "origin", "main")
        (clone / "a.txt").write_text("modifica dell'utente non salvata\n")
        r = m.applica(prova=True)
        controlla("file modificato qui: git rifiuta e il riquadro lo dice",
                  not r["avviato"] and "git" in r["motivo"] and (clone / "a.txt").read_text() == "modifica dell'utente non salvata\n", r)
        controlla("registro dell'aggiornamento scritto",
                  "avanti veloce rifiutato" in (clone / "command-center" / "lavori" / "aggiornamento.log").read_text())

        # come si riavvia
        vecchio = dict(os.environ)
        os.environ["XPC_SERVICE_NAME"] = "com.jarvis.command-center"
        descr, cmd = m.comando_riavvio()
        controlla("Mac sotto launchd: kickstart -k staccato", sys.platform != "darwin" or (cmd and "kickstart -k" in cmd[-1]), descr)
        os.environ.pop("XPC_SERVICE_NAME", None)
        os.environ.pop("INVOCATION_ID", None)
        descr, cmd = m.comando_riavvio()
        controlla("fuori da launchd/systemd: si rilancia da sé", cmd is None, descr)
        os.environ.clear()
        os.environ.update(vecchio)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{sum(ESITI)}/{len(ESITI)} prove passate")
    return 0 if all(ESITI) else 1


if __name__ == "__main__":
    sys.exit(main())
