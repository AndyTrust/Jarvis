#!/usr/bin/env python3
"""Nomi, riassunti e ripresa delle sessioni di Claude Code (decisione dell'utente del 24/09/2026).

Ogni sessione riceve un nome chiaro (spazio-progetto-data-ora, più il tema) e una nota in
`<memoria>/Sessioni/`; l'indice è `<memoria>/Sessioni.md`. Al 95% del contesto l'ultimo aggiornamento (e
prima di ogni compattazione) si chiede il riassunto e si salva la memoria, così una
sessione nuova riparte dal riassunto e non da zero.

Hook (in ~/.claude/settings.json):   inizio · prompt · compatta · fine   (JSON su stdin)
A mano:
  sessioni.py tema <id|nome> "tema"          dà il tema alla sessione
  sessioni.py riassunto <id|nome> "testo"    aggiunge un riassunto (fatto, da fare, errori)
  sessioni.py trova "parole"                 trova una sessione e dice come riprenderla
  sessioni.py elenco                          le ultime sessioni
  sessioni.py ultima [--comando]             l'ultima chat (con --comando: solo il comando per riaprirla)
"""
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

CASA = Path.home()


def _percorsi():
    """Vault, OneDrive e repo da strumenti/percorsi_vault.py (Mac e VPS, 04/10/2026); se manca, i percorsi del Mac."""
    for r in (os.environ.get("JARVIS_REPO", ""), str(CASA / "Jarvis"), "/root/jarvis"):
        if r and (Path(os.path.expanduser(r)) / "strumenti/percorsi_vault.py").is_file():
            sys.path.insert(0, str(Path(os.path.expanduser(r)) / "strumenti"))
            try:
                import percorsi_vault as pv
                return pv.vault(), pv.onedrive(), pv.radici_onedrive(), pv.repo(), pv.macchina()
            except Exception:
                break
            finally:
                sys.path.pop(0)
    od = CASA / "Library/CloudStorage/OneDrive"
    try:
        mem = Path(os.path.expanduser(json.loads((CASA / ".jarvis/percorsi.json").read_text()).get("memoria", "")))
    except (OSError, ValueError):
        mem = None
    return (mem if mem and str(mem) not in ("", ".") else CASA / "Jarvis-Memoria"), od, [od], CASA / "Jarvis", "mac" if sys.platform == "darwin" else "vps"


BRAIN, OD, TUTTE_OD, REPO, MACCHINA = _percorsi()
SU_MAC = MACCHINA == "mac"
if not SU_MAC and not os.environ.get("TZ"):
    # la VPS sta su UTC: nomi e date delle note in ora italiana, come quelle del Mac
    os.environ["TZ"] = "Europe/Rome"
    time.tzset()
CARTELLA_NOTE = BRAIN / "Sessioni"
# Sulla VPS un indice a parte: «Sessioni.md» lo riscrive il Mac a ogni evento e due scrittori sullo stesso file
# fanno i .conflictN di rclone bisync. Le note hanno il prefisso «vps-», quindi non si toccano mai con quelle del Mac.
INDICE = BRAIN / ("Sessioni.md" if SU_MAC else "Sessioni VPS.md")
PREFISSO = "" if SU_MAC else "vps-"
REGISTRO = CASA / ".jarvis/sessioni.json"
CTX = CASA / ".jarvis/ctx"
SPAZI = REPO / "command-center/spazi.json"
SOGLIE = (95,)        # 02/10/2026 (l'utente): la soglia del 50% non serve più; resta solo l'ultimo aggiornamento al 95%


def ora():
    return time.strftime("%Y-%m-%d %H:%M")


def slug(t, n=40):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n].strip("-")


def leggi():
    try:
        return json.loads(REGISTRO.read_text())
    except (OSError, ValueError):
        return {}


def scrivi(reg):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRO.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    tmp.replace(REGISTRO)


def progetto_di(cwd):
    """(spazio, progetto) dalla cartella, con spazi.json; se no il nome della cartella."""
    try:
        vero = Path(cwd).resolve()
        dati = json.loads(SPAZI.read_text())
        migliore = None
        # solo le cartelle OneDrive che contengono la cartella di lavoro: sulla VPS un resolve() su /mnt/onedrive
        # (rclone) a cache fredda costa circa un secondo, e qui ce ne sarebbero una decina
        dentro = [o for o in TUTTE_OD if o == vero or o.resolve() in vero.parents] or [OD]
        for sp in dati.get("spazi", []):
            for pr in sp.get("progetti", []):
                cart = pr.get("cartella", "")
                if cart.startswith("~/Jarvis"):
                    cart = str(REPO) + cart[len("~/Jarvis"):]
                # «OD/…» si prova su ogni cartella OneDrive presente (sulla VPS: copia locale e /mnt/onedrive)
                for od in dentro if cart.startswith("OD/") else [None]:
                    c = Path(os.path.expanduser(cart.replace("OD/", str(od) + "/", 1) if od else cart)).resolve()
                    if vero == c or c in vero.parents:
                        if not migliore or len(str(c)) > len(str(migliore[2])):
                            migliore = (sp.get("nome", ""), pr.get("nome", ""), c)
        if migliore:
            return migliore[0], migliore[1]
    except Exception:
        pass
    if Path(cwd).resolve() == CASA:
        return "Chat master", "tutto il computer"
    return "", Path(cwd).name


def nome_base(cwd, quando):
    spazio, prog = progetto_di(cwd)
    pezzi = [slug(spazio, 16), slug(prog, 20)] if spazio else [slug(prog, 30)]
    return PREFISSO + "-".join(p for p in pezzi if p) + "-" + time.strftime("%Y%m%d-%H%M", time.localtime(quando))


def nome(s):
    return s["base"] + (("-" + slug(s["tema"], 30)) if s.get("tema") else "")


def ripresa(s):
    return f"cd '{s['cwd']}' && claude --resume {s['id']}"


def scrivi_testo(file, testo):
    """Una scrittura sola per file, atomica: sulla VPS la copia del vault la porta su OneDrive rclone bisync
    (timer jarvis-vault-sync, 5 minuti) e i *.tmp sono esclusi dal suo filtro, quindi non parte mai un file a metà."""
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(testo)
    tmp.replace(file)


def nota(s):
    CARTELLA_NOTE.mkdir(parents=True, exist_ok=True)
    righe = ["---", "tipo: sessione", f"nome: {nome(s)}", f"id: {s['id']}", f"spazio: {s.get('spazio','')}",
             f"progetto: {s.get('progetto','')}", f"stato: {s['stato']}", f"aggiornato: {ora()}", "---", "",
             f"# {nome(s)}", "", f"- Tema: {s.get('tema') or '—'}", f"- Cartella: `{s['cwd']}`",
             f"- Iniziata: {s['inizio']} · ultimo segno: {s.get('ultimo', s['inizio'])} · stato: {s['stato']}",
             f"- Contesto usato: {s.get('ctx', '—')}%"] + ([] if SU_MAC else ["- Macchina: VPS (`ssh vps-tuo`, poi il comando qui sotto)"]) + [
             "", "Per riprenderla:", "", "```", ripresa(s), "```", "",
             "## Riassunti", ""]
    for r in s.get("riassunti", []) or []:
        righe += [f"### {r['quando']} · {r['chi']}", "", r["testo"].strip(), ""]
    if not s.get("riassunti"):
        righe += ["Nessun riassunto ancora: arriva al 95% del contesto o prima di una compattazione.", ""]
    righe += ["## Riferimenti", "", f"- [[{INDICE.stem}]]", "- [[Memoria]]"]
    scrivi_testo(CARTELLA_NOTE / f"{s['file']}.md", "\n".join(righe) + "\n")


def indice(reg):
    ss = sorted(reg.values(), key=lambda s: s.get("ultimo", s["inizio"]), reverse=True)[:60]
    righe = ["---", "tipo: indice", f"aggiornato: {ora()}", "---", "", f"# {INDICE.stem}",
             "", ("" if SU_MAC else "Le chat di Claude Code della VPS (quelle del Mac sono in [[Sessioni]]). ") + "Le sessioni di Claude Code, le più recenti in alto. Si rigenera da solo "
             "(`~/.claude/hooks/sessioni.py`). Per riprenderne una: apri la sua nota e copia il comando, "
             "oppure scrivi alla chat «riprendi <nome o tema>».", "",
             "| Sessione | Spazio · progetto | Stato | Ultimo segno | Ctx | Riassunti |", "|---|---|---|---|---|---|"]
    for s in ss:
        righe.append(f"| [[Sessioni/{s['file']}\\|{nome(s)}]] | {s.get('spazio','')} · {s.get('progetto','')} | "
                     f"{s['stato']} | {s.get('ultimo', s['inizio'])} | {s.get('ctx','—')}% | {len(s.get('riassunti') or [])} |")
    scrivi_testo(INDICE, "\n".join(righe) + "\n")


def salva(reg, s):
    reg[s["id"]] = s
    scrivi(reg)
    try:
        nota(s)
        indice(reg)
    except OSError:
        pass  # OneDrive non pronto: il registro locale resta giusto, la nota si rifà al giro dopo


PROFILO_JARVIS = REPO / "profilo-jarvis.md"
UMORISMO_JARVIS = ["nessuno", "misurato", "vivace", "sfacciato"]
SERIETA_JARVIS = ["leggero", "pacato", "professionale", "rigoroso"]


def profilo_jarvis():
    """Tono e umorismo di Jarvis, scelti dall'utente dalla lavagna (scheda «Jarvis — orchestratore»)."""
    try:
        testo = PROFILO_JARVIS.read_text(encoding="utf-8")
        campi = dict(re.findall(r"^(tono|serieta|umorismo|model|chiamami|nome_assistente|lingua|fuso_orario):[ \t]*(.*)$", testo.split("---")[1], re.M))
        u = max(0, min(3, int(campi.get("umorismo", "1") or 1)))
        sr = max(0, min(3, int(campi.get("serieta", "3") or 3)))
        chi = (campi.get("chiamami") or "").strip().strip('"')
        nome = (campi.get("nome_assistente") or "").strip().strip('"') or "Jarvis"
        identita = (f"\n\nIDENTITÀ (da profilo-jarvis.md): ti chiami {nome}; chiama l'utente «{chi}»"
                    + (f"; lingua: {campi.get('lingua').strip()}" if campi.get("lingua") else "")
                    + (f"; fuso orario: {campi.get('fuso_orario').strip()}" if campi.get("fuso_orario") else "") + "."
                    if chi and "{{" not in chi else
                    "\n\nIDENTITÀ: profilo-jarvis.md non dice ancora come chiamare l'utente: chiediglielo (comando /inizia).")
        return identita + (f"\n\nPROFILO DI JARVIS (scelto dall'utente sulla lavagna, vale per come parli in questa chat): "
                f"tono: {campi.get('tono', '').strip() or 'ironico ma misurato'}; serietà: {sr} su 3 ({SERIETA_JARVIS[sr]}) e umorismo: {u} su 3 ({UMORISMO_JARVIS[u]}) insieme. "
                "Le regole di CLAUDE.md e «Come si scrive» restano; l'umorismo non prende mai il posto dell'informazione.")
    except (OSError, ValueError, IndexError):
        return ""


def contesto(testo):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": sys.argv[1] == "inizio" and "SessionStart"
                                             or "UserPromptSubmit", "additionalContext": testo}},
                     ensure_ascii=False))


def ultime_richieste(percorso, n=6):
    out = []
    try:
        for riga in Path(percorso).read_text(errors="replace").splitlines()[-4000:]:
            try:
                d = json.loads(riga)
            except ValueError:
                continue
            if d.get("type") == "user":
                c = d.get("message", {}).get("content")
                t = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text")
                t = " ".join(t.split())
                if t and not t.startswith("<") and not t.startswith("Controllo dei 30 minuti"):
                    out.append(t[:220])
    except OSError:
        pass
    return out[-n:]


def trova_sessione(reg, chiave):
    if chiave in reg:
        return reg[chiave]
    k = slug(chiave, 80)
    trovate = [s for s in reg.values() if k and (k in nome(s) or k in slug(s.get("tema") or "", 80))]
    return max(trovate, key=lambda s: s.get("ultimo", s["inizio"])) if trovate else None


def ultima(reg, escludi=None):
    """L'ultima sessione vera prima di questa: salta quella in corso e le aperte da meno di 2 minuti senza lavoro."""
    adesso = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 120))
    cand = [s for s in reg.values() if s["id"] != escludi and
            (s.get("riassunti") or s.get("tema") or s.get("ultimo", s["inizio"]) < adesso)]
    return max(cand, key=lambda s: s.get("ultimo", s["inizio"])) if cand else None


def hook(evento):
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return 0
    sid, reg = d.get("session_id"), leggi()
    if not sid:
        return 0
    s = reg.get(sid)
    if evento == "inizio":
        if not s:
            quando = time.time()
            spazio, prog = progetto_di(d.get("cwd") or os.getcwd())
            s = {"id": sid, "cwd": d.get("cwd") or os.getcwd(), "inizio": ora(), "spazio": spazio,
                 "progetto": prog, "base": nome_base(d.get("cwd") or os.getcwd(), quando), "tema": "",
                 "stato": "aperta", "riassunti": [], "soglie": []}
            s["file"] = s["base"]
        s["stato"], s["ultimo"], s["pid"] = "aperta", ora(), os.getppid()
        salva(reg, s)
        ultimo = (s.get("riassunti") or [None])[-1]
        testo = (f"Questa sessione si chiama «{nome(s)}» (id {sid}). La sua nota è `Jarvis Brain/Sessioni/{s['file']}.md`. "
                 f"Per riprenderla: `{ripresa(s)}`. Quando capisci l'argomento dalle prime richieste dell'utente, dagli un tema "
                 f"corto: `python3 ~/.claude/hooks/sessioni.py tema {sid} \"tema\"`. Se l'utente dice «riprendi <qualcosa>», "
                 "usa `python3 ~/.claude/hooks/sessioni.py trova \"<qualcosa>\"` e riparti dall'ultimo riassunto, senza rianalizzare.")
        if ultimo:
            testo += f"\nUltimo riassunto ({ultimo['quando']}):\n{ultimo['testo']}"
        prec = ultima(reg, sid)
        if prec and d.get("source") != "resume":
            r = (prec.get("riassunti") or [None])[-1]
            testo += (f"\n\nL'ULTIMA CHAT prima di questa è «{nome(prec)}» ({prec['stato']}, ultimo segno {prec.get('ultimo')}). "
                      "Se l'utente dice «riprendi l'ultima chat», «apri l'ultima chat» o simili, riparti da qui senza rianalizzare "
                      f"(nota: `Jarvis Brain/Sessioni/{prec['file']}.md`; per riaprirla proprio: `{ripresa(prec)}`).")
            if r:
                testo += f"\nIl suo ultimo riassunto ({r['quando']}):\n{r['testo']}"
        contesto(testo + profilo_jarvis())
        return 0
    if not s:
        return 0
    s["ultimo"] = ora()
    if evento == "prompt":
        try:
            s["ctx"] = round(float((CTX / sid).read_text().strip()))
        except (OSError, ValueError):
            pass
        testo = None
        for soglia in SOGLIE:
            if s.get("ctx", 0) >= soglia and soglia not in s.get("soglie", []):
                s.setdefault("soglie", []).append(soglia)
                if soglia < 90:
                    testo = (f"CONTESTO AL {s['ctx']}% (soglia {soglia}%). Regola dell'utente del 29/09/2026: adesso aggiorna il contesto della chat e avvia la skill "
                             "`/aggiorna-memoria` (salva in memoria: note in Jarvis Brain/Memoria/<spazio>, Da fare, diario; poi la pulizia di ~/.claude con "
                             "`python3 ~/Jarvis/strumenti/pulisci_claude.py --applica`). Scrivi il riassunto con "
                             f"`python3 ~/.claude/hooks/sessioni.py riassunto {sid} \"FATTO: ... | DA FARE: ... | DA CONCLUDERE: ... | ERRORI: ...\"`. "
                             "Poi rispondi alla sua richiesta e CONTINUA a lavorare in questa stessa chat: il contesto si usa fino al 95%, dove c'è l'ultimo aggiornamento.")
                else:
                    testo = (f"CONTESTO AL {s['ctx']}% (soglia {soglia}%): ULTIMO AGGIORNAMENTO. Prima di rispondere all'utente: 1) `/aggiorna-memoria` (memoria, Da fare, diario, "
                             "pulizia con pulisci_claude.py --applica); 2) riassunto finale con "
                             f"`python3 ~/.claude/hooks/sessioni.py riassunto {sid} \"FATTO: ... | DA FARE: ... | DA CONCLUDERE: ... | ERRORI: ...\"` (è il piccolo report che la chat nuova leggerà); "
                             f"3) di' all'utente in una riga che la sessione «{nome(s)}» è chiusa e che per continuare apre una CHAT NUOVA e scrive «riprendi l'ultima chat» "
                             "(legge solo il riassunto, non l'intera sessione; `--resume` solo se serve davvero tutta la cronologia). Poi rispondi alla sua richiesta.")
        salva(reg, s)
        if testo:
            contesto(testo)
        return 0
    if evento == "compatta":
        richieste = ultime_richieste(d.get("transcript_path", ""))
        s.setdefault("riassunti", []).append({"quando": ora(), "chi": "automatico prima della compattazione",
                                              "testo": "Ultime richieste dell'utente:\n" + "\n".join(f"- {r}" for r in richieste)})
        salva(reg, s)
        return 0
    if evento == "fine":
        s["stato"] = "chiusa"
        salva(reg, s)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    c = sys.argv[1]
    if c in ("inizio", "prompt", "compatta", "fine"):
        if os.environ.get("JARVIS_SESSIONI", "1") == "0":  # i giri automatici (claude -p) possono spegnere la nota
            return 0
        try:
            return hook(c)
        except Exception as e:  # un hook non deve mai fermare Claude Code
            print(f"sessioni.py: {e}", file=sys.stderr)
            return 0
    reg = leggi()
    if c in ("tema", "riassunto") and len(sys.argv) >= 4:
        s = trova_sessione(reg, sys.argv[2])
        if not s:
            sys.exit("sessione non trovata")
        if c == "tema":
            s["tema"] = sys.argv[3]
        else:
            s.setdefault("riassunti", []).append({"quando": ora(), "chi": "Jarvis", "testo": sys.argv[3]})
        s["ultimo"] = ora()
        salva(reg, s)
        print(f"{nome(s)} · nota: Jarvis Brain/Sessioni/{s['file']}.md")
        return 0
    if c == "trova" and len(sys.argv) >= 3:
        s = trova_sessione(reg, " ".join(sys.argv[2:]))
        if not s:
            sys.exit("nessuna sessione trovata")
        print(f"{nome(s)}  ({s['stato']}, ultimo segno {s.get('ultimo')})\nripresa: {ripresa(s)}\n"
              f"nota: {CARTELLA_NOTE / (s['file'] + '.md')}")
        for r in (s.get("riassunti") or [])[-1:]:
            print(f"\nultimo riassunto ({r['quando']}):\n{r['testo']}")
        return 0
    if c == "ultima":
        p = ultima(reg, sys.argv[2] if len(sys.argv) > 2 else None)
        if not p:
            sys.exit("nessuna sessione precedente")
        if "--comando" in sys.argv:
            print(ripresa(p))
            return 0
        print(f"{nome(p)}  ({p['stato']}, ultimo segno {p.get('ultimo')})\nripresa: {ripresa(p)}")
        for r in (p.get("riassunti") or [])[-1:]:
            print(f"\nultimo riassunto ({r['quando']}):\n{r['testo']}")
        return 0
    if c == "elenco":
        for s in sorted(reg.values(), key=lambda s: s.get("ultimo", s["inizio"]), reverse=True)[:15]:
            print(f"{s.get('ultimo','')}  {s['stato']:7} {nome(s)}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
