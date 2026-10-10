#!/usr/bin/env python3
"""Il diario degli agenti del CRM, scritto da solo a fine lavoro (l'utente, 2026-10-05: installato nel CRM e sul PC).

Gancio di Claude Code per gli eventi Stop e SubagentStop, uguale su Mac e PC Windows. Quando un agente del CRM finisce:
  1. nel suo quaderno (<CRM>/.claude/memoria/agenti/<nome>.md, formato di strumenti/quaderno.py) salva le righe
     «DA SALVARE:», «ERRORE DA SALVARE:», «DA VERIFICARE:», «FONTE:», «PROPOSTA:» del suo ultimo messaggio, e una riga
     di Diario (data e ora assolute con il fuso, quaderno.riga_diario) se quaderno.py ha la sezione «diario»;
  2. in <CRM>/_CONDIVISO-AGENTI/registro/<PC>.log aggiunge `AAAA-MM-GG HH:MM | PC | chi | FINE <cosa> | esito`,
     se l'agente non l'ha già scritta lui negli ultimi 15 minuti.
Un agente è «del CRM» se il suo profilo sta in <CRM>/.claude/agents/<nome>.md: per tutti gli altri il gancio non fa niente.
Non blocca mai: qualunque errore finisce in <temp>/diario-agenti.log e il gancio esce con 0.

Solo libreria standard. Niente fcntl/msvcrt: il lucchetto è un file creato in esclusiva (os.O_EXCL), che vale su tutti e due.
La cartella del CRM: JARVIS_CRM, poi quella che contiene il gancio (<CRM>/.claude/hooks/), poi %OneDrive% (e OneDriveConsumer/OneDriveCommercial), ~/OneDrive, la cartella OneDrive del Mac.
Il nome della macchina: JARVIS_MACCHINA, poi %COMPUTERNAME% su Windows, «MAC» sul Mac (come i file che ci sono già).

  python diario_agenti.py < evento.json        (così lo chiama Claude Code; prove: prova_diario_agenti.py)
  python diario_agenti.py --da-utente < …      (gancio delle impostazioni UTENTE del Mac, per la chat master che parte da ~):
                                               se la sessione è già dentro la cartella del CRM non fa niente, perché
                                               lì scatta il gancio del progetto (<CRM>/.claude/settings.json)
Dove sta: <CRM>/.claude/hooks/diario_agenti.py (una copia sola, sulla cartella condivisa); sorgente in strumenti/ di Jarvis.
"""
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

NOME_CRM = os.environ.get("JARVIS_CRM_NOME", "")      # cartella condivisa di un progetto (facoltativa)
MARCHE = re.compile(r"^\s*[-*]?\s*\**(DA SALVARE|ERRORE DA SALVARE|DA VERIFICARE|FONTE|PROPOSTA)\**\s*:", re.M)
LOG = Path(tempfile.gettempdir()) / "diario-agenti.log"
FINESTRA_DOPPIONE = 15 * 60


def dentro(crm, cartella):
    """True se cartella sta dentro la cartella del CRM (confronto senza maiuscole e con / e \\ uguali, per Windows)."""
    if not cartella:
        return False
    a = os.path.normcase(os.path.realpath(str(crm))).rstrip("\\/")          # realpath: ~/OneDrive è un collegamento
    b = os.path.normcase(os.path.realpath(str(cartella)))
    return b == a or b.startswith(a + os.sep)


def cartella_crm():
    if os.environ.get("JARVIS_CRM"):
        return Path(os.environ["JARVIS_CRM"])
    qui = Path(__file__).resolve()
    if qui.parent.name == "hooks" and qui.parent.parent.name == ".claude" and (qui.parents[2] / ".claude" / "agents").is_dir():
        return qui.parents[2]                            # <CRM>/.claude/hooks/diario_agenti.py: il CRM è dove sta il gancio
    basi = [os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    basi += [str(Path.home() / "OneDrive"), str(Path.home() / "Library" / "CloudStorage" / "OneDrive")]
    for b in basi:
        if b and NOME_CRM and (Path(b) / NOME_CRM).is_dir():
            return Path(b) / NOME_CRM
    return None


def macchina():
    if os.environ.get("JARVIS_MACCHINA"):
        return os.environ["JARVIS_MACCHINA"].upper()
    if sys.platform == "win32":
        return (os.environ.get("COMPUTERNAME") or "PC").upper()
    return "MAC" if sys.platform == "darwin" else (os.uname().nodename.split(".")[0].upper() or "LINUX")


def trova_quaderno_py():
    """quaderno.py del Jarvis di questa macchina: una sola fonte per il formato del quaderno."""
    cand = [os.environ.get("JARVIS_REPO", ""), str(Path.home() / "Jarvis"), str(Path.home() / "jarvis"),
            str(Path.home() / "jarvis" / "app")]
    for c in cand:
        if c and (Path(c) / "strumenti" / "quaderno.py").is_file():
            sys.path.insert(0, str(Path(c) / "strumenti"))
            import quaderno                                                  # noqa: E402
            return quaderno
    return None


# --- leggere l'evento ------------------------------------------------------------------------------------------------

def righe_trascrizione(percorso):
    try:
        with open(percorso, encoding="utf-8") as f:
            for r in f:
                try:
                    yield json.loads(r)
                except ValueError:
                    continue
    except OSError:
        return


def testo_di(msg):
    c = (msg or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def dalla_trascrizione(percorso):
    """(primo messaggio dell'utente = il compito, ultimo testo dell'assistente = il resoconto)"""
    primo, ultimo = "", ""
    for r in righe_trascrizione(percorso):
        m = r.get("message") or {}
        if r.get("type") == "user" and not primo:
            primo = testo_di(m)
        elif r.get("type") == "assistant":
            t = testo_di(m)
            if t.strip():
                ultimo = t
    return primo, ultimo


def chi_e(evento, compito, crm):
    """Il nome dell'agente, solo se ha un profilo nel CRM. Gli agenti del CRM si lanciano come general-purpose col
    profilo nel compito: il nome si ricava da agent_type, poi da «--agente <nome>», poi dal frontmatter «name:»."""
    agenti = crm / ".claude" / "agents"
    candidati = [evento.get("agent_type") or ""]
    candidati += re.findall(r"--agente[= ]+[\"']?([\w.-]+)", compito)
    candidati += re.findall(r"^name:\s*([\w.-]+)\s*$", compito, re.M)
    if evento.get("hook_event_name") == "Stop":
        candidati.insert(0, os.environ.get("JARVIS_AGENTE", ""))
    for c in candidati:
        c = c.strip().lower()
        if c and (agenti / f"{c}.md").is_file():
            return c
    return None


def una_riga(t, n):
    t = " ".join(str(t).replace("|", "/").split())
    return t if len(t) <= n else t[: n - 1] + "…"


# --- scrivere --------------------------------------------------------------------------------------------------------

class Lucchetto:
    """File creato in esclusiva: va su Windows e su Mac. Locale (cartella temporanea), non su OneDrive: fra macchine
    diverse non servirebbe, perché ognuna scrive il suo file di registro. Dopo 30 s un lucchetto è considerato orfano."""
    def __init__(self, nome):
        self.p = Path(tempfile.gettempdir()) / f"diario-agenti-{nome}.lock"

    def __enter__(self):
        fine = time.time() + 10
        while True:
            try:
                os.close(os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > 30:
                        self.p.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > fine:
                    raise TimeoutError(f"lucchetto occupato: {self.p}")
                time.sleep(0.1)

    def __exit__(self, *x):
        try:
            self.p.unlink()
        except OSError:
            pass


def gia_scritta(log, chi):
    """True se negli ultimi 15 minuti c'è già un FINE di questo agente (lo scrive lui, come dice PROMPT-PC-WINDOWS.md)."""
    if not log.is_file():
        return False
    ora = datetime.now()
    for r in log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]:
        parti = [x.strip() for x in r.split("|")]
        if len(parti) >= 4 and parti[2].lower() == chi and parti[3].startswith("FINE"):
            try:
                if (ora - datetime.strptime(parti[0], "%Y-%m-%d %H:%M")).total_seconds() < FINESTRA_DOPPIONE:
                    return True
            except ValueError:
                continue
    return False


def scrivi(evento, crm, quaderno=None):
    """→ dizionario con cosa ha fatto (per le prove e per il log)."""
    percorso = evento.get("agent_transcript_path") or evento.get("transcript_path") or ""
    compito, resoconto = dalla_trascrizione(percorso) if percorso else ("", "")
    resoconto = evento.get("last_assistant_message") or resoconto
    chi = chi_e(evento, compito, crm)
    if not chi:
        return {"fatto": "niente", "perche": "non è un agente del CRM"}
    pc = macchina()
    cosa = una_riga((compito.strip().splitlines() or ["lavoro"])[0], 100)
    esito_righe = [r for r in resoconto.splitlines() if r.strip() and not MARCHE.match(r)]
    esito = una_riga(esito_righe[0] if esito_righe else "senza resoconto", 160)
    out = {"chi": chi, "pc": pc, "quaderno": 0, "registro": False}
    with Lucchetto(chi):
        if quaderno is not None:
            voci = quaderno.raccogli_da_testo(resoconto) if hasattr(quaderno, "raccogli_da_testo") else []
            if any(k == "diario" for k, _ in getattr(quaderno, "SEZIONI", [])):
                testo = f"{cosa} → {esito}"
                voci.append(("diario", quaderno.riga_diario(testo, pc) if hasattr(quaderno, "riga_diario")
                             else f"{datetime.now().astimezone().isoformat(timespec='minutes')} {pc} · {testo}"))
            f = crm / ".claude" / "memoria" / "agenti" / f"{chi}.md"
            out["quaderno"] = quaderno.aggiungi(f, chi, voci) if voci else 0
        log = crm / "_CONDIVISO-AGENTI" / "registro" / f"{pc}.log"
        if not gia_scritta(log, chi):
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M} | {pc} | {chi} | FINE {cosa} | esito (dal gancio, da verificare): {esito}\n")
            out["registro"] = True
    return out


def main():
    try:
        evento = json.loads(sys.stdin.read() or "{}")
        if evento.get("stop_hook_active"):
            return                                       # Claude sta già continuando per un gancio Stop: non si riscrive
        crm = cartella_crm()
        if not crm:
            return
        if "--da-utente" in sys.argv and dentro(crm, evento.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")):
            return                                       # ci pensa il gancio del progetto CRM: niente doppioni
        esito = scrivi(evento, crm, trova_quaderno_py())
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {evento.get('hook_event_name')} {json.dumps(esito, ensure_ascii=False)}\n")
    except Exception as e:                               # un gancio non deve mai fermare l'agente
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} ERRORE {type(e).__name__}: {e}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
