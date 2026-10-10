#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Applica le risposte delle domande di avvio (/inizia) e installa Jarvis su questo Mac.

    python3 strumenti/installa_guidata.py --prova                 dice cosa farebbe, non scrive niente
    python3 strumenti/installa_guidata.py                         lo fa
    python3 strumenti/installa_guidata.py --risposte FILE         risposte da un altro file
Opzioni: --senza-brew (non installa programmi), --senza-venv (non crea ambienti Python), --si (non chiede conferme).
Le risposte stanno in ~/.jarvis/risposte-avvio.json (modello: docs/risposte-avvio.esempio.json). Nessun segreto lì dentro:
le chiavi vanno in ~/.env.jarvis, che resta sul Mac e non entra mai in un repository.

Si può rilanciare quando vuoi (idempotente): quello che è già a posto si salta. Ogni file che esiste e va cambiato
prima si copia in <file>.bak-AAAAMMGG. La casa è $HOME: per provarlo su una casa finta,
    HOME=/tmp/casa-finta python3 strumenti/installa_guidata.py --senza-brew --senza-venv

Passi:
  1. controlla le risposte (campi obbligatori, niente che sembri una chiave);
  2. programmi dal Brewfile, solo i gruppi che servono (base, voce, mani, terminale, telefono);
  3. ambienti Python: orb sul Mac e missioni (claude-agent-sdk); con la voce scarica backtalk dalla fonte originale;
  4. profilo-jarvis.md dal modello, con il tuo nome, quello dell'assistente, lingua, tono e fuso orario;
  5. configurazione del Command Center: configurazione.json dall'esempio, spazi.json vuoto (si parte da zero);
  6. ~/.claude: ganci (anche quelli che aggiornano lo stato dei progetti), agenti e skill aggiorna-memoria;
  7. memoria condivisa e collegamenti (collega_memoria.py);
  7b. il primo progetto, solo se l'hai chiesto (crea_progetto.py);
  8. lavori automatici di launchd, solo se li hai chiesti;
  9. scrive ~/.jarvis/installato.json: da lì in poi CLAUDE.md non rifà le domande di avvio.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

QUI = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("HOME", str(Path.home())))
J = HOME / ".jarvis"
OGGI = time.strftime("%Y%m%d")
ADESSO = time.strftime("%Y-%m-%d %H:%M")
PROVA = "--prova" in sys.argv
MAC = sys.platform == "darwin"
SEGRETI = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-|eyJ[A-Za-z0-9_-]{20,}\.|-----BEGIN)")
passi = []
sys.stdout.reconfigure(line_buffering=True)   # l'uscita dei comandi figli resta nell'ordine giusto


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


def titolo(t):
    print(f"\n== {t}")


def dice(t):
    print(("   [prova] " if PROVA else "   ") + t)


def esegui(cmd, sicuro=False, **kw):
    """Lancia un comando (in prova lo mostra soltanto, salvo i comandi «sicuri»: quelli lanciati a loro volta
    in prova, che leggono e basta). Torna True se è andato bene."""
    dice("$ " + " ".join(map(str, cmd)))
    if PROVA and not sicuro:
        return True
    r = subprocess.run(list(map(str, cmd)), env={**os.environ, "HOME": str(HOME)}, **kw)
    return r.returncode == 0


def con_backup(f, testo):
    """Scrive f solo se cambia; prima tiene una copia .bak-AAAAMMGG. Torna True se ha scritto (o scriverebbe)."""
    f = Path(f)
    if f.is_file() and f.read_text(encoding="utf-8") == testo:
        dice(f"già a posto: {f}")
        return False
    dice(("aggiorno" if f.exists() else "scrivo") + f": {f}" + (" (copia .bak prima)" if f.exists() else ""))
    if not PROVA:
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            shutil.copy2(f, f.with_name(f.name + f".bak-{OGGI}"))
        f.write_text(testo, encoding="utf-8")
    return True


# ---------------------------------------------------------------- 1
def controlla(r):
    titolo("1. Risposte di avvio")
    errori = []
    if not str(r.get("come_chiamarti", "")).strip():
        errori.append("manca «come_chiamarti» (come vuoi essere chiamato)")
    if not isinstance(r.get("spazi", []), list):
        errori.append("«spazi» deve essere un elenco")
    if r.get("avvio", "zero") not in ("zero", "primo"):
        errori.append("«avvio» vale «zero» o «primo»")
    if r.get("avvio") == "primo" and not str((r.get("primo_progetto") or {}).get("nome", "")).strip():
        errori.append("con «avvio»: «primo» serve «primo_progetto»: {\"nome\": \"...\"}")
    if r.get("creazione", "piano") not in ("piano", "automatica"):
        errori.append("«creazione» vale «piano» o «automatica»")
    testo = json.dumps(r, ensure_ascii=False)
    if SEGRETI.search(testo):
        errori.append("nelle risposte c'è qualcosa che sembra una chiave o un token: toglilo, le chiavi vanno in ~/.env.jarvis")
    for s in r.get("spazi", []) or []:
        for c in s.get("cartelle", []) if isinstance(s, dict) else []:
            if not Path(os.path.expanduser(c)).exists():
                dice(f"attenzione: la cartella «{c}» dello spazio «{s.get('nome')}» non esiste (la memoria la segue lo stesso)")
    if errori:
        for e in errori:
            print("   ERRORE: " + e)
        sys.exit(2)
    dice(f"ti chiamerò «{r['come_chiamarti']}», l'assistente si chiama «{r.get('nome_assistente') or 'Jarvis'}», "
         + ("primo progetto: «" + r["primo_progetto"]["nome"] + "»" if r.get("avvio") == "primo" else "si parte da zero (nessun progetto)")
         + f", memoria in {r.get('memoria') or '~/Jarvis-Memoria'}")
    passi.append("risposte")


# ---------------------------------------------------------------- 2
def gruppi(r):
    s = r.get("servizi") or {}
    g = {"base"}
    if s.get("voce"):
        g.add("voce")
    if s.get("mani_sul_mac", True):
        g.add("mani")
    if s.get("terminale", True) or s.get("telegram"):
        g.add("terminale")
    if s.get("telefono"):
        g.add("telefono")
    return g


def brew(r):
    titolo("2. Programmi di sistema (Brewfile)")
    if "--senza-brew" in sys.argv:
        dice("saltato (--senza-brew)")
        return
    if not MAC or not shutil.which("brew"):
        dice("Homebrew non c'è: installalo da https://brew.sh e rilancia, oppure usa --senza-brew")
        return
    g = gruppi(r)
    righe = []
    for riga in (QUI / "Brewfile").read_text(encoding="utf-8").splitlines():
        m = re.search(r"#\s*\[(\w+)\]", riga)
        if riga.strip().startswith(("brew ", "cask ")) and (not m or m.group(1) in g):
            righe.append(riga)
    filtrato = J / "Brewfile.scelto"
    dice(f"gruppi: {', '.join(sorted(g))} → {len(righe)} programmi")
    if not PROVA:
        J.mkdir(parents=True, exist_ok=True)
        filtrato.write_text("\n".join(righe) + "\n", encoding="utf-8")
    if not PROVA and subprocess.run(["brew", "bundle", "check", f"--file={filtrato}"], capture_output=True).returncode == 0:
        dice("già tutti installati")
    else:
        esegui(["brew", "bundle", f"--file={filtrato}"])
    passi.append("brew")


# ---------------------------------------------------------------- 3
def ambienti(r):
    titolo("3. Ambienti Python")
    if "--senza-venv" in sys.argv:
        dice("saltato (--senza-venv)")
        return
    py = sys.executable
    if MAC:
        w = HOME / ".locale-onedrive" / "jarvis-widget-venv"
        if (w / "bin" / "python3").exists():
            dice(f"orb: ambiente già pronto ({w})")
        else:
            esegui([py, "-m", "venv", w]) and esegui([w / "bin" / "pip", "install", "-q", "-r", QUI / "requirements" / "mac-widget.txt"])
        vv = HOME / ".jarvis" / "vault-venv"      # il Vault: «cryptography» in un ambiente a parte
        if (vv / "bin" / "python3").exists():
            dice(f"Vault: ambiente già pronto ({vv})")
        else:
            esegui([py, "-m", "venv", vv]) and esegui([vv / "bin" / "pip", "install", "-q", "-r", QUI / "requirements" / "vault.txt"])
    bt = QUI / "backtalk"
    voce = (r.get("servizi") or {}).get("voce")
    if voce and not (bt / "install.sh").exists():
        dice("voce: scarico backtalk dalla fonte originale (github.com/jaredrhod/backtalk, licenza AGPL-3.0, di un altro autore)")
        if bt.exists() and any(bt.iterdir()):
            dice(f"{bt} esiste già e non è vuota: la lascio com'è")
        else:
            esegui(["git", "clone", "--depth", "1", "https://github.com/jaredrhod/backtalk", bt])
    if voce and (bt / "install.sh").exists():
        esegui(["bash", bt / "install.sh"])
        esegui([py, QUI / "strumenti" / "installa_voce.py"] + (["--prova"] if PROVA else []))
    elif (bt / ".venv" / "bin" / "python3").exists():
        dice("missioni: ambiente già pronto")
    else:
        esegui([py, "-m", "venv", bt / ".venv"]) and esegui([bt / ".venv" / "bin" / "pip", "install", "-q", "-r", QUI / "requirements" / "missioni.txt"])
    passi.append("ambienti")


# ---------------------------------------------------------------- 4
def profilo(r):
    titolo("4. Profilo dell'assistente")
    modello = (QUI / "profilo-jarvis.esempio.md").read_text(encoding="utf-8")
    valori = {"NOME_ASSISTENTE": r.get("nome_assistente") or "Jarvis", "COME_CHIAMARTI": r["come_chiamarti"],
              "LINGUA": r.get("lingua") or "italiano", "FUSO_ORARIO": r.get("fuso_orario") or time.strftime("%Z"),
              "TONO": r.get("tono") or "semplice e diretto"}
    f = QUI / "profilo-jarvis.md"
    if f.is_file():
        # il profilo c'è già (magari ritoccato dalla lavagna): si cambiano solo i campi delle risposte
        testo = f.read_text(encoding="utf-8")
        for chiave, campo in (("nome_assistente", "NOME_ASSISTENTE"), ("chiamami", "COME_CHIAMARTI"),
                              ("lingua", "LINGUA"), ("fuso_orario", "FUSO_ORARIO"), ("tono", "TONO")):
            riga = f"{chiave}: {valori[campo]}"
            testo = re.sub(rf"(?m)^{chiave}:.*$", riga, testo, count=1) if re.search(rf"(?m)^{chiave}:", testo) \
                else testo.replace("---\n", f"---\n{riga}\n", 1)
    else:
        testo = modello
        for k, v in valori.items():
            testo = testo.replace("{{" + k + "}}", str(v))
    con_backup(f, testo)
    passi.append("profilo")


# ---------------------------------------------------------------- 5
def configurazione(r):
    titolo("5. Configurazione del Command Center")
    cc = QUI / "command-center"
    conf = cc / "configurazione.json"
    if conf.is_file():
        dice("configurazione.json c'è già: lo lascio")
    else:
        d = json.loads((cc / "configurazione.esempio.json").read_text(encoding="utf-8"))
        d["cartella_agente"] = str(QUI)
        d["vault"] = r.get("memoria") or "~/Jarvis-Memoria"
        con_backup(conf, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    # Jarvis parte da zero: spazi.json nasce vuoto; i progetti li crea crea_progetto.py (passo 7b e dopo, a richiesta)
    f = cc / "spazi.json"
    if f.is_file():
        dice("spazi.json c'è già: lo lascio (i tuoi progetti restano)")
    else:
        con_backup(f, json.dumps({"spazi": []}, ensure_ascii=False, indent=2) + "\n")
    passi.append("configurazione")


# ---------------------------------------------------------------- 6, 7, 8
def claude_config():
    titolo("6. Claude Code: ganci, agenti, skill aggiorna-memoria")
    esegui([sys.executable, QUI / "strumenti" / "installa_claude_config.py", "--home", HOME] + (["--prova"] if PROVA else []), sicuro=True)
    if (QUI / ".git").exists():          # a ogni commit e push del repo di Jarvis lo stato si salva da solo
        esegui([sys.executable, QUI / "strumenti" / "ganci_git.py", QUI] + (["--prova"] if PROVA else []), sicuro=True)
    passi.append("claude")


def memoria(file_risposte):
    titolo("7. Memoria condivisa e collegamenti")
    esegui([sys.executable, QUI / "strumenti" / "collega_memoria.py", "--risposte", file_risposte] + ([] if PROVA else ["--applica"]), sicuro=True)
    passi.append("memoria")


def primi_progetti(r):
    """7b. Il primo progetto, se scelto alle domande di avvio (e, per chi ha risposte vecchie, le cartelle di «spazi»)."""
    titolo("7b. Progetti")
    da_creare = []
    if r.get("avvio") == "primo":
        p = r.get("primo_progetto") or {}
        da_creare.append((p["nome"], p.get("spazio"), p.get("cartella")))
    for s in r.get("spazi") or []:                      # risposte della versione precedente
        for c in s.get("cartelle", []) if isinstance(s, dict) else []:
            da_creare.append((Path(os.path.expanduser(c)).name, s.get("nome"), c))
    if not da_creare:
        dice("si parte da zero: nessun progetto. Nascono quando li nomini (skill nuovo-progetto, /nuovo-progetto).")
        return
    for nome, spazio, cartella in da_creare:
        cmd = [sys.executable, QUI / "strumenti" / "crea_progetto.py", nome]
        cmd += ["--spazio", spazio] if spazio else []
        cmd += ["--cartella", os.path.expanduser(cartella)] if cartella else []
        if PROVA:
            dice("$ " + " ".join(map(str, cmd)) + "   (dopo la memoria: in prova si mostra soltanto)")
        else:
            esegui(cmd)
    passi.append("progetti")


def launchd(r):
    titolo("8. Lavori automatici (launchd)")
    if not r.get("launchd"):
        dice("non chiesti: saltato (si accendono dopo con python3 strumenti/installa_launchd.py --attiva)")
        return
    esegui([sys.executable, QUI / "strumenti" / "installa_launchd.py", "--home", HOME] + (["--prova"] if PROVA else ["--attiva"]), sicuro=True)
    passi.append("launchd")


def fine(r):
    titolo("9. Fatto")
    versione = (QUI / "VERSIONE").read_text().strip() if (QUI / "VERSIONE").exists() else "?"
    stato = {"installato": ADESSO, "versione": versione, "repo": str(QUI), "passi": passi,
             "come_chiamarti": r["come_chiamarti"], "nome_assistente": r.get("nome_assistente") or "Jarvis"}
    con_backup(J / "installato.json", json.dumps(stato, ensure_ascii=False, indent=1) + "\n")
    s = r.get("servizi") or {}
    print("\nRestano a te:")
    print(" - le chiavi (se servono) in ~/.env.jarvis, con: chmod 600 ~/.env.jarvis. Mai in un repository.")
    if MAC:
        print(" - Impostazioni di Sistema → Privacy e sicurezza: Accessibilità e Registrazione schermo al Terminale.")
    if s.get("vps"):
        print(" - VPS: guida in docs/wiki/VPS.md (facoltativa).")
    print(" - Accendi il pannello: python3 command-center/server.py → http://127.0.0.1:7777")


def main():
    f = Path(opzione("--risposte") or J / "risposte-avvio.json").expanduser()
    if not f.is_file():
        sys.exit(f"mancano le risposte: {f}. In Claude Code scrivi /inizia, oppure copia docs/risposte-avvio.esempio.json.")
    try:
        r = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        sys.exit(f"{f} non è un JSON valido: {e}")
    print(f"Jarvis · installazione guidata · {ADESSO} · casa {HOME}" + (" · PROVA: non scrivo niente" if PROVA else ""))
    controlla(r)
    brew(r)
    ambienti(r)
    profilo(r)
    configurazione(r)
    claude_config()
    memoria(f)
    primi_progetti(r)
    launchd(r)
    if PROVA:
        print("\nProva finita: niente è stato scritto. Rilancia senza --prova per installare.")
    else:
        fine(r)


if __name__ == "__main__":
    main()
