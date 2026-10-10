#!/usr/bin/env python3
"""Scrive .jarvis_status nel bus: cosa sta facendo questa sessione di
Claude Code adesso, per il pannello "Claude adesso" nel Command Center e
nel volto grafo.

Uso: jarvis_status.py <evento>, con l'evento hook di Claude Code su stdin.
  prompt      UserPromptSubmit — una richiesta è arrivata
  stop        Stop — il turno è finito, torna inattivo
  pre-agent   PreToolUse, matcher "Agent" — un sottoagente è stato lanciato
  post-agent  PostToolUse, matcher "Agent" — finito (o passato in background)
  sub-stop    SubagentStop — un sottoagente in background ha finito
  post        PostToolUse, tutti i tool — cosa sta facendo adesso

Ogni agente ha `stato` (attivo / finito) e `nodo`: il nome dell'agente nella
catena (il capogruppo <progetto>-ceo e, sotto di lui, gli specialisti), ricavato dal tipo o dal
profilo citato nel prompt, per accenderlo nel pannello del Command Center.

Un file solo, letto-modificato-riscritto sotto un lucchetto (fcntl), e scritto
in modo atomico (file temporaneo + rename). Serve: per lo strumento Agent
girano in parallelo due ganci PostToolUse, e senza lucchetto uno leggeva il
file a metà scrittura, lo trovava vuoto e lo riscriveva senza gli agenti.
"""
try:
    import fcntl
except ImportError:            # Windows (ramo windows): niente fcntl, lucchetto con msvcrt
    fcntl = None
    import msvcrt
import json
import os
import re
import sys
import time
from pathlib import Path

BUS = Path(os.environ.get("JARVIS_BUS") or (Path.home() / "my-agent/backtalk/.jarvis_status"))
# Windows (ramo windows): Jarvis non sta in ~/my-agent ma nella cartella che contiene questo gancio
_QUI = Path(__file__).resolve().parents[2]
if sys.platform == "win32" and not os.environ.get("JARVIS_BUS"):
    BUS = (_QUI if (_QUI / "command-center").is_dir() else Path.home() / "my-agent") / "backtalk" / ".jarvis_status"
MAX_AGENTI = 8

# 2026-10-02 (audit della lavagna): oltre al bus, che tiene solo gli ultimi 8 lanci, ogni passaggio va
# nel registro delle attività (command-center/attivita.py, JSONL un file al giorno). Se manca, il gancio
# resta quello di prima.
sys.path.insert(0, str((_QUI if sys.platform == "win32" else Path.home() / "my-agent") / "command-center"))
try:
    import attivita  # noqa: E402
except Exception:  # noqa: BLE001
    attivita = None


def registra(*args, **kw):
    if attivita is not None:
        attivita.registra(*args, fonte="hook", **kw)


def tool_use_del_sottoagente(dati, agent_id):
    """Il tool_use_id che ha lanciato un sottoagente, dal suo meta.json (lo scrive Claude Code accanto
    alla trascrizione: ~/.claude/projects/<prog>/<sessione>/subagents/agent-<id>.meta.json, campo toolUseId)."""
    if not agent_id:
        return ""
    tp = Path(str(dati.get("transcript_path") or ""))
    candidati = [tp.parent / str(dati.get("session_id") or "") / "subagents" / f"agent-{agent_id}.meta.json",
                 tp.parent / f"agent-{agent_id}.meta.json"]
    for f in candidati:
        try:
            return json.loads(f.read_text()).get("toolUseId") or ""
        except (OSError, ValueError):
            continue
    return ""


def mittente(dati, d):
    """Chi manda la richiesta: il sottoagente che sta lavorando (se il gancio scatta dentro di lui),
    altrimenti chi ha aperto la sessione (JARVIS_MITTENTE, messo dal pannello per le chat con un agente),
    altrimenti Jarvis."""
    tid = tool_use_del_sottoagente(dati, dati.get("agent_id"))
    if tid:
        for a in d.get("agenti") or []:
            if a.get("id") == tid:
                return a.get("nodo") or a.get("tipo") or "?"
        return "?:sottoagente"
    return os.environ.get("JARVIS_MITTENTE") or "jarvis"


def testo_risposta(risposta):
    if isinstance(risposta, dict):
        c = risposta.get("content")
        if isinstance(c, list):
            return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        return str(c or risposta.get("result") or risposta.get("output") or "")
    return str(risposta or "")


def errore_di(risposta):
    """Il motivo, se lo strumento Agent è tornato con un errore; '' se è andato."""
    if isinstance(risposta, dict) and (risposta.get("is_error") or risposta.get("error")):
        return str(risposta.get("error") or testo_risposta(risposta) or "errore")[:300]
    t = testo_risposta(risposta).lstrip()
    if t.startswith(("Error:", "<tool_use_error>", "Agent type '")):
        return t[:300]
    return ""


NOTIFICA = re.compile(r"<tool-use-id>(?P<tid>[^<]+)</tool-use-id>.*?<status>(?P<stato>[^<]+)</status>"
                      r"(?:.*?<summary>(?P<riassunto>.*?)</summary>)?(?:.*?<result>(?P<esito>.*?)(?:</result>|$))?", re.S)


def leggi():
    try:
        return json.loads(BUS.read_text())
    except (OSError, ValueError):
        return {}


def scrivi(d):
    try:
        tmp = BUS.with_name(BUS.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, BUS)
    except OSError:
        pass


def nome_tool(tool):
    # gli strumenti MCP arrivano come "mcp__server__metodo": lungo e tecnico,
    # per il pannello basta l'ultimo pezzo (il metodo vero).
    if tool.startswith("mcp__"):
        return tool.rsplit("__", 1)[-1]
    return tool


def nodo_di(ti):
    """Il nome dell'agente nella catena: il tipo, se non è generico, oppure il
    profilo che Jarvis gli ha passato nel prompt (…/agents/<nome>.md)."""
    tipo = ti.get("subagent_type") or ""
    if tipo and tipo not in ("general-purpose", "claude", "fork", "Explore", "Plan"):
        return tipo
    testo = str(ti.get("prompt") or "")
    # 2026-10-02: prima il segnaposto esplicito «[AGENTE progetto:nome]» (o «[AGENTE nome]») in testa al
    # compito, poi «[INIZIO PROFILO nome]». Il percorso «agents/<nome>.md» vale solo nelle prime 400 lettere:
    # cercato in tutto il testo prendeva il primo file citato (02/10: «Ripulisce regole obsolete» → postino).
    # 2026-10-05 (lavagna viva): anche «Agente: marketing (gruppo <spazio>)» e «(agente: nome)», la forma
    # che la chat master usa davvero per riunioni e programmatori. Senza, 66 lanci su 66 del 05/10 finivano
    # su «general-purpose», che la lavagna non sa dove mettere («?:general-purpose»): niente si muoveva.
    m = (re.search(r"\[\s*AGENTE\s+([\w-]+(?::[\w-]+)?)\s*\]", testo, re.I)
         or re.search(r"\[\s*INIZIO\s+PROFILO\s+([\w-]+)\s*\]", testo, re.I)
         or re.search(r"\bagente\s*:\s*`?([\w-]+(?::[\w-]+)?)", testo[:400], re.I)
         or re.search(r"agents[\\/]([\w-]+)\.md", testo[:400]) )
    if not m:
        return tipo
    nome = m.group(1)
    gruppo, _ = gruppo_di(testo)
    # il gruppo (spazio o progetto) davanti al nome: il server sceglie l'agente giusto fra omonimi
    # («revisore» del gruppo <spazio> = <spazio>:revisore)
    return f"{gruppo}:{nome}" if gruppo and ":" not in nome else nome


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", str(t or "").lower()).strip("-")


def gruppo_di(testo):
    """(gruppo, riunione): il gruppo dal percorso della riunione (…/riunioni/<gruppo>/AAAA-MM-GG/) o da
    «(gruppo <spazio>» nelle prime righe; riunione=True se viene dal percorso."""
    testo = str(testo or "")
    m = re.search(r"riunioni[\\/]([\w-]+)[\\/]\d{4}-\d\d-\d\d", testo[:1500])
    if m:
        return _slug(m.group(1)), True
    m = re.search(r"\(\s*gruppo\s+([^,)\n]+)", testo[:400], re.I)
    return (_slug(m.group(1)), False) if m else ("", False)


def chiudi(agenti, trova):
    for a in reversed(agenti):              # il più vecchio ancora attivo
        if a.get("stato") == "attivo" and trova(a):
            a["stato"] = "finito"
            a["fine"] = time.time()
            return True
    return False


def testo_azione(tool, ti):
    if tool in ("Read", "Edit", "Write", "NotebookEdit"):
        p = ti.get("file_path") or ti.get("path") or ""
        return Path(p).name if p else ""
    if tool == "Bash":
        return (ti.get("description") or ti.get("command") or "")[:80]
    if tool == "Agent":
        return (ti.get("description") or ti.get("subagent_type") or "")[:80]
    if tool in ("Grep", "Glob"):
        return (ti.get("pattern") or "")[:80]
    if tool in ("WebFetch", "WebSearch"):
        return (ti.get("url") or ti.get("query") or "")[:80]
    return ""


def main():
    # 2026-09-26: i claude -p di servizio del Command Center (la sentinella su Haiku) non sono
    # «Jarvis al lavoro»: con JARVIS_STATUS_MUTO=1 il gancio non scrive nel bus.
    if os.environ.get("JARVIS_STATUS_MUTO"):
        return
    evento = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        dati = json.load(sys.stdin)
    except ValueError:
        dati = {}

    if sys.platform == "win32":
        BUS.parent.mkdir(parents=True, exist_ok=True)
    lucchetto = open(BUS.with_name(BUS.name + ".lock"), "w")
    if fcntl:
        fcntl.flock(lucchetto, fcntl.LOCK_EX)
    else:
        for _ in range(100):           # msvcrt non attende: si riprova per ~5 s
            try:
                msvcrt.locking(lucchetto.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.05)
    d = leggi()
    now = time.time()

    testo_prompt = str(dati.get("prompt", "")).lstrip()
    if evento == "prompt" and testo_prompt.startswith("<task-notification>"):
        # 2026-10-02: la fine VERA di un sottoagente in sfondo arriva qui, con il suo tool_use_id, lo stato
        # (completed / failed / killed) e il risultato. Prima si scartava e la fine la decideva SubagentStop,
        # che chiudeva «il più vecchio general-purpose attivo» dopo ~31 s (prova: 8 lanci su 8 il 02/10).
        m = NOTIFICA.search(testo_prompt)
        if m:
            tid, st = m.group("tid").strip(), m.group("stato").strip().lower()
            for a in d.get("agenti") or []:
                if a.get("id") == tid:
                    if a.get("stato") == "attivo":
                        a["stato"], a["fine"] = ("finito" if st == "completed" else "errore"), now
                    ok = st == "completed"
                    registra("risposta" if ok else "errore", tid, a.get("nodo") or a.get("tipo"), a.get("da") or "jarvis",
                             a.get("descrizione", ""), esito=(m.group("esito") or m.group("riassunto") or "")[:400],
                             errore="" if ok else f"{st}: {m.group('riassunto') or ''}"[:300],
                             durata_s=round(now - a.get("ts", now), 1), sessione=dati.get("session_id"))
                    break
            d["ts"] = now
            scrivi(d)
        return
    if evento == "prompt" and testo_prompt.startswith(("Warmup ping", "<system-reminder>")):
        return          # riscaldamento della voce o avviso interno, non una richiesta dell'utente
    if evento == "prompt":
        prompt = str(dati.get("prompt", ""))[:160]
        d.update({"lavorando": True, "richiesta": prompt, "richiesta_ts": now,
                  "azione": "", "dettaglio": ""})
    elif evento == "stop":
        d.update({"lavorando": False, "azione": "", "dettaglio": "", "ts": now})
        # un agente in primo piano non sopravvive al turno: se è rimasto «attivo» (chiamata fallita, gancio
        # di fine perso) lo si chiude qui, così la sinapsi non resta accesa per ore (29/09/2026, dal Jarvis Windows)
        # 2026-10-02: solo gli agenti di QUESTA sessione (sul Mac girano più sessioni sullo stesso bus)
        sessione = dati.get("session_id")
        for a in d.get("agenti") or []:
            if a.get("stato") == "attivo" and not a.get("sfondo") and (not a.get("sessione") or a.get("sessione") == sessione):
                a["stato"], a["fine"] = "finito", now
                registra("errore", a.get("id"), a.get("nodo"), a.get("da") or "jarvis", a.get("descrizione", ""),
                         errore="turno finito senza la risposta dell'agente", durata_s=round(now - a.get("ts", now), 1))
    elif evento == "pre-agent":
        ti = dati.get("tool_input") or {}
        agenti = d.get("agenti") or []
        da = mittente(dati, d)
        nodo = nodo_di(ti)
        # 2026-10-05 (lavagna viva): in una riunione chi chiede è il capogruppo del gruppo, non Jarvis
        # (l'utente: «capogruppo ↔ specialisti ↔ revisore»). Il server trova il capogruppo («<gruppo>:capogruppo»)
        # e, se il gruppo non ha una scheda, torna a «jarvis».
        gruppo, riunione = gruppo_di(ti.get("prompt"))
        if riunione and da == "jarvis" and not nodo.split(":")[-1].startswith("ceo-"):
            da = f"{gruppo}:capogruppo"
        tid = dati.get("tool_use_id", "")
        agenti.insert(0, {"ts": now, "tipo": ti.get("subagent_type", ""),
                          "descrizione": (ti.get("description") or "")[:100],
                          "nodo": nodo, "stato": "attivo", "id": tid, "da": da,
                          "sessione": dati.get("session_id", ""),
                          "sfondo": bool(ti.get("run_in_background"))})
        d["agenti"] = agenti[:MAX_AGENTI]
        registra("richiesta", tid, da, nodo, ti.get("description") or "", sessione=dati.get("session_id"),
                 cwd=dati.get("cwd"), modello=ti.get("model"), tipo=ti.get("subagent_type"),
                 sfondo=bool(ti.get("run_in_background")), dettaglio=str(ti.get("prompt") or "")[:300])
    elif evento == "post-agent":
        tid = dati.get("tool_use_id", "")
        # Un agente in background risponde subito «launched»: il PostToolUse
        # arriva al lancio, non alla fine. Lo chiude la <task-notification> (vedi «prompt»).
        grezza = dati.get("tool_response", "")
        risposta = json.dumps(grezza, ensure_ascii=False).lower()
        in_sfondo = "async" in risposta or "launched" in risposta
        errore = errore_di(grezza)
        for a in d.get("agenti") or []:
            if a.get("id") and a.get("id") == tid:
                if in_sfondo and not errore:
                    a["sfondo"] = True
                    registra("partito", tid, a.get("da") or "jarvis", a.get("nodo"), sfondo=True)
                elif not a.get("sfondo") or errore:
                    a["stato"] = "errore" if errore else "finito"
                    a["fine"] = now
                    registra("errore" if errore else "risposta", tid, a.get("nodo"), a.get("da") or "jarvis",
                             a.get("descrizione", ""), esito=testo_risposta(grezza)[:400], errore=errore,
                             durata_s=round(now - a.get("ts", now), 1))
    elif evento == "sub-stop":
        # 2026-10-02: si chiude solo l'agente giusto, ritrovato dal suo meta.json. Prima si chiudeva «il più
        # vecchio attivo dello stesso tipo»: con tutti general-purpose chiudeva quello sbagliato, e un
        # SubagentStop che arriva ~31 s dopo ogni lancio in sfondo li dava tutti finiti (02/10: 8 su 8).
        # Gli agenti in sfondo li chiude la <task-notification>; qui solo quelli in primo piano.
        tid = tool_use_del_sottoagente(dati, dati.get("agent_id"))
        chiudi(d.get("agenti") or [], lambda a: a.get("id") == tid and not a.get("sfondo"))
    elif evento == "post":
        tool = dati.get("tool_name", "")
        ti = dati.get("tool_input") or {}
        d.update({"lavorando": True, "azione": nome_tool(tool),
                  "dettaglio": testo_azione(tool, ti), "azione_ts": now})

    d["ts"] = now
    scrivi(d)


if __name__ == "__main__":
    main()
