#!/usr/bin/env python3
"""Una missione di Jarvis: un obiettivo, uno spazio, uno o più progetti.

Dal 23/09/2026 una missione è UN solo processo SDK. Dentro gira un
orchestratore (sonnet) che lancia IN PARALLELO gli esperti dei progetti scelti
come sottoagenti dello stesso processo (strumento Agent/Task), senza aprire
altre finestre o sessioni. Prima era un processo per progetto con il
caposquadra in cima: con tanti lavori si aprivano tante chat e non reggeva.

Gira con il Python di backtalk (ha claude_agent_sdk). Il server la lancia così:
    python missione.py <cartella_missione>
Nella cartella trova missione.json (spazio, progetti, obiettivo, max_paralleli,
modalita, report_file). Scrive:
    registro.log           cosa dicono e fanno l'orchestratore e gli esperti
    stato.json             in corso / attende conferma / attende istruzioni / chiusa
    agenti.json            l'albero: un sottoagente per riga, con stato ed esito
    richieste/<id>.json    un'azione da confermare; aspetta <id>.risposta.json
Legge:
    messaggi/*.txt         nuove istruzioni dell'utente durante la missione
    chiudi                 file vuoto: chiude la missione

Ogni strumento passa da can_use_tool. In modalità «lavoro» chiede la conferma
dell'utente nel Command Center solo quello che conferme.py giudica irreversibile o
fuori dal progetto (regola dell'utente del 19/09/2026). In modalità «lettura» nega
senza chiedere ogni scrittura, tranne il report della missione. Nessuna
risposta in 30 minuti vale come «no».

Il tetto al parallelo sta in un gancio PreToolUse sullo strumento Agent: se ci
sono già N esperti al lavoro il nuovo lancio si nega con «aspetta che uno
finisca», e l'orchestratore riprova dopo.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (AgentDefinition, AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient,
                              HookMatcher, PermissionResultAllow, PermissionResultDeny, ResultMessage,
                              TaskNotificationMessage, TaskStartedMessage, TaskUpdatedMessage, TextBlock, ToolResultBlock,
                              ToolUseBlock, UserMessage)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conferme import motivo, motivo_lettura, radici  # noqa: E402
# 2026-10-03 sera (server-modo-ponte-2.patch): da internet anche leggere un file passa dall'utente (la lettura di una
# chiave ssh è passata da sola nella prova del revisore); restano liberi solo la lista delle cose da fare e i sottoagenti,
# le cui chiamate passano comunque di qui.
STRUMENTI_LIBERI_SITO = {"TodoWrite", "Agent", "Task"}
import spazi  # noqa: E402
try:                    # registro delle attività degli agenti (2026-10-02): se manca, la missione va avanti uguale
    import attivita  # noqa: E402
except Exception:  # noqa: BLE001
    attivita = None

ATTESA_CONFERMA_S = 30 * 60
ATTESA_ISTRUZIONI_S = 60 * 60
BATTITO_OGNI_S = 60         # rinfresca «lavori.py chi» durante la missione (30/09/2026, vedi battito_lavori)
STRUMENTI_AGENTE = ("Agent", "Task")
# gli strumenti stanno accanto a command-center/, ovunque sia installato Jarvis (niente ~/Jarvis scritto a mano);
# idea dal Jarvis Windows (29/09/2026). Il percorso non passa da resolve(): ~/Jarvis è un collegamento e resta com'è.
STRUMENTI_DIR = (Path(__file__).absolute().parents[1] / "strumenti").as_posix()
PY_CMD = "python" if sys.platform == "win32" else "python3"
LAVORI = f'{PY_CMD} "{STRUMENTI_DIR}/lavori.py"'

DIR = Path(sys.argv[1]).resolve()
CONF = json.loads((DIR / "missione.json").read_text())
RICHIESTE = DIR / "richieste"
CATENA = CONF.get("genere") == "aggiorna_catena"     # «Aggiorna agenti → Jarvis» (2026-09-26)
ULTIME = CATENA and CONF.get("ambito") == "ultime"    # solo gli agenti delle ultime modifiche (2026-09-26 19:10)
SOLO = CONF.get("solo_agenti") or {}                  # progetto -> nomi degli agenti coinvolti
ATTESA_FINE_CATENA_S = 20
ATTESA_NOTIFICA_S = 30      # task «completed» senza notifica: si consegna dopo 30 s (27/09/2026)
CHIUSURA_CLIENT_S = 20      # l'uscita del client SDK a volte resta appesa: dopo 20 s si va avanti (27/09/2026)
MESSAGGI = DIR / "messaggi"
RICHIESTE.mkdir(exist_ok=True)
MESSAGGI.mkdir(exist_ok=True)
REGISTRO = DIR / "registro.log"
LETTURA = CONF.get("modalita", "lettura") != "lavoro"
MAX_PARALLELI = max(1, int(CONF.get("max_paralleli") or 5))
REPORT_DIR = Path(CONF["report"])
REPORT_FILE = Path(CONF["report_file"])
# in lettura si scrive solo il report e la cartella della missione
RADICI = [REPORT_DIR.resolve(), DIR] if LETTURA else radici(CONF["cwd"], CONF.get("add_dirs", []))


def scrivi(riga):
    with open(REGISTRO, "a") as f:
        f.write(f"[{datetime.now():%H:%M:%S}] {riga}\n")


def stato(valore, **altro):
    dati = {"stato": valore, "aggiornato": datetime.now().isoformat(timespec="seconds"), **altro}
    tmp = DIR / "stato.json.tmp"
    tmp.write_text(json.dumps(dati, ensure_ascii=False))
    tmp.replace(DIR / "stato.json")


def breve(tool, inp):
    inp = inp or {}
    if tool == "Bash":
        return inp.get("command", "")
    if tool in ("Edit", "Write", "Read", "NotebookEdit"):
        return inp.get("file_path", "")
    if tool in STRUMENTI_AGENTE:
        # 27/09/2026: stesso default di agente(), se no il registro diceva «agente:» e la consegna «general-purpose»
        return f"{inp.get('subagent_type') or 'general-purpose'}: {inp.get('description', '')}"
    if tool in ("WebFetch",):
        return inp.get("url", "")
    return json.dumps(inp, ensure_ascii=False)[:300]


# ---------------------------------------------------------------- l'albero degli agenti
# Un sottoagente per chiave tool_use_id. Stati: «in coda» (chiesto, non ancora
# partito o rimandato dal tetto), «lavora», «consegnato», «errore».
AGENTI = {}
MODELLO = {}          # nome esperto -> modello del profilo
CAPOGRUPPI = set()
PROG_DI = {}          # nome esperto (come lo vede l'SDK) -> id del suo progetto (2026-10-02)
NOME_VERO = {}        # «crm-revisore» (nome reso unico) -> «revisore» (nome del profilo)


def chiave(nome):
    """«progetto:nome» di un esperto, come la usa la lavagna. Con più progetti nella missione il server
    oggi mette tutti sotto il primo: qui ognuno sta sotto il suo."""
    nome = str(nome or "general-purpose")
    if nome == "orchestratore":
        return f"{CONF['progetti'][0]['id']}:orchestratore"
    return f"{PROG_DI.get(nome) or CONF['progetti'][0]['id']}:{NOME_VERO.get(nome, nome)}"


def mittente(descrizione):
    """«[<capogruppo>] …» nella description: l'orchestratore lancia per conto di quel capogruppo (catena)."""
    m = re.match(r"\[([\w.-]+)\]", str(descrizione or "").strip())
    return chiave(m.group(1)) if m else chiave("orchestratore")


def traccia(ev, tid, da, a, testo="", **altro):
    if attivita is not None:
        attivita.registra(ev, tid, da, a, testo, fonte="missione", missione=DIR.name, **altro)


def salva_agenti():
    righe = sorted(AGENTI.values(), key=lambda a: (a.get("inizio") or "9", a["chiesto"]))
    tmp = DIR / "agenti.json.tmp"
    tmp.write_text(json.dumps({"max_paralleli": MAX_PARALLELI, "agenti": righe}, ensure_ascii=False, indent=1))
    tmp.replace(DIR / "agenti.json")


def al_lavoro():
    return sum(1 for a in AGENTI.values() if a["stato"] == "lavora")


def agente(tid, inp):
    """La riga di un sottoagente: la crea se manca (il gancio può arrivare prima del messaggio)."""
    if tid not in AGENTI:
        tipo = (inp or {}).get("subagent_type") or "general-purpose"
        AGENTI[tid] = {"id": tid, "tipo": tipo, "descrizione": (inp or {}).get("description", ""),
                       "da": mittente((inp or {}).get("description", "")),
                       "modello": (inp or {}).get("model") or MODELLO.get(tipo, "—"),
                       "capogruppo": tipo in CAPOGRUPPI, "stato": "in coda",
                       "chiesto": datetime.now().isoformat(timespec="seconds"),
                       "inizio": None, "fine": None, "esito": "", "ultima": ""}
    return AGENTI[tid]


TASK = {}            # task_id della CLI -> tool_use_id, per i messaggi di fine in sottofondo
FINITI_SENZA_NOTIFICA = {}   # tool_use_id -> (quando, testo): «completed» visto solo in TaskUpdatedMessage
LANCIATO_IN_SOTTOFONDO = re.compile(r"\s*(Async agent launched successfully|Cloud agent launched)\b")


def leggi_uscita(msg):
    """L'esito di un esperto in sottofondo: il riassunto della notifica (è la sua risposta),
    se no il file d'uscita, ma solo se è testo e non la trascrizione JSON della sessione."""
    if (msg.summary or "").strip():
        return msg.summary.strip()
    try:
        testo = Path(msg.output_file).read_text(encoding="utf-8")[-60000:] if msg.output_file else ""
    except OSError:
        testo = ""
    return "" if testo.lstrip().startswith("{") else testo.strip()


def testo_risultato(contenuto):
    if isinstance(contenuto, str):
        return contenuto
    parti = []
    for c in contenuto or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parti.append(c.get("text", ""))
    return "\n".join(parti)


def prime_righe(testo, n=6):
    righe = [r for r in (testo or "").strip().splitlines() if r.strip()]
    return "\n".join(righe[:n])[:900]


def consegna(tid, testo, errore=False):
    a = AGENTI.get(tid)
    if not a or a["stato"] in ("consegnato", "errore"):
        return
    if a["stato"] == "in coda":        # negato dal tetto o dall'utente: resta in coda, riproverà
        a["esito"] = prime_righe(testo, 2)
        salva_agenti()
        return
    a["stato"] = "errore" if errore else "consegnato"
    a["fine"] = datetime.now().isoformat(timespec="seconds")
    a["esito"] = prime_righe(testo)
    (DIR / "esiti").mkdir(exist_ok=True)                  # l'esito intero, per il pulsante «apri»
    (DIR / "esiti" / f"{tid}.md").write_text(testo or "")
    salva_agenti()
    scrivi(f"◆ {a['tipo']} {a['stato']}: {prime_righe(testo, 1)[:200]}")
    traccia("errore" if errore else "risposta", tid, chiave(a["tipo"]), a.get("da") or chiave("orchestratore"),
            a.get("descrizione", ""), esito=prime_righe(testo, 3)[:400], errore=prime_righe(testo, 1)[:300] if errore else "",
            durata_s=round(time.time() - a["t0"], 1) if a.get("t0") else None, modello=a.get("modello"))
    if CATENA:
        controlla_riscritti(a["tipo"])


async def gancio_agent(inp, tool_use_id, ctx):
    """PreToolUse su Agent/Task: il tetto al parallelo."""
    tinp = inp.get("tool_input") or {}
    tid = inp.get("tool_use_id") or tool_use_id or uuid.uuid4().hex
    a = agente(tid, tinp)

    def nega(perche):
        a["esito"] = perche
        salva_agenti()
        scrivi(f"⏳ {a['tipo']} rimandato: {perche}")
        traccia("rimandato", tid, a.get("da") or chiave("orchestratore"), chiave(a["tipo"]), a["descrizione"], errore=perche[:300])
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": perche}}

    if al_lavoro() >= MAX_PARALLELI:
        return nega(f"Ci sono già {MAX_PARALLELI} esperti al lavoro (il tetto di questa missione): "
                    "aspetta che uno finisca, poi rilancia questo.")
    # un lancio vero toglie le righe «in coda» dello stesso esperto rimandate prima
    for k in [k for k, x in AGENTI.items() if k != tid and x["stato"] == "in coda" and x["tipo"] == a["tipo"]]:
        del AGENTI[k]
    a["stato"] = "lavora"
    a["inizio"] = datetime.now().isoformat(timespec="seconds")
    a["t0"] = time.time()
    a["esito"] = ""
    salva_agenti()
    a["modello"] = tinp.get("model") or a.get("modello") or "—"     # il modello usato va nel registro (2026-09-26)
    scrivi(f"▶ {a['tipo']} parte [{a['modello']}] ({al_lavoro()}/{MAX_PARALLELI} al lavoro): {a['descrizione']}")
    traccia("partito", tid, a.get("da") or chiave("orchestratore"), chiave(a["tipo"]), a["descrizione"], modello=a["modello"])
    return {}


# ---------------------------------------------------------------- permessi
# 27/09/2026: con due conferme aperte insieme, la prima che finiva scriveva «in corso» mentre
# l'altra aspettava ancora. Si contano: «in corso» solo quando non ne resta nessuna.
PENDENTI = {"n": 0}


async def conferma(tool, tool_input, ctx):
    if LETTURA:
        perche = motivo_lettura(tool, tool_input, RADICI)
        if perche is None and CONF.get("chiedi_tutto") and tool not in STRUMENTI_LIBERI_SITO:
            return await chiedi_a_utente(tool, tool_input, "dal sito: lo decide l'utente")
        if perche is None:
            return PermissionResultAllow(behavior="allow")
        scrivi(f"✗ negato in sola lettura [{perche}]: {tool} · {breve(tool, tool_input)[:160]}")
        return PermissionResultDeny(behavior="deny", interrupt=False,
                                    message=f"Missione in sola lettura: {perche}. Non scrivere e non "
                                            "cercare un'altra strada; riferisci cosa andrebbe fatto.")
    perche = motivo(tool, tool_input, RADICI, catena=CATENA)
    # proposta 2026-10-03: missione «lavoro» lanciata dal sito = ogni strumento che non è di sola lettura passa dall'utente
    if perche is None and CONF.get("chiedi_tutto") and tool not in STRUMENTI_LIBERI_SITO:
        perche = "dal sito: lo decide l'utente"
    if perche is None:
        return PermissionResultAllow(behavior="allow")
    return await chiedi_a_utente(tool, tool_input, perche)


async def chiedi_a_utente(tool, tool_input, perche):
    """La scheda di conferma della missione (prima stava dentro conferma(); ora la usa anche la lettura dal sito)."""
    rid = datetime.now().strftime("%H%M%S") + uuid.uuid4().hex[:4]
    dettaglio = json.dumps(tool_input, ensure_ascii=False, indent=2)
    if len(dettaglio) > 6000:
        dettaglio = dettaglio[:6000] + "\n… (tagliato)"
    richiesta = {"id": rid, "strumento": tool, "motivo": perche,
                 "sintesi": f"[{perche}] {breve(tool, tool_input)}"[:500],
                 "dettaglio": dettaglio, "ora": datetime.now().strftime("%H:%M:%S")}
    (RICHIESTE / f"{rid}.json").write_text(json.dumps(richiesta, ensure_ascii=False))
    scrivi(f"⏸ chiede conferma: {tool} · {richiesta['sintesi'][:200]}")
    PENDENTI["n"] += 1
    stato("attende conferma")
    try:
        return await _aspetta_risposta(tool, RICHIESTE / f"{rid}.risposta.json")
    finally:
        PENDENTI["n"] -= 1
        if PENDENTI["n"] <= 0:
            stato("in corso")


async def _aspetta_risposta(tool, risposta_file):
    limite = time.monotonic() + ATTESA_CONFERMA_S
    while time.monotonic() < limite:
        if (DIR / "chiudi").exists():
            break
        if risposta_file.exists():
            r = json.loads(risposta_file.read_text())
            if r.get("ok"):
                scrivi(f"✓ l'utente approva: {tool}")
                return PermissionResultAllow(behavior="allow")
            nota = (r.get("nota") or "").strip()
            scrivi(f"✗ l'utente rifiuta: {tool}" + (f" · «{nota}»" if nota else ""))
            return PermissionResultDeny(behavior="deny", interrupt=False,
                                        message="L'utente non ha approvato." + (f" Ha scritto: {nota}" if nota else ""))
        await asyncio.sleep(1)
    scrivi(f"✗ nessuna risposta, non eseguo: {tool}")
    # la richiesta scaduta si chiude anche su disco: il pannello non la mostra più come aperta
    risposta_file.write_text(json.dumps({"ok": False, "nota": "scaduta senza risposta"}, ensure_ascii=False))
    return PermissionResultDeny(behavior="deny", interrupt=False,
                                message="Nessuna conferma dall'utente entro il tempo limite: azione non eseguita.")


# ---------------------------------------------------------------- esperti e istruzioni
def regole_esperto(nome, progetto):
    modo = ("MODALITÀ LETTURA: leggi e riferisci, non modificare niente (le scritture vengono negate)."
            if LETTURA else
            "MODALITÀ LAVORO: le modifiche ai file del progetto partono; l'irreversibile aspetta il sì dell'utente.")
    return (
        "\n\n---\nREGOLE DI QUESTA MISSIONE (Command Center di Jarvis)\n"
        f"- Lavori nel progetto «{progetto['nome']}», cartella: {progetto['cartella']}\n"
        f"- {modo}\n"
        f"- Badge: all'inizio `{LAVORI} prendo \"{progetto['nome']}\" \"<il tuo pezzo>\" --agente {nome} --insisto`, "
        f"alla fine `{LAVORI} finito \"<esito>\" --agente {nome}`. L'--agente non è facoltativo.\n"
        "- Niente segreti: password, chiavi e token non si leggono ad alta voce, non si scrivono in note o risposte.\n"
        "- Niente produzione, database, VPS, pubblicazioni o messaggi a nessuno senza conferma dell'utente.\n"
        "- Chiudi con un resoconto breve in italiano: fatto, verificato con cosa, cosa resta aperto.\n"
        "- IL TUO QUADERNO (l'utente, 2026-10-04: impari da solo): a fine lavoro scrivi quello che hai imparato con "
        f"`python3 ~/Jarvis/strumenti/quaderno.py scrivi {nome} --cartella \"{progetto['cartella']}\" --imparato \"…\" "
        "--errore \"…\" --verifica \"…\" --fonte \"…\" --proposta \"…\"` (solo fatti verificati, niente segreti); "
        "se non puoi lanciare comandi, lascia nel resoconto le righe «DA SALVARE: …», «ERRORE DA SALVARE: …», «PROPOSTA: …».\n"
        + quaderno_di(nome, progetto)
    )


def quaderno_di(nome, progetto):
    """Il digesto del quaderno dell'esperto (strumenti/quaderno.py), da mettere nel suo prompt. Vuoto = una riga sola."""
    try:
        r = subprocess.run([sys.executable, str(Path.home() / "Jarvis" / "strumenti" / "quaderno.py"), "leggi", nome,
                            "--cartella", str(progetto["cartella"]), "--righe", "8"],
                           capture_output=True, text=True, timeout=20)
        testo = (r.stdout or "").strip()
        return ("- " + testo.replace("\n", "\n  ") + "\n") if testo else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def costruisci_agenti():
    """AgentDefinition per ogni profilo dei progetti scelti, capogruppo compreso."""
    definizioni, elenco, visti = {}, [], set()
    for p in CONF["progetti"]:
        if p.get("capogruppo"):
            CAPOGRUPPI.add(p["capogruppo"])
        for prof in spazi.profili(p["cartella"], p.get("capogruppo")):
            if not prof.get("attivo", True):
                continue                           # spento dalla lavagna (attivo: false, 2026-09-26): non si lancia
            if ULTIME and prof["nome"] not in (SOLO.get(p["id"]) or []):
                continue                           # «ultime modifiche»: solo gli agenti coinvolti
            nome = prof["nome"]
            if nome in visti:                      # stesso nome in due progetti: si distingue
                nome = f"{p['id']}-{nome}"
            visti.add(nome)
            PROG_DI[nome], NOME_VERO[nome] = p["id"], prof["nome"]
            if prof["capogruppo"]:
                PROG_DI.setdefault(prof["nome"], p["id"])
            strumenti = prof["strumenti"] or None
            if LETTURA and strumenti:
                strumenti = [t for t in strumenti if t not in ("Edit", "Write", "NotebookEdit", "MultiEdit")]
            # la catena gira su haiku (l'utente, 2026-09-26 18:35); con «ultime» gli specialisti su sonnet: pochi agenti,
            # e haiku ha riscritto parti vietate e messo refusi nella prova delle 19:10
            modello = prof["modello"] if not CATENA else ("sonnet" if ULTIME and not prof["capogruppo"] else "haiku")
            definizioni[nome] = AgentDefinition(
                description=prof["descrizione"],
                prompt=spazi.corpo_profilo(prof["file"]) + regole_esperto(nome, p),
                tools=strumenti, model=modello)
            MODELLO[nome] = modello
            elenco.append((p["nome"], nome, modello, prof["capogruppo"], prof["descrizione"][:140]))
    return definizioni, elenco




def istruzioni_ultime(elenco):
    """«Aggiorna ultime modifiche»: la stessa discesa e risalita, ma solo sugli agenti toccati dalle modifiche
    pendenti della lavagna, con la domanda dell'utente per ognuna."""
    capi = [p.get("capogruppo") for p in CONF["progetti"] if p.get("capogruppo")]
    modifiche = "\n".join(f"- {r.get('tipo')} · {r.get('progetto')}:{r.get('agente')}"
                          + (f" con {', '.join(r.get('con') or [])}" if r.get("con") else "")
                          for r in CONF.get("modifiche") or [])
    squadre = "\n".join(f"- {c}: " + (", ".join(n for pr2, n, _m, cg, _d in elenco if not cg and pr2 == pr) or "nessuno")
                        for pr, c in ((p["nome"], p.get("capogruppo")) for p in CONF["progetti"]) if c)
    return (
        "\n\nQUESTA MISSIONE È «AGGIORNA LE ULTIME MODIFICHE DELLA LAVAGNA». Il capogruppo gira su haiku, gli altri su sonnet.\n"
        f"Modifiche da verificare (dalla lavagna dell'utente):\n{modifiche}\n"
        f"Agenti coinvolti (capogruppo: altri):\n{squadre}\n"
        "Per ogni modifica la domanda è: «verifica questa modifica (collegamento/aggiunta/spegnimento): il profilo "
        "è coerente? il collegamento ha senso e la sezione Comunica con è reciproca? servono altri collegamenti "
        "(proponili e scrivili)? tono e umorismo sono coerenti con lo spazio?».\n"
        "DISCESA. 1) Lancia il capogruppo (" + ", ".join(capi) + "), description «[orchestratore] verifica le "
        "ultime modifiche», con l'elenco delle modifiche: risponde con una riga per agente coinvolto su cosa "
        "controllare. Se la consegna è vuota o senza elenco, rilancialo una volta con model=\"sonnet\".\n"
        "2) Lancia gli altri agenti coinvolti UNO ALLA VOLTA, description «[<capogruppo>] verifica la modifica», "
        "con la riga del capogruppo e la domanda. Ognuno corregge SOLO il proprio file; se serve un collegamento "
        "reciproco o nuovo lo scrive nel frontmatter «comunica» del PROPRIO profilo e lo dice. Risponde con "
        "l'elenco delle modifiche o «nessuna modifica».\n"
        "RISALITA. 3) Rilancia il capogruppo, description «[orchestratore] chiude la verifica», coi resoconti.\n"
        "4) Report breve e chiudi. Il conteggio finale lo fa il sistema dai file.")


def istruzioni_catena(elenco):
    """«Aggiorna agenti → Jarvis» (l'utente, 2026-09-26 18:10 e 18:35): tutti gli agenti di ogni progetto si
    attivano, in discesa (orchestratore → capogruppo → specialisti) e poi in risalita (specialista →
    capogruppo → orchestratore → Jarvis → l'utente). Ogni passaggio è un lancio con lo strumento Agent, così
    finisce nel registro e la lavagna accende le sinapsi.
    🔴 Un sottoagente di Claude Code non ha lo strumento Agent: un capogruppo non può lanciare i suoi
    specialisti da sé. I lanci li fa l'orchestratore PER CONTO del capogruppo, con «[mittente]» davanti
    alla description: il registro e la lavagna li mostrano come capogruppo → specialista."""
    capi = [p.get("capogruppo") for p in CONF["progetti"] if p.get("capogruppo")]
    squadre = "\n".join(f"- {c}: " + (", ".join(n for pr2, n, _m, cg, _d in elenco if not cg and pr2 == pr) or "nessuno")
                        for pr, c in ((p["nome"], p.get("capogruppo")) for p in CONF["progetti"]) if c)
    return (
        "\n\nQUESTA MISSIONE È «AGGIORNA LA CATENA DEGLI AGENTI». Tutti gli esperti girano su haiku.\n"
        f"Squadre (capogruppo: specialisti):\n{squadre}\n"
        "DISCESA. 1) Lancia TUTTI i capigruppo (" + ", ".join(capi) + ") in parallelo, description "
        "«[orchestratore] rilegge profilo e squadra»: ognuno rilegge il proprio profilo (.claude/agents/<nome>.md), "
        f"quelli dei suoi specialisti e la memoria dello spazio ({CONF['memoria']}); risponde con un ELENCO, una "
        "riga per specialista, di cosa quello specialista deve controllare o correggere. Se la consegna di un "
        "capogruppo è vuota, in errore o senza quell'elenco, rilancialo UNA volta con model=\"sonnet\".\n"
        "2) Per ogni squadra lancia gli specialisti UNO ALLA VOLTA (squadre diverse possono andare in parallelo), "
        "description «[<capogruppo>] rivede il proprio profilo», con nel prompt la riga del capogruppo. Lo "
        "specialista rilegge il PROPRIO profilo, la memoria dello spazio e i profili degli agenti con cui "
        "«comunica»; corregge SOLO il proprio file (frontmatter e corpo; mai la parte fra i commenti "
        "comunica-con); risponde al capogruppo con l'elenco delle modifiche o «nessuna modifica».\n"
        "RISALITA. 3) Rilancia ogni capogruppo con description «[orchestratore] chiude la revisione» e i "
        "resoconti dei suoi specialisti: corregge il proprio profilo se serve e risponde con l'elenco delle "
        "modifiche della squadra.\n"
        "4) Scrivi il report (per ogni agente: verificato, cosa è cambiato) e chiudi con un resoconto breve per "
        "Jarvis. Niente domande all'utente se non serve. Il conteggio finale dei profili corretti lo fa il sistema "
        "dai file: tu non inventare numeri.")


def istruzioni(elenco):
    progetti = "\n".join(f"- {p['nome']}: {p['cartella']} (capogruppo: {p.get('capogruppo') or 'nessuno'})"
                         for p in CONF["progetti"])
    esperti = "\n".join(f"- {n} [{m}]{' CAPOGRUPPO' if c else ''} ({pr}): {d}" for pr, n, m, c, d in elenco) \
        or "- nessun esperto: il lavoro lo fai tu"
    abilita = [str(f) for p in CONF["progetti"] for f in sorted(Path(p["cartella"]).glob(".claude/skills/*/SKILL.md"))]
    if abilita:     # le skill del progetto sono specialisti anche loro
        esperti += ("\nSkill del progetto (specialisti scritti come skill: leggi il SKILL.md e passalo a un "
                    "esperto general-purpose con il compito):\n" + "\n".join(f"- {f}" for f in abilita))
    modo = ("LETTURA: nessuno modifica niente. Le scritture vengono negate senza chiedere; l'unico file che "
            "scrivi è il report." if LETTURA else
            "LAVORO: le modifiche ai file dei progetti partono; quello che non si disfa aspetta il sì dell'utente "
            "nel Command Center.")
    return (
        "MISSIONE DAL COMMAND CENTER DI JARVIS.\n"
        f"Sei l'orchestratore di questa missione per lo spazio «{CONF['spazio_nome']}». L'utente (l'utente) ha dato "
        "l'obiettivo a Jarvis, Jarvis lo passa a te. Non fai il lavoro degli esperti: lo distribuisci, "
        "lo fai verificare e lo controlli.\n"
        f"Progetti:\n{progetti}\n"
        f"Esperti che puoi lanciare con lo strumento Agent (subagent_type = nome):\n{esperti}\n"
        f"Modalità: {modo}\n"
        f"Tetto: al massimo {MAX_PARALLELI} esperti insieme. Se un lancio viene negato con «aspetta che uno "
        "finisca», rilancialo quando un altro ha consegnato.\n\n"
        "Come lavori:\n"
        f"1. Badge: `{LAVORI} prendo \"{CONF['progetti'][0]['nome']}\" \"missione: <obiettivo breve>\" "
        f"--agente orchestratore-{DIR.name}`.\n"
        f"2. Memoria dello spazio: leggi {CONF['memoria']}, poi per ogni progetto lo `Stato.md` e la `Guida agenti.md` nella sua cartella di Memoria "
        "(Memoria/<spazio>/<progetto>/) e cerca quello che serve con "
        f"`{PY_CMD} \"{STRUMENTI_DIR}/cerca_memoria.py\" --spazio \"{CONF['spazio_nome']}\" <parole>`. "
        "Guarda anche .claude/memoria/ dei progetti (errori da non ripetere).\n"
        "3. Scrivi il piano in poche righe: compiti, a quale esperto, come verifichi.\n"
        "4. Lancia gli esperti IN PARALLELO: più chiamate Agent nello STESSO messaggio. Partono in "
        "sottofondo e ti arriva una notifica quando ognuno consegna: per aspettare NON usare sleep, "
        "ScheduleWakeup o comandi a vuoto, chiudi il turno e riprendi alla notifica. A ognuno dai un "
        "compito preciso e cosa deve restituire. Ogni esperto si lancia UNA volta sola, salvo lavoro da "
        "rifare. Il capogruppo NON va in questo primo giro.\n"
        "5. Quando gli esperti hanno consegnato, lancia il capogruppo del progetto (se c'è) con i loro "
        "resoconti: li verifica e dice cosa regge e cosa no.\n"
        "6. Tu controlli almeno un risultato con un comando o un file. Un resoconto non è una prova. "
        "Il lavoro non finito o sciatto torna allo STESSO esperto, con scritto cosa manca.\n"
        "   GOAL: all'inizio scrivi il criterio di fatto (3-5 righe). Dopo la verifica del capogruppo confronta il "
        "risultato col criterio: se manca qualcosa RIPARTI dal punto 4 solo per la parte mancante (al massimo 3 giri). "
        "Se un esperto non chiude al secondo giro, rilancialo con model=\"sonnet\" se era haiku, con model=\"opus\" se "
        "era sonnet (serve a raggiungere il goal; a goal raggiunto torni al modello normale). Al terzo giro fallito "
        "fermati e dì all'utente cosa blocca. Fra gli esperti che hanno prodotto il lavoro e quello che verifica ci "
        "deve essere sempre un agente diverso.\n"
        f"7. Aggiorna il report in «{REPORT_FILE}» (italiano semplice, frasi corte). È l'UNICO report vivo del "
        "progetto: se esiste, prima copia la versione attuale in «_archivio/AAAA-MM/» accanto a lui, poi riscrivilo "
        "tenendo ciò che è ancora aperto e togliendo ciò che è chiuso. Sezioni: Fatto, Aperto, Decisioni dell'utente, "
        "Ultimo giro (data e ora, chi ha fatto cosa, cosa hai verificato e con cosa). Poi il PDF: "
        f"`{PY_CMD} \"{STRUMENTI_DIR}/report_pdf.py\" \"{REPORT_FILE}\"`.\n"
        f"8. Badge d'uscita: `{LAVORI} finito \"<esito>\" --agente orchestratore-{DIR.name}`, poi chiudi "
        "con un resoconto breve: fatto, verificato con cosa, cosa resta aperto.\n"
        "Se serve una decisione dell'utente, fermati e fai UNA domanda chiara.\n"
        "Regole: niente segreti in chiaro, niente produzione/database/VPS/pubblicazioni/messaggi senza il sì "
        "dell'utente; se l'utente rifiuta, non cercare un'altra strada per la stessa cosa. Scrivi in italiano "
        "semplice, frasi corte."
    )


COSTO = {"usd": 0.0, "somma": 0.0}
FERMO = {"da": None}     # quando l'orchestratore ha chiuso l'ultimo turno senza esperti al lavoro
TURNO = {"aperto": False}  # l'orchestratore sta lavorando (dal primo messaggio al ResultMessage)


def tratta(msg):
    """Un messaggio della sessione: registro, albero degli agenti, stato."""
    if FERMO["da"] is not None and not isinstance(msg, ResultMessage) and \
            isinstance(msg, (AssistantMessage, UserMessage)):
        FERMO["da"] = None                         # un turno aperto dalla CLI (notifica di un esperto)
        stato("in corso")
    padre = getattr(msg, "parent_tool_use_id", None)
    if not padre and isinstance(msg, (AssistantMessage, UserMessage)):
        TURNO["aperto"] = True
    if isinstance(msg, AssistantMessage):
        for b in msg.content:
            if padre:                                  # dentro un esperto: solo l'ultima azione
                a = AGENTI.get(padre)
                if a and isinstance(b, ToolUseBlock):
                    a["ultima"] = f"{b.name}: {breve(b.name, b.input)}"[:200]
                    salva_agenti()
                    if b.name in STRUMENTI_AGENTE:     # un esperto che lancia un altro esperto (2026-10-02)
                        inp = b.input or {}
                        traccia("richiesta", b.id, chiave(a["tipo"]), chiave(inp.get("subagent_type") or "general-purpose"),
                                inp.get("description", ""), modello=inp.get("model"), annidato=True)
                continue
            if isinstance(b, TextBlock) and b.text.strip():
                scrivi(b.text.strip())
            elif isinstance(b, ToolUseBlock):
                scrivi(f"→ {b.name}: {breve(b.name, b.input)[:300]}")
                if b.name in STRUMENTI_AGENTE:
                    nuovo = agente(b.id, b.input)
                    salva_agenti()
                    traccia("richiesta", b.id, nuovo["da"], chiave(nuovo["tipo"]),
                            re.sub(r"^\[[\w.-]+\]\s*", "", nuovo["descrizione"]), modello=nuovo.get("modello"),
                            dettaglio=str((b.input or {}).get("prompt") or "")[:300])
    elif isinstance(msg, UserMessage) and not padre and isinstance(msg.content, list):
        for b in msg.content:
            if isinstance(b, ToolResultBlock) and b.tool_use_id in AGENTI:
                testo = testo_risultato(b.content)
                # 27/09/2026: il testo esatto della CLI (_bundled/claude: «Async agent launched successfully.»,
                # «Cloud agent launched.»); la regex di prima scartava anche consegne vere come «I launched…»
                if LANCIATO_IN_SOTTOFONDO.match(testo) and not b.is_error:
                    continue                           # partito in sottofondo: la fine arriva dopo
                consegna(b.tool_use_id, testo, bool(b.is_error))
    elif isinstance(msg, TaskStartedMessage) and msg.tool_use_id in AGENTI:
        TASK[msg.task_id] = msg.tool_use_id
        a = AGENTI[msg.tool_use_id]
        if a["stato"] == "in coda":
            a["stato"], a["inizio"] = "lavora", datetime.now().isoformat(timespec="seconds")
            salva_agenti()
    elif isinstance(msg, TaskNotificationMessage) and (msg.tool_use_id or TASK.get(msg.task_id)) in AGENTI:
        # 27/09/2026: la notifica può arrivare con tool_use_id=None: si ritrova dal task_id
        tid = msg.tool_use_id or TASK.get(msg.task_id)
        TASK[msg.task_id] = tid
        FINITI_SENZA_NOTIFICA.pop(tid, None)
        consegna(tid, leggi_uscita(msg), msg.status not in ("completed",))
    elif isinstance(msg, TaskUpdatedMessage) and (msg.status or "") in ("failed", "killed"):
        # un esperto fermato o caduto a volte lo dice solo qui
        tid = TASK.get(msg.task_id)
        if tid:
            consegna(tid, (msg.patch or {}).get("summary", "") or msg.status, True)
    elif isinstance(msg, TaskUpdatedMessage) and msg.status == "completed":
        # «completed» arriva anche PRIMA della notifica con l'esito: chiudere subito lasciava «completed»
        # come esito. Ma a volte la notifica non arriva mai (tipi dell'SDK) e l'esperto restava «lavora»
        # per sempre: si aspetta ATTESA_NOTIFICA_S, poi si consegna con quello che c'è (27/09/2026)
        tid = TASK.get(msg.task_id)
        if tid and tid in AGENTI and AGENTI[tid]["stato"] == "lavora":
            patch = msg.patch or {}
            testo = next((str(patch[k]) for k in ("summary", "result", "output") if patch.get(k)), "")
            FINITI_SENZA_NOTIFICA[tid] = (time.monotonic(), testo)
    elif isinstance(msg, ResultMessage):
        TURNO["aperto"] = False
        (DIR / "sessione.txt").write_text(getattr(msg, "session_id", "") or "")
        costo = getattr(msg, "total_cost_usd", None)
        if isinstance(costo, (int, float)):
            # quanto costa la missione (2026-09-26): la CLI dà il costo della sessione fino a qui
            # non è detto che sia cumulativo fra un turno e l'altro: si tengono il massimo e la somma
            COSTO["usd"] = max(COSTO["usd"], costo)
            COSTO["somma"] += costo
            scrivi(f"$ costo del turno: {costo:.2f} USD (massimo {COSTO['usd']:.2f}, somma {COSTO['somma']:.2f})")
        if getattr(msg, "is_error", False):
            scrivi("⚠ il turno è finito con un errore")
        if al_lavoro():
            scrivi(f"… {al_lavoro()} esperti ancora al lavoro: aspetto la loro consegna")
        else:
            fermo()


def fermo():
    if FERMO["da"] is None:
        FERMO["da"] = time.monotonic()
        stato("attende istruzioni")
        scrivi("— in attesa di nuove istruzioni o della chiusura —")


def consegne_tardive():
    """Gli esperti «completed» senza notifica: passati ATTESA_NOTIFICA_S si consegnano col testo che
    c'è (patch, se no il file d'uscita del task). Se era l'ultimo e il turno è chiuso, la missione è ferma."""
    adesso = time.monotonic()
    for tid, (quando, testo) in list(FINITI_SENZA_NOTIFICA.items()):
        if adesso - quando < ATTESA_NOTIFICA_S:
            continue
        del FINITI_SENZA_NOTIFICA[tid]
        if AGENTI.get(tid, {}).get("stato") != "lavora":
            continue
        scrivi(f"⚠ {AGENTI[tid]['tipo']}: task completato senza notifica, consegno dopo {ATTESA_NOTIFICA_S} s")
        consegna(tid, testo or "completato (la CLI non ha mandato l'esito)")
        if not al_lavoro() and not TURNO["aperto"]:
            fermo()


async def lettore(client):
    """Legge TUTTA la sessione, non un turno alla volta. La CLI 2.1 lancia gli esperti in
    sottofondo e, quando consegnano, apre da sola un turno nuovo dell'orchestratore: chi
    leggeva solo fino alla fine del turno lo perdeva, e la missione restava ferma a
    «attende istruzioni» con il capogruppo al lavoro (prove del 24/09/2026)."""
    async for msg in client.receive_messages():
        tratta(msg)


def _impronte_profili():
    """nome file -> contenuto dei profili dei progetti della missione (per contare i corretti)."""
    fuori = {}
    for p in CONF["progetti"]:
        for f in (Path(p["cartella"]) / ".claude" / "agents").glob("*.md"):
            try:
                fuori[str(f)] = f.read_text(encoding="utf-8")
            except OSError:
                pass
    return fuori


IMPRONTE_INIZIO = {}
COPIA_PRIMA = DIR / "agenti-prima"      # i profili com'erano, per ripristinare quello che la catena rompe
RIPRISTINATI = []


def copia_profili():
    import shutil
    for p in CONF["progetti"]:
        cartella = Path(p["cartella"]) / ".claude" / "agents"
        if cartella.is_dir():
            dest = COPIA_PRIMA / p["id"]
            dest.mkdir(parents=True, exist_ok=True)
            for f in cartella.glob("*.md"):
                shutil.copy2(f, dest / f.name)


def _nomi_esistenti():
    return {a["nome"] for s_ in spazi.carica() for pr in s_["progetti"] if pr["esiste"]
            for a in spazi.profili(pr["cartella"], pr.get("capogruppo"))}


def controlla_riscritti(solo=None):
    """Dopo la consegna di un agente (solo = il suo nome) o a fine missione: ogni profilo cambiato si
    controlla con spazi.controlla_profilo; se non regge torna com'era, e il registro lo dice."""
    import shutil
    nomi = _nomi_esistenti()
    for p in CONF["progetti"]:
        cartella = Path(p["cartella"]) / ".claude" / "agents"
        for prima in sorted((COPIA_PRIMA / p["id"]).glob("*.md")):
            if solo and prima.stem != solo:
                continue
            ora = cartella / prima.name
            try:
                t_prima, t_ora = prima.read_text(encoding="utf-8"), ora.read_text(encoding="utf-8")
            except OSError:
                continue
            if t_prima == t_ora:
                continue
            motivo = spazi.controlla_profilo(t_ora, nomi, con_sezione="## Comunica con" in t_prima)
            if motivo:
                shutil.copy2(prima, ora)
                RIPRISTINATI.append(prima.stem)
                scrivi(f"✗ profilo di {prima.stem} ripristinato: {motivo}")


def riepilogo_catena():
    """«N profili verificati, M corretti», contati dai file e dall'albero degli agenti, non dal modello.
    Va nel registro (riga «⇧ riepilogo:», da lì le sinapsi orchestratore → jarvis → utente), in stato.json,
    in coda al report della missione e nel report comune del giorno (Memoria/00 Comune/Report/)."""
    controlla_riscritti()                 # anche i file toccati da chi non era di turno
    dopo = _impronte_profili()
    corretti = sorted(Path(f).stem for f, t in dopo.items() if IMPRONTE_INIZIO.get(f) not in (None, t))
    verificati = sorted({a["tipo"] for a in AGENTI.values() if a["stato"] == "consegnato"})
    testo = f"{len(verificati)} profili verificati, {len(corretti)} corretti"
    rip = sorted(set(RIPRISTINATI))
    if ULTIME:
        aggiunti = 0
        for f, t in dopo.items():
            if f in IMPRONTE_INIZIO and IMPRONTE_INIZIO[f] != t:
                prima = set(spazi.comunica_di(*spazi.frontmatter(IMPRONTE_INIZIO[f])))
                aggiunti += len(set(spazi.comunica_di(*spazi.frontmatter(t))) - prima)
        testo = (f"{len(CONF.get('modifiche') or [])} modifiche verificate, {aggiunti} collegamenti aggiunti "
                 f"({len(corretti)} profili corretti)")
    testo += f", {len(rip)} ripristinati"
    scrivi(f"⇧ riepilogo: {testo}" + (f" ({', '.join(corretti)})" if corretti else ""))
    ora = datetime.now()
    blocco = (f"\n\n## Riepilogo della catena ({ora:%Y-%m-%d %H:%M})\n\n- Spazio: {CONF['spazio_nome']}\n"
              f"- {testo}\n- Verificati: {', '.join(verificati) or 'nessuno'}\n"
              f"- Corretti: {', '.join(corretti) or 'nessuno'}\n- Missione: `{DIR.name}`\n")
    if REPORT_FILE.exists():
        with open(REPORT_FILE, "a", encoding="utf-8") as f:
            f.write(blocco)
    comune = REPORT_DIR.parent / "Comune"
    if comune.is_dir():
        f = comune / f"{ora:%Y-%m-%d} Aggiorna catena agenti.md"
        if not f.exists():
            f.write_text(f"---\ntitolo: Aggiorna catena agenti {ora:%Y-%m-%d}\ntipo: report\n---\n\n"
                         f"# Aggiorna catena agenti · {ora:%Y-%m-%d}\n\nUna sezione per spazio, scritta a fine "
                         "missione da missione.py. Collegato a [[Memoria]].", encoding="utf-8")
        with open(f, "a", encoding="utf-8") as g:
            g.write(blocco)
    return {"testo": testo, "verificati": verificati, "corretti": corretti, "ripristinati": rip}


def battito_lavori():
    """Rinfresca il «segno di vita» della/e presa/e che l'agente ha preso con `lavori.py prendo`.

    30/09/2026: nessuno lo chiamava mai durante la missione, quindi `lavori.py chi` mostrava
    sempre «ultimo segno di vita» identico a «iniziato», anche per missioni vive e attive da
    ore — sembravano tutte bloccate. `lavori.py battito` aggiorna le prese della sessione che
    gli è indicata (macchina + sessione), quindi basta passargli lo stesso CLAUDE_SESSION_ID
    che usano le chiamate a `prendo`/`finito` dell'agente (in `sessione.txt`, scritto dalla SDK)."""
    sid = (DIR / "sessione.txt").read_text(encoding="utf-8").strip() if (DIR / "sessione.txt").exists() else ""
    if not sid:
        return
    try:
        subprocess.run([PY_CMD, f"{STRUMENTI_DIR}/lavori.py", "battito"],
                        env={**os.environ, "CLAUDE_SESSION_ID": sid}, capture_output=True, timeout=20)
    except Exception:
        pass    # un battito mancato non deve mai fermare la missione


async def main():
    if CATENA:
        IMPRONTE_INIZIO.update(_impronte_profili())
        copia_profili()
    stato("in corso")
    nomi = ", ".join(p["nome"] for p in CONF["progetti"])
    scrivi(f"Missione {CONF['spazio_nome']} · {nomi} ({'lettura' if LETTURA else 'lavoro'}, "
           f"max {MAX_PARALLELI} in parallelo): {CONF['obiettivo']}")
    definizioni, elenco = costruisci_agenti()
    scrivi(f"Esperti disponibili: {', '.join(definizioni) or 'nessuno'}")
    salva_agenti()
    aggiunta = (istruzioni_ultime(elenco) if ULTIME else istruzioni_catena(elenco)) if CATENA else ""
    # revisione 2 (2026-10-03): le missioni in lettura o «chiedi all'utente» (dal sito) non caricano i settings di
    # progetto (le «allow» del CRM su OneDrive come Bash(rm -rf *) deciderebbero prima di conferma()), e le «allow»
    # dell'utente diventano «ask»: così ogni strumento passa da conferma(). Il CLAUDE.md della cartella arriva con
    # add_dirs + CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD; gli esperti sono già in «agents».
    protetta = LETTURA or bool(CONF.get("chiedi_tutto"))
    extra_opzioni = {}
    if protetta:
        import approvazioni as _A
        extra_opzioni = dict(
            setting_sources=["user"],
            settings=json.dumps({"permissions": {"ask": _A.regole_ask()},
                                 "env": {"CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1"}}, ensure_ascii=False),
        )
    opzioni = ClaudeAgentOptions(
        **extra_opzioni,
        cwd=CONF["cwd"],
        # l'orchestratore coordina e verifica: sonnet (regola dei modelli del 20/09/2026,
        # opus solo per la programmazione). Gli esperti prendono il model: del proprio profilo.
        model="sonnet",
        permission_mode="default",
        can_use_tool=conferma,
        hooks={"PreToolUse": [HookMatcher(matcher="Agent|Task", hooks=[gancio_agent])]},
        agents=definizioni,
        system_prompt={"type": "preset", "preset": "claude_code", "append": istruzioni(elenco) + aggiunta},
        add_dirs=list(CONF.get("add_dirs", [])) + ([CONF["cwd"]] if protetta and CONF.get("cwd") else []),
    )
    # 27/09/2026: il client si apre e si chiude a mano. Con «async with» l'uscita (disconnect) a volte
    # restava appesa e la missione non arrivava mai a «chiusa»; e su eccezione gli agenti «lavora» e il
    # controllo dei profili riscritti della catena saltavano. Ora la chiusura sta in un finally.
    client = ClaudeSDKClient(options=opzioni)
    lettura, errore = None, None
    try:
        await client.connect()
        lettura = asyncio.create_task(lettore(client))
        await client.query(CONF["obiettivo"])
        ultimo_battito = time.monotonic()
        while not lettura.done():
            if (DIR / "chiudi").exists():
                break
            consegne_tardive()
            if time.monotonic() - ultimo_battito > BATTITO_OGNI_S:
                battito_lavori()
                ultimo_battito = time.monotonic()
            # la catena non aspetta istruzioni: finito l'ultimo giro senza esperti al lavoro, si chiude
            if CATENA and FERMO["da"] is not None and time.monotonic() - FERMO["da"] > ATTESA_FINE_CATENA_S:
                break
            # un'ora ferma senza istruzioni e senza esperti al lavoro: la missione si chiude
            if FERMO["da"] is not None and time.monotonic() - FERMO["da"] > ATTESA_ISTRUZIONI_S:
                break
            nuovi = sorted(MESSAGGI.glob("*.txt"))
            if nuovi:
                testo = nuovi[0].read_text().strip()
                nuovi[0].rename(nuovi[0].with_suffix(".letto"))
                scrivi(f"L'utente: {testo}")
                FERMO["da"] = None
                stato("in corso")
                await client.query(testo)
            await asyncio.sleep(1)
        if lettura.done() and not lettura.cancelled() and lettura.exception():
            raise lettura.exception()
    except BaseException as e:
        errore = e
        raise
    finally:
        if lettura is not None:
            lettura.cancel()
        await chiudi_client(client)
        chiudi_missione(errore)


async def chiudi_client(client):
    """disconnect() con un tetto: asyncio.wait non aspetta il task dopo il tempo (wait_for sì)."""
    uscita = asyncio.ensure_future(client.disconnect())
    try:
        fatti, _ = await asyncio.wait({uscita}, timeout=CHIUSURA_CLIENT_S)
    except BaseException:                  # noqa: BLE001 (anche se ci cancellano, si va avanti a chiudere)
        fatti = set()
    if uscita in fatti:
        if not uscita.cancelled() and uscita.exception():
            scrivi(f"⚠ chiusura del client: {uscita.exception()}")
        return
    uscita.cancel()
    scrivi(f"⚠ il client SDK non si è chiuso in {CHIUSURA_CLIENT_S} s: proseguo senza aspettarlo")


FINE = {"scritta": False}


def chiudi_missione(errore=None):
    """Chiude la missione anche dopo un'eccezione: agenti rimasti «lavora», controllo e ripristino dei
    profili della catena, stato finale («chiusa» o «errore», senza nascondere l'eccezione)."""
    # chi è rimasto «lavora» a missione chiusa non consegnerà più
    for tid, a in AGENTI.items():
        if a["stato"] == "lavora":
            a["stato"], a["fine"], a["esito"] = "errore", datetime.now().isoformat(timespec="seconds"), \
                "missione chiusa prima della consegna"
            traccia("errore", tid, chiave(a["tipo"]), a.get("da") or chiave("orchestratore"), a.get("descrizione", ""),
                    errore="missione chiusa prima della consegna" + (f" ({errore!r})" if errore else "")[:200],
                    durata_s=round(time.time() - a["t0"], 1) if a.get("t0") else None)
    salva_agenti()
    riepilogo = None
    if CATENA:
        try:
            riepilogo = riepilogo_catena()
        except Exception as e:  # noqa: BLE001
            scrivi(f"⚠ riepilogo della catena non riuscito: {e}")
    altro = {"report": str(REPORT_FILE) if REPORT_FILE.exists() else "", "costo_usd": round(COSTO["usd"], 4),
             "costo_somma_usd": round(COSTO["somma"], 4), **({"riepilogo": riepilogo} if riepilogo else {})}
    if errore is None:
        scrivi("Missione chiusa.")
        stato("chiusa", **altro)
    else:
        scrivi(f"⚠ errore: {errore!r}")
        stato("errore", errore=str(errore) or type(errore).__name__, **altro)
    FINE["scritta"] = True
    # se l'SDK tiene vivo il processo anche dopo (task appesi nell'uscita di asyncio.run), si esce lo stesso
    import os
    import threading
    uscita = threading.Timer(CHIUSURA_CLIENT_S + 10, os._exit, (0 if errore is None else 1,))
    uscita.daemon = True
    uscita.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as e:  # noqa: BLE001
        if not FINE["scritta"]:            # errore prima del client (profili, opzioni): chiudi_missione non è passata
            scrivi(f"⚠ errore: {e}")
            stato("errore", errore=str(e))
        raise
