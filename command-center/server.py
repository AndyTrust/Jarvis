#!/usr/bin/env python3
"""Command Center di Jarvis.

Server locale (solo 127.0.0.1) che mostra lo stato dei pezzi di Jarvis, del
telefono e della VPS, accende e spegne gli strumenti che l'utente lancia gia' dalle
icone in avvio/, e fa partire le verifiche. Solo libreria standard.

Sicurezza:
- la chat del pannello (tipo «chiedi» e /api/claude-code) lancia il motore scelto (Claude Code,
  Gemini, Codex, Cursor: comando_motore, dal 2026-09-26 sera) e lavora nel modo scelto
  dall'interruttore in chat, «modo_chat» in configurazione.json: «lavoro» (default
  dal 2026-09-26, decisione dell'utente) lancia claude con --dangerously-skip-permissions,
  e la guardia dei comandi (~/.claude/hooks/guardia_comandi.py, hook PreToolUse) resta
  accesa anche col bypass; «lettura» lo lancia in --permission-mode plan; «approvazione»
  (2026-10-03, decisione dell'utente: niente bypass) lo lancia in modalità normale con il gestore dei
  permessi approvazioni_mcp.py: le azioni della lista automatica passano, le altre chiedono all'utente
  con una scheda (GET /api/approvazioni, POST /api/azione tipo «approva», evento «approvazione»
  sul flusso, Telegram per rischio medio/alto). Contratto: CONTRATTO-approvazioni.md;
- gli altri lanci (agenti del CRM, comandi rapidi, «Jarvis») restano in modalita'
  «plan», cioe' in sola lettura; le missioni hanno il loro «modalita»; la sentinella
  ripulisce da script e scrive il rapporto in Python, senza modelli (dal 2026-09-26
  17:35, decisione dell'utente; vedi il blocco «sentinella»);
- i permessi di Jarvis («chiede prima», «Al PC») qui si leggono soltanto; si
  cambiano chiedendolo a Jarvis in chat, dove ogni modifica passa dalla conferma;
- i fili di chat (2026-10-03, fili.py): domanda e risposta della chat della pagina si salvano in
  ~/.locale-onedrive/jarvis-cc/fili/ (0700, fuori da git e da OneDrive) e si leggono con
  GET /api/fili e /api/fili/<sessione>, evento «fili» sul flusso. Nessuna scrittura dal client.

Uso:  python3 command-center/server.py        poi http://127.0.0.1:7777

Copia di prova (2026-09-26):  CC_PORTA=7778 CC_PROVA=1 python3 server.py
  CC_PORTA cambia la porta; CC_PROVA=1 non accende il volto, non scrive le note del vault
  (cruscotto, mappa agenti), non archivia missioni, non tocca Telegram e non spegne le
  pagine: la copia legge e basta, il pannello vero sulla 7777 resta com'è.
  CC_HOST (2026-09-26) cambia l'indirizzo di ascolto: serve solo dentro un contenitore
  Docker (CC_HOST=0.0.0.0, vedi docker/Dockerfile.template). Sul Mac resta 127.0.0.1.

Windows (unione del ramo windows, 2026-10-02): lo stesso file gira sul PC dell'amministrazione.
Ogni differenza è dietro `sys.platform == "win32"`; sul Mac non cambia niente.
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[0])); import senza_finestre  # noqa: E402,F401  (Windows: niente finestre di terminale)
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
import contextvars
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class ServerVeloce(ThreadingHTTPServer):
    """ThreadingHTTPServer senza socket.getfqdn() all'avvio (27/09/2026): quella ricerca DNS inversa
    sui Mac di GitHub Actions (e su reti lente) tiene fermo il pannello ~25 s prima che ascolti.
    Il nome del server serve solo a http.server per SERVER_NAME, che il pannello non usa."""
    def server_bind(self):
        import socketserver
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


QUI = Path(__file__).resolve().parent
HOME = Path.home()

sys.path.insert(0, str(QUI))
import tecnico  # noqa: E402  — il banco di collaudo dell'app Android
import spazi  # noqa: E402  — spazi → progetti → capogruppo ed esperti (spazi.json)
import conversazione  # noqa: E402  — memoria continua del filo di chat: in sospeso, in corso, fatte
import approvazioni  # noqa: E402  — modo «approvazione» (2026-10-03): archivio dei permessi chiesti all'utente
import fili  # noqa: E402  — archivio dei fili di chat (2026-10-03): la stessa conversazione su Mac e telefono
import fonte_vps  # noqa: E402  — 2026-10-05: lavagna, fili, aspetto e barra hanno una sola fonte, la VPS (solo sul Mac)
try:  # 2026-10-03 (prestazioni da internet): ETag/304 e /api/stato a pezzi, solo se la pagina li chiede
    import condizionale  # noqa: E402
except ImportError:  # senza il file il server risponde come prima
    condizionale = None


# ---------------------------------------------------------------- motori (2026-09-26 sera)
# l'utente: «sei sicuro che i motori funzionano? passo da una chat all'altra e tutte comunicano con
# Jarvis?». Fino a oggi no: il selettore scriveva motore_attivo.json ma la chat lanciava sempre
# `claude -p`. Da qui: Jarvis è l'harness, il motore è intercambiabile. comando_motore() costruisce
# il comando del motore scelto; la memoria è la stessa perché ogni motore legge il suo file di
# istruzioni nella cartella di lavoro (~/Jarvis): Claude CLAUDE.md, Codex e Cursor AGENTS.md,
# Gemini GEMINI.md (che importa AGENTS.md). Gli agenti sono gli stessi profili .md.
# Tolti il 2026-09-26: /api/chat, chat_con_claude (API Anthropic diretta con una chiave, storia di
# 20 messaggi, system prompt di due righe, senza vault né agenti né guardia) e chat_con_gemini.
# Nessuno li chiamava: grep in static/, backtalk/, ai-visualizer/, jarvis-agent/, strumenti/
# trova solo /api/chat/storia (la conversazione a voce), che resta.
#
# Un solo file di stato, letto sia dalla sidebar del Command Center sia dalla bolla del widget
# desktop (strumenti/jarvis_widget.py): non duplicare lo stato in due posti.
MOTORE_FILE = HOME / ".claude" / "skills" / "aggiorna-memoria" / "motore_attivo.json"
MOTORI = ("claude", "gemini", "cursor", "codex")
MOTORI_NOME = {"claude": "Claude Code", "gemini": "Gemini", "cursor": "Cursor", "codex": "Codex"}
MOTORI_COMANDO = {"claude": "claude", "gemini": "gemini", "cursor": "cursor-agent", "codex": "codex"}
ENV_JARVIS = HOME / ".env.jarvis"
# Gemini (verificato il 2026-09-26 17:40): il login Google del CLI (oauth-personal) risponde
# «IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals».
# Funziona con una chiave AI Studio. Per non toccare ~/.gemini dell'utente, il pannello dà a gemini una
# casa sua (GEMINI_CLI_HOME) con auth «gemini-api-key»; la chiave resta in ~/.env.jarvis, sul Mac.
GEMINI_CASA = HOME / ".locale-onedrive" / "gemini-pannello"
GEMINI_CHIAVI = ("GEMINI_API_KEY", "GOOGLE_AI_STUDIO_KEY")
# Il modello si fissa (2026-09-26 17:55): lasciato al router, gemini sceglie gemini-3-flash-preview,
# che con la chiave gratuita ha finito la quota del giorno dopo poche domande («TerminalQuotaError:
# You have exhausted your daily quota on this model»); gemini-2.5-flash nello stesso momento risponde.
# Si cambia senza toccare il codice con «modello_gemini» in configurazione.json.
GEMINI_MODELLO = "gemini-2.5-flash"
SESSIONI_MOTORI_FILE = QUI / "sessioni_motori.json"     # sessione della pagina -> {motore: id del motore}
SESSIONI_MOTORI_LOCK = threading.Lock()
_AUTH_CACHE = {}          # motore -> (ts, pronto, motivo)
_AUTH_LOCK = threading.Lock()


def _motore_disponibile(id_motore):
    return shutil.which(MOTORI_COMANDO[id_motore]) is not None


def _motore_attivo_salvato():
    try:
        m = json.loads(MOTORE_FILE.read_text()).get("motore", "claude")
        return m if m in MOTORI else "claude"
    except Exception:
        return "claude"


def _chiave_env_jarvis(nomi):
    try:
        righe = ENV_JARVIS.read_text().splitlines()
    except OSError:
        return ""
    for nome in nomi:
        for r in righe:
            if r.startswith(nome + "="):
                v = r.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    return ""


def _prepara_gemini():
    """La casa di gemini per il pannello: auth con la chiave e la home dell'utente fra le cartelle fidate."""
    d = GEMINI_CASA / ".gemini"
    d.mkdir(parents=True, exist_ok=True)
    # Come Claude Code: le regole globali (~/.claude/CLAUDE.md) più quelle della cartella (CLAUDE.md,
    # e GEMINI.md che importa AGENTS.md). Gemini non importa file fuori dalla cartella di lavoro
    # (provato il 2026-09-26: «@/Users/…/.claude/CLAUDE.md» ignorato), quindi la sua memoria globale,
    # <casa>/.gemini/CLAUDE.md, è un collegamento a ~/.claude/CLAUDE.md: una sola fonte.
    impostazioni = {"security": {"auth": {"selectedType": "gemini-api-key"}},
                    # discoveryMaxDirs 1: senza, gemini legge anche i CLAUDE.md delle sottocartelle
                    # (fullstack-agent/, ai-memory-vault/templates/): rumore, non regole di Jarvis
                    "context": {"fileName": ["GEMINI.md", "CLAUDE.md"], "discoveryMaxDirs": 1}}
    globale = d / "CLAUDE.md"
    if not globale.is_symlink():
        globale.unlink(missing_ok=True)
        globale.symlink_to(HOME / ".claude" / "CLAUDE.md")
    f = d / "settings.json"
    if leggi_json(f, None) != impostazioni:
        scrivi_atomico(f, json.dumps(impostazioni, indent=1))
    t = d / "trustedFolders.json"
    if not t.exists():
        scrivi_atomico(t, json.dumps({str(HOME): "TRUST_FOLDER"}, indent=1))


def env_motore(motore):
    """L'ambiente del processo del motore. Solo Gemini ha bisogno di qualcosa in più."""
    if motore != "gemini":
        return ENV
    _prepara_gemini()
    return {**ENV, "GEMINI_CLI_HOME": str(GEMINI_CASA), "GEMINI_API_KEY": _chiave_env_jarvis(GEMINI_CHIAVI)}


def _prova_autenticazione(motore):
    """(pronto, motivo). Legge lo stato del login senza spendere una domanda."""
    if not _motore_disponibile(motore):
        return False, f"{MOTORI_COMANDO[motore]} non è installato"
    try:
        if motore == "claude":
            r = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20,
                               env=ENV, stdin=subprocess.DEVNULL)
            ok = '"loggedIn": true' in r.stdout
            return ok, "" if ok else "Claude Code non ha fatto il login: nel Terminale «claude», poi /login"
        if motore == "gemini":
            if _chiave_env_jarvis(GEMINI_CHIAVI):
                return True, ""
            return False, ("Gemini: il login Google del CLI non è più accettato (IneligibleTierError). Serve una "
                           "chiave di aistudio.google.com/apikey in ~/.env.jarvis come GEMINI_API_KEY=…")
        if motore == "codex":
            r = subprocess.run(["codex", "login", "status"], capture_output=True, text=True, timeout=20,
                               env=ENV, stdin=subprocess.DEVNULL)
            ok = r.returncode == 0 and "logged in" in (r.stdout + r.stderr).lower()
            return ok, "" if ok else "Codex non ha fatto il login: nel Terminale «codex login»"
        if motore == "cursor":
            r = subprocess.run(["cursor-agent", "status"], capture_output=True, text=True, timeout=20,
                               env=ENV, stdin=subprocess.DEVNULL)
            ok = r.returncode == 0 and "logged in" in (r.stdout + r.stderr).lower()
            return ok, "" if ok else "Cursor non ha fatto il login: nel Terminale «cursor-agent login»"
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{MOTORI_NOME[motore]}: stato del login non leggibile ({e})"
    return False, "motore sconosciuto"


def autenticazione_motore(motore, fresca=False):
    """(pronto, motivo) con 5 minuti di memoria: la pagina chiede lo stato spesso."""
    with _AUTH_LOCK:
        c = _AUTH_CACHE.get(motore)
    if c and not fresca and time.time() - c[0] < 300:
        return c[1], c[2]
    pronto, motivo = _prova_autenticazione(motore)
    with _AUTH_LOCK:
        _AUTH_CACHE[motore] = (time.time(), pronto, motivo)
    return pronto, motivo


def stato_motori():
    attivo = _motore_attivo_salvato()
    motori = []
    for m in MOTORI:
        installato = _motore_disponibile(m)
        pronto, motivo = autenticazione_motore(m) if installato else (False, f"{MOTORI_COMANDO[m]} non è installato")
        motori.append({"id": m, "nome": MOTORI_NOME[m], "installato": installato, "pronto": pronto, "motivo": motivo})
    if not next(x for x in motori if x["id"] == attivo)["pronto"]:
        attivo = "claude"
    return {"attivo": attivo, "motori": motori}


def imposta_motore(id_motore):
    if id_motore not in MOTORI:
        return {"errore": f"motore sconosciuto: {id_motore}"}, 400
    if not _motore_disponibile(id_motore):
        return {"errore": f"{MOTORI_NOME[id_motore]} non è installato su questo Mac"}, 409
    pronto, motivo = autenticazione_motore(id_motore, fresca=True)
    if not pronto:
        return {"errore": motivo}, 409          # il pannello non cambia motore
    MOTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    scrivi_atomico(MOTORE_FILE, json.dumps({"motore": id_motore}))
    evento(f"motore attivo -> {MOTORI_NOME[id_motore]}")
    return stato_motori(), 200


def motore_richiesto(dati):
    """Il motore di una richiesta: il campo «motore» vince su quello salvato. ValueError se non è pronto."""
    motore = (dati.get("motore") or "").strip().lower() or _motore_attivo_salvato()
    if motore not in MOTORI:
        raise ValueError(f"motore sconosciuto: {motore}")
    pronto, motivo = autenticazione_motore(motore)
    if not pronto:
        raise ValueError(f"{MOTORI_NOME[motore]} non è pronto: {motivo}")
    return motore


def _sessioni_motori():
    return leggi_json(SESSIONI_MOTORI_FILE, {})


def sessione_del_motore(sessione, motore):
    """L'id che il motore ha dato al filo della pagina (None se non c'è)."""
    with SESSIONI_MOTORI_LOCK:
        return (_sessioni_motori().get(sessione) or {}).get(motore)


def segna_sessione_motore(sessione, motore, id_motore):
    if not sessione or not id_motore:
        return
    with SESSIONI_MOTORI_LOCK:
        d = _sessioni_motori()
        d.setdefault(sessione, {})[motore] = id_motore
        if len(d) > 500:            # i fili più vecchi escono: un dict JSON tiene l'ordine d'inserimento
            d = dict(list(d.items())[-500:])
        scrivi_atomico(SESSIONI_MOTORI_FILE, json.dumps(d, indent=1))


# 2026-10-03 sera (revisione di sicurezza del ponte, server-modo-ponte-2.patch): una richiesta arrivata da internet
# (intestazione «X-CC-Ponte: 1», la mette solo cc-ponte; la pagina non può darsela al contrario perché il segno toglie
# e non dà) vale per tutto quello che quella richiesta lancia, anche in profondità (skill, controllo delle scadenze,
# missioni, CEO della squadra): nessun motore parte con i permessi saltati.
DAL_PONTE = contextvars.ContextVar("dal_ponte", default=False)
CAMPI_ISTRUZIONI = ("description", "tools", "tono")


def modo_sicuro(modo):
    """Il modo da usare davvero. Fino al 2026-10-04 dal ponte «lavoro» diventava «approvazione»; l'utente il 2026-10-04
    ha deciso che dal telefono e da internet si lavora come dal Mac, senza blocchi: il modo resta quello scelto."""
    return modo


def comando_motore(motore, testo, modo, sessione=None, continua=False, agente=None, lavoro_id=None, cwd=None):
    """Il comando di un motore per la chat del pannello.

    modo: «lavoro», «lettura» o «approvazione» (vedi claude_comando). sessione: l'uuid del filo della pagina.
    lavoro_id e cwd servono solo al modo «approvazione» (il gestore dei permessi sa a chi appartiene la
    richiesta). Gli altri motori non hanno un gestore dei permessi: in «approvazione» lavorano in «lettura».
    agente: il profilo (dict con «nome» e «file») o il solo nome per Claude.
    Differenze vere, verificate il 2026-09-26 con --help e una prova per motore:
      claude  --session-id/--resume con l'uuid della pagina; --agent; lavoro = skip-permissions
              con la guardia dei comandi (hook PreToolUse) accesa; lettura = plan.
      gemini  -p … -o json; l'id lo dà gemini (--resume <id>); lavoro = --approval-mode yolo
              dentro il sandbox di macOS (-s: scrive solo nella cartella di lavoro); lettura = plan.
      codex   exec --json; l'id è il thread_id (exec resume <id>); lavoro = sandbox workspace-write;
              lettura = read-only. Niente bypass del sandbox: la guardia di Claude qui non c'è.
      cursor  -p --output-format json; --resume <id>; lavoro = --force con --sandbox enabled;
              lettura = --mode plan.
    Il profilo agente per gli altri motori diventa testo in testa alla richiesta."""
    modo = modo_sicuro(modo if modo in MODI_CHAT else modo_chat())
    nome_agente = agente.get("nome") if isinstance(agente, dict) else agente
    if motore == "claude":
        cmd = claude_comando(testo, modo=modo, lavoro_id=lavoro_id, sessione=sessione, chi=nome_agente, cwd=cwd)
        if sessione:
            # un filo nato su un altro motore non esiste ancora per claude: lo dice il suo file
            # ~/.claude/projects/<cartella>/<uuid>.jsonl, non il «continua» della pagina
            esiste = any((HOME / ".claude" / "projects").glob(f"*/{sessione}.jsonl"))
            # 2026-10-01 (memoria continua): se il filo esiste lo si riprende sempre, qualunque cosa dica
            # il client in «continua» — un --session-id su un uuid già vivo è il reset cieco
            cmd += ["--resume", sessione] if esiste else ["--session-id", sessione]
        if nome_agente:
            cmd += ["--agent", nome_agente]
        return cmd
    if nome_agente:
        if isinstance(agente, dict):
            file_profilo = agente.get("file") or ""
        else:           # solo il nome (/api/claude-code): il profilo si cerca fra gli agenti di Jarvis
            file_profilo = next((str(f) for f in (AGENTE / ".claude" / "agents" / f"{nome_agente}.md",
                                                  HOME / ".claude" / "agents" / f"{nome_agente}.md") if f.exists()), "")
        testa = (f"Agisci come l'agente {nome_agente}: segui il profilo in {_breve(file_profilo)}."
                 if file_profilo else f"Agisci come l'agente {nome_agente}.")
        testo = testa + "\n\n" + testo
    id_motore = sessione_del_motore(sessione, motore) if sessione else None
    if modo == "approvazione":
        modo = "lettura"          # gemini, codex, cursor: niente gestore dei permessi (2026-10-03)
    if motore == "gemini":
        cmd = ["gemini", "-p", testo, "--output-format", "json", "-m", config_caldo("modello_gemini", GEMINI_MODELLO)]
        cmd += ["--approval-mode", "yolo", "--sandbox"] if modo == "lavoro" else ["--approval-mode", "plan"]
        if id_motore:
            cmd += ["--resume", id_motore]
        return cmd
    if motore == "codex":
        sandbox = "workspace-write" if modo == "lavoro" else "read-only"
        base = ["codex", "exec", "--json", "--skip-git-repo-check"]
        if id_motore:
            return base + ["-c", f'sandbox_mode="{sandbox}"', "resume", id_motore, testo]
        return base + ["-s", sandbox, testo]
    if motore == "cursor":
        cmd = ["cursor-agent", "-p", testo, "--output-format", "json", "--trust"]
        cmd += ["--force", "--sandbox", "enabled"] if modo == "lavoro" else ["--mode", "plan"]
        if id_motore:
            cmd += ["--resume", id_motore]
        return cmd
    raise ValueError(f"motore sconosciuto: {motore}")


def _primo_json(testo):
    """Il primo oggetto JSON che comincia a inizio riga (prima ci possono essere righe di servizio)."""
    for m in re.finditer(r"(?m)^\{", testo):
        try:
            return json.JSONDecoder().raw_decode(testo[m.start():])[0], m.start()
        except ValueError:
            continue
    return None, -1


def _risultato_stream(testo):
    """L'evento {"type": "result"} di un'uscita stream-json di claude (None se non c'è)."""
    for riga in reversed(testo.splitlines()):
        if riga.startswith("{") and '"result"' in riga:
            try:
                ev = json.loads(riga)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("type") == "result":
                return ev
    return None


def estrai_risposta(testo, motore):
    """(risposta, id della sessione del motore, extra) dall'uscita di un motore; risposta None se
    l'uscita non si capisce (allora resta com'è)."""
    if motore == "codex":
        risposta, errori, tid = None, [], ""
        for riga in testo.splitlines():
            if not riga.startswith("{"):
                continue
            try:
                ev = json.loads(riga)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "thread.started":
                tid = ev.get("thread_id") or tid
            elif t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                risposta = ev["item"].get("text") or ""
            elif t in ("turn.failed", "error"):
                errori.append(str((ev.get("error") or {}).get("message") or ev.get("message") or ev)[:400])
        if risposta is None and errori:
            risposta = "Errore da Codex: " + errori[-1]
        return risposta, tid, {}
    dati, _ = _primo_json(testo)
    if not isinstance(dati, dict):
        return None, "", {}
    if motore == "claude" and dati.get("type") == "system":
        # --output-format stream-json (modo «approvazione», 2026-10-03): la risposta è l'evento «result»,
        # di solito l'ultima riga. Con --output-format json il primo oggetto è già il risultato.
        dati = _risultato_stream(testo) or dati
    if motore == "claude":
        costo = dati.get("total_cost_usd")
        return (dati.get("result") or "(nessuna risposta)"), dati.get("session_id") or "", {
            "turni": dati.get("num_turns"), "costo": round(costo, 4) if isinstance(costo, (int, float)) else None}
    if motore == "gemini":
        if dati.get("error"):
            e = dati["error"]
            msg = str(e.get("message") if isinstance(e, dict) else e)
            if msg in ("", "[object Object]"):      # gemini 0.31 perde il messaggio: sta nelle righe prima
                m = re.search(r"\b(\w+Error): ([^\n]+)", testo)
                msg = f"{m.group(1)}: {m.group(2)}" if m else msg
            return "Errore da Gemini: " + msg[:400], "", {}
        return (dati.get("response") or "(nessuna risposta)"), dati.get("session_id") or "", {}
    if motore == "cursor":
        r = dati.get("result") or ""
        return (("Errore da Cursor: " + r) if dati.get("is_error") else (r or "(nessuna risposta)")), \
            dati.get("session_id") or "", {}
    return None, "", {}


def risposta_motore(motore, sessione=None, nota=""):
    """La funzione «dopo» dei lavori di chat: nel log resta solo il testo della risposta.
    nota (2026-10-03): una riga in testa alla risposta (es. «questo motore in approvazione lavora in lettura»)."""
    def dopo(log):
        testo = Path(log).read_text()
        testa = testo[:testo.find("\n\n") + 2] if testo.startswith("(cartella:") else ""
        risposta, id_motore, extra = estrai_risposta(testo[len(testa):], motore)
        if risposta is None:
            if nota:
                scrivi_atomico(log, testa + nota + "\n\n" + testo[len(testa):])
            return {"motore": motore}
        scrivi_atomico(log, testa + (nota + "\n\n" if nota else "") + risposta + "\n")
        segna_sessione_motore(sessione, motore, id_motore)
        return {"sessione": sessione or id_motore, "motore": motore, **extra}
    return dopo


def risposta_flusso(motore, sessione=None):
    """«dopo» del modo «approvazione» (2026-10-03): l'uscita stream-json sta in <log>.flusso, fuori dalla
    pagina (dentro ci sono i risultati grezzi degli strumenti, cioè anche il contenuto dei file letti).
    Nel log va solo la risposta; il file .flusso si cancella."""
    def dopo(log):
        flusso = Path(log).with_suffix(".flusso")
        try:
            grezzo = flusso.read_text(errors="replace")
        except OSError:
            grezzo = ""
        testo = Path(log).read_text()
        testa = testo[:testo.find("\n\n") + 2] if testo.startswith("(cartella:") else ""
        if _risultato_stream(grezzo) is None:
            # niente risposta (errore di avvio, opzione sconosciuta…): resta la coda, ripulita dai segreti
            righe = [r for r in grezzo.splitlines() if not r.startswith("{")][-40:]
            scrivi_atomico(log, testa + approvazioni.pulisci("\n".join(righe) or "(nessuna risposta)", 4000) + "\n")
            flusso.unlink(missing_ok=True)
            return {"motore": motore}
        risposta, id_motore, extra = estrai_risposta(grezzo, motore)
        scrivi_atomico(log, testa + (risposta or "(nessuna risposta)") + "\n")
        flusso.unlink(missing_ok=True)
        segna_sessione_motore(sessione, motore, id_motore)
        return {"sessione": sessione or id_motore, "motore": motore, **extra}
    return dopo


def solo_risposta(log):
    """Tiene del JSON di claude -p solo il testo della risposta (agenti, comandi rapidi, chiamate)."""
    return risposta_motore("claude")(log)


def _configurazione():
    """Legge configurazione.json: qui stanno i percorsi e i siti di chi lo usa.

    Senza quel file il pannello parte lo stesso, con i valori di esempio: serve
    a poterlo provare appena scaricato."""
    esempio = {
        "cartella_agente": "~/Jarvis",
        "vault": "",
        "indice_progetti": "~/.ai-memory/global/projects-index.md",
        "progetto_agenti": "",
        "siti": {},
        "verifiche": [],
        "porta": 7777,
    }
    for nome in ("configurazione.json", "configurazione.esempio.json"):
        p = QUI / nome
        if p.exists():
            try:
                return {**esempio, **json.loads(p.read_text())}
            except ValueError:
                print(f"{nome} non è JSON valido: uso i valori di esempio")
                break
    return esempio


CFG = _configurazione()


def _percorso(valore, default=None):
    if not valore:
        return default
    return Path(str(valore).replace("~", str(HOME), 1))


# CC_PORTA e CC_PROVA servono alla copia di prova (2026-09-26): vedi l'intestazione
PORTA = int(os.environ.get("CC_PORTA") or CFG.get("porta") or 7777)
PROVA = os.environ.get("CC_PROVA") == "1"
# CC_HOST (2026-09-26): 0.0.0.0 solo nel contenitore Docker del template; default 127.0.0.1
HOST = os.environ.get("CC_HOST") or "127.0.0.1"
AGENTE = _percorso(CFG["cartella_agente"], HOME / "Jarvis")
sys.path.insert(0, str(AGENTE / "strumenti"))
try:
    import agenti as _agenti_mod
except Exception:
    _agenti_mod = None
try:
    import sentinella as _sentinella_mod     # la pulizia e il rapporto in Python (strumenti/sentinella.py)
except Exception:
    _sentinella_mod = None


def _carica_assistenza():
    """Assistenza a distanza a pagamento (2026-09-29): strumenti/assistenza.py accanto a questo
    Command Center, caricata per percorso (non da AGENTE, che può essere un'altra cartella)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("assistenza", QUI.parent / "strumenti" / "assistenza.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


_assistenza_mod = _carica_assistenza()


def _carica_assistenza_codice():
    """Lato tecnico dell'assistenza (2026-09-29): strumenti/assistenza_codice.py c'è solo sul Mac di
    L'utente (il template lo toglie). Usa lo stesso modulo assistenza già caricato, così gli errori
    sono della stessa classe. Se manca o non si carica: None, e gli endpoint /tecnico/ danno 404."""
    if not _assistenza_mod:
        return None
    f = QUI.parent / "strumenti" / "assistenza_codice.py"
    if not f.is_file():
        return None
    try:
        import importlib.util
        sys.modules.setdefault("assistenza", _assistenza_mod)
        spec = importlib.util.spec_from_file_location("assistenza_codice", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001
        return None


_assistenza_codice_mod = _carica_assistenza_codice()


def assistenza_tecnico():
    """Il modulo del lato tecnico, solo se c'è la chiave privata su questo Mac; altrimenti None."""
    m = _assistenza_codice_mod
    try:
        return m if m and m.disponibile() else None
    except Exception:  # noqa: BLE001
        return None
STATIC = QUI / "static"
LAVORI_DIR = QUI / "lavori"
LAVORI_DIR.mkdir(exist_ok=True)
CRM = _percorso(CFG.get("progetto_agenti"), AGENTE)
VAULT = _percorso(CFG.get("vault"), AGENTE / "vault")
BACKTALK_JSON = AGENTE / "backtalk" / "backtalk.json"
SETTINGS_LOCALI = AGENTE / ".claude" / "settings.local.json"
PATH_ENV = f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ENV = {**os.environ, "PATH": PATH_ENV}
if sys.platform == "win32":
    # 29/09/2026 (ramo windows): la stringa con i «:» rompeva il PATH dei sottoprocessi; si parte da quello vero.
    # PYTHONUTF8: senza, un sottoprocesso Python va in UnicodeEncodeError al primo carattere non ASCII.
    PATH_ENV = f"{HOME}\\.local\\bin;" + os.environ.get("PATH", "")
    ENV = {**os.environ, "PATH": PATH_ENV, "PYTHONUTF8": "1"}
TOKEN = secrets.token_urlsafe(24)
fili.nascondi_anche(TOKEN)       # il token della pagina non finisce mai nell'archivio dei fili


def _scrivi_token_locale():
    """2026-10-05 (notifiche): strumenti/notifica.py sulla stessa macchina manda POST /api/notifica con questo
    token. File 0600 dell'utente del server, fuori da git e da OneDrive; la copia di prova non lo scrive."""
    if PROVA_TOKEN_NO:
        return
    try:
        f = HOME / ".locale-onedrive" / "jarvis-cc" / "token-locale"
        f.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(f) + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as h:
            h.write(TOKEN)
        os.replace(str(f) + ".tmp", f)
    except OSError:
        pass


PROVA_TOKEN_NO = os.environ.get("CC_PROVA") == "1"
_scrivi_token_locale()
MISSIONI_DIR = QUI / "missioni"
MISSIONI_DIR.mkdir(exist_ok=True)
# le missioni chiuse escono dal pannello: la cartella si sposta qui, non si cancella
ARCHIVIO_MISSIONI_DIR = QUI / "missioni_archivio"
ARCHIVIO_MISSIONI_DIR.mkdir(exist_ok=True)
PY_SDK = AGENTE / "backtalk" / ".venv" / "bin" / "python3"
if sys.platform == "win32":     # su Windows il Python con claude_agent_sdk è il .venv di questa cartella
    PY_SDK = AGENTE / ".venv" / "Scripts" / "python.exe"
INDICE_PROGETTI = _percorso(CFG.get("indice_progetti"), HOME / ".ai-memory/global/projects-index.md")
TELEFONO = AGENTE / "telefono"
AST = TELEFONO / "asterisk" / "sbin" / "asterisk"
AST_CONF = TELEFONO / "asterisk" / "etc" / "asterisk" / "asterisk.conf"

# Comandi con cui Jarvis lavora sullo schermo («Al PC»)
REGOLE_AL_PC = ["Bash(cliclick:*)", "Bash(screencapture:*)", "Bash(osascript:*)",
                "Bash(python3 strumenti/mac.py:*)"]

# I siti da tenere d'occhio e gli script di verifica arrivano da configurazione.json
SITI = dict(CFG.get("siti") or {})

VERIFICHE = {
    "autocontrollo": {
        "nome": "Autocontrollo di Jarvis",
        "descrizione": "Prova i suoi pezzi e lo stato del sistema, e scrive prove/RAPPORTO.md",
        "cwd": AGENTE,
        "cmd": ["bash", "prove/esegui.sh"],
    },
}
for _v in CFG.get("verifiche") or []:
    if _v.get("id") and _v.get("cmd"):
        VERIFICHE[_v["id"]] = {"nome": _v.get("nome", _v["id"]),
                               "descrizione": _v.get("descrizione", ""),
                               "cwd": _percorso(_v.get("cartella"), AGENTE),
                               "cmd": _v["cmd"]}

PROMPT_AGENTE = (
    "Fai la tua verifica di routine sui dati aggiornati a ieri, restando nella tua "
    "competenza. Rispondi in italiano in al massimo 15 righe: cosa torna, cosa non "
    "torna con il numero e la fonte che lo prova, e cosa andrebbe fatto."
)


def _ssh_su_se_stessa(cmd):
    """Se cmd è `ssh [opzioni] <host> <comando remoto>` e <host> è questa stessa macchina
    (l'alias si risolve solo su loopback: Command Center acceso sulla VPS), restituisce il
    comando remoto da eseguire in locale. Altrimenti None."""
    if not (isinstance(cmd, list) and len(cmd) >= 3 and cmd[0] == "ssh"):
        return None
    i = 1
    while i < len(cmd) and cmd[i].startswith("-"):
        i += 2 if cmd[i] in ("-o", "-i", "-p", "-l", "-L", "-R", "-w") else 1
    if i != len(cmd) - 2 or "-N" in cmd or "-t" in cmd:
        return None
    try:
        import socket as _socket
        indirizzi = {a[4][0] for a in _socket.getaddrinfo(cmd[i], 22)}
    except OSError:
        return None
    return cmd[i + 1] if indirizzi and all(a in ("::1", "127.0.0.1") for a in indirizzi) else None


def sh(cmd, timeout=20, cwd=None):
    """Esegue un comando e restituisce (codice, testo). Non solleva."""
    locale = _ssh_su_se_stessa(cmd)
    if locale is not None:
        cmd = ["bash", "-c", locale]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd, env=ENV, shell=isinstance(cmd, str))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "tempo scaduto"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def leggi_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def pid_su_porta(porta):
    _, out = sh(["lsof", "-ti", f"tcp:{porta}", "-sTCP:LISTEN"], timeout=5)
    return [int(x) for x in out.split() if x.isdigit()]


_PROC_WIN = {"ts": 0.0, "righe": []}


def _processi_windows():
    """(pid, riga di comando) di tutti i processi su Windows: una sola lettura ogni 3 s, condivisa."""
    if time.time() - _PROC_WIN["ts"] > 3:
        _, out = sh(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | "
                     "ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CommandLine }"], timeout=20)
        righe = []
        for riga in out.splitlines():
            pid, _, cmd = riga.partition("|")
            if pid.strip().isdigit():
                righe.append((int(pid), cmd))
        _PROC_WIN.update(ts=time.time(), righe=righe)
    return _PROC_WIN["righe"]


def processi(schema):
    if sys.platform == "win32":     # niente pgrep: la tabella dei processi di Windows (lo schema è testo, non regex)
        return [p for p, cmd in _processi_windows()
                if schema in cmd and p != os.getpid() and "powershell" not in cmd.lower()]
    _, out = sh(["pgrep", "-f", schema], timeout=5)
    return [int(x) for x in out.split() if x.isdigit() and int(x) != os.getpid()]


# ---------------------------------------------------------------- pagine nel browser
# Volto e Mani sono pagine: l'interruttore è acceso solo se il server risponde E la
# scheda è aperta. Chiudere la scheda spegne il server; spegnere chiude la scheda.
PEZZI_PAGINA = {"volto": ("ai-visualizer", 8790, ""), "mani": ("barehands", 8794, "stage.html")}
NOME_PEZZO = {"volto": "Jarvis Talk", "mani": "Jarvis Lavagna"}   # i nomi che vede l'utente
ACCESO_IL = {}                 # nome -> quando è stato acceso dal pannello
ATTESA_PAGINA = 25             # secondi concessi alla scheda per aprirsi
PAGINA_ASSENTE = {}            # nome -> letture negative consecutive (scheda non trovata)
LETTURE_PER_SPEGNERE = 3       # si spegne solo dopo 3 letture certe di fila senza la scheda (~45 s)
BROWSER = ("Google Chrome", "Safari")


def _schede_browser(app):
    """Le porte locali aperte in un browser: set (anche vuoto) se il browser ha risposto davvero,
    "spento" se non è aperto, None se non si sa (tempo scaduto, permesso Automazione tolto, errore).

    🔴 Fino al 26/09/2026 un browser chiuso rispondeva codice 0 e testo vuoto, contato come «letto,
    nessuna scheda»: se Chrome (dove sta la Lavagna) non rispondeva in tempo e Safari era chiuso, la
    pagina risultava chiusa e la Lavagna si spegneva mentre l'utente la usava. Ora ogni esito ha una marca."""
    script = (f'if application "{app}" is running then\n'
              f' tell application "{app}" to set u to URL of every tab of every window\n'
              ' set out to "LETTO"\n'
              ' repeat with w in u\n  repeat with t in w\n   try\n'
              '    set out to out & " " & (t as text)\n'
              '   end try\n  end repeat\n end repeat\n'
              ' return out\nelse\n return "SPENTO"\nend if')
    codice, out = sh(["osascript", "-e", script], timeout=8)
    out = out.strip()
    if codice != 0:
        return None
    if out == "SPENTO":
        return "spento"
    if not out.startswith("LETTO"):
        return None
    return {int(x) for x in re.findall(r"https?://(?:127\.0\.0\.1|localhost):(\d+)", out)}


def schede_locali():
    """Porte delle schede aperte su 127.0.0.1/localhost nei browser; None se non si può dire.

    Una porta vista in un browser che ha risposto vale sempre. «Nessuna scheda» vale solo se
    TUTTI i browser hanno risposto davvero (o sono chiusi): uno che tace rende la lettura incerta."""
    porte, incerto = set(), False
    for app in BROWSER:
        r = _schede_browser(app)
        if r is None:
            incerto = True
        elif r != "spento":
            porte |= r
    if porte:
        return porte
    return None if incerto else porte


def chiudi_schede(porta):
    for app in BROWSER:
        righe = "\n".join(f'    close (every tab of w whose URL starts with "http://{h}:{porta}")'
                          for h in ("127.0.0.1", "localhost"))
        sh(["osascript", "-e", f'if application "{app}" is running then\n tell application "{app}"\n'
            f'  repeat with w in windows\n{righe}\n  end repeat\n end tell\nend if'], timeout=8)


def spegni_pezzo(nome, perche=""):
    cartella, porta, _ = PEZZI_PAGINA[nome]
    ACCESO_IL.pop(nome, None)
    PAGINA_ASSENTE.pop(nome, None)
    chiudi_schede(porta)
    for _ in range(10):
        pids = pid_su_porta(porta)
        if not pids:
            break
        termina(pids)
        time.sleep(0.5)
    else:
        for p in pid_su_porta(porta):
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
    evento(f"{NOME_PEZZO[nome]} spento" + (f": {perche}" if perche else ""))


def chiudi_finestre_terminale(parola):
    """Chiude le finestre del Terminale il cui titolo contiene «parola» (mai quelle della chat)."""
    if "Chat with Jarvis" in parola:
        return
    chiudi = ('if application "Terminal" is running then\n tell application "Terminal"\n  repeat with w in windows\n'
              f'    if name of w contains "{parola}" and name of w does not contain "Chat with Jarvis" then close w saving no\n'
              '  end repeat\n end tell\nend if')
    conta = ('if application "Terminal" is running then\n tell application "Terminal" to count '
             f'(every window whose name contains "{parola}" and visible is true)\nelse\n 0\nend if')
    # appena fermato il processo il Terminale lo crede ancora vivo e non chiude: si riprova
    for _ in range(5):
        sh(["osascript", "-e", chiudi], timeout=8)
        _, n = sh(["osascript", "-e", conta], timeout=8)
        if n.strip() in ("", "0"):
            return
        time.sleep(1)


def apri_nel_terminale(script):
    return sh(["open", "-a", "Terminal", str(script)], timeout=10)


def avvia_staccato(cmd, cwd, log):
    with open(log, "ab") as f:
        subprocess.Popen(cmd, cwd=cwd, env=ENV, stdout=f, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)


# L'orb di Jarvis (strumenti/jarvis_widget.py, portato da quello di Windows il 29/09/2026) parte da solo
# quando si apre la webapp e quando parte il pannello. Gira con il Python di ~/.locale-onedrive/jarvis-widget-venv
# (PyObjC + Pillow + numpy). Una sola istanza: lo garantisce anche lo script (porta 47771).
ORB_PY = HOME / ".locale-onedrive" / "jarvis-widget-venv" / "bin" / "python3"
ORB_SCRIPT = AGENTE / "strumenti" / "jarvis_widget.py"
SCRIPT_VOCE_WIN = "talk_to_jarvis_windows"   # Windows: Shift destro, Whisper -> Claude -> voce Sara (Kokoro)
SCRIPT_ORB_WIN = "jarvis_orb_windows"        # Windows: il cerchio flottante sul desktop


def avvia_windows(script):
    """Windows: lancia strumenti/<script>.py con pythonw, senza finestra, come i collegamenti sul Desktop."""
    env = {**ENV, "PYTHONUTF8": "1", "PATH": r"C:\Program Files\eSpeak NG;" + ENV.get("PATH", "")}
    pyw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(AGENTE / "strumenti" / f"{script}.py")],
                     cwd=str(AGENTE), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=0x00000008 | 0x08000000)   # DETACHED | NO_WINDOW
_ORB_ULTIMO = {"ts": 0.0}


def _orb_diario(testo):
    try:
        (AGENTE / "log").mkdir(exist_ok=True)
        with open(AGENTE / "log" / "orb-avvio.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {testo}\n")
    except OSError:
        pass


def avvia_orb(da="?"):
    if sys.platform == "win32":
        return _avvia_orb_windows(da)
    if PROVA or sys.platform != "darwin" or not ORB_PY.exists() or not ORB_SCRIPT.exists():
        return False
    if time.time() - _ORB_ULTIMO["ts"] < 20:        # ricaricare la pagina non lancia nulla di nuovo
        return False
    _ORB_ULTIMO["ts"] = time.time()
    # solo processi Python che lanciano lo script: un altro comando che ne cita il nome non conta come orb acceso
    if processi(r"^[^ ]*[Pp]ython[^ ]* [^ ]*strumenti/jarvis_widget[.]py"):
        _orb_diario(f"{da}: già acceso")
        return False
    try:
        (AGENTE / "log").mkdir(exist_ok=True)
        avvia_staccato([str(ORB_PY), str(ORB_SCRIPT)], str(AGENTE), AGENTE / "log" / "orb.log")
        evento("orb di Jarvis acceso")
        _orb_diario(f"{da}: acceso")
        return True
    except OSError as e:
        evento(f"orb: {e}")
        _orb_diario(f"{da}: errore {e}")
        return False


def _avvia_orb_windows(da):
    """Windows (ramo windows, 04a9331): strumenti/jarvis_orb_windows.py, una sola istanza."""
    if PROVA or not (AGENTE / "strumenti" / f"{SCRIPT_ORB_WIN}.py").exists():
        return False
    if time.time() - _ORB_ULTIMO["ts"] < 20:
        return False
    _ORB_ULTIMO["ts"] = time.time()
    if processi(SCRIPT_ORB_WIN):
        _orb_diario(f"{da}: già acceso")
        return False
    try:
        avvia_windows(SCRIPT_ORB_WIN)
        _PROC_WIN["ts"] = 0
        evento("orb di Jarvis acceso")
        _orb_diario(f"{da}: acceso")
        return True
    except OSError as e:
        evento(f"orb: {e}")
        _orb_diario(f"{da}: errore {e}")
        return False


def termina(pids):
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)       # su Windows SIGTERM = TerminateProcess: qui va bene, si vuole chiudere
        except (ProcessLookupError, OSError):
            pass


# ---------------------------------------------------------------- tempo reale
# Dal 2026-09-26 la pagina non aspetta più il suo giro di 5 s: apre /api/flusso (SSE) e
# ricarica lo stato quando la versione sale. La versione sale a ogni cambio vero: un
# dato di STATO diverso da prima, un evento, un lavoro che parte o finisce, un file di
# missione, di sincronia o di presa che cambia (vedi sorveglia_file).

VERSIONE = {"n": 0, "ts": time.time()}
VERSIONE_STORIA = []                   # (versione, chiave): le ultime 300, per dire al flusso cosa è cambiato
VERSIONE_COND = threading.Condition()  # i client di /api/flusso aspettano qui
ULTIMO_TOCCO = {}                      # chiave -> time.time() dell'ultimo tocca(): sorveglia_file non ritocca le scritture nostre (02/10/2026)


def tocca(*chiavi):
    """Un cambio vero: la versione sale e i client del flusso si svegliano."""
    with VERSIONE_COND:
        VERSIONE["n"] += 1
        VERSIONE["ts"] = time.time()
        for c in chiavi or ("stato",):
            VERSIONE_STORIA.append((VERSIONE["n"], c))
            ULTIMO_TOCCO[c] = VERSIONE["ts"]
        del VERSIONE_STORIA[:-300]
        VERSIONE_COND.notify_all()


def versione():
    with VERSIONE_COND:
        return VERSIONE["n"]


FLUSSO_EVENTI = []       # (versione, nome, dati): gli eventi con nome del flusso (2026-10-03, contratto approvazioni)


def emetti_flusso(nome, dati):
    """Un evento con nome e dati su /api/flusso («approvazione», «attivita»), oltre al solito messaggio con le chiavi."""
    with VERSIONE_COND:
        tocca(nome)
        FLUSSO_EVENTI.append((VERSIONE["n"], nome, dati))
        del FLUSSO_EVENTI[:-300]


# 2026-10-03 (fili): un filo cambiato nell'archivio = evento «fili» {sessione, interlocutore, versione, aggiornato}
fili.AVVISA = lambda dati: emetti_flusso("fili", dati)


def _senza_ora(v):
    """Il dato senza i campi che cambiano a ogni lettura: serve a capire se è cambiato davvero."""
    if isinstance(v, dict):
        return {k: x for k, x in v.items() if k not in ("letto_ts", "errore_ts", "letto", "quando_ts")}
    return v


# ---------------------------------------------------------------- stato

class Stato:
    def __init__(self):
        self.dati = {"locale": {}, "vps": {}, "memoria": {}, "telefono": {}, "telegram": {}}
        self.lock = threading.Lock()

    def set(self, chiave, valore):
        if isinstance(valore, dict):
            # quando è stato letto davvero, e se l'ultima lettura è fallita (vedi segna_errore)
            valore = {**valore, "letto_ts": time.time()}
            valore.setdefault("errore", "")
        with self.lock:
            prima = self.dati.get(chiave)
            self.dati[chiave] = valore
        if _senza_ora(prima) != _senza_ora(valore):
            tocca(chiave)

    def segna_errore(self, chiave, errore):
        """La lettura è fallita: il dato di prima resta, con il suo letto_ts vecchio e il motivo.
        Prima restava e basta, e la pagina lo mostrava come fresco (es. «Sincronia ✓» vecchia di ore)."""
        with self.lock:
            vecchio = self.dati.get(chiave)
            vecchio = dict(vecchio) if isinstance(vecchio, dict) else {"letto_ts": None}
            vecchio["errore"] = str(errore)[:300] or "lettura fallita"
            vecchio["errore_ts"] = time.time()
            self.dati[chiave] = vecchio
        tocca(chiave)

    def get(self):
        with self.lock:
            return json.loads(json.dumps(self.dati))

    def uno(self, chiave):
        """Una sezione sola, copiata come fa get(); KeyError se non c'è."""
        with self.lock:
            return json.loads(json.dumps(self.dati[chiave]))


STATO = Stato()

# 2026-10-03 (prestazioni da internet): i cambi più frequenti (claude_ora a ogni passo degli hook di Claude, anche
# ogni 2 s; locale ogni pochi secondi) viaggiano DENTRO il messaggio del flusso, così la pagina non rilegge
# /api/stato per qualche centinaio di byte. Solo se TUTTE le chiavi cambiate sono qui e insieme stanno sotto
# SPINTA_MAX: altrimenti il messaggio è quello di sempre e la pagina rilegge lo stato. I valori sono gli stessi
# che /api/stato mette sotto quelle chiavi (STATO.get() e claude_ora()).
SPINTA_STATO = frozenset(("locale", "vps", "telefono", "telegram", "memoria", "portiere", "comunicazioni", "sentinella", "claude"))
SPINTA_MAX = 8192


def stato_spinto(chiavi):
    if not chiavi:
        return None
    fuori = {}
    try:
        for c in chiavi:
            if c == "claude_ora":
                fuori[c] = claude_ora()
            elif c in SPINTA_STATO:
                fuori[c] = STATO.uno(c)
            else:
                return None
    except Exception:  # noqa: BLE001  — sezione assente o illeggibile: la pagina rilegge lo stato come prima
        return None
    return fuori if len(json.dumps(fuori, ensure_ascii=False)) <= SPINTA_MAX else None
EVENTI = []
EVENTI_LOCK = threading.Lock()


def evento(testo):
    with EVENTI_LOCK:
        EVENTI.insert(0, {"ora": datetime.now().strftime("%H:%M:%S"), "testo": testo})
        del EVENTI[60:]
    tocca("eventi")


_FIDATA_CACHE = {"mtime": None, "valore": False}


def fidata():
    """La cartella di Jarvis è fidata per Claude Code. ~/.claude.json pesa più di 100 KB: si rilegge
    solo quando cambia, non a ogni giro di 5 secondi."""
    f = HOME / ".claude.json"
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return False
    if mtime != _FIDATA_CACHE["mtime"]:
        p = leggi_json(f, {}).get("projects", {})
        _FIDATA_CACHE.update(mtime=mtime, valore=bool(p.get(str(AGENTE), {}).get("hasTrustDialogAccepted")))
    return _FIDATA_CACHE["valore"]


def mac_risorse():
    _, ncpu = sh(["sysctl", "-n", "hw.ncpu"], timeout=5)
    _, cpu = sh("ps -A -o %cpu | awk '{s+=$1} END {print s}'", timeout=5)
    try:
        cpu_pct = round(float(cpu.strip()) / int(ncpu.strip()))
    except ValueError:
        cpu_pct = None
    _, vm = sh(["vm_stat"], timeout=5)
    _, tot = sh(["sysctl", "-n", "hw.memsize"], timeout=5)
    ram_pct = None
    try:
        pagina = int(re.search(r"page size of (\d+)", vm).group(1))
        val = {k: int(v) for k, v in re.findall(r"Pages (\w[\w ]*?):\s+(\d+)", vm)}
        usata = (val.get("active", 0) + val.get("wired down", 0)
                 + val.get("occupied by compressor", 0)) * pagina
        ram_pct = round(usata * 100 / int(tot.strip()))
    except (AttributeError, ValueError):
        pass
    return {"cpu": cpu_pct, "ram": ram_pct}


_PONTE_CACHE = {"ts": 0, "dati": None}


def ponte_android():
    """Il ponte dell'app Jarvis sulla VPS: dice se l'app sul telefono è collegata e quale versione offre.
    Una richiesta ogni 60 secondi al massimo."""
    if time.time() - _PONTE_CACHE["ts"] < 60 and _PONTE_CACHE["dati"] is not None:
        return _PONTE_CACHE["dati"]
    dati = {"raggiungibile": False, "app_collegata": False, "versione_offerta": None}
    base = (CFG.get("ponte_android_url") or "https://vps.esempio.it").rstrip("/")
    try:
        import urllib.request as _u
        with _u.urlopen(base + "/health", timeout=6) as r:
            h = json.loads(r.read())
        dati["raggiungibile"] = bool(h.get("ok"))
        dati["app_collegata"] = bool(h.get("phoneConnected"))
        with _u.urlopen(base + "/update/version.json", timeout=6) as r:
            dati["versione_offerta"] = json.loads(r.read()).get("versionName")
    except Exception:
        pass
    _PONTE_CACHE.update(ts=time.time(), dati=dati)
    return dati


def voci_stato():
    """Come ascolta, pensa e parla Jarvis: letto dalla configurazione vera della voce e dal processo che gira,
    non scritto a mano. Nessuna chiave esce da qui."""
    if sys.platform == "win32":
        # Windows non usa backtalk: l'ascolto è talk_to_jarvis_windows.py, tutto in locale
        return {
            "voce_accesa": bool(processi(SCRIPT_VOCE_WIN)),
            "ascolto": {"nome": "Whisper", "dettaglio": "faster-whisper «small», su questo PC", "lingua": "it"},
            "cervello": {"nome": "Claude"},
            "motori": [{"id": "kokoro", "nome": "Kokoro Sara", "attivo": True,
                        "nota": "voce italiana, su questo PC, nessun servizio nella nuvola"}],
            "ultimo_motore": None, "ultimo_ts": None,
        }
    cfg = leggi_json(AGENTE / "backtalk" / "backtalk.json", {})
    acceso = bool(processi("backtalk.main"))
    ultimo = leggi_json(AGENTE / "backtalk" / "motore.json", {})
    az, ed, ge = cfg.get("azure_voce") or {}, cfg.get("edge_voce") or {}, cfg.get("gemini_voce") or {}
    return {
        "voce_accesa": acceso,
        "ascolto": {"nome": "Whisper", "dettaglio": cfg.get("stt_model") or "", "lingua": cfg.get("stt_language") or ""},
        "cervello": {"nome": "Claude"},
        "motori": [
            {"id": "gemini", "nome": "Gemini", "attivo": bool(ge.get("enabled") and ge.get("webhook")),
             "nota": "primo se è acceso; oggi è spento"},
            {"id": "azure", "nome": "Azure", "attivo": bool(az.get("enabled") and az.get("key")),
             "nota": (az.get("voce") or "") + " · nella nuvola di Microsoft"},
            {"id": "edge", "nome": "Edge TTS", "attivo": bool(ed.get("enabled", True)),
             "nota": (ed.get("voce") or "") + " · riserva, nella nuvola di Microsoft"},
            {"id": "kokoro", "nome": "Kokoro", "attivo": True,
             "nota": (cfg.get("voice") or "") + " · sul Mac, ultimo della catena"},
        ],
        "ultimo_motore": ultimo.get("motore"),
        "ultimo_ts": ultimo.get("ts"),
    }



AGENTI_CACHE = {"ts": 0, "righe": [], "orfani": []}
NOMI_SESSIONI_FILE = QUI / "sessioni-nomi.json"


def nomi_sessioni():
    """Pid -> nome leggibile, per riconoscere a colpo d'occhio Telegram, Cloud,
    ecc. nel pannello. File a mano, si aggiorna quando il pid di un servizio
    cambia (es. dopo un riavvio)."""
    try:
        d = json.loads(NOMI_SESSIONI_FILE.read_text())
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except Exception:
        return {}


def raccogli_agenti():
    """Le sessioni di Claude aperte adesso: pid, se lavora davvero o e' ferma, da quando,
    processore consumato, in quale progetto. Stessa fonte di strumenti/agenti.py."""
    if _agenti_mod is None:
        return
    try:
        righe, orfani = _agenti_mod.guarda(1.5)
    except Exception as e:
        evento(f"agenti: {e}")
        return
    nomi = nomi_sessioni()
    AGENTI_CACHE["ts"] = time.time()
    AGENTI_CACHE["righe"] = [
        {"pid": r["pid"], "lavora": r["lavora"], "cpu": round(r["cpu"], 1), "acceso": r["acceso"],
         "ore": round(r["ore"], 1), "dove": (r["dove"].replace(str(HOME), "~") if r["dove"] else ""),
         "cosa": r["cosa"], "ascolto": r.get("ascolto") or "",
         "nome": nomi.get(str(r["pid"])) or r.get("ascolto") or None}
        for r in righe
    ]
    AGENTI_CACHE["orfani"] = len(orfani)


def android():
    if CFG.get("android") is False:
        return {"installato": False, "dispositivi": [], "spento": True}
    if not shutil.which("adb", path=PATH_ENV):
        return {"installato": False, "dispositivi": []}
    _, out = sh(["adb", "devices", "-l"], timeout=8)
    disp = []
    for riga in out.splitlines()[1:]:
        parti = riga.split()
        if len(parti) >= 2 and parti[1] == "device":
            modello = next((x.split(":", 1)[1] for x in parti if x.startswith("model:")), parti[0])
            disp.append({"id": parti[0], "modello": modello.replace("_", " ")})
    batteria = None
    if disp:
        _, b = sh(["adb", "-s", disp[0]["id"], "shell", "dumpsys", "battery"], timeout=8)
        m = re.search(r"level:\s*(\d+)", b)
        batteria = int(m.group(1)) if m else None
    return {"installato": True, "dispositivi": disp, "batteria": batteria,
            "schermo": bool(processi("scrcpy")),
            "controllo": (TELEFONO / "android" / "agisci.sh").exists(),
            "ponte": ponte_android()}


# La parte pesante (osascript sui browser, adb, risorse del Mac) gira ogni 15 s in un suo ciclo e
# lascia qui il risultato; raccogli_locale, ogni 5 s, la unisce alla parte leggera. Prima partivano
# ~16 processi ogni 5 secondi anche a pagina chiusa.
LOCALE_PESANTE = {}
LOCALE_PESANTE_LOCK = threading.Lock()


_GIRO_PESANTE = threading.Lock()   # un giro alla volta: due giri insieme conterebbero doppie le letture negative


def raccogli_locale_pesante():
    with _GIRO_PESANTE:
        if sys.platform == "win32":      # niente sysctl, vm_stat, adb: solo l'orb
            dati = {**stato_pagine()}
        else:
            dati = {**stato_pagine(), "mac": mac_risorse(), "android": android()}
    with LOCALE_PESANTE_LOCK:
        LOCALE_PESANTE.clear()
        LOCALE_PESANTE.update(dati)
    raccogli_locale()


SU_LINUX = sys.platform.startswith("linux")
VOCE_VPS_CONTENITORE = "jarvis-agent"


def voce_vps():
    """(accesa, stato) della voce sulla VPS: il contenitore jarvis-agent risponde a /health (porta 8790).
    «stato» dice se l'app del telefono è collegata in questo momento."""
    c, out = sh(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                 VOCE_VPS_CONTENITORE], timeout=5)
    ip = (out or "").split()[0] if c == 0 and (out or "").split() else ""
    if not ip:
        return False, "spenta"
    try:
        with urllib.request.urlopen(f"http://{ip}:8790/health", timeout=3) as r:
            d = json.loads(r.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return False, "non risponde"
    if not d.get("ok"):
        return False, "non risponde"
    return True, "telefono collegato" if d.get("phoneConnected") else "accesa, telefono non collegato"


def raccogli_locale():
    bt = leggi_json(BACKTALK_JSON, {})
    deny = leggi_json(SETTINGS_LOCALI, {}).get("permissions", {}).get("deny", [])
    try:
        voce_stato = (AGENTE / "backtalk" / ".voice_state").read_text(encoding="utf-8").strip() or "idle"
    except OSError:
        voce_stato = "idle"
    with LOCALE_PESANTE_LOCK:
        pesante = dict(LOCALE_PESANTE)
    if SU_LINUX:      # 2026-10-05: sulla VPS la voce è il ponte del telefono (jarvis-agent), non backtalk del Mac
        voce, voce_stato = voce_vps()
    else:
        voce = bool(processi(SCRIPT_VOCE_WIN if sys.platform == "win32" else "backtalk.main"))
    STATO.set("locale", {
        "voce": voce,
        "voce_stato": voce_stato,
        **pesante,
        "telefono": bool(processi("claude remote-control")),
        "schermo_telefono": bool(processi("scrcpy")),
        "chiede_prima": bt.get("permission_mode", "ask") != "bypassPermissions",
        "al_pc": shutil.which("cliclick", path=PATH_ENV) is not None and not any(r in deny for r in REGOLE_AL_PC),
        "fidata": fidata(),
        "voci": voci_stato(),
        "agenti_sessioni": {"aggiornato": AGENTI_CACHE["ts"], "sessioni": AGENTI_CACHE["righe"], "orfani": AGENTI_CACHE["orfani"]},
    })


def stato_pagine():
    """Acceso = server vivo e scheda aperta. Se la scheda è stata chiusa, spegne il server."""
    if sys.platform == "win32":     # Windows: il «volto» è l'orb sul desktop, acceso se il processo c'è
        return {"volto": bool(processi(SCRIPT_ORB_WIN))}
    if PROVA:
        # la copia di prova non spegne e non chiude niente: il pannello vero lo fa già
        return {nome: bool(pid_su_porta(porta)) for nome, (_, porta, _) in PEZZI_PAGINA.items()}
    schede = schede_locali()
    ora = time.time()
    fuori = {}
    for nome, (_, porta, _) in PEZZI_PAGINA.items():
        server = bool(pid_su_porta(porta))
        if nome == "volto":
            # il volto e il grafo sinapsi stanno DENTRO il pannello (iframe), non in una scheda del browser:
            # basta che il server risponda. Prima si spegneva da solo dopo 25 s senza scheda, e il grafo cadeva.
            fuori[nome] = server
            continue
        dentro_attesa = ora - ACCESO_IL.get(nome, 0) < ATTESA_PAGINA
        if schede is None:
            # lettura incerta (un browser non ha risposto): non si decide niente, resta com'era
            fuori[nome] = server
            continue
        pagina = porta in schede
        if pagina or not server or dentro_attesa:
            PAGINA_ASSENTE.pop(nome, None)
        if server and not pagina and not dentro_attesa:
            PAGINA_ASSENTE[nome] = PAGINA_ASSENTE.get(nome, 0) + 1
            if PAGINA_ASSENTE[nome] >= LETTURE_PER_SPEGNERE:
                spegni_pezzo(nome, f"pagina chiusa nel browser ({LETTURE_PER_SPEGNERE} letture di fila)")
                server = False
            else:
                fuori[nome] = True        # ancora acceso finché la chiusura non è confermata
                continue
        elif pagina and not server and not dentro_attesa:
            chiudi_schede(porta)          # pagina orfana: il suo server non c'è più
            pagina = False
        fuori[nome] = server and (pagina or dentro_attesa)
    return fuori


def raccogli_claude():
    """Il pallino «Claude» in basso: login vero di Claude Code, non un colore fisso."""
    codice, out = sh(["claude", "auth", "status"], timeout=20)
    try:
        d = json.loads(out[out.find("{"):])
    except ValueError:
        d = {}
    STATO.set("claude", {"collegato": codice == 0 and bool(d.get("loggedIn")),
                         "metodo": d.get("authMethod") or "", "errore": "" if d else out.strip()[:200]})


def ast(comando, timeout=12):
    """Un comando alla console del centralino."""
    if not AST.exists():
        return ""
    return sh([str(AST), "-C", str(AST_CONF), "-rx", comando], timeout=timeout)[1]


def raccogli_telefono():
    acceso = bool(processi("telefono/asterisk/sbin/asterisk"))
    registrazione = ""
    armata = False
    if acceso:
        for riga in ast("pjsip show registrations").splitlines():
            m = re.search(r"\b(Registered|Rejected|Unregistered|Rejected_Permanent)\b", riga)
            if ENDPOINT_SIP in riga and m:
                registrazione = m.group(1)
        armata = ast("database get jarvis rispondi").strip().endswith("1")
    chiamate = []
    cartella = TELEFONO / "chiamate"
    if cartella.is_dir():
        for f in sorted(cartella.glob("*.json"), reverse=True)[:8]:
            d = leggi_json(f, {})
            esito = d.get("esito", "")
            ultima = (d.get("trascrizione") or [{}])[-1]
            if not esito and ultima.get("chi") == "sistema":
                esito = "chiamata interrotta: " + ultima.get("testo", "")   # niente resoconto
            chiamate.append({"quando": d.get("quando", f.stem), "numero": d.get("numero", ""),
                             "chi": d.get("chi", ""), "tipo": d.get("tipo", ""),
                             "durata": d.get("durata"), "esito": esito,
                             "domande": d.get("domande", []), "accordi": d.get("accordi", ""),
                             "da_fare": d.get("da_fare", ""), "file": f.stem})
    STATO.set("telefono", {
        "centralino": acceso, "registrazione": registrazione, "risposta_armata": armata,
        "ponte_locale": bool(pid_su_porta(9093)), "ponte_gemini": bool(pid_su_porta(9092)),
        "chiamate": chiamate,
    })


COMANDI_RAPIDI = {
    "briefing": {"nome": "Briefing", "descrizione": "Jarvis riassume come siamo messi, in sola lettura",
                 "richiesta": "Fammi il briefing: cosa è in corso, cosa resta da fare sui progetti aperti, "
                              "cosa non torna sulla VPS o nei dati. Massimo dieci righe, in italiano."},
    "domande_telefono": {"nome": "Domande dalle chiamate", "descrizione": "raccoglie le domande lasciate dalle telefonate",
                         "richiesta": "Leggi i resoconti in telefono/chiamate/ degli ultimi sette giorni e "
                                      "riportami in un elenco solo le domande per me e le cose da fare ancora aperte."},
    "migliorati": {"nome": "Come migliorarti", "descrizione": "Jarvis legge l'autocontrollo e le chiamate e propone",
                   "richiesta": "Leggi prove/RAPPORTO.md, gli ultimi resoconti in telefono/chiamate/ e i registri "
                                "delle ultime missioni in command-center/missioni/. Dimmi, al massimo in dieci righe: "
                                "cosa si è rotto o è andato storto di recente, quale difetto vale la pena sistemare per "
                                "primo e perché, e quale prova manca nell'autocontrollo per accorgersene prima. "
                                "Solo cose che hai letto davvero nei file, con il nome del file accanto."},
}
# comandi e collegamenti propri di chi lo usa: stanno in configurazione.json
for _c in CFG.get("comandi") or []:
    if _c.get("id") and _c.get("richiesta"):
        COMANDI_RAPIDI[_c["id"]] = {"nome": _c.get("nome", _c["id"]),
                                    "descrizione": _c.get("descrizione", ""),
                                    "richiesta": _c["richiesta"]}

APRI_RAPIDO = {"guida_telefono": None,
               # ex Avvia Cloud (claude --cloud Jarvis) → un'app esterna (l'utente 23/09/2026)
               "avvia_cloud": str(AGENTE / "avvio" / "Apri un'app esterna.command")}
APRI_RAPIDO.update(CFG.get("collegamenti") or {})


def claude_ora():
    """Cosa sta facendo la sessione di Claude Code in chat adesso: scritto
    dagli hook in .claude/hooks/jarvis_status.py nello stesso bus della voce."""
    d = leggi_json(AGENTE / "backtalk" / ".jarvis_status", {})
    if not d:
        return None
    agenti = [a for a in (d.get("agenti") or []) if time.time() - a.get("ts", 0) < 1800]
    for a in agenti:   # registrati prima del gancio di fine: stato ignoto, non «attivo»
        a.setdefault("stato", "finito")
        a["nodo"] = _nodo_bus(a.get("nodo"))
    return {"lavorando": bool(d.get("lavorando")), "richiesta": d.get("richiesta", ""),
            "richiesta_ts": d.get("richiesta_ts"), "azione": d.get("azione", ""),
            "dettaglio": d.get("dettaglio", ""), "agenti": agenti[:5]}


def _nodo_bus(nodo):
    """2026-10-05: il gancio scrive «gruppo:nome» (Azienda Due:revisore); la pagina cerca gli agenti per nome
    (trovaAgente): qui il nome vero dell'agente risolto (revisore-Azienda Due), o il nome com'era."""
    n = str(nodo or "")
    if ":" not in n:
        return nodo
    try:
        k = risolvi_chiave(n)
    except Exception:  # noqa: BLE001
        k = ""
    return k.split(":", 1)[1] if k and ":" in k and not k.startswith("?:") else n.split(":", 1)[1]


def raccogli_catena():
    """La catena degli agenti e la sincronia memoria ↔ vault di ogni progetto,
    da sincro/controlla.py (una sola fonte; schema nella scheda «Schema agenti
    Jarvis» del vault)."""
    r = subprocess.run([sys.executable, str(AGENTE / "sincro/controlla.py"), "--json"],
                       capture_output=True, text=True, timeout=60)
    try:
        dati = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"controlla.py esito {r.returncode}: "
                           f"{(r.stderr or r.stdout or 'nessuna uscita').strip()[-200:]}") from None
    progetti = []
    for p in dati.get("progetti", []):
        if p["progetto"].startswith("Jarvis"):
            continue
        progetti.append({k: p.get(k) for k in ("progetto", "ceo", "specialisti",
                         "ultimo_report", "avvisi", "memoria", "dati", "registro_ceo")})
    # dal 23/09/2026 gli agenti di comando stanno in ~/.claude/agents (in Jarvis resta solo LEGGIMI.md)
    propri = sorted({f.stem for cartella in (HOME / ".claude/agents", AGENTE / ".claude/agents")
                     for f in cartella.glob("*.md") if f.stem != "LEGGIMI"})
    modelli = {}
    for p in dati.get("progetti", []):
        modelli.update(p.get("modelli") or {})
    entro = (date.today() + timedelta(days=7)).isoformat()
    r = subprocess.run([sys.executable, str(AGENTE / "sincro/controlla.py"),
                        "--registro", entro, "--json"], capture_output=True, text=True, timeout=60)
    try:
        scadenze = json.loads(r.stdout)
    except ValueError:
        scadenze = []
    STATO.set("catena", {"jarvis": propri, "progetti": progetti, "modelli": modelli,
                         "scadenze": scadenze, "scadenze_entro": entro})


def agenti_attivi():
    """Quali agenti stanno lavorando adesso, letti dai registri delle missioni."""
    attivi = []
    for d in sorted(MISSIONI_DIR.iterdir(), reverse=True) if MISSIONI_DIR.is_dir() else []:
        if not d.is_dir():
            continue
        st = leggi_json(d / "stato.json", {}).get("stato")
        if st not in ("in corso", "attende conferma"):
            continue
        conf = leggi_json(d / "missione.json", {})
        if not (conf.get("pid") and _missione_viva(conf["pid"], d)):
            continue                  # processo morto: non lavora nessuno
        ultimo = ""
        try:
            for riga in reversed((d / "registro.log").read_text().splitlines()):
                m = re.search(r"→ (?:Agent|Task): (.+)", riga)
                if m:
                    ultimo = m.group(1)[:80]
                    break
        except OSError:
            pass
        try:
            ts = datetime.strptime(d.name, "%Y-%m-%d_%H%M%S").timestamp()
        except ValueError:
            ts = None
        # le missioni per spazi (dal 23/09/2026): chi lavora sta in agenti.json
        esperti = [a for a in leggi_json(d / "agenti.json", {}).get("agenti", []) if a.get("stato") == "lavora"]
        nome = conf.get("progetto") or " + ".join(p["nome"] for p in conf.get("progetti") or [])
        attivi.append({"missione": d.name, "progetto": nome, "spazio": conf.get("spazio_nome"),
                       "chi": conf.get("ceo") or ("orchestratore" if conf.get("progetti") else "Jarvis"),
                       "stato": st, "ultimo": ultimo, "ts": ts,
                       "esperti": [{"nome": a["tipo"], "descrizione": a.get("descrizione", ""),
                                    "inizio": a.get("inizio"), "ultima": a.get("ultima", "")} for a in esperti]})
    return attivi


VPS = (CFG.get("vps") or "").strip()
ENDPOINT_SIP = (CFG.get("endpoint_sip") or "linea").strip()


def raccogli_vps():
    if not VPS:
        siti = {}
        for nome, url in SITI.items():
            _, c = sh(["curl", "-s", "-o", "/dev/null", "-m", "10", "-w", "%{http_code}", url], timeout=15)
            siti[nome] = c.strip()[-3:]
        STATO.set("vps", {"configurata": False, "raggiungibile": None, "siti": siti,
                          "contenitori": [], "letto": datetime.now().strftime("%H:%M")})
        return
    codice, out = sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS,
                      "docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}';"
                      "echo ===; df -P / | tail -1; echo ===; free -b | sed -n 2p"], timeout=25)
    vps = {"raggiungibile": codice == 0, "contenitori": [], "disco": None, "ram": None}
    if codice == 0:
        blocchi = out.split("===")
        for riga in blocchi[0].strip().splitlines():
            nome, stato, dettaglio = (riga.split("|") + ["", ""])[:3]
            vps["contenitori"].append({"nome": nome, "attivo": stato == "running", "dettaglio": dettaglio})
        try:
            vps["disco"] = int(blocchi[1].split()[4].rstrip("%"))
            m = blocchi[2].split()
            vps["ram"] = round(int(m[2]) * 100 / int(m[1]))
        except (IndexError, ValueError):
            pass
    siti = {}
    for nome, url in SITI.items():
        _, c = sh(["curl", "-s", "-o", "/dev/null", "-m", "10", "-w", "%{http_code}", url], timeout=15)
        siti[nome] = c.strip()[-3:]
    vps["siti"] = siti
    vps["letto"] = datetime.now().strftime("%H:%M")
    vps["configurata"] = True
    vps["nome"] = CFG.get("nome_vps") or f"Server {VPS}"
    STATO.set("vps", vps)


# Jarvis su Telegram, sul Mac (@tuo_bot) e sulla VPS (@tuo_bot_vps). Lo tiene su il guardiano
# strumenti/telegram_guardia.py, lanciato ogni minuto da launchd (Mac) e da systemd (VPS).
GUARDIA = AGENTE / "strumenti" / "telegram_guardia.py"
GUARDIA_VPS = "/opt/jarvis-vps/strumenti/telegram_guardia.py"
BOT_TELEGRAM = {"mac": "@tuo_bot", "vps": "@tuo_bot_vps"}


def guardia(dove, comando):
    if dove == "mac":
        return sh(["python3", str(GUARDIA), comando], timeout=25)
    if not VPS:
        return 1, "VPS non configurata"
    # 30/09/2026: la sessione vera del bot VPS è dell'utente "jarvis" (dal 28/09, per
    # --dangerously-skip-permissions: Claude Code lo rifiuta come root). Chiamare lo script
    # da root, come faceva ssh prima, guarda il socket tmux di root (/tmp/tmux-0/), sempre
    # vuoto: il pannello diceva "scollegato" anche con il bot vivo e agganciato.
    return sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS,
               f"sudo -u jarvis env HOME=/home/jarvis python3 {GUARDIA_VPS} {comando}"], timeout=30)


def guardia_mac():
    """Finché il Command Center è acceso tiene su TuoBot (decisione dell'utente del 19/09/2026 22:00)."""
    guardia("mac", "controlla")


def raccogli_telegram():
    if sys.platform == "win32":
        # 28/09/2026 (ramo windows): Telegram non è configurato sul PC; «spento» toglie anche l'anomalia dalla sentinella
        STATO.set("telegram", {d: {"spento": True, "bot": BOT_TELEGRAM[d]} for d in ("mac", "vps")})
        return
    t = {}
    for dove in ("mac", "vps"):
        c, out = guardia(dove, "stato")
        try:
            t[dove] = json.loads(out.strip().splitlines()[-1])
        except (IndexError, ValueError):
            t[dove] = {"errore": out.strip()[:200] or "nessuna risposta"}
        t[dove]["bot"] = BOT_TELEGRAM[dove]
    STATO.set("telegram", t)


def battito():
    """L'ultimo giro del battito dei 15 minuti (sincro/ogni30.py).

    🔴 Fino al 20/09/2026 questo riquadro contava note, sessioni e sviluppi del
    vault: numeri che salgono e sembrano uno stato, ma non dicono se la memoria
    di un progetto sia aggiornata. Lo stato vero sta qui: una riga per progetto,
    con l'ora della memoria, del vault e dell'ultimo lavoro.
    """
    d = leggi_json(AGENTE / "sincro/ultimo.json", {})
    if not d:
        return {"acceso": False, "perche": "il battito non è mai passato"}
    if sys.platform == "win32" and "progetti" in d:
        # 28/09/2026 (ramo windows): ultimo.json può arrivare dal Mac col repository; qui solo i progetti di spazi.json
        nomi_qui = {p["nome"] for s in spazi.carica() for p in s["progetti"]}
        d = {**d, "progetti": [p for p in d["progetti"] if p.get("progetto") in nomi_qui]}
    try:
        passato = (datetime.now() - datetime.strptime(d["quando"], "%Y-%m-%d %H:%M")).total_seconds()
    except (KeyError, ValueError):
        return {"acceso": False, "perche": "ultimo.json senza data leggibile"}
    # 15 minuti di intervallo più un giro di tolleranza: oltre, è fermo davvero
    fermo = passato > 15 * 60 * 2
    d.update({"acceso": not fermo, "minuti_fa": int(passato // 60),
              "perche": "l'ultimo giro è di %d minuti fa" % (passato // 60) if fermo else ""})
    return d


def raccogli_memoria():
    note = sum(1 for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts) if VAULT.exists() else 0
    oggi = date.today().isoformat()
    diario = any(VAULT.glob(f"Memoria/00 Comune/Diario/**/{oggi}*.md")) if VAULT.exists() else False
    cartella_sessioni = HOME / ".claude/projects" / str(AGENTE).replace("/", "-")
    sessioni = len(list(cartella_sessioni.glob("*.jsonl"))) if cartella_sessioni.is_dir() else 0
    sviluppi = []
    indice = VAULT / "Memoria" / "Vita personale" / "Jarvis" / "Sviluppi" / "Sviluppi.md"
    if indice.exists():
        for riga in indice.read_text().splitlines():
            m = re.match(r"\|\s*\[\[(.+?)\]\]\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", riga)
            if not m:
                continue
            scheda = VAULT / "Memoria" / "Vita personale" / "Jarvis" / "Sviluppi" / f"{m.group(1)}.md"
            aperti = []
            if scheda.exists():
                aperti = [t.strip()[6:] for t in scheda.read_text().splitlines() if t.strip().startswith("- [ ]")]
            sviluppi.append({"nome": m.group(1), "progetto": m.group(2), "stato": m.group(3), "task": aperti})
    STATO.set("memoria", {"note": note, "diario_oggi": diario, "sessioni": sessioni,
                          "sviluppi": sviluppi, "battito": battito()})


def _genera_nota(script, tetto):
    """Lancia uno script di strumenti/ che scrive una nota generata in Obsidian.
    Un processo a parte con un tetto di tempo: il server non si blocca e un
    errore dello script non lo tocca. Gira nel suo thread di ciclo()."""
    r = subprocess.run([sys.executable, str(QUI.parent / "strumenti" / script)], cwd=str(QUI.parent),
                       env=ENV, capture_output=True, text=True, timeout=tetto, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        evento(f"{script}: esito {r.returncode} {(r.stderr or r.stdout).strip()[-200:]}")


def aggiorna_cruscotto():
    """«Jarvis Brain/00 Cruscotto.md», ogni 120 s (strumenti/cruscotto.py)."""
    _genera_nota("cruscotto.py", 60)


def aggiorna_mappa_agenti():
    """Le note degli agenti e «Mappa agenti», ogni 30 minuti (strumenti/mappa_agenti.py).
    Riscrive solo le note cambiate."""
    _genera_nota("mappa_agenti.py", 300)


# ---------------------------------------------------------------- la lavagna come motore degli agenti (2026-09-26 sera)
# l'utente: «la lavagna deve essere il nostro motore in tempo reale degli agenti: creare, modificare, aggiornare
# tutto compreso tono e umorismo». Fonte di verità: il profilo .claude/agents/<nome>.md; pannello.json è solo
# disposizione (contratto, punto 13). Un agente tolto va in .claude/agents/_archivio/: mai cancellato.
MODELLO_AGENTE = QUI / "modelli" / "agente.md"
AGENTI_LOCK = threading.Lock()
NOME_AGENTE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _cartelle_agenti():
    return [Path(p["cartella"]) / ".claude" / "agents" for s_ in spazi.carica() for p in s_["progetti"] if p["esiste"]]


def campi_come_parla(dati):
    """tono, umorismo (0–3), attivo dal corpo di una richiesta: None = non toccare."""
    fuori = {}
    if dati.get("tono") is not None:
        fuori["tono"] = " ".join(str(dati["tono"]).split())[:120]
    if dati.get("umorismo") is not None:
        try:
            u = int(dati["umorismo"])
        except (TypeError, ValueError):
            raise ValueError("umorismo: un numero da 0 a 3") from None
        if not 0 <= u <= 3:
            raise ValueError("umorismo: un numero da 0 a 3")
        fuori["umorismo"] = str(u)
    if dati.get("serieta") is not None:
        try:
            sr = int(dati["serieta"])
        except (TypeError, ValueError):
            raise ValueError("serietà: un numero da 0 a 3") from None
        if not 0 <= sr <= 3:
            raise ValueError("serietà: un numero da 0 a 3")
        fuori["serieta"] = str(sr)
    if dati.get("attivo") is not None:
        fuori["attivo"] = "true" if bool(dati["attivo"]) else "false"
    return fuori


def _progetto(pid):
    for s_ in spazi.carica():
        for p in s_["progetti"]:
            if p["id"] == pid:
                if not p["esiste"]:
                    raise ValueError(f"cartella di {p['nome']} non trovata")
                return s_, p
    raise ValueError("progetto sconosciuto")


def _tutti_profili():
    """(chiave «progetto:nome», profilo) di tutti gli agenti degli spazi.

    Due progetti dello stesso spazio possono condividere la stessa cartella (voci come
    «azioni»/«app-github», investimenti senza specialisti propri, appoggiate al capogruppo
    di un altro progetto, 27/09/2026): i suoi agenti si leggono una sola volta, altrimenti
    lo stesso profilo risulterebbe doppio o triplo."""
    for s_ in spazi.carica():
        viste = set()
        for p in s_["progetti"]:
            if p["esiste"] and p["cartella"] not in viste:
                viste.add(p["cartella"])
                for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                    yield f"{p['id']}:{a['nome']}", a


def _scrivi_comunica(file, nomi):
    f = Path(file)
    prima = f.read_text(encoding="utf-8")
    nuovo = aggiorna_comunica_con(prima, list(dict.fromkeys(nomi)))
    if nuovo != prima:
        scrivi_atomico(f, nuovo)


def _cambia_comunica(file, aggiungi=(), togli=()):
    a = next((x for _, x in _tutti_profili() if x["file"] == str(file)), None)
    attuali = a["comunica"] if a else []
    nomi = [n for n in attuali if n not in set(togli)] + [n for n in aggiungi if n not in attuali]
    if nomi != attuali:
        _scrivi_comunica(file, nomi)


GRUPPI_ARCHIVIO = QUI / "gruppi-archiviati.json"
# Aggiorna tutti / ultime modifiche (l'utente, 2026-09-26 19:10: «ogni volta che faccio una modifica sulla lavagna
# valutiamo solo quel collegamento o quell'aggiunta»). Ogni cambiamento agli agenti è una riga qui; quelle dopo
# l'ultimo aggiornamento, tolte le «da: catena» (fatte dalla missione stessa), sono le pendenti.
MODIFICHE_FILE = QUI / "modifiche-agenti.jsonl"
CATENA_STATO = QUI / "catena-stato.json"          # {"ultimo_aggiornamento_ts": …}; fuori da git
MODIFICHE_LOCK = threading.Lock()


def registra_modifica(tipo, progetto, agente, con=(), da="lavagna"):
    riga = {"ts": time.time(), "tipo": tipo, "progetto": progetto or "", "agente": agente or "",
            "con": [c for c in con if c], "da": da}
    with MODIFICHE_LOCK:
        if tipo == "filo":
            # un filo scrive il nome in tutte e due le schede: la seconda metà dello stesso filo non è una riga nuova
            for r in reversed(_leggi_modifiche()[-20:]):
                if (r.get("tipo") == "filo" and riga["ts"] - r.get("ts", 0) < 120 and r.get("da") == da
                        and set(r.get("con") or []) == {agente} and set(riga["con"]) == {r.get("agente")}):
                    return
        with open(MODIFICHE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(riga, ensure_ascii=False) + "\n")
    tocca("modifiche")


def _leggi_modifiche():
    fuori = []
    try:
        for r in MODIFICHE_FILE.read_text(encoding="utf-8").splitlines():
            try:
                fuori.append(json.loads(r))
            except ValueError:
                pass
    except OSError:
        pass
    return fuori


def _progetto_di_file(file):
    f = str(Path(file).resolve())
    for s_ in spazi.carica():
        for p in s_["progetti"]:
            if p["esiste"] and Path(p["cartella"]).resolve() in Path(f).parents:    # su Windows i percorsi hanno «\\»
                return p["id"]
    return ""


def modifiche_pendenti():
    ultimo = leggi_json(CATENA_STATO, {}).get("ultimo_aggiornamento_ts") or 0
    # 30/09/2026: una modifica il cui progetto non esiste più in nessuno spazio (es. un gruppo
    # tolto dalla lavagna e archiviato) restava comunque «pendente» per sempre: il badge la
    # contava, ma «Aggiorna ultime modifiche» non trovava nessun progetto vivo da aggiornare e
    # falliva con «nessun progetto con un capogruppo in questo spazio» — un fantasma bloccava
    # il tasto anche quando tutto il resto era davvero a posto.
    progetti_vivi = {p["id"] for s_ in spazi.carica() for p in s_["progetti"]}
    pendenti = [r for r in _leggi_modifiche()
                if r.get("ts", 0) > ultimo and r.get("da") != "catena" and r.get("progetto") in progetti_vivi]
    per_nome = {}
    for k, _ in _tutti_profili():
        per_nome.setdefault(k.split(":", 1)[1], []).append(k)
    coinvolti = []
    for r in pendenti:
        chiavi = [f"{r['progetto']}:{r['agente']}"] if r.get("agente") else []
        for n in r.get("con") or []:
            vicine = per_nome.get(n) or []
            chiavi.append(next((k for k in vicine if k.startswith(r["progetto"] + ":")), vicine[0] if vicine else n))
        coinvolti += [k for k in chiavi if k not in coinvolti]
    return {"ultimo_aggiornamento_ts": ultimo or None, "pendenti": pendenti, "agenti_coinvolti": coinvolti}


PROFILO_JARVIS = AGENTE / "profilo-jarvis.md"


def nota_di_casa(nome):
    """Le note della lavagna che non sono progetti ma sono comunque reali (27/09/2026, richiesta di
    L'utente: «deve essere certo che sia collegata»): Memoria è la cartella vera, esecutore e
    ricercatore-web sono agenti veri di Jarvis (~/.claude/agents/), fuori da ogni progetto."""
    if nome == "memoria" and sys.platform == "win32":
        # ramo windows: la memoria dell'utente di questo PC, la cartella che dice utente.json (dall'installatore)
        mem = leggi_json(AGENTE / "utente.json", {}).get("memoria_dir") or ".claude/memoria-utente"
        return {"tipo": "cartella", "percorso": str(AGENTE / mem).replace(str(HOME), "~")}
    if nome == "memoria":
        mem = leggi_json(HOME / ".jarvis" / "percorsi.json", {}).get("memoria") or str(HOME / "Jarvis-Memoria")
        return {"tipo": "cartella", "percorso": str(Path(os.path.expanduser(mem))).replace(str(HOME), "~")}
    # Jarvis stesso (29/09/2026, l'utente: «non riesco ad assegnargli umore e caratteristiche»): il suo profilo
    # è ~/Jarvis/profilo-jarvis.md; tono e umorismo li legge il gancio di apertura delle chat (sessioni.py)
    f = PROFILO_JARVIS if nome == "jarvis" else HOME / ".claude" / "agents" / f"{nome}.md"
    if nome in ("jarvis", "esecutore", "ricercatore-web") and f.is_file():
        campi, _ = spazi.frontmatter(f.read_text(encoding="utf-8"))
        try:
            umorismo = max(0, min(3, int(campi.get("umorismo"))))
        except (TypeError, ValueError):
            umorismo = None
        try:
            serieta = max(0, min(3, int(campi.get("serieta"))))
        except (TypeError, ValueError):
            serieta = None
        return {"tipo": "agente", "percorso": str(f).replace(str(HOME), "~"),
                "descrizione": campi.get("description", ""), "modello": campi.get("model", ""),
                "strumenti": campi.get("tools", ""), "tono": campi.get("tono", ""), "umorismo": umorismo,
                "serieta": serieta}
    raise ValueError("non è una nota di casa riconosciuta")


def scrivi_nota_di_casa(nome, dati):
    """Scrive i campi di esecutore/ricercatore-web (soli due, per non aprire una porta a scrivere
    un file a piacere): stesso motore delle schede degli altri agenti, aggiorna_frontmatter."""
    if nome not in ("jarvis", "esecutore", "ricercatore-web"):
        raise ValueError("questa nota di casa non si modifica da qui")
    f = PROFILO_JARVIS if nome == "jarvis" else HOME / ".claude" / "agents" / f"{nome}.md"
    if not f.is_file():
        raise ValueError(f"{nome}: profilo non trovato")
    with AGENTI_LOCK:
        testo = f.read_text(encoding="utf-8")
        nuovo, cambiate = spazi.aggiorna_frontmatter(testo, {
            "description": dati.get("description"), "model": dati.get("model"),
            "tools": dati.get("tools"), "tono": dati.get("tono"),
            "umorismo": dati.get("umorismo") if dati.get("umorismo") is not None else None,
            "serieta": dati.get("serieta") if dati.get("serieta") is not None else None})
        if cambiate:
            scrivi_atomico(f, nuovo)
    return {"messaggio": "salvato" if cambiate else "nessuna modifica", "cambiate": cambiate}


def _radice_spazio(sp, base=""):
    """Dove stanno le cartelle dei progetti di uno spazio: la cartella di riferimento scelta dall'utente (base,
    percorso assoluto già esistente, ovunque sul Mac) oppure, come prima, Progetti/<spazio>/ in Jarvis Brain."""
    if base:
        b = Path(base).expanduser()
        if not b.is_absolute() or not b.is_dir():
            raise ValueError("la cartella di riferimento deve essere un percorso assoluto già esistente")
        return b
    if sys.platform == "win32":
        # ramo windows: Jarvis Brain non c'è; si parte dalla cartella che contiene i progetti già nello spazio
        for p in sp.get("progetti") or []:
            c = spazi.percorso(p.get("cartella"))
            if c and c.is_dir():
                return c.parent
        return spazi.OD
    return spazi.percorso(f"OD/Jarvis Brain/Progetti/{_cartella_spazio(sp)}")


def cartelle_progetto(spazio_id, base=""):
    """Le cartelle di primo livello dentro la cartella di riferimento dello spazio, per scegliere «cartella
    esistente» invece di farne nascere sempre una nuova (richiesta dell'utente, 27/09/2026; cartella di
    riferimento scelta a mano con Sfoglia: 29/09/2026, dal Jarvis Windows). Dice anche se una cartella
    è già usata da un altro progetto dello stesso spazio (condivisione possibile, non un errore)."""
    sp = next((x for x in spazi.carica() if x["id"] == spazio_id), None)
    if not sp:
        raise ValueError("spazio sconosciuto")
    radice = _radice_spazio(sp, base)
    usate = {Path(p["cartella"]).name: p["nome"] for p in sp["progetti"]}
    out = []
    if radice.is_dir():
        for d in sorted(radice.iterdir(), key=lambda x: x.name.lower()):
            if d.is_dir() and not d.name.startswith("."):
                out.append({"nome": d.name, "usata_da": usate.get(d.name)})
    return {"radice": str(radice), "cartelle": out}


def scegli_cartella():
    """La finestra «Scegli una cartella» del Mac (osascript, in un processo a parte per non bloccare il server).
    Torna il percorso scelto, o "" se l'utente annulla. Su Windows: «Sfoglia cartelle» con tkinter."""
    if sys.platform.startswith("linux"):
        raise ValueError("sulla VPS non c'è una finestra per scegliere: scrivi il percorso a mano")
    if sys.platform == "win32":
        codice = ("import tkinter as t, tkinter.filedialog as f\n"
                  "r = t.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
                  "print(f.askdirectory(title='Cartella del gruppo', mustexist=True) or '')")
        _, out = sh([sys.executable, "-c", codice], timeout=180)
        return out.strip().replace("/", "\\")
    copione = ('tell application "System Events"\n'
               '  activate\n'
               '  try\n'
               '    set c to POSIX path of (choose folder with prompt "Cartella di riferimento del gruppo")\n'
               '  on error\n'
               '    set c to ""\n'
               '  end try\n'
               '  return c\n'
               'end tell')
    _, out = sh(["osascript", "-e", copione], timeout=180)
    return out.strip().rstrip("/")


def _cartella_spazio(sp):
    """Il nome DELLA CARTELLA dello spazio (Memoria/<nome>/…, Progetti/<nome>): si ricava dal percorso `memoria`
    di spazi.json, così rinominare lo spazio (nome mostrato) non sposta dove nascono i gruppi nuovi."""
    try:
        m = spazi.percorso(sp.get("memoria"))
        if m and m.parent.name and m.parent.name != "Memoria":
            return m.parent.name
    except Exception:  # noqa: BLE001
        pass
    return sp["nome"]


def rinomina_spazio(spazio_id, nome):
    """02/10/2026 (audit menu, D13): rinominare un gruppo-spazio dal menu cambia il nome vero in spazi.json, i nomi
    dei gruppi nel menu e le schede «📁 …» sulle lavagne, così menu, lavagna e missioni dicono lo stesso nome.
    Le cartelle (memoria, report, progetti) NON si spostano: restano quelle di prima."""
    nome = " ".join(str(nome or "").split())[:60]
    if not nome or "/" in nome or nome.startswith("."):
        raise ValueError("nome dello spazio non valido")
    with AGENTI_LOCK:
        d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
        sp = next((x for x in d["spazi"] if x["id"] == spazio_id), None)
        if not sp:
            raise ValueError("spazio sconosciuto")
        if sp.get("sistema"):
            raise ValueError("gli spazi di sistema non si rinominano")
        if any(x["id"] != spazio_id and x["nome"].lower() == nome.lower() for x in d["spazi"]):
            raise ValueError(f"esiste già uno spazio chiamato {nome}")
        vecchio = sp["nome"]
        if vecchio == nome:
            return {"messaggio": "il nome è già questo"}
        cartella = _cartella_spazio(sp)
        sp.setdefault("cartella_nome", cartella)          # la cartella resta quella di prima
        sp["nome"] = nome
        spazi.salva(d)
        progetti = [(p["id"], p["nome"]) for p in sp["progetti"]]
    molti = len(progetti) > 1
    def etichetta(sn, pn):
        return "📁 " + (f"{sn} · {pn}" if molti and sn != pn else pn)
    cambi = {vecchio: nome}
    for _, pn in progetti:
        cambi[etichetta(vecchio, pn)] = etichetta(nome, pn)
    with PANNELLO_LOCK:
        if PANNELLO_FILE.exists():
            attuale = leggi_pannello()
            pd = json.loads(json.dumps(attuale))
            toccato = False
            for k, L in (pd.get("lavagne") or {}).items():
                if str(k).startswith("demo") or not isinstance(L, dict):
                    continue
                for n in L.get("nodi") or []:
                    if isinstance(n, dict) and n.get("tipo") == "nota" and n.get("testo") in cambi:
                        n["testo"] = cambi[n["testo"]]; toccato = True
            for g in pd.get("gruppi") or []:
                if g.get("id") == f"spazio-{spazio_id}" and g.get("nome") != nome:
                    g["nome"] = nome; toccato = True
            if toccato:
                _scrivi_pannello_sotto_lock(pulisci_pannello(pd), attuale)
    registra_modifica("gruppo", spazio_id, "")
    evento(f"spazio rinominato: {vecchio} → {nome}")
    tocca("spazi")
    tocca("pannello")
    return {"messaggio": f"spazio rinominato in {nome}"}


def crea_gruppo(dati):
    """Un progetto nuovo dalla lavagna (contratto, punto 14): cartella, capogruppo dal modello, sezione di
    memoria con «Da fare.md», voce in spazi.json. Niente si sovrascrive: se c'è già, si rifiuta.

    27/09/2026 (l'utente): la cartella può essere una già esistente (dentro Progetti/<spazio>/, scelta
    dall'elenco di cartelle_progetto) invece di nascerne sempre una nuova dal nome."""
    pid = str(dati.get("id") or "").strip()
    nome = " ".join(str(dati.get("nome") or "").split())[:60]
    if not NOME_AGENTE.fullmatch(pid):
        raise ValueError("id del gruppo: minuscole, cifre e trattini")
    if not nome or "/" in nome or nome.startswith("."):
        raise ValueError("nome del gruppo non valido")
    # 30/09/2026 (l'utente): «Nuovo gruppo» parte dalla cartella. Senza `spazio` nasce uno spazio nuovo (come
    # Azienda Due) con la cartella dentro; il capogruppo si crea solo se `crea_capogruppo` è vero, gli agenti
    # si aggiungono dopo dalla lavagna.
    nuovo_spazio = not dati.get("spazio")
    if nuovo_spazio:
        if any(x["id"] == pid for x in spazi.carica()):
            raise ValueError(f"l'id {pid} è già usato da uno spazio")
        sp = {"id": pid, "nome": nome}
    else:
        sp = next((x for x in spazi.carica() if x["id"] == dati.get("spazio")), None)
        if not sp:
            raise ValueError("spazio sconosciuto")
    if any(p["id"] == pid for x in spazi.carica() for p in x["progetti"]):
        raise ValueError(f"l'id {pid} è già usato")
    # 02/10/2026 (l'utente): ogni gruppo nasce con il suo CEO, col nome del progetto; il CEO legge la cartella e crea la squadra
    crea_capo = True
    capo = str(dati.get("capogruppo") or f"ceo-{pid}").strip()
    if crea_capo and not NOME_AGENTE.fullmatch(capo):
        raise ValueError("nome del capogruppo: minuscole, cifre e trattini")
    cartella_esistente = str(dati.get("cartella_esistente") or "").strip()
    base = str(dati.get("cartella_base") or "").strip()
    scelta = str(dati.get("cartella") or "").strip()     # ramo windows (29/09/2026): percorso intero scelto con Sfoglia
    if scelta:
        radice = None
    elif sys.platform == "win32" and not base and nuovo_spazio:
        raise ValueError("scegli la cartella del progetto (Sfoglia): il gruppo si collega a una cartella già sul PC")
    else:
        radice = _radice_spazio(sp, base) if (base or not nuovo_spazio) else spazi.percorso("OD/Jarvis Brain/Progetti")
    if scelta:
        cartella = Path(scelta).expanduser()
        if not cartella.is_absolute() or not cartella.is_dir():
            raise ValueError("la cartella del progetto deve essere un percorso assoluto già esistente")
        cartella = cartella.resolve()
        for x in spazi.carica():               # una cartella non si collega due volte
            for p in x["progetti"]:
                if _stessa_cartella(p, cartella):
                    raise ValueError(f"questa cartella è già collegata a «{p.get('nome') or p['id']}» (spazio {x['nome']})")
    elif cartella_esistente == "@base":          # il gruppo è la cartella di riferimento stessa
        cartella = radice
    elif cartella_esistente:
        if "/" in cartella_esistente or "\\" in cartella_esistente or cartella_esistente.startswith("."):
            raise ValueError("cartella non valida")
        cartella = radice / cartella_esistente
        if not cartella.is_dir():
            raise ValueError(f"la cartella «{cartella_esistente}» non esiste in {radice}")
    else:
        cartella = radice / nome
    if cartella.exists() and not cartella.is_dir():
        raise ValueError(f"{cartella} esiste ed è un file")
    try:                                        # dentro OneDrive si scrive «OD/…», altrove il percorso intero
        cartella_rel = "OD/" + cartella.resolve().relative_to(spazi.OD.resolve()).as_posix()
    except ValueError:
        cartella_rel = str(cartella)
    if sys.platform == "win32":     # ramo windows: Jarvis Brain è la memoria dell'utente, qui mai; la memoria sta nel progetto
        memoria = cartella / ".claude" / "memoria"
    else:
        memoria = spazi.OD / "Jarvis Brain" / "Memoria" / _cartella_spazio(sp) / nome
    agenti_dir = cartella / ".claude" / "agents"
    if crea_capo and ((agenti_dir / f"{capo}.md").exists() or (agenti_dir / "_archivio" / f"{capo}.md").exists()):
        raise ValueError(f"{capo} esiste già in {cartella}")
    # 27/09/2026: modello e umorismo si controllano PRIMA di scrivere spazi.json; prima un valore
    # sbagliato lasciava la voce del gruppo senza capogruppo
    if (dati.get("model") or "sonnet") not in spazi.MODELLI:
        raise ValueError("modello: haiku, sonnet o opus")
    campi_come_parla({"umorismo": dati.get("umorismo"), "serieta": dati.get("serieta")})
    with AGENTI_LOCK:
        agenti_dir.mkdir(parents=True, exist_ok=True)
        memoria.mkdir(parents=True, exist_ok=True)
        if nuovo_spazio and sys.platform != "win32":
            ora = datetime.now().strftime("%Y-%m-%d %H:%M")
            pagina = spazi.OD / "Jarvis Brain" / "Memoria" / nome / f"{nome}.md"
            if not pagina.exists():
                pagina.write_text(f"---\ntitolo: {nome}\ntipo: spazio\naggiornato: {ora}\n---\n\n# {nome}\n\n"
                                  f"Spazio creato dalla lavagna del Command Center il {ora}. Cartella: `{cartella}`. "
                                  f"Da fare: [[Da fare]].\n", encoding="utf-8")
            (spazi.OD / "Jarvis Brain" / "Memoria" / nome / "Report").mkdir(parents=True, exist_ok=True)
        if not (memoria / "Da fare.md").exists():
            ora = datetime.now().strftime("%Y-%m-%d %H:%M")
            (memoria / "Da fare.md").write_text(f"---\ntitolo: Da fare · {nome}\ntipo: da-fare\naggiornato: {ora}\n---\n\n"
                                                f"# Da fare · {nome}\n\nCreato dalla lavagna del Command Center il {ora}. "
                                                f"Collegato a [[{sp['nome']}]].\n", encoding="utf-8")
        d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
        voce = {"id": pid, "nome": nome, "cartella": cartella_rel, "sezioni_memoria": [f"{_cartella_spazio(sp)}/{nome}"]}
        if sys.platform == "win32":     # ramo windows: niente sezioni in Jarvis Brain, la memoria propria è nel progetto
            voce["sezioni_memoria"] = []
            voce["memoria_propria"] = [str(memoria)]
        if crea_capo:
            voce["capogruppo"] = capo
        if nuovo_spazio and sys.platform == "win32":
            d["spazi"].append({"id": pid, "nome": nome, "memoria": str(memoria / "Da fare.md"),
                               "report": str(memoria / "Report"), "progetti": [voce]})
        elif nuovo_spazio:
            d["spazi"].append({"id": pid, "nome": nome, "memoria": f"OD/Jarvis Brain/Memoria/{nome}/{nome}.md",
                               "report": f"OD/Jarvis Brain/Memoria/{nome}/Report", "progetti": [voce]})
        else:
            next(x for x in d["spazi"] if x["id"] == sp["id"])["progetti"].append(voce)
        spazi.salva(d)
    # il capogruppo (se richiesto) nasce dal modello, come ogni agente, senza nessuno sopra
    try:
        if crea_capo: azione_agente({"cosa": "crea", "progetto": pid, "nome": capo, "capogruppo": "",
                       "description": dati.get("description") or f"Capogruppo di {nome}: distribuisce il lavoro ai "
                                                                   "suoi specialisti, lo verifica e riferisce a Jarvis.",
                       "model": dati.get("model") or "sonnet", "tono": dati.get("tono"),
                       "umorismo": dati.get("umorismo"), "serieta": dati.get("serieta"), "ceo": True})
    except Exception:
        # 27/09/2026: capogruppo non creato → la voce esce da spazi.json (cartelle e «Da fare» restano)
        with AGENTI_LOCK:
            d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
            for x in d["spazi"]:
                x["progetti"] = [p for p in x["progetti"] if p["id"] != pid]
            if nuovo_spazio:
                d["spazi"] = [x for x in d["spazi"] if x["id"] != pid]
            spazi.salva(d)
        tocca("spazi")
        raise
    registra_modifica("gruppo", pid, capo)
    try:
        _pannello_gruppo_nasce(pid)
    except Exception as e:  # noqa: BLE001
        evento(f"gruppo {nome}: la lavagna non si è aggiornata da sola ({e})")
    if crea_capo and dati.get("squadra_ceo", True):
        try:
            crea_squadra(pid)
        except ValueError as e:
            evento(f"squadra di {nome} non avviata: {e}")
    evento(f"gruppo nuovo: {nome} in {sp['nome']}, " + (f"capogruppo {capo}" if crea_capo else "cartella collegata, senza agenti"))
    tocca("spazi")
    progetto = next(p for x in elenco_spazi() for p in x["progetti"] if p["id"] == pid)
    return {"messaggio": f"gruppo {nome} creato", "progetto": progetto}


# ---------------------------------------------------------------- tombe e squadra del CEO (2026-10-02)
# l'utente: «quando cancello o tolgo un gruppo o un agente dalla lavagna non va rimesso». Ogni agente tolto o eliminato
# lascia una tomba (progetto → nomi). Il CEO che compone la squadra, l'aggiornamento della catena e ogni
# creazione automatica la rispettano; solo un «Nuovo agente» fatto a mano dall'utente (azione crea) la cancella.
TOMBE_FILE = QUI / "agenti-tolti.json"          # fuori da git, come gruppi-archiviati.json
SQUADRA_STATO = {}                              # progetto -> {"stato": "in corso"|"fatta"|"errore", "messaggio", "creati"}


def leggi_tombe():
    return leggi_json(TOMBE_FILE, {})


def segna_tomba(pid, nome):
    t = leggi_tombe()
    if nome not in t.setdefault(pid, []):
        t[pid].append(nome)
    if not TOMBE_FILE.exists():
        TOMBE_FILE.write_text("{}")
    scrivi_atomico(TOMBE_FILE, json.dumps(t, ensure_ascii=False, indent=1))


def togli_tomba(pid, nome):
    t = leggi_tombe()
    if nome in t.get(pid, []):
        t[pid].remove(nome)
        scrivi_atomico(TOMBE_FILE, json.dumps(t, ensure_ascii=False, indent=1))


def _json_dalla_risposta(testo):
    """Il primo array JSON di oggetti dentro la risposta del CEO (anche in un blocco ```)."""
    for m in re.finditer(r"\[\s*\{", testo):
        prof = 0
        for i in range(m.start(), len(testo)):
            prof += {"[": 1, "]": -1}.get(testo[i], 0)
            if prof == 0:
                try:
                    return json.loads(testo[m.start():i + 1])
                except ValueError:
                    break
    raise ValueError("il CEO non ha risposto con un elenco JSON di agenti")


def crea_squadra(pid):
    """Il CEO del gruppo legge la cartella del progetto e propone i suoi sottoagenti; il server li valida e li
    crea con l'azione «crea» di sempre (stesso modello, stesse regole). Parte in sottofondo: la lavagna si
    aggiorna da sola a ogni agente creato. Decisione dell'utente del 2026-10-02: «assegno solo il CEO, lui legge
    le cartelle e crea i sotto agenti; poi io modifico, aggiungo o tolgo»."""
    _, p = _progetto(pid)
    capo = p.get("capogruppo")
    if not capo or not (Path(p["cartella"]) / ".claude" / "agents" / f"{capo}.md").exists():
        raise ValueError("questo gruppo non ha un capogruppo: crealo prima")
    if SQUADRA_STATO.get(pid, {}).get("stato") == "in corso":
        raise ValueError("il CEO sta già componendo la squadra")
    SQUADRA_STATO[pid] = {"stato": "in corso", "messaggio": f"{capo} legge la cartella", "creati": []}
    threading.Thread(target=_squadra_in_sottofondo, args=(pid,), daemon=True).start()
    evento(f"{capo} legge {p['nome']} per comporre la squadra")
    tocca("spazi")
    return {"messaggio": f"{capo} sta leggendo la cartella: gli agenti compaiono sulla lavagna man mano"}


def _digest_cartella(cart, max_file=160):
    """Esplorazione deterministica della cartella di un progetto per il CEO: albero (profondità 3), conteggio per tipo,
    README/CLAUDE.md e l'inizio dei file principali. Il CEO decide sui fatti che gli diamo qui; il server poi controlla
    che i file citati esistano. (Il CEO da solo non esplorava: rispondeva in un turno senza leggere.)"""
    ignora = {".git", "node_modules", ".venv", "venv", "__pycache__", "_archivio", ".DS_Store", "dist", "build", ".next"}
    files = []
    for dirpath, dirs, nomi in os.walk(cart):
        dirs[:] = sorted(d for d in dirs if d not in ignora and not d.startswith("_archivio") and d != "agents")
        prof = len(Path(dirpath).relative_to(cart).parts)
        if prof >= 4:
            dirs[:] = []
            continue
        for n in sorted(nomi):
            if n in ignora or n.endswith((".pyc", ".log")):
                continue
            f = Path(dirpath) / n
            try:
                files.append((str(f.relative_to(cart)), f.stat().st_size))
            except OSError:
                pass
    tipi = {}
    for rel, _ in files:
        e = Path(rel).suffix.lower() or "(senza estensione)"
        tipi[e] = tipi.get(e, 0) + 1
    chiave = [r for r, _ in files if Path(r).name.lower() in ("readme.md", "claude.md", "agents.md", "package.json", "pyproject.toml", "requirements.txt")]
    principali = sorted((x for x in files if Path(x[0]).suffix in (".py", ".js", ".ts", ".php", ".md", ".sql", ".sh") and x[0] not in chiave),
                        key=lambda x: (len(Path(x[0]).parts), -x[1]))[:6]
    righe = [f"Tipi di file: " + ", ".join(f"{k} ×{v}" for k, v in sorted(tipi.items(), key=lambda x: -x[1])[:12]),
             f"File ({min(len(files), max_file)} di {len(files)}):"]
    righe += [f"- {r} ({sz} byte)" for r, sz in files[:max_file]]
    for r in chiave[:4] + [x[0] for x in principali]:
        try:
            testo = (cart / r).read_text(encoding="utf-8", errors="ignore")[:2500 if r in chiave else 1200]
        except OSError:
            continue
        righe += ["", f"=== {r} (inizio) ===", testo]
    return "\n".join(righe), {r for r, _ in files}


def _squadra_in_sottofondo(pid):
    st = SQUADRA_STATO[pid]
    try:
        _, p = _progetto(pid)
        capo = p["capogruppo"]
        cart = Path(p["cartella"])
        esistenti = sorted(a["nome"] for a in spazi.profili(p["cartella"], capo))
        tombe = leggi_tombe().get(pid, [])
        sunto, reali = _digest_cartella(cart)
        base = (
            f"Sei {capo}, capogruppo del progetto «{p['nome']}». La cartella è {p['cartella']}.\n"
            "Qui sotto trovi l'esplorazione della cartella fatta dal sistema (file e contenuti veri). Studiala e componi la squadra di specialisti "
            "che questo progetto richiede DAVVERO: ogni agente deve avere un compito che si vede nei file (cosa c'è, cosa manca, cosa va verificato). "
            "Niente ruoli generici di riempimento.\n"
            f"Agenti già presenti (non riproporli): {', '.join(esistenti) or 'nessuno'}.\n"
            f"Agenti che l'utente ha tolto di proposito (MAI riproporli): {', '.join(tombe) or 'nessuno'}.\n"
            "Regole: da 2 a 8 specialisti; nome in minuscolo con trattini e legato al dominio del progetto; modello haiku per comandi già scritti, "
            "sonnet per ricerca, analisi, testi e verifica, opus SOLO per chi programma. Un revisore indipendente che verifica il lavoro degli altri è quasi sempre utile.\n"
            "Se gli agenti già presenti coprono già tutto quello che serve, rispondi con l'elenco vuoto [] (niente agenti di riempimento). "
            "Rispondi SOLO con un elenco JSON, senza altro testo: "
            '[{"nome":"...","description":"quando usarlo, 1-2 frasi","model":"sonnet","tools":"Read, Grep, Glob","prove":["percorso/relativo/di/un/file/dell-elenco"]}]. '
            "«prove» = da 1 a 3 percorsi presi DALL'ELENCO dei file qui sotto che giustificano l'agente. «tools» è facoltativo (vuoto = tutti).\n\n"
            "=== ESPLORAZIONE DELLA CARTELLA ===\n" + sunto
        )
        proposta, errore = None, ""
        for tentativo in (1, 2):
            richiesta = base if tentativo == 1 else (base + f"\n\nIl tentativo precedente non era valido ({errore}). Esplora la cartella con gli strumenti e rispondi col solo JSON.")
            cmd = ["claude", "-p", richiesta, "--agent", capo, "--output-format", "json", "--max-turns", "12",
                   "--tools", "Read,Glob,Grep", "--allowedTools", "Read", "Glob", "Grep"]
            st["messaggio"] = f"{capo} legge la cartella (tentativo {tentativo})"
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=p["cartella"], env=ENV)
            if r.returncode != 0:
                errore = (r.stderr or r.stdout or "claude non ha risposto")[:160]
                continue
            risposta = json.loads(r.stdout).get("result", "")
            try:
                if re.fullmatch(r"\s*(```(?:json)?)?\s*\[\s*\]\s*(```)?\s*", risposta):
                    proposta = []
                    break
                proposta = _json_dalla_risposta(risposta)[:8]
                break
            except ValueError:
                errore = "risposta senza JSON: " + risposta[:120].replace("\n", " ")
        if proposta is None:
            raise ValueError(errore)
        scartati = []
        for a in proposta:
            nome = str(a.get("nome") or "").strip()
            if nome in leggi_tombe().get(pid, []):
                continue
            # prova dei fatti: almeno un file citato deve esistere davvero nella cartella (il CEO non può inventare il ruolo)
            prove = [x.lstrip("/") for x in (a.get("prove") or []) if isinstance(x, str) and (x.lstrip("/") in reali or (cart / x.lstrip("/")).exists())]
            if not prove:
                scartati.append(nome)
                continue
            modello = a.get("model") if a.get("model") in spazi.MODELLI else "sonnet"
            if modello == "opus" and not re.search(r"programm|codice|sviluppo|refactor|bug", str(a.get("description")), re.I):
                modello = "sonnet"            # regola dell'utente: opus solo programmazione
            try:
                azione_agente({"cosa": "crea", "progetto": pid, "nome": nome, "capogruppo": capo, "da": "lavagna",
                               "description": f"{a.get('description')} (motivo: {', '.join(prove)})", "model": modello, "tools": a.get("tools") or ""})
                st["creati"].append(nome)
                st["messaggio"] = f"creati {len(st['creati'])} agenti"
            except ValueError as e:
                evento(f"squadra {p['nome']}: {nome} saltato ({e})")
        if scartati:
            evento(f"squadra {p['nome']}: scartati senza prova nei file: {', '.join(scartati)}")
        st["stato"] = "fatta"
        st["messaggio"] = f"{capo} ha creato {len(st['creati'])} agenti: " + ", ".join(st["creati"]) + (f" · scartati senza prova: {', '.join(scartati)}" if scartati else "")
        if st["creati"]:
            try:
                st["allineamento"] = allinea_progetto(pid)
                st["messaggio"] += " · progetto allineato (" + ", ".join(x["passo"] for x in st["allineamento"] if x["ok"]) + ")"
            except Exception as e:  # noqa: BLE001
                st["allineamento"] = [{"passo": "allineamento", "ok": False, "dettaglio": str(e)[:140]}]
    except Exception as e:  # noqa: BLE001
        st["stato"] = "errore"
        st["messaggio"] = str(e)[:240]
    evento(f"squadra {pid}: {st['messaggio']}")
    tocca("spazi")


# ---------------------------------------------------------------- controllo della lavagna e allineamento del progetto nuovo (2026-10-02)
# l'utente: «una guida dentro ogni operazione, così capiamo se sbaglio io o sbagliate voi; poi l'aggiornamento a Jarvis che
# allinea memoria, progetti e agenti». lavagna_verifica() dice cosa non torna e DI CHI è il problema; allinea_progetto()
# è il passo dopo la squadra del CEO.
STRUMENTI_JARVIS = Path(__file__).resolve().parents[1] / "strumenti"


def lavagna_verifica():
    problemi, controllati = [], {"progetti": 0, "agenti": 0}

    def p(livello, dove, cosa, di_chi, rimedio):
        problemi.append({"livello": livello, "dove": dove, "cosa": cosa, "di_chi": di_chi, "rimedio": rimedio})

    tombe = leggi_tombe()
    tutti = set()
    elenco = spazi.carica()
    per_progetto = {}
    for s_ in elenco:
        for pr in s_["progetti"]:
            if pr["esiste"]:
                profili = spazi.profili(pr["cartella"], pr.get("capogruppo"))
                per_progetto[pr["id"]] = profili
                tutti |= {a["nome"] for a in profili}
    for s_ in elenco:
        if not Path(s_["report"]).is_dir():
            p("avviso", s_["nome"], f"la cartella dei report non esiste: {s_['report']}", "lavagna/spazi.json",
              "si crea da sola alla prima missione; se è un errore di percorso correggi `report` in spazi.json")
        for pr in s_["progetti"]:
            controllati["progetti"] += 1
            dove = f"{s_['nome']} › {pr['nome']}"
            if not pr["esiste"]:
                p("errore", dove, "la cartella del progetto non esiste", "lavagna", "ricollega la cartella dalla scheda del gruppo o togli il gruppo")
                continue
            profili = per_progetto.get(pr["id"], [])
            nomi = {a["nome"] for a in profili}
            capo = pr.get("capogruppo")
            di_jarvis = bool(s_.get("sistema"))     # «Agenti di casa» e «Memoria dell'utente» sono di Jarvis: a capo c'è lui (l'utente, 02/10/2026)
            if di_jarvis:
                pass
            elif not capo:
                p("avviso", dove, "il gruppo non ha un CEO: nessuno orchestra e verifica", "L'utente (scelta)", "«＋ Nuovo agente» con capogruppo, oppure rifai il gruppo: nasce sempre col CEO")
            elif capo and capo not in nomi:
                p("errore", dove, f"il CEO {capo} non ha il profilo in .claude/agents", "lavagna/profili", f"crea {capo} da «＋ Nuovo agente»")
            elif len(nomi) == 1:
                p("avviso", dove, "il CEO è solo: la squadra non è stata composta", "CEO / Jarvis",
                  "scheda del gruppo → «Il CEO compone la squadra dalla cartella»")
            for a in profili:
                controllati["agenti"] += 1
                if a["nome"] in tombe.get(pr["id"], []):
                    p("errore", f"{dove} › {a['nome']}", "è un agente tolto dall'utente ma il profilo c'è di nuovo", "chi l'ha ricreato (missione o CEO)",
                      "«Elimina» di nuovo: la tomba resta e il CEO non lo riproporrà")
                if a.get("riporta_a") and a["riporta_a"] not in nomi and a["riporta_a"] != "jarvis":
                    p("avviso", f"{dove} › {a['nome']}", f"riporta a {a['riporta_a']}, che non c'è in questo progetto", "profilo", "correggi «riporta_a» nella scheda dell'agente")
                for c in a["comunica"]:
                    if c not in tutti:
                        p("avviso", f"{dove} › {a['nome']}", f"«comunica con» {c}, che non esiste", "profilo/lavagna", "togli il filo o ricrea l'agente; «Allinea» sistema i fili")
            for sez in pr.get("sezioni_memoria") or []:
                if sez.count("/") == 1 and not (spazi.OD / "Jarvis Brain" / "Memoria" / sez / "Stato.md").exists():
                    p("avviso", dove, f"manca lo Stato in Memoria/{sez}", "Jarvis (memoria)", "parte da solo ogni 30 minuti, oppure `python3 ~/Jarvis/strumenti/stato_vault.py`")
    # schede della lavagna che puntano ad agenti spariti
    chiavi = {f"{pid}:{a['nome']}" for pid, ag in per_progetto.items() for a in ag}
    pannello = leggi_pannello()
    vivi = {s_["id"] for s_ in elenco}
    gruppi_menu = {str(g.get("id")) for g in pannello.get("gruppi") or [] if isinstance(g, dict)}
    for nome_lav, L in (pannello.get("lavagne") or {}).items():
        if nome_lav.startswith("demo"):
            continue
        # 02/10/2026 (audit menu): lavagna di un gruppo che non c'è più (spazio uscito, gruppo personalizzato tolto)
        orfana = ((nome_lav.startswith("spazio-") and nome_lav[7:] not in vivi)
                  or (nome_lav.startswith("g-") and nome_lav not in gruppi_menu))
        if orfana:
            p("avviso", f"lavagna «{nome_lav}»", f"è la lavagna di un gruppo che non c'è più ({len(L.get('nodi') or [])} schede)",
              "lavagna (dato rimasto da prima del 02/10)", "menu a sinistra: «Togli» sulla riga 👻 in fondo ai gruppi (nessun file si tocca), oppure «Elimina definitivamente» del gruppo in «Gruppi archiviati»")
            continue
        morte = [n for n in (L.get("nodi") or []) if n.get("tipo") == "agente" and n.get("agente") not in chiavi]
        if morte:
            p("avviso", f"lavagna «{nome_lav}»", f"{len(morte)} schede puntano ad agenti che non esistono più", "lavagna",
              "si ripuliscono da sole all'apertura della pagina (pulisciSchedeOrfane) o con «Tutta la catena»")
    for g in pannello.get("gruppi") or []:
        gid = str((g or {}).get("id") or "")
        if gid.startswith("spazio-") and gid[7:] not in vivi:
            p("avviso", f"menu › {g.get('nome') or gid}", f"gruppo fantasma: lo spazio «{gid[7:]}» non c'è più in spazi.json",
              "lavagna (dato rimasto da prima del 02/10)", "menu a sinistra: «Togli» sulla riga 👻 in fondo ai gruppi (toglie voce e lavagna; nessun file si tocca)")
    # gruppi archiviati che non si possono più ripristinare
    arch = leggi_json(GRUPPI_ARCHIVIO, {})
    for pid, a in (arch.items() if isinstance(arch, dict) else []):
        if not isinstance(a, dict):
            continue
        nome = (a.get("voce") or {}).get("nome") or pid
        if a.get("archivio") and not (Path(a["archivio"]) / "agents").is_dir():
            p("avviso", f"Gruppi archiviati › {nome}", f"l'archivio degli agenti non c'è più ({Path(a['archivio']).name}): il ripristino non è possibile",
              "chi ha spostato o cancellato la cartella _archivio", "«Elimina definitivamente» toglie la voce (la cartella del progetto resta)")
        elif a.get("spazio") not in vivi and not _spazio_voce_di(arch, a):
            p("avviso", f"Gruppi archiviati › {nome}", f"lo spazio «{a.get('spazio')}» non c'è più e nessun archiviato ne ha la voce",
              "dato vecchio (prima del 02/10)", "ricrea lo spazio con «＋ Nuovo gruppo», poi «Ripristina»; oppure «Elimina definitivamente»")
    return {"quando": datetime.now().strftime("%Y-%m-%d %H:%M"), "controllati": controllati, "problemi": problemi,
            "in_ordine": not any(x["livello"] == "errore" for x in problemi)}


def allinea_progetto(pid):
    """Dopo la squadra del CEO: cartellini, Stato e Guida del progetto, profili che leggono lo Stato, poi la
    missione «Aggiorna ultime modifiche» (Jarvis fa rileggere e allineare gli agenti nuovi)."""
    spazio, pr = _progetto(pid)
    passi = []
    for nome, cmd in (("cartellini delle note", ["python3", str(STRUMENTI_JARVIS / "vault_cartellini.py"), "--applica"]),
                      ("Stato e Guida del progetto", ["python3", str(STRUMENTI_JARVIS / "stato_vault.py")]),
                      ("profili: leggono lo Stato", ["python3", str(STRUMENTI_JARVIS / "agenti_leggono_stato.py"), "--applica"])):
        c, out = sh(cmd, timeout=180)
        passi.append({"passo": nome, "ok": c == 0, "dettaglio": (out.strip().splitlines() or [""])[0][:140]})
    try:
        r = aggiorna_catena(spazio["id"], "ultime")
        passi.append({"passo": "Jarvis: aggiorna le ultime modifiche (missione)", "ok": True, "dettaglio": r.get("messaggio", "")})
    except ValueError as e:
        passi.append({"passo": "Jarvis: aggiorna le ultime modifiche (missione)", "ok": False, "dettaglio": str(e)[:140]})
    return passi


def _stessa_cartella(voce, cartella):
    """La voce di spazi.json (grezza) punta a questa cartella?"""
    c = spazi.percorso(voce.get("cartella"))
    return bool(c) and c.resolve() == Path(cartella).resolve()


def togli_gruppo(pid):
    """Toglie un progetto dalla lavagna: .claude/agents va in <progetto>/_archivio-AAAAMMGG-HHMM/ e la voce
    esce da spazi.json (tenuta in gruppi-archiviati.json per ripristinarla). La cartella del progetto e la
    memoria non si toccano."""
    with AGENTI_LOCK:
        d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
        sp, voce = next(((x, p) for x in d["spazi"] for p in x["progetti"] if p["id"] == pid), (None, None))
        if not voce:
            raise ValueError("progetto sconosciuto")
        cartella = spazi.percorso(voce["cartella"])
        if cartella and (cartella.resolve() == Path(AGENTE).resolve()
                         or Path(AGENTE).resolve() in cartella.resolve().parents):
            raise ValueError("questa è la cartella di Jarvis stesso (o sta dentro): i suoi agenti non si archiviano da qui")
        agenti_dir = cartella / ".claude" / "agents"
        archivio = cartella / f"_archivio-{datetime.now():%Y%m%d-%H%M%S}"
        # 27/09/2026: più progetti possono condividere la cartella (utente, azioni, app-github in
        # Patrimonio). Se un altro la usa ancora, esce solo la voce: gli agenti restano dove sono.
        condivisa = any(p["id"] != pid and _stessa_cartella(p, cartella) for x in d["spazi"] for p in x["progetti"])
        if agenti_dir.is_dir() and not condivisa:
            archivio.mkdir()
            agenti_dir.rename(archivio / "agents")
        sp["progetti"] = [p for p in sp["progetti"] if p["id"] != pid]
        # 30/09/2026 (l'utente): togliere l'ultimo progetto di uno spazio toglie anche lo spazio, se no restava
        # un gruppo vuoto in barra e sulla lavagna. Lo spazio si ricorda per il ripristino.
        spazio_tolto = None
        if not sp["progetti"] and not sp.get("sistema"):
            spazio_tolto = {k: v for k, v in sp.items() if k != "progetti"}
            d["spazi"] = [x for x in d["spazi"] if x["id"] != sp["id"]]
        spazi.salva(d)
        arch = leggi_json(GRUPPI_ARCHIVIO, {})
        arch[pid] = {"spazio": sp["id"], "voce": voce, "archivio": str(archivio) if archivio.exists() else "",
                     "condivisa": condivisa, "ts": time.time(), **({"spazio_voce": spazio_tolto} if spazio_tolto else {})}
        if not GRUPPI_ARCHIVIO.exists():
            GRUPPI_ARCHIVIO.write_text("{}")
        scrivi_atomico(GRUPPI_ARCHIVIO, json.dumps(arch, ensure_ascii=False, indent=1))
    registra_modifica("gruppo", pid, voce.get("capogruppo") or "")
    dove = "cartella condivisa: agenti lasciati al loro posto" if condivisa else f"agenti in {archivio.name}"
    evento(f"gruppo {voce['nome']} tolto dalla lavagna ({dove})")
    # 02/10/2026 (audit menu, P4): il gruppo esce anche da pannello.json, così menu e lavagna non divergono
    try:
        _pulisci_pannello_gruppo(pid, voce.get("nome") or pid, sp.get("nome", ""), sp["id"] if spazio_tolto else "")
    except Exception as e:  # noqa: BLE001
        evento(f"gruppo {voce.get('nome')} tolto, ma la lavagna non si è ripulita: {e}")
    tocca("spazi")
    return {"messaggio": f"gruppo {voce['nome']} tolto", "archivio": str(archivio) if archivio.exists() else "",
            "condivisa": condivisa}


def _pulisci_pannello_gruppo(pid, nome, spazio_nome="", spazio_tolto=""):
    """02/10/2026 (audit menu, P4): il gruppo tolto esce anche da pannello.json: schede dei suoi agenti e
    note-cartella in tutte le lavagne (non demo), le sue chiavi nei gruppi del menu e, se è uscito lo spazio,
    il gruppo spazio-<id> e la sua lavagna. Prima restavano per sempre (gruppo fantasma senza tasto per toglierlo).
    Vero se ha scritto qualcosa."""
    pref = f"{pid}:"
    note = {nome, f"📁 {nome}", f"📁 {nome} · nessun agente ancora", f"{nome} · senza capogruppo"}
    if spazio_nome:
        note.add(f"📁 {spazio_nome} · {nome}")
        if spazio_tolto:
            note.add(spazio_nome)
    with PANNELLO_LOCK:
        if not PANNELLO_FILE.exists():
            return False
        attuale = leggi_pannello()
        d = json.loads(json.dumps(attuale))
        cambiato = False
        for k, L in (d.get("lavagne") or {}).items():
            if str(k).startswith("demo") or not isinstance(L, dict):
                continue
            via = {n.get("id") for n in L.get("nodi") or [] if isinstance(n, dict) and (
                (n.get("tipo") == "agente" and str(n.get("agente", "")).startswith(pref))
                or (n.get("tipo") == "nota" and n.get("testo") in note))}
            if via:
                L["nodi"] = [n for n in L["nodi"] if n.get("id") not in via]
                L["fili"] = [f for f in L.get("fili") or [] if f.get("da") not in via and f.get("a") not in via]
                cambiato = True
        for g in d.get("gruppi") or []:
            prima = len(g.get("agenti") or [])
            g["agenti"] = [a for a in g.get("agenti") or [] if not str(a).startswith(pref)]
            cambiato |= len(g["agenti"]) != prima
        if spazio_tolto:
            gid = f"spazio-{spazio_tolto}"
            n = len(d.get("gruppi") or [])
            d["gruppi"] = [g for g in d.get("gruppi") or [] if g.get("id") != gid]
            cambiato |= len(d["gruppi"]) != n
            cambiato |= (d.get("lavagne") or {}).pop(gid, None) is not None
        if not cambiato:
            return False
        _scrivi_pannello_sotto_lock(pulisci_pannello(d), attuale)
    tocca("pannello")
    return True


def _pannello_gruppo_nasce(pid):
    """Un gruppo nuovo (creato da qualunque scheda, dall'API o da un CEO) compare da solo sulla lavagna generale:
    la scheda «📁 cartella» collegata a Jarvis e, sotto, il suo capogruppo. Posto libero: in fondo alla riga delle
    cartelle. «Tutta la catena» lo risistema nella piramide completa."""
    spazio, pr = _progetto(pid)
    capo = pr.get("capogruppo")
    etichetta = "📁 " + ((f"{spazio['nome']} · {pr['nome']}") if len(spazio.get("progetti") or []) > 1 and spazio["nome"] != pr["nome"] else pr["nome"])
    with PANNELLO_LOCK:
        if not PANNELLO_FILE.exists():
            return False
        attuale = leggi_pannello()
        d = json.loads(json.dumps(attuale))
        L = (d.get("lavagne") or {}).get("generale")
        if not isinstance(L, dict):
            return False
        nodi = L.setdefault("nodi", [])
        cartelle = [n for n in nodi if isinstance(n, dict) and n.get("tipo") == "nota" and str(n.get("testo", "")).startswith("📁 ")]
        if any(n.get("testo") == etichetta for n in cartelle):
            return False
        if cartelle:
            y = min(n.get("y", 0) for n in cartelle)
            x = max(n.get("x", 0) for n in cartelle) + 240
        else:
            y, x = 220, 0
        nota = {"id": "n" + secrets.token_hex(5), "tipo": "nota", "agente": "", "testo": etichetta, "x": x, "y": y}
        nodi.append(nota)
        jarvis = next((n for n in nodi if isinstance(n, dict) and n.get("tipo") == "nota" and str(n.get("testo", "")).lower().startswith("jarvis")), None)
        fili = L.setdefault("fili", [])
        if jarvis:
            fili.append({"da": jarvis["id"], "a": nota["id"]})
        if capo and any(a["nome"] == capo for a in spazi.profili(pr["cartella"], capo)):
            ceo = {"id": "n" + secrets.token_hex(5), "tipo": "agente", "agente": f"{pid}:{capo}", "x": x, "y": y + 110}
            nodi.append(ceo)
            fili.append({"da": nota["id"], "a": ceo["id"]})
        _scrivi_pannello_sotto_lock(pulisci_pannello(d), attuale)
    tocca("pannello")
    return True


def _riporta_a_di(pr, nome):
    for a in spazi.profili(pr["cartella"], pr.get("capogruppo")):
        if a["nome"] == nome:
            return a.get("riporta_a") or pr.get("capogruppo") or ""
    return pr.get("capogruppo") or ""


def _pannello_agente_nasce(pid, nome, capo="", progetto_nome="", spazio_nome=""):
    """02/10/2026 (l'utente: lavagna e menu devono essere collegati in tempo reale, chiunque crei l'agente): l'agente
    nuovo compare da solo sulle lavagne che hanno già la scheda del suo capo (la generale e quella del suo spazio),
    sotto di lui e collegato, come fa «＋ Nuovo agente». Chi l'ha tolto a mano con «Solo la scheda» non c'entra:
    questa funzione parte solo da crea e ripristina."""
    chiave = f"{pid}:{nome}"
    capo_k = f"{pid}:{capo}" if capo else ""
    with PANNELLO_LOCK:
        if not PANNELLO_FILE.exists():
            return False
        attuale = leggi_pannello()
        d = json.loads(json.dumps(attuale))
        cambiato = False
        for k, L in (d.get("lavagne") or {}).items():
            if str(k).startswith("demo") or not isinstance(L, dict):
                continue
            nodi = L.setdefault("nodi", [])
            if any(isinstance(n, dict) and n.get("tipo") == "agente" and n.get("agente") == chiave for n in nodi):
                continue
            nc = next((n for n in nodi if isinstance(n, dict) and n.get("tipo") == "agente" and n.get("agente") == capo_k), None) if capo_k else None
            if not nc and progetto_nome:           # è il capogruppo: sta sotto la scheda «📁 cartella» del suo progetto
                etichette = {f"📁 {progetto_nome}", f"📁 {progetto_nome} · nessun agente ancora", f"{progetto_nome} · senza capogruppo"}
                if spazio_nome:
                    etichette.add(f"📁 {spazio_nome} · {progetto_nome}")
                nc = next((n for n in nodi if isinstance(n, dict) and n.get("tipo") == "nota" and n.get("testo") in etichette), None)
            if not nc:
                continue
            x = nc.get("x", 0)
            sotto = [n.get("y", 0) for n in nodi if isinstance(n, dict) and abs(n.get("x", 0) - x) < 10 and n.get("y", 0) > nc.get("y", 0)]
            y = max([nc.get("y", 0) + 100] + [v + 70 for v in sotto])
            nuovo = {"id": "n" + secrets.token_hex(5), "tipo": "agente", "agente": chiave, "x": x, "y": y}
            nodi.append(nuovo)
            L.setdefault("fili", []).append({"da": nc["id"], "a": nuovo["id"]})
            cambiato = True
        if not cambiato:
            return False
        _scrivi_pannello_sotto_lock(pulisci_pannello(d), attuale)
    tocca("pannello")
    return True


def _pannello_agente_esce(pid, nome):
    """Un agente tolto o eliminato esce da TUTTE le lavagne e dai gruppi del menu, con i suoi fili: lo fa il server,
    così lo vedono anche le altre schede del browser (prima toccava alla pagina che aveva premuto il tasto)."""
    chiave = f"{pid}:{nome}"
    with PANNELLO_LOCK:
        if not PANNELLO_FILE.exists():
            return False
        attuale = leggi_pannello()
        d = json.loads(json.dumps(attuale))
        cambiato = False
        for k, L in (d.get("lavagne") or {}).items():
            if str(k).startswith("demo") or not isinstance(L, dict):
                continue
            via = {n.get("id") for n in L.get("nodi") or [] if isinstance(n, dict) and n.get("tipo") == "agente" and n.get("agente") == chiave}
            if via:
                L["nodi"] = [n for n in L["nodi"] if n.get("id") not in via]
                L["fili"] = [f for f in L.get("fili") or [] if f.get("da") not in via and f.get("a") not in via]
                cambiato = True
        for g in d.get("gruppi") or []:
            prima = len(g.get("agenti") or [])
            g["agenti"] = [a for a in g.get("agenti") or [] if a != chiave]
            cambiato |= len(g["agenti"]) != prima
        if not cambiato:
            return False
        _scrivi_pannello_sotto_lock(pulisci_pannello(d), attuale)
    tocca("pannello")
    return True


def _spazio_voce_di(arch, a):
    """La voce dello spazio da ricreare per il ripristino: quella del gruppo o, se l'ha un altro gruppo archiviato
    dello stesso spazio, la sua (audit menu, P9: prima solo il gruppo uscito per ultimo si poteva ripristinare)."""
    return a.get("spazio_voce") or next((v["spazio_voce"] for v in arch.values()
                                         if isinstance(v, dict) and v.get("spazio") == a.get("spazio") and v.get("spazio_voce")), None)


def _archivio_del_gruppo(a):
    """La cartella _archivio-… del gruppo, solo se è davvero quella scritta da togli_gruppo; None se non c'è
    (o se il gruppo non ne aveva una). Se c'è ma non è dove la mette «Togli gruppo»: ValueError, non si tocca."""
    if not a.get("archivio"):
        return None
    ar = Path(a["archivio"])
    if not ar.exists() and not ar.is_symlink():
        return None
    cartella = spazi.percorso(a["voce"]["cartella"])
    if (ar.is_symlink() or not ar.is_dir() or not re.fullmatch(r"_archivio-\d{8}-\d{4,6}", ar.name)
            or not cartella or ar.parent.resolve() != cartella.resolve()):
        raise ValueError(f"l'archivio {ar} non è dove lo mette «Togli gruppo»: non lo tocco")
    return ar


def anteprima_elimina_gruppo(pid):
    """Cosa sparisce e cosa resta se si elimina definitivamente un gruppo archiviato (sola lettura)."""
    a = leggi_json(GRUPPI_ARCHIVIO, {}).get(pid)
    if not a:
        raise ValueError("questo gruppo non è nell'archivio")
    ar = _archivio_del_gruppo(a)
    file = sorted(str(f.relative_to(ar)) for f in ar.rglob("*") if f.is_file()) if ar else []
    cartella = spazi.percorso(a["voce"]["cartella"])
    return {"progetto": pid, "nome": a["voce"].get("nome") or pid, "archivio": str(ar) if ar else "",
            "archivio_mancante": bool(a.get("archivio")) and not ar, "file": file,
            "tombe": leggi_tombe().get(pid, []),
            "restano": [str(cartella).replace(str(HOME), "~")]
                       + [f"Memoria/{s}" for s in a["voce"].get("sezioni_memoria") or []]}


def elimina_gruppo(pid, conferma):
    """02/10/2026 (l'utente): un gruppo archiviato si cancella. La cartella _archivio-… va nel Cestino del Mac
    (~/.Trash, solo os.rename: mai rmtree; definitivo per il Command Center, recuperabile a mano dal Cestino).
    Sparisce: la voce in gruppi-archiviati.json, le tombe del progetto, le schede rimaste sulla lavagna.
    Restano: la cartella del progetto e i suoi file, la memoria nel vault, i report, modifiche-agenti.jsonl."""
    with AGENTI_LOCK:
        arch = leggi_json(GRUPPI_ARCHIVIO, {})
        a = arch.get(pid)
        if not a:
            raise ValueError("questo gruppo non è nell'archivio")
        nome = a["voce"].get("nome") or pid
        if str(conferma or "").strip() != nome:
            raise ValueError(f"per eliminare scrivi esattamente il nome del gruppo: {nome}")
        ar = _archivio_del_gruppo(a)
        cestinato = ""
        if ar and sys.platform == "win32":
            # ramo windows: esce dall'elenco, la cartella _archivio-… resta sul disco e si recupera a mano
            ar = None
        if ar:
            cestino = HOME / ".Trash"
            if not cestino.is_dir() and sys.platform.startswith("linux"):
                cestino.mkdir(mode=0o700)     # 2026-10-05: sulla VPS il «Cestino» è /root/.Trash, si svuota a mano
            if not cestino.is_dir():
                raise ValueError(f"non trovo il Cestino del Mac ({cestino}): non cancello niente")
            dest = cestino / f"{Path(str(spazi.percorso(a['voce']['cartella']))).name} {ar.name}"
            if dest.exists():
                dest = dest.with_name(f"{dest.name}-{int(time.time())}")
            try:
                os.rename(ar, dest)           # stesso volume: uno spostamento, niente copia e niente rmtree
            except OSError as e:
                # 02/10/2026: dentro OneDrive (File Provider) il rename verso ~/.Trash dà «Resource deadlock avoided»:
                # lo fa Finder, che è il modo giusto di mettere una cartella nel Cestino e la lascia recuperabile.
                # Se anche Finder non riesce, non si cancella niente.
                c_f, out_f = sh(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{ar}" as alias)'], timeout=60)
                if c_f != 0 or ar.exists():
                    raise ValueError(f"non riesco a mettere {ar.name} nel Cestino ({e.strerror}; Finder: {out_f.strip()[:100]}): non cancello niente") from None
                dest = Path("Cestino (Finder)")
            cestinato = str(dest)
        if a.get("spazio_voce"):              # chi resta archiviato nello stesso spazio eredita la voce dello spazio
            erede = next((v for k, v in arch.items() if k != pid and isinstance(v, dict) and v.get("spazio") == a.get("spazio")), None)
            if erede is not None and not erede.get("spazio_voce"):
                erede["spazio_voce"] = a["spazio_voce"]
        arch.pop(pid)
        scrivi_atomico(GRUPPI_ARCHIVIO, json.dumps(arch, ensure_ascii=False, indent=1))
        t = leggi_tombe()
        if t.pop(pid, None) is not None:
            scrivi_atomico(TOMBE_FILE, json.dumps(t, ensure_ascii=False, indent=1))
        vivi = {x["id"] for x in json.loads(spazi.FILE.read_text(encoding="utf-8")).get("spazi", [])} if spazi.FILE.exists() else set()
    sv = _spazio_voce_di(arch, a) or a.get("spazio_voce") or {}
    try:                                       # le schede rimaste da prima del 02/10 (gruppo fantasma, lavagna orfana)
        _pulisci_pannello_gruppo(pid, nome, sv.get("nome", ""), a.get("spazio") if a.get("spazio") not in vivi else "")
    except Exception as e:  # noqa: BLE001
        evento(f"gruppo {nome} eliminato, ma la lavagna non si è ripulita: {e}")
    evento(f"gruppo archiviato {nome} eliminato" + (f" (archivio nel Cestino: {Path(cestinato).name})" if cestinato else ""))
    tocca("spazi")
    return {"messaggio": f"gruppo {nome} eliminato" + (": l'archivio degli agenti è nel Cestino del Mac" if cestinato else ""),
            "cestino": cestinato}


def ripristina_gruppo(pid):
    with AGENTI_LOCK:
        arch = leggi_json(GRUPPI_ARCHIVIO, {})
        a = arch.get(pid)
        if not a:
            raise ValueError("questo gruppo non è nell'archivio")
        # 02/10/2026 (audit menu, P9): archivio sparito = errore chiaro PRIMA di toccare qualunque cosa
        if a.get("archivio") and not (Path(a["archivio"]) / "agents").is_dir():
            raise ValueError(f"l'archivio degli agenti non c'è più ({Path(a['archivio']).name}): "
                             "non si può ripristinare, usa «Elimina definitivamente»")
        d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
        if any(p["id"] == pid for x in d["spazi"] for p in x["progetti"]):
            raise ValueError(f"l'id {pid} è di nuovo in uso")
        sp = next((x for x in d["spazi"] if x["id"] == a["spazio"]), None)
        voce_spazio = _spazio_voce_di(arch, a)
        if not sp and voce_spazio:                 # lo spazio era uscito insieme al suo ultimo gruppo
            sp = {**voce_spazio, "progetti": []}
            d["spazi"].append(sp)
        if not sp:
            raise ValueError("lo spazio del gruppo non c'è più e nessun gruppo archiviato ne ha la voce: ricrealo con «＋ Nuovo gruppo»")
        # 27/09/2026: se nel frattempo un altro progetto usa la stessa cartella (es. «metatrader» su
        # Progetto B) non si sovrappone niente, salvo che il gruppo fosse già in condivisione quando è uscito
        cartella = spazi.percorso(a["voce"]["cartella"]).resolve()
        altro = next(((x, p) for x in d["spazi"] for p in x["progetti"] if _stessa_cartella(p, cartella)), None)
        if altro and not a.get("condivisa"):
            raise ValueError(f"la cartella {cartella.name} ora è di «{altro[1].get('nome') or altro[1]['id']}» "
                             f"({altro[1]['id']}, spazio {altro[0].get('nome') or altro[0]['id']}): non ripristino "
                             f"{a['voce'].get('nome') or pid} sopra i suoi agenti. Togli prima quel gruppo o "
                             "sposta la cartella.")
        agenti_dir = spazi.percorso(a["voce"]["cartella"]) / ".claude" / "agents"
        if a.get("archivio"):
            if agenti_dir.exists():
                raise ValueError(f"{agenti_dir} esiste già: non la sovrascrivo")
            (Path(a["archivio"]) / "agents").rename(agenti_dir)
            try:
                Path(a["archivio"]).rmdir()
            except OSError:
                pass
        sp["progetti"].append(a["voce"])
        spazi.salva(d)
        arch.pop(pid)
        scrivi_atomico(GRUPPI_ARCHIVIO, json.dumps(arch, ensure_ascii=False, indent=1))
    registra_modifica("gruppo", pid, a["voce"].get("capogruppo") or "")
    evento(f"gruppo {a['voce']['nome']} ripristinato")
    tocca("spazi")
    return {"messaggio": f"gruppo {a['voce']['nome']} ripristinato"}


def _cambia_capogruppo_voce(pid, nome, togli):
    """02/10/2026 (audit menu, D16). Chi chiama tiene AGENTI_LOCK.
    togli=True: il capogruppo è stato tolto o eliminato → «capogruppo» esce dalla voce di spazi.json (prima restava
    e «Controlla lavagna» dava errore «il CEO non ha il profilo»); il nome si ricorda in «capogruppo_tolto».
    togli=False: ripristino dell'agente → se era lui il capogruppo tolto, torna capogruppo."""
    if not spazi.FILE.exists():
        return
    d = json.loads(spazi.FILE.read_text(encoding="utf-8"))
    voce = next((p for x in d.get("spazi", []) for p in x.get("progetti", []) if p.get("id") == pid), None)
    if not voce:
        return
    if togli and voce.get("capogruppo") == nome:
        voce.pop("capogruppo", None)
        voce["capogruppo_tolto"] = nome
    elif not togli and voce.get("capogruppo_tolto") == nome and not voce.get("capogruppo"):
        voce["capogruppo"] = nome
        voce.pop("capogruppo_tolto", None)
    else:
        return
    spazi.salva(d)


def azione_agente(dati):
    cosa = dati.get("cosa")
    if cosa == "crea_gruppo":
        return crea_gruppo(dati)
    if cosa == "crea_squadra":
        return crea_squadra(dati.get("progetto"))
    if cosa == "rinomina_spazio":
        return rinomina_spazio(dati.get("spazio"), dati.get("nome"))
    if cosa == "togli_gruppo":
        return togli_gruppo(dati.get("progetto"))
    if cosa == "ripristina_gruppo":
        return ripristina_gruppo(dati.get("progetto"))
    if cosa == "anteprima_elimina_gruppo":
        return anteprima_elimina_gruppo(dati.get("progetto"))
    if cosa == "elimina_gruppo":
        return elimina_gruppo(dati.get("progetto"), dati.get("conferma"))
    if cosa == "aggiorna_catena":
        return aggiorna_catena(dati.get("spazio") or "tutti", dati.get("ambito"))
    if cosa == "allinea":
        return allinea(dati.get("lavagna") or "generale", dati.get("verso"))
    if cosa == "salva_casa":
        return scrivi_nota_di_casa(str(dati.get("nome") or ""), dati)
    spazio, p = _progetto(dati.get("progetto"))
    nome = str(dati.get("nome") or "").strip()
    if not NOME_AGENTE.fullmatch(nome):
        raise ValueError("nome dell'agente: minuscole, cifre e trattini (es. sito-seo)")
    cartella = Path(p["cartella"]) / ".claude" / "agents"
    file, archivio = cartella / f"{nome}.md", cartella / "_archivio" / f"{nome}.md"
    with AGENTI_LOCK:
        if cosa == "crea":
            if file.exists() or archivio.exists():
                raise ValueError(f"{nome} esiste già" + (" (in _archivio: ripristinalo)" if archivio.exists() else ""))
            descrizione = " ".join(str(dati.get("description") or "").split())[:600]
            if not descrizione:
                raise ValueError("scrivi la descrizione: dice a Jarvis quando usarlo")
            modello = dati.get("model") or "sonnet"
            if modello not in spazi.MODELLI:
                raise ValueError("modello: haiku, sonnet o opus")
            come = campi_come_parla({"tono": dati.get("tono") or "diretto, ironico ma misurato",
                                     "umorismo": 1 if dati.get("umorismo") is None else dati.get("umorismo"),
                                     "serieta": 2 if dati.get("serieta") is None else dati.get("serieta")})
            # «capogruppo» può essere qualunque agente del progetto (terzo livello); "" = nessuno sopra
            capo = str(dati["capogruppo"] if "capogruppo" in dati else p.get("capogruppo") or "").strip()
            if capo == nome:
                capo = ""
            strumenti = " ".join(str(dati.get("tools") or "").split())
            testo = MODELLO_AGENTE.read_text(encoding="utf-8").format(
                name=nome, description=descrizione, description_yaml=spazi.valore_yaml(descrizione), model=modello,
                tools=f" {strumenti}" if strumenti else "", tono=come["tono"], tono_yaml=spazi.valore_yaml(come["tono"]),
                umorismo=come["umorismo"], serieta=come["serieta"], capogruppo=capo or "nessuno", progetto=p["nome"],
                memoria=spazio["memoria"].replace(str(HOME), "~"), creato=datetime.now().strftime("%Y-%m-%d %H:%M"))
            testo = spazi.con_come_parla(testo)      # il blocco «Come parli» (serietà, umorismo, tono) dai campi del profilo
            if dati.get("ceo"):                      # il capogruppo di un gruppo nuovo: orchestratore con goal, squadra e verifica
                sez = (QUI / "modelli" / "ceo-sezione.md").read_text(encoding="utf-8").format(
                    progetto=p["nome"], cartella=p["cartella"].replace(str(HOME), "~"))
                marcatore = "<!-- comunica-con:inizio"
                testo = testo.replace(marcatore, sez.lstrip("\n") + "\n" + marcatore, 1) if marcatore in testo else testo + sez
            if not capo:
                testo = aggiorna_comunica_con(testo, [])
                testo, _ = spazi.aggiorna_frontmatter(testo, {"comunica": "", "riporta_a": ""})
            elif not (cartella / f"{capo}.md").exists():
                raise ValueError(f"{capo} non è un agente di {p['nome']}")
            cartella.mkdir(parents=True, exist_ok=True)
            file.write_text(testo, encoding="utf-8")
            togli_tomba(p["id"], nome)       # l'utente lo ha chiesto a mano: la tomba non vale più
            if capo:
                capo_file = cartella / f"{capo}.md"
                if capo_file.exists():
                    _cambia_comunica(capo_file, aggiungi=[nome])
            msg = f"agente {nome} creato in {p['nome']}" + (f", collegato a {capo}" if capo else "")
        elif cosa == "togli":
            if not file.exists():
                raise ValueError(f"{nome} non c'è in {p['nome']}")
            archivio.parent.mkdir(exist_ok=True)
            if archivio.exists():      # un archivio vecchio con lo stesso nome non si perde
                archivio.rename(archivio.with_name(f"{nome}.{datetime.now():%Y%m%d-%H%M%S}.md"))
            for _, a in _tutti_profili():
                if nome in a["comunica"] and a["file"] != str(file):
                    _cambia_comunica(a["file"], togli=[nome])
            file.rename(archivio)
            segna_tomba(p["id"], nome)
            msg = f"agente {nome} tolto da {p['nome']} (è in .claude/agents/_archivio/)"
            if nome == p.get("capogruppo"):
                _cambia_capogruppo_voce(p["id"], nome, togli=True)
                msg += " · il gruppo resta senza capogruppo"
        elif cosa == "elimina":
            # 30/09/2026 (l'utente): «se lo cancello deve essere cancellato». Come «togli», più la copia in
            # _archivio: il profilo non esiste più da nessuna parte (i backup a parte restano).
            if not file.exists():
                raise ValueError(f"{nome} non c'è in {p['nome']}")
            for _, a in _tutti_profili():
                if nome in a["comunica"] and a["file"] != str(file):
                    _cambia_comunica(a["file"], togli=[nome])
            file.unlink()
            if archivio.exists():
                archivio.unlink()
            segna_tomba(p["id"], nome)
            msg = f"agente {nome} eliminato da {p['nome']} (profilo cancellato)"
            if nome == p.get("capogruppo"):
                _cambia_capogruppo_voce(p["id"], nome, togli=True)
                msg += " · il gruppo resta senza capogruppo"
        elif cosa == "ripristina":
            if file.exists():
                raise ValueError(f"{nome} c'è già in {p['nome']}")
            if not archivio.exists():
                raise ValueError(f"{nome} non è nell'archivio di {p['nome']}")
            archivio.rename(file)
            togli_tomba(p["id"], nome)
            _cambia_capogruppo_voce(p["id"], nome, togli=False)   # se era il capogruppo tolto, torna capogruppo
            campi, corpo = spazi.frontmatter(file.read_text(encoding="utf-8"))
            for altro in spazi.comunica_di(campi, corpo):   # i suoi colleghi tornano a conoscerlo
                altro_file = cartella / f"{altro}.md"
                if altro_file.exists():
                    _cambia_comunica(altro_file, aggiungi=[nome])
            msg = f"agente {nome} ripristinato in {p['nome']}"
        elif cosa == "elimina_archiviato":
            # ramo windows (02/10/2026): via dall'elenco degli archiviati; il profilo non si cancella,
            # va in _archivio/_eliminati/ (si recupera a mano). La tomba resta: il CEO non lo ripropone.
            if not archivio.exists():
                raise ValueError(f"{nome} non è nell'archivio di {p['nome']}")
            cestino = archivio.parent / "_eliminati"
            cestino.mkdir(exist_ok=True)
            archivio.rename(cestino / f"{nome}.{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}.md")
            segna_tomba(p["id"], nome)
            msg = f"agente {nome} eliminato dall'archivio di {p['nome']} (copia in _archivio/_eliminati/)"
        elif cosa == "attivo":
            if not file.exists():
                raise ValueError(f"{nome} non c'è in {p['nome']}")
            prima = file.read_text(encoding="utf-8")
            nuovo, _ = spazi.aggiorna_frontmatter(prima, campi_come_parla({"attivo": bool(dati.get("valore"))}))
            if nuovo != prima:
                scrivi_atomico(file, nuovo)
            msg = f"agente {nome} " + ("attivo" if dati.get("valore") else "spento: le missioni non lo lanciano")
        else:
            raise ValueError("agente: cosa = crea|togli|elimina|elimina_archiviato|ripristina|attivo|allinea|aggiorna_catena|crea_gruppo|"
                             "togli_gruppo|ripristina_gruppo|anteprima_elimina_gruppo|elimina_gruppo")
    try:                                   # lavagna e menu in tempo reale, chiunque agisca (02/10/2026)
        if cosa in ("crea", "ripristina"):
            _pannello_agente_nasce(p["id"], nome, capo if cosa == "crea" else _riporta_a_di(p, nome),
                                   p.get("nome", ""), spazio.get("nome", ""))
        elif cosa in ("togli", "elimina"):
            _pannello_agente_esce(p["id"], nome)
    except Exception as e:  # noqa: BLE001
        evento(f"agente {nome}: la lavagna non si è aggiornata da sola ({e})")
    registra_modifica(cosa, p["id"], nome, con=[capo] if cosa == "crea" else [],
                      da=dati.get("da") if dati.get("da") in ("lavagna", "scheda", "catena") else "lavagna")
    evento(msg)
    tocca("spazi")
    return {"messaggio": msg, "spazi": elenco_spazi()}


def _fili_agenti(lavagna):
    """{(chiave a, chiave b)} dei fili fra due schede agente di una lavagna, e le schede."""
    lav = (leggi_pannello().get("lavagne") or {}).get(lavagna)
    if lav is None:
        raise ValueError(f"lavagna sconosciuta: {lavagna}")
    nodi = {n["id"]: n for n in lav.get("nodi") or [] if n.get("tipo") == "agente" and n.get("agente")}
    fili = {(nodi[f["da"]]["agente"], nodi[f["a"]]["agente"]) for f in lav.get("fili") or []
            if f.get("da") in nodi and f.get("a") in nodi}
    return lav, nodi, fili


def allineamento(lavagna):
    """I fili agente→agente della lavagna contro le sezioni «Comunica con» dei profili.
    Un filo vale nei due versi (la pagina scrive il nome a tutte e due le schede). Una coppia
    conta una volta sola anche se il problema si vede da tutti e due i lati: 30/09/2026, l'utente ha
    trovato «18 differenze» sempre uguali e sembravano troppe — erano 13 coppie reali, 5 contate
    due volte (una per ogni profilo che nomina l'altro senza filo, es. azd-gestionale↔azd-partner)."""
    _, nodi, fili = _fili_agenti(lavagna)
    profili = dict(_tutti_profili())
    chiavi = {n["agente"] for n in nodi.values()} & set(profili)
    per_nome = {}
    for k in chiavi:
        per_nome.setdefault(k.split(":", 1)[1], set()).add(k)
    collegati = {(a, b) for a, b in fili} | {(b, a) for a, b in fili}
    viste, differenze = set(), []
    for a in sorted(chiavi):
        nomi = set(profili[a]["comunica"])
        for x, b in sorted(collegati):
            # 27/09/2026: il filo è a posto se ALMENO UNO dei due profili nomina l'altro (stessa regola
            # di allinea verso «lavagna»); prima serviva che lo nominassero tutti e due e il badge
            # non tornava mai «allineati».
            if x == a and b in chiavi and b.split(":", 1)[1] not in nomi \
                    and a.split(":", 1)[1] not in profili[b]["comunica"] and frozenset((a, b)) not in viste:
                viste.add(frozenset((a, b)))
                differenze.append({"tipo": "filo-senza-profilo", "da": a, "a": b})
        for nome in sorted(nomi):
            for b in sorted(per_nome.get(nome, ())):
                if b != a and (a, b) not in collegati and frozenset((a, b)) not in viste:
                    viste.add(frozenset((a, b)))
                    differenze.append({"tipo": "profilo-senza-filo", "da": a, "a": b})
    return {"lavagna": lavagna, "differenze": differenze, "allineata": not differenze}


def allinea(lavagna, verso):
    if verso not in ("profili", "lavagna"):
        raise ValueError("allinea: verso = profili|lavagna")
    diff = allineamento(lavagna)["differenze"]
    if not diff:
        return {"messaggio": "lavagna e profili dicono già la stessa cosa", "cambiati": 0}
    profili = dict(_tutti_profili())
    if verso == "profili":
        # ogni profilo sulla lavagna: i nomi dei fili, più quelli che la lavagna non mostra (agenti non in scheda)
        lav, nodi, fili = _fili_agenti(lavagna)
        sulla = {n["agente"] for n in nodi.values()}
        cambiati = 0
        with AGENTI_LOCK:
            for a in sorted(sulla & set(profili)):
                dai_fili = [b.split(":", 1)[1] for x, b in sorted(fili | {(b, a2) for a2, b in fili}) if x == a]
                fuori = [n for n in profili[a]["comunica"]
                         if not any(k.split(":", 1)[1] == n for k in sulla)]
                nomi = list(dict.fromkeys(dai_fili + fuori))
                if nomi != profili[a]["comunica"]:
                    _scrivi_comunica(profili[a]["file"], nomi)
                    cambiati += 1
                    diversi = sorted(set(nomi) ^ set(profili[a]["comunica"]))
                    registra_modifica("comunica", a.split(":", 1)[0], a.split(":", 1)[1], con=diversi)
        msg = f"profili allineati alla lavagna «{lavagna}»: {cambiati} cambiati"
    else:
        d = leggi_pannello()
        lav = d["lavagne"][lavagna]
        per_chiave = {}
        for n in lav.get("nodi") or []:
            if n.get("tipo") == "agente" and n.get("agente"):
                per_chiave.setdefault(n["agente"], n["id"])
        fili = list(lav.get("fili") or [])
        esistenti = {(f["da"], f["a"]) for f in fili} | {(f["a"], f["da"]) for f in fili}
        cambiati = 0
        toccati = []           # 27/09/2026: nel registro solo le differenze che hanno cambiato un filo
        for x in diff:
            ida, ia = per_chiave.get(x["da"]), per_chiave.get(x["a"])
            if not ida or not ia:
                continue
            if x["tipo"] == "profilo-senza-filo" and (ida, ia) not in esistenti:
                fili.append({"da": ida, "a": ia})
                esistenti |= {(ida, ia), (ia, ida)}
                cambiati += 1
                toccati.append(x)
            elif x["tipo"] == "filo-senza-profilo":
                # il filo resta solo se almeno uno dei due profili nomina l'altro
                nomina = x["a"].split(":", 1)[1] in profili[x["da"]]["comunica"] or \
                    x["da"].split(":", 1)[1] in profili[x["a"]]["comunica"]
                if not nomina:
                    prima = len(fili)
                    fili = [f for f in fili if {f["da"], f["a"]} != {ida, ia}]
                    if len(fili) != prima:
                        cambiati += prima - len(fili)
                        toccati.append(x)
        if cambiati:
            lav["fili"] = fili
            try:
                scrivi_pannello(d, versione=d.get("versione", 0))
            except PannelloVecchio:
                raise ValueError("la lavagna è cambiata proprio adesso: riprova l'allineamento") from None
        for x in toccati:
            registra_modifica("filo", x["da"].split(":", 1)[0], x["da"].split(":", 1)[1], con=[x["a"].split(":", 1)[1]])
        msg = f"lavagna «{lavagna}» allineata ai profili: {cambiati} fili cambiati"
    evento(msg)
    tocca("spazi")
    return {"messaggio": msg, "cambiati": cambiati, **allineamento(lavagna)}


def aggiorna_catena(spazio_id, ambito=None):
    """«Aggiorna agenti → Jarvis»: una missione per spazio, modalità lavoro, 5 in parallelo. L'obiettivo
    lungo (capogruppo → specialisti uno alla volta) lo aggiunge missione.py con genere «aggiorna_catena».
    ambito «ultime» (2026-09-26 19:10): solo gli agenti delle modifiche pendenti, col loro capogruppo."""
    stato_mod = modifiche_pendenti()
    if ambito not in ("tutti", "ultime"):
        ambito = "ultime" if stato_mod["pendenti"] else "tutti"
    if ambito == "ultime" and not stato_mod["pendenti"]:
        raise ValueError("nessuna modifica da aggiornare: usa «Aggiorna tutti»")
    scelti_spazi = [s_ for s_ in spazi.carica() if spazio_id in ("tutti", s_["id"])]
    if not scelti_spazi:
        raise ValueError("spazio sconosciuto")
    coinvolti = set(stato_mod["agenti_coinvolti"])
    missioni_ = []
    for s_ in scelti_spazi:
        viste = set()
        progetti = []
        for p in s_["progetti"]:
            if p["esiste"] and p.get("capogruppo") and p["cartella"] not in viste:
                viste.add(p["cartella"])
                progetti.append(p)
        if ambito == "ultime":
            progetti = [p for p in progetti if any(k.startswith(p["id"] + ":") for k in coinvolti)]
            if not progetti:
                continue
            ids = {p["id"] for p in progetti}
            solo = {}
            for p in progetti:
                nomi = {k.split(":", 1)[1] for k in coinvolti if k.startswith(p["id"] + ":")}
                profili_p = {a["nome"]: a for a in spazi.profili(p["cartella"], p.get("capogruppo"))}
                for n in list(nomi):       # ognuno col suo capogruppo e con chi gli sta sopra
                    if profili_p.get(n, {}).get("riporta_a"):
                        nomi.add(profili_p[n]["riporta_a"])
                if p.get("capogruppo"):    # 02/10/2026: dopo D16 un gruppo può restare senza capogruppo
                    nomi.add(p["capogruppo"])
                solo[p["id"]] = sorted(n for n in nomi if n in profili_p)
            modifiche = [r for r in stato_mod["pendenti"] if r.get("progetto") in ids]
            # 02/10/2026: niente voci su agenti che non esistono più (eliminati dall'utente): la missione le chiedeva a lui
            vivi = {(p["id"], a["nome"]) for p in progetti for a in spazi.profili(p["cartella"], p.get("capogruppo"))}
            modifiche = [r for r in modifiche if not r.get("agente") or (r.get("progetto"), r.get("agente")) in vivi or r.get("tipo") in ("gruppo",)]
            # e una sola missione «ultime» per spazio alla volta
            for d_ in (MISSIONI_DIR.iterdir() if MISSIONI_DIR.is_dir() else []):
                mm = leggi_json(d_ / "missione.json", {})
                if mm.get("genere") == "aggiorna_catena" and mm.get("ambito") == "ultime" and mm.get("spazio") == s_["id"] \
                        and leggi_missione(d_)["stato"] in ("in corso", "attende conferma", "in avvio"):
                    raise ValueError(f"c'è già una missione di aggiornamento in corso per «{s_['nome']}» ({d_.name}): aspetta che finisca")
            obiettivo = (f"Verifica le ultime modifiche agli agenti dello spazio «{s_['nome']}»: "
                         f"{len(modifiche)} modifiche, agenti coinvolti: "
                         + ", ".join(n for v in solo.values() for n in v) + ".")
            r = lancia_missione(s_, progetti, obiettivo, "lavoro", 5, genere="aggiorna_catena",
                                extra={"ambito": "ultime", "solo_agenti": solo, "modifiche": modifiche[-50:]})
            missioni_.append(r["missione"])
            continue
        if not progetti:
            continue
        obiettivo = ("Aggiorna la catena degli agenti dello spazio «" + s_["nome"] + "»: ogni capogruppo rilegge "
                     "il proprio profilo e quelli dei suoi specialisti, uno per uno, e li rende coerenti con la "
                     "memoria dello spazio, con «Comunica con» e con tono e umorismo.")
        r = lancia_missione(s_, progetti, obiettivo, "lavoro", 5, genere="aggiorna_catena")
        missioni_.append(r["missione"])
    if not missioni_:
        raise ValueError("nessun progetto con un capogruppo in questo spazio")
    evento(f"aggiorna catena ({ambito}): {len(missioni_)} missioni avviate ({spazio_id})")
    # 27/09/2026: «missione» (la prima) per la pagina che legge d.missione; «missioni» resta com'era
    return {"messaggio": f"aggiorno la catena ({ambito}): {len(missioni_)} missioni", "missioni": missioni_,
            "missione": missioni_[0], "ambito": ambito}


def scrivi_config_catena(ts):
    """L'ultimo aggiornamento della catena: da qui in poi le modifiche contano come pendenti."""
    if not CATENA_STATO.exists():
        CATENA_STATO.write_text("{}")
    d = leggi_json(CATENA_STATO, {})
    d["ultimo_aggiornamento_ts"] = ts
    scrivi_atomico(CATENA_STATO, json.dumps(d, ensure_ascii=False, indent=1))


def fine_catena():
    """A missione «aggiorna catena» chiusa: la mappa degli agenti nel vault si rifà e la pagina rilegge gli
    spazi. Una volta sola per missione (il segno è il file «mappa_fatta» nella sua cartella)."""
    for d in MISSIONI_DIR.iterdir() if MISSIONI_DIR.is_dir() else []:
        if not d.is_dir() or (d / "mappa_fatta").exists():
            continue
        if leggi_json(d / "missione.json", {}).get("genere") != "aggiorna_catena":
            continue
        if leggi_json(d / "stato.json", {}).get("stato") not in ("chiusa", "errore"):
            continue
        (d / "mappa_fatta").touch()
        conf_m = leggi_json(d / "missione.json", {})
        st_m = leggi_json(d / "stato.json", {})
        riepilogo = st_m.get("riepilogo") if isinstance(st_m.get("riepilogo"), dict) else {}
        riep = riepilogo.get("testo")
        for nome in riepilogo.get("corretti") or []:
            prog = next((p["id"] for p in conf_m.get("progetti") or []
                         if (Path(p["cartella"]) / ".claude" / "agents" / f"{nome}.md").exists()), "")
            registra_modifica("profilo", prog, nome, da="catena")
        # 27/09/2026: le pendenti si tagliano all'ora di PARTENZA della missione (quelle fatte mentre
        # girava non le ha viste) e solo se è chiusa davvero con il riepilogo; in errore restano pendenti
        if st_m.get("stato") == "chiusa" and riepilogo:
            try:
                partenza = datetime.strptime(d.name[:17], "%Y-%m-%d_%H%M%S").timestamp()
            except ValueError:
                partenza = None
            ultimo = leggi_json(CATENA_STATO, {}).get("ultimo_aggiornamento_ts") or 0
            if partenza and partenza > ultimo:
                scrivi_config_catena(partenza)
        tocca("modifiche")
        if riep:
            evento(f"aggiorna catena · {leggi_json(d / 'missione.json', {}).get('spazio_nome', d.name)}: {riep}")
        if PROVA:
            evento(f"aggiorna catena {d.name} chiusa (copia di prova: la mappa del vault non si rifà)")
        else:
            aggiorna_mappa_agenti()
            evento(f"aggiorna catena {d.name} chiusa: mappa degli agenti rifatta")
        tocca("spazi")


# ---------------------------------------------------------------- scadenze (2026-09-26)
# La pagina «Scadenze» (contratto, punto 9): tre fonti, solo le voci APERTE (l'utente: «tutto il
# vecchio chiuso va eliminato»). Nessun doppione: ogni voce vive nel suo file e si chiude lì.
#   azienda    = il registro di direzione del CRM (stessa selezione di sincro/controlla.py:
#               decisioni «proposta»/«in_corso», domande «aperta»), tutte, non solo entro 7 giorni;
#   personali = Memoria/Patrimonio/Scadenze personali.md, una casella per riga;
#   task      = le caselle di strumenti/task.py (oggi e i 3 giorni prima, come «task.py lista»).
OD = HOME / "OneDrive" if sys.platform == "win32" else HOME / "Library" / "CloudStorage" / "OneDrive"
# 2026-09-26: i due file si possono spostare da configurazione.json («registro_scadenze»,
# «scadenze_personali»), così il template su un'altra macchina non crea cartelle OneDrive finte.
# Senza le due chiavi restano i percorsi dell'utente di sempre; «registro_scadenze»: "" spegne la fonte.
REGISTRO_140 = _percorso(CFG.get("registro_scadenze", str(OD / "CRM Azienda Uno/Reports/Direzione/registro.json")),
                         QUI / "registro-scadenze-non-configurato.json")
SCADENZE_PERSONALI = _percorso(CFG.get("scadenze_personali", str(AGENTE / "Scadenze personali.md") if sys.platform == "win32"
                                       else "~/Library/CloudStorage/OneDrive/"
                                       "Jarvis Brain/Memoria/Patrimonio/Scadenze personali.md"),
                               AGENTE / "Scadenze personali.md")
TASK_PY = AGENTE / "strumenti" / "task.py"
SCADENZE_LOCK = threading.Lock()
# chiudere dal pannello: la decisione diventa «fatta», la domanda «superata» (stati già previsti dal
# registro); lo stato di prima resta in «stato_prima», così «riapri» lo rimette com'era
CHIUSA_REGISTRO = {"decisioni": "fatta", "domande": "superata"}
APERTA_REGISTRO = {"decisioni": ("proposta", "in_corso"), "domande": ("aperta",)}
RIGA_PERSONALE = re.compile(r"^- \[( |x)\] (\d{4}-\d{2}-\d{2})(?: → chiusa (\d{4}-\d{2}-\d{2} \d{2}:\d{2}))? · (.*)$")


_TASK_MOD = {}


def _task_mod():
    """task.py caricato una volta (lo usa anche il controllo dei file ogni 2 s)."""
    if "m" in _TASK_MOD:
        return _TASK_MOD["m"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_jarvis", TASK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _TASK_MOD["m"] = mod
    return mod


def _voce(fonte, id_, entro, testo, tipo="", chi="", eur=None, nota=""):
    giorni = None
    if entro:
        try:
            giorni = (date.fromisoformat(entro[:10]) - date.today()).days
        except ValueError:
            entro = None
    return {"id": id_, "entro": entro[:10] if entro else None, "testo": testo, "tipo": tipo, "chi": chi,
            "eur": eur, "scaduta": giorni is not None and giorni < 0, "giorni": giorni, "fonte": fonte, "nota": nota}


def _in_ordine(voci):
    # le scadute per prime, poi per data; quelle senza data in fondo
    return sorted(voci, key=lambda v: (not v["scaduta"], v["entro"] is None, v["entro"] or ""))


def scadenze_azienda():
    if not REGISTRO_140.exists():
        raise FileNotFoundError(f"registro delle scadenze assente: {REGISTRO_140} "
                                "(chiave «registro_scadenze» di configurazione.json)")
    r = json.loads(REGISTRO_140.read_text(encoding="utf-8"))
    voci = [_voce("azienda", d["id"], d.get("entro"), d.get("titolo", ""), "DEC", d.get("responsabile", ""),
                  d.get("beneficio_eur"), d.get("stato", ""))
            for d in r.get("decisioni", []) if d.get("stato") in APERTA_REGISTRO["decisioni"]]
    voci += [_voce("azienda", d["id"], d.get("entro"), d.get("domanda", ""), "DOM", d.get("chi_chiede", ""),
                   None, d.get("perche", ""))
             for d in r.get("domande", []) if d.get("stato") in APERTA_REGISTRO["domande"]]
    return _in_ordine(voci)


def _personali_testo():
    if not SCADENZE_PERSONALI.exists():
        SCADENZE_PERSONALI.parent.mkdir(parents=True, exist_ok=True)
        ora = datetime.now().strftime("%Y-%m-%d %H:%M")
        SCADENZE_PERSONALI.write_text(
            f"---\ntitolo: Scadenze personali\ntipo: scadenze\naggiornato: {ora}\n---\n\n# Scadenze personali\n\n"
            "Una scadenza per riga: `- [ ] AAAA-MM-GG · testo · fonte: <id gmail o «a mano»>`.\n"
            "Chiusa: `- [x] AAAA-MM-GG → chiusa AAAA-MM-GG HH:MM · testo …`; il Command Center mostra solo le aperte.\n"
            "La scrive il Command Center (pagina «Scadenze») o Jarvis; data e ora vengono dal sistema. "
            "Collegata a [[Memoria]].\n\n", encoding="utf-8")
    return SCADENZE_PERSONALI.read_text(encoding="utf-8")


def scadenze_personali():
    voci = []
    for riga in _personali_testo().splitlines():
        m = RIGA_PERSONALE.match(riga.strip())
        if m and m.group(1) == " ":
            corpo = m.group(4)
            fonte = re.search(r" · fonte: (.*)$", corpo)
            voci.append(_voce("personali", f"{m.group(2)} · {corpo}", m.group(2),
                              corpo[:fonte.start()] if fonte else corpo, nota=f"fonte: {fonte.group(1)}" if fonte else ""))
    return _in_ordine(voci)


def scadenze_task():
    t = _task_mod()
    voci = []
    for indietro in range(4):      # stessa finestra di «task.py lista»
        g = date.today() - timedelta(days=indietro)
        _, testo = t.apri(g)
        for riga in (testo or "").splitlines():
            m = re.match(r"- \[ \] (\d{2}:\d{2}) · (.*)", riga)
            if m:
                voci.append(_voce("task", f"{g.isoformat()} {m.group(1)} · {m.group(2)}", None, m.group(2),
                                  nota=f"aperta il {g.isoformat()} alle {m.group(1)}"))
    return voci


def scadenze():
    fuori = {"letto_ts": time.time(), "errori": {}}
    for nome, f in (("azienda", scadenze_azienda), ("personali", scadenze_personali), ("task", scadenze_task)):
        try:
            fuori[nome] = f()
        except Exception as e:  # noqa: BLE001  — una fonte rotta non spegne le altre due
            fuori[nome] = []
            fuori["errori"][nome] = f"{type(e).__name__}: {e}"[:300]
    return fuori


# Chi ha chiuso e perché (2026-09-26 sera, contratto punto 12). Il registro Azienda Uno lo tiene nella voce;
# le righe del diario e delle scadenze personali non hanno posto per il «perché», e cambiarne il formato
# cambierebbe gli id. Si tiene qui a parte: (fonte, id) -> {chiusa_da, perche, ts}. Solo per le chiuse dal pannello.
CHIUSE_FILE = QUI / "scadenze-chiuse.json"


def _chiuse_note():
    d = leggi_json(CHIUSE_FILE, {})
    return d if isinstance(d, dict) else {}


def _segna_chiusa(fonte, id_, chiusa_da, perche="", togli=False):
    d = _chiuse_note()
    chiave = f"{fonte}|{id_}"
    if togli:
        if d.pop(chiave, None) is None:
            return
    else:
        d[chiave] = {"chiusa_da": chiusa_da, "perche": perche, "ts": time.time()}
        limite = time.time() - 90 * 86400
        d = {k: v for k, v in d.items() if v.get("ts", 0) > limite}
    if not CHIUSE_FILE.exists():
        CHIUSE_FILE.write_text("{}")
    scrivi_atomico(CHIUSE_FILE, json.dumps(d, ensure_ascii=False, indent=1))


def scadenze_chiuse(giorni):
    """Le voci chiuse negli ultimi «giorni»: stesse voci delle aperte, più chiusa_ts, chiusa_da, perche.
    Registro: solo quelle chiuse dal pannello (le sole che «riapri» sa rimettere). Task: le note del diario
    di quei giorni. Personali: le [x] con la data di chiusura nel periodo."""
    limite = time.time() - giorni * 86400
    note = _chiuse_note()
    fuori = []

    def metti(v, ts, chi_default=""):
        n = note.get(f"{v['fonte']}|{v['id']}") or {}
        v.update(chiusa_ts=ts, chiusa_da=n.get("chiusa_da") or chi_default, perche=n.get("perche", ""))
        fuori.append(v)

    r = json.loads(REGISTRO_140.read_text(encoding="utf-8"))
    for sezione, tipo, campo, chi in (("decisioni", "DEC", "titolo", "responsabile"), ("domande", "DOM", "domanda", "chi_chiede")):
        for d in r.get(sezione, []):
            try:
                ts = datetime.strptime(d.get("chiusa") or "", "%Y-%m-%d %H:%M").timestamp()
            except ValueError:
                continue
            if ts >= limite:
                v = _voce("azienda", d["id"], d.get("entro"), d.get(campo, ""), tipo, d.get(chi, ""),
                          d.get("beneficio_eur"), d.get("stato", ""))
                metti(v, ts)
                v["chiusa_da"], v["perche"] = d.get("chiusa_da", ""), d.get("perche_chiusa", "") or v["perche"]
    for riga in _personali_testo().splitlines():
        m = RIGA_PERSONALE.match(riga.strip())
        if m and m.group(1) == "x" and m.group(3):
            ts = datetime.strptime(m.group(3), "%Y-%m-%d %H:%M").timestamp()
            if ts >= limite:
                corpo = m.group(4)
                fonte = re.search(r" · fonte: (.*)$", corpo)
                metti(_voce("personali", f"{m.group(2)} · {corpo}", m.group(2),
                            corpo[:fonte.start()] if fonte else corpo,
                            nota=f"fonte: {fonte.group(1)}" if fonte else ""), ts)
    t = _task_mod()
    for indietro in range(min(int(giorni), 90) + 1):
        g = date.today() - timedelta(days=indietro)
        _, testo = t.apri(g)
        for riga in (testo or "").splitlines():
            m = re.match(r"- \[x\] (\d{2}:\d{2}) → (\d{2}:\d{2}) · (.*)", riga)
            if m:
                ts = datetime.strptime(f"{g.isoformat()} {m.group(2)}", "%Y-%m-%d %H:%M").timestamp()
                metti(_voce("task", f"{g.isoformat()} {m.group(1)} · {m.group(3)}", None, m.group(3),
                            nota=f"aperta il {g.isoformat()} alle {m.group(1)}"), ts)
    return sorted(fuori, key=lambda v: v["chiusa_ts"], reverse=True)


def chiudi_molte(voci, perche):
    """Pulizia (contratto, punto 12): chiude più voci insieme. Una sola copia di sicurezza del registro per
    chiamata, e il registro si riscrive una volta sola. Una voce che non si chiude non ferma le altre."""
    perche = " ".join(str(perche or "").split())[:200]
    chi = "L'utente dal Command Center (pulizia)"
    if not isinstance(voci, list) or not voci:
        raise ValueError("chiudi_molte: serve l'elenco delle voci")
    chiuse, errori = 0, []
    azienda = [v for v in voci if isinstance(v, dict) and v.get("fonte") == "azienda"]
    with SCADENZE_LOCK:
        if azienda:
            r = json.loads(REGISTRO_140.read_text(encoding="utf-8"))
            indice = {d.get("id"): (sez, d) for sez in ("decisioni", "domande") for d in r.get(sez, [])}
            cambiate = 0
            ora = datetime.now().strftime("%Y-%m-%d %H:%M")
            for v in azienda:
                sez, d = indice.get(v.get("id"), (None, None))
                if not d:
                    errori.append(f"azienda {v.get('id')}: non trovata")
                elif d.get("stato") not in APERTA_REGISTRO[sez]:
                    errori.append(f"azienda {v.get('id')}: non è aperta (stato «{d.get('stato')}»)")
                else:
                    d.update(stato_prima=d.get("stato"), stato=CHIUSA_REGISTRO[sez], chiusa=ora, chiusa_da=chi,
                             perche_chiusa=perche)
                    cambiate += 1
            if cambiate:
                copia = REGISTRO_140.parent / f"registro.json.bak-{datetime.now():%Y%m%d-%H%M}"
                if not copia.exists():
                    shutil.copy2(REGISTRO_140, copia)
                scrivi_atomico(REGISTRO_140, json.dumps(r, ensure_ascii=False, indent=1))
                chiuse += cambiate
        for v in voci:
            if not isinstance(v, dict) or v.get("fonte") == "azienda":
                continue
            try:
                if v.get("fonte") == "personali":
                    _personali_cambia("chiudi", v.get("id"))
                elif v.get("fonte") == "task":
                    _task_cambia("chiudi", v.get("id"))
                else:
                    raise ValueError("fonte sconosciuta")
                _segna_chiusa(v["fonte"], v.get("id"), chi, perche)
                chiuse += 1
            except (ValueError, OSError) as e:
                errori.append(f"{v.get('fonte')} {str(v.get('id'))[:60]}: {e}")
    evento(f"scadenze · pulizia: {chiuse} chiuse" + (f", {len(errori)} non chiuse" if errori else "")
           + (f" ({perche[:60]})" if perche else ""))
    tocca("scadenze")
    return {"chiuse": chiuse, "errori": errori, "messaggio": f"{chiuse} voci chiuse"}


CONTROLLO_TETTO = 12000
CONTROLLO_TESTO = (
    "Controlla quali di queste scadenze aperte sono GIÀ FATTE o superate. Per il registro Azienda Uno usa il "
    "capogruppo ceo-ai e i suoi specialisti (report in Reports/Direzione/, dati in Odoo, note in Memoria/<spazio>/)"
    ", per le personali la posta (strumenti/posta.py) e Memoria/Patrimonio/, per le caselle il diario. "
    "Rispondi SOLO con un blocco ```json``` con [{\"fonte\":\"...\",\"id\":\"...\",\"perche\":\"<una riga con "
    "la prova>\"}] delle voci da chiudere, poi una riga per quelle su cui non sei sicuro.")


def testi_controllo(fonte):
    """I testi da mandare a Jarvis: l'elenco compatto delle voci aperte, al massimo 12000 caratteri
    ciascuno; se non ci stanno si spezza per fonte, e una fonte troppo lunga in più pezzi."""
    fonti = ("azienda", "personali", "task") if fonte == "tutte" else (fonte,)
    tutte = scadenze()
    tetto = CONTROLLO_TETTO - len(CONTROLLO_TESTO) - 80     # il tetto vale per il testo intero, istruzioni comprese
    pezzi, pezzo, lung = [], [], 0
    for f in fonti:
        if pezzo and fonte == "tutte" and lung + sum(len(json.dumps(v, ensure_ascii=False)) for v in tutte[f]) > tetto:
            pezzi.append(pezzo)            # la fonte non ci sta insieme alle altre: pezzo suo
            pezzo, lung = [], 0
        for v in tutte[f]:
            riga = json.dumps({"fonte": f, "id": v["id"], "entro": v["entro"], "tipo": v["tipo"],
                               "testo": _corto(v["testo"], 220), "chi": v["chi"], "eur": v["eur"]},
                              ensure_ascii=False, separators=(",", ":"))
            if pezzo and lung + len(riga) + 1 > tetto:
                pezzi.append(pezzo)
                pezzo, lung = [], 0
            pezzo.append(riga)
            lung += len(riga) + 1
    if pezzo:
        pezzi.append(pezzo)
    oggi = datetime.now().strftime("%Y-%m-%d %H:%M")
    n = len(pezzi)
    return [f"{CONTROLLO_TESTO}\n\nOggi è {oggi}. Voci aperte" + (f" (parte {i + 1} di {n})" if n > 1 else "")
            + ":\n" + "\n".join(p) for i, p in enumerate(pezzi)]


def controllo_scadenze(fonte):
    if fonte not in ("azienda", "personali", "task", "tutte"):
        raise ValueError("controllo: fonte = azienda|personali|task|tutte")
    testi = testi_controllo(fonte)
    if not testi:
        return {"messaggio": "nessuna voce aperta da controllare", "lavoro": None, "lavori": []}
    lavori = []
    for i, testo in enumerate(testi):
        titolo = f"Controllo scadenze ({fonte})" + (f" {i + 1}/{len(testi)}" if len(testi) > 1 else "")
        lavori.append(chiedi({"testo": testo, "sessione": str(uuid.uuid4())}, tipo="scadenze-controllo",
                             titolo=titolo)["lavoro"])
    evento(f"scadenze · controllo chiesto a Jarvis ({fonte}, {len(lavori)} lavori)")
    return {"lavoro": lavori[0], "lavori": lavori, "messaggio": f"controllo avviato: {len(lavori)} lavori"}


def _copia_registro_del_giorno():
    """Prima scrittura del giorno sul registro: copia di sicurezza accanto, registro.json.bak-AAAAMMGG-HHMM."""
    oggi = datetime.now().strftime("%Y%m%d")
    if not list(REGISTRO_140.parent.glob(f"registro.json.bak-{oggi}-*")):
        shutil.copy2(REGISTRO_140, REGISTRO_140.parent / f"registro.json.bak-{datetime.now():%Y%m%d-%H%M}")


def _registro_cambia(id_, chiudi):
    testo = REGISTRO_140.read_text(encoding="utf-8")
    r = json.loads(testo)
    for sezione in ("decisioni", "domande"):
        for d in r.get(sezione, []):
            if d.get("id") != id_:
                continue
            if chiudi:
                if d.get("stato") not in APERTA_REGISTRO[sezione]:
                    raise ValueError(f"{id_} non è aperta (stato «{d.get('stato')}»)")
                d.update(stato_prima=d.get("stato"), stato=CHIUSA_REGISTRO[sezione],
                         chiusa=datetime.now().strftime("%Y-%m-%d %H:%M"), chiusa_da="L'utente dal Command Center")
            else:
                if "chiusa" not in d:
                    raise ValueError(f"{id_} non è stata chiusa dal Command Center: si riapre dal registro")
                d["stato"] = d.pop("stato_prima", None) or APERTA_REGISTRO[sezione][0]
                d.pop("chiusa", None)
                d.pop("chiusa_da", None)
                d.pop("perche_chiusa", None)
                d["riaperta"] = datetime.now().strftime("%Y-%m-%d %H:%M") + " · l'utente dal Command Center"
            _copia_registro_del_giorno()
            # stesso formato del file (indent 1, accenti in chiaro, niente a capo finale): il diff resta piccolo
            scrivi_atomico(REGISTRO_140, json.dumps(r, ensure_ascii=False, indent=1))
            return d.get("titolo") or d.get("domanda") or id_
    raise ValueError(f"voce {id_} non trovata nel registro")


def _personali_cambia(cosa, id_=None, testo=None, entro=None):
    t = _personali_testo()
    ora = datetime.now().strftime("%Y-%m-%d %H:%M")
    righe = t.split("\n")
    if cosa == "aggiungi":
        testo = " ".join((testo or "").split())
        if not testo:
            raise ValueError("scrivi la scadenza")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entro or ""):
            raise ValueError("entro: una data AAAA-MM-GG")
        date.fromisoformat(entro)
        if " · fonte: " not in testo:
            testo += " · fonte: a mano"
        while righe and righe[-1] == "":
            righe.pop()
        righe += [f"- [ ] {entro} · {testo}", ""]
    else:
        for i, riga in enumerate(righe):
            m = RIGA_PERSONALE.match(riga.strip())
            if not m or f"{m.group(2)} · {m.group(4)}" != id_:
                continue
            if cosa == "chiudi" and m.group(1) == " ":
                righe[i] = f"- [x] {m.group(2)} → chiusa {ora} · {m.group(4)}"
                break
            if cosa == "riapri" and m.group(1) == "x":
                righe[i] = f"- [ ] {m.group(2)} · {m.group(4)}"
                break
        else:
            raise ValueError("scadenza personale non trovata (o già in quello stato)")
    nuovo = re.sub(r"^aggiornato:.*$", f"aggiornato: {ora}", "\n".join(righe), count=1, flags=re.M)
    scrivi_atomico(SCADENZE_PERSONALI, nuovo)


def _task_cambia(cosa, id_=None, testo=None):
    if cosa in ("aggiungi", "chiudi"):
        if cosa == "aggiungi":
            arg = ["add", " ".join((testo or "").split())]
            if not arg[1]:
                raise ValueError("scrivi il testo della casella")
        else:
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) · (.+)", id_ or "", flags=re.S)
            if not m:
                raise ValueError("casella non valida")
            arg = ["fatto", m.group(3)]
        r = subprocess.run([sys.executable, str(TASK_PY), *arg], capture_output=True, text=True, timeout=30,
                           env=ENV, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise ValueError((r.stdout or r.stderr).strip()[-200:] or "task.py non ha risposto")
        return
    # riapri: task.py non lo sa fare. Si toglie la x e il «→ ora» sulla riga, nella nota di quel giorno
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) · (.+)", id_ or "", flags=re.S)
    if not m:
        raise ValueError("casella non valida")
    t = _task_mod()
    p, testo_nota = t.apri(date.fromisoformat(m.group(1)))
    if testo_nota is None:
        raise ValueError("nota del giorno non trovata")
    chiusa = re.compile(rf"^- \[x\] {re.escape(m.group(2))} → \d{{2}}:\d{{2}} · {re.escape(m.group(3))}$", re.M)
    if not chiusa.search(testo_nota):
        raise ValueError("casella spuntata non trovata in quella nota")
    nuovo = chiusa.sub(f"- [ ] {m.group(2)} · {m.group(3)}".replace("\\", "\\\\"), testo_nota, count=1)
    ora = datetime.now().strftime("%Y-%m-%d %H:%M")
    scrivi_atomico(p, re.sub(r"^aggiornato:.*$", f"aggiornato: {ora}", nuovo, count=1, flags=re.M))


def azione_scadenze(dati):
    cosa, fonte, id_ = dati.get("cosa"), dati.get("fonte"), dati.get("id")
    if cosa == "chiudi_molte":
        return chiudi_molte(dati.get("voci"), dati.get("perche"))
    if cosa == "controllo":
        return controllo_scadenze(dati.get("fonte") or "tutte")
    if cosa not in ("chiudi", "riapri", "aggiungi") or fonte not in ("azienda", "personali", "task"):
        raise ValueError("scadenze: cosa = chiudi|riapri|aggiungi, fonte = azienda|personali|task")
    if cosa != "aggiungi" and not isinstance(id_, str):
        raise ValueError("scadenze: manca l'id")
    with SCADENZE_LOCK:
        if fonte == "azienda":
            if cosa == "aggiungi":
                raise ValueError("il registro di direzione si scrive dalla skill report-direzione, non da qui")
            nome = _registro_cambia(id_, cosa == "chiudi")
            msg = f"Azienda Uno: {id_} {'chiusa' if cosa == 'chiudi' else 'riaperta'}"
        elif fonte == "personali":
            _personali_cambia(cosa, id_, dati.get("testo"), dati.get("entro"))
            nome = (dati.get("testo") or id_ or "")[:80]
            msg = f"scadenza personale {'aggiunta' if cosa == 'aggiungi' else 'chiusa' if cosa == 'chiudi' else 'riaperta'}"
        else:
            _task_cambia(cosa, id_, dati.get("testo"))
            nome = (dati.get("testo") or id_ or "")[:80]
            msg = f"casella {'aggiunta' if cosa == 'aggiungi' else 'spuntata' if cosa == 'chiudi' else 'riaperta'}"
    if fonte in ("personali", "task") and cosa in ("chiudi", "riapri"):
        _segna_chiusa(fonte, id_, "L'utente dal Command Center", togli=cosa == "riapri")
    evento(f"scadenze · {msg}: {str(nome)[:80]}")
    tocca("scadenze")
    return {"messaggio": msg, "scadenze": scadenze()}


# ---------------------------------------------------------------- portiere (2026-09-26)
# Chi lavora, chi tiene chiavi, cosa non torna: lo dice strumenti/portiere.py --json (una sola
# fonte). Si lancia come processo e non si importa: lavori.py tiene stato a livello di modulo e
# stampa, e un suo errore non deve toccare il server. Misurato: 0,6 s a giro.
PORTIERE_PY = AGENTE / "strumenti" / "portiere.py"
SESSIONI_HOOK = HOME / ".claude" / "hooks" / "sessioni.py"


def _sessioni_hook():
    """pid -> {nome, id} dalle sessioni registrate dall'hook sessioni.py (registro in
    ~/.locale-onedrive/sessioni.json). Un pid si riusa: vince la sessione aperta più recente."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("sessioni_hook", SESSIONI_HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        reg = mod.leggi()
        nome_di = mod.nome
    except Exception:  # noqa: BLE001
        return {}
    fuori = {}
    for sess in sorted(reg.values(), key=lambda x: x.get("ultimo") or x.get("inizio") or ""):
        if sess.get("pid") and sess.get("stato") == "aperta":
            try:
                fuori[str(sess["pid"])] = {"nome": nome_di(sess), "id": sess.get("id", "")}
            except Exception:  # noqa: BLE001
                pass
    return fuori


def leggi_processi(pids):
    """Per ogni pid vivo: comando (argv accorciato a 120), cwd, avvio, cpu, padre. Due comandi in
    tutto, non due per pid. Solo lettura: niente kill."""
    # macOS non va oltre 99998: un pid più grande fa fallire ps per tutti («process id too large»)
    pids = sorted({int(p) for p in pids if str(p).isdigit() and 0 < int(p) < 100000})
    if not pids:
        return {}
    lista = ",".join(map(str, pids))
    fuori = {}
    # LC_ALL=C: con la lingua del Mac (it_IT) ps scrive «sab 26 set» e «0,5», e la riga non si legge più
    try:
        out = subprocess.run(["ps", "-o", "pid=,ppid=,%cpu=,lstart=,command=", "-p", lista], capture_output=True,
                             text=True, timeout=8, env={**ENV, "LC_ALL": "C"}).stdout
    except (subprocess.TimeoutExpired, OSError):
        out = ""
    for riga in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+([\d.,]+)\s+(\w+ \w+\s+\d+ [\d:]+ \d+)\s+(.*)", riga)
        if not m:
            continue
        try:
            avvio = datetime.strptime(" ".join(m.group(4).split()), "%a %b %d %H:%M:%S %Y").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            avvio = m.group(4)
        fuori[m.group(1)] = {"ppid": int(m.group(2)), "cpu": float(m.group(3).replace(",", ".")),
                             "acceso_da": avvio, "comando": m.group(5).strip()[:120], "cwd": ""}
    if fuori:
        _, out = sh(["lsof", "-a", "-p", ",".join(fuori), "-d", "cwd", "-Fpn"], timeout=8)
        pid = None
        for riga in out.splitlines():
            if riga.startswith("p"):
                pid = riga[1:]
            elif riga.startswith("n") and pid in fuori:
                fuori[pid]["cwd"] = riga[1:].replace(str(HOME), "~")
    return fuori


def raccogli_portiere():
    r = subprocess.run([sys.executable, str(PORTIERE_PY), "--json"], capture_output=True, text=True,
                       timeout=30, env=ENV, stdin=subprocess.DEVNULL)
    try:
        g = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError(f"portiere.py esito {r.returncode}: "
                           f"{(r.stderr or r.stdout or 'nessuna uscita').strip()[-200:]}") from None
    note = []
    for n in g.get("note") or []:
        presa = n.get("presa") or {}
        pid = presa.get("pid")
        if not pid:     # MUTO: il pid sta solo nel testo («sessione pid 87643 aperta…»)
            m = re.search(r"\bpid (\d+)", n.get("perche") or "")
            pid = int(m.group(1)) if m else None
        nota = {"tipo": n.get("tipo"), "pid": pid, "chiavi": n.get("chiavi") or [],
                "perche": n.get("perche") or "", "agente": presa.get("agente") or "",
                "cosa": presa.get("cosa") or "", "nome": "", "cwd": "", "comando": ""}
        # Decisione dell'utente del 2026-09-26: la shell sulla VPS senza chiave non si chiama «abusivo».
        # Il tipo resta quello del portiere; etichetta e testo sono quelli da mostrare.
        if nota["tipo"] == "ABUSIVO" and "vps-shell" in nota["chiavi"]:
            nota.update(etichetta="VPS", testo="terminale VPS aperto senza chiave")
        note.append(nota)
    vivi = leggi_processi(n["pid"] for n in note if n["pid"])
    nomi, hook = nomi_sessioni(), _sessioni_hook()
    for n in note:
        p = vivi.get(str(n["pid"]))
        if p:
            # «del_pannello»: un claude -p lanciato da questo server (chat, sentinella). Il portiere lo
            # vede MUTO, ma è un lavoro del pannello già in «lavori»: la sentinella non lo conta
            n.update(cwd=p["cwd"], comando=p["comando"], del_pannello=p["ppid"] == os.getpid())
        if n["pid"]:
            n["nome"] = nomi.get(str(n["pid"])) or (hook.get(str(n["pid"])) or {}).get("nome", "")
    STATO.set("portiere", {"quando_ts": time.time(), "chiavi_in_giro": sum((g.get("chiavi_in_giro") or {}).values()),
                           "da_guardare": note, "fantasmi": sum(1 for n in note if n["tipo"] == "FANTASMA"),
                           "sessioni": g.get("sessioni"), "lavori_vivi": g.get("lavori_vivi"),
                           "in_ascolto": g.get("in_ascolto") or []})


def portiere_identifica(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise ValueError("pid non valido") from None
    p = leggi_processi([pid]).get(str(pid))
    if not p:
        raise ValueError(f"nessun processo vivo con pid {pid}")
    sess = _sessioni_hook().get(str(pid)) or {}
    riga = next((r for r in AGENTI_CACHE["righe"] if r["pid"] == pid), None)
    # «lavora»: la stessa misura della pagina «Sessioni Claude» se il pid è lì, se no il processore adesso
    lavora = bool(riga["lavora"]) if riga else p["cpu"] >= 5
    return {"pid": pid, "comando": p["comando"], "cwd": p["cwd"],
            "nome": nomi_sessioni().get(str(pid)) or sess.get("nome", ""), "sessione": sess.get("id", ""),
            "acceso_da": p["acceso_da"], "lavora": lavora, "cpu": p["cpu"], "ppid": p["ppid"]}


def portiere_ritira_fantasmi():
    """Solo le prese col processo morto su questo Mac (portiere.py --fantasmi = ritira_fantasmi()).
    Le chiavi di chi è vivo, anche scadute, non si toccano da qui."""
    r = subprocess.run([sys.executable, str(PORTIERE_PY), "--fantasmi"], capture_output=True, text=True,
                       timeout=60, env=ENV, stdin=subprocess.DEVNULL)
    m = re.search(r"prese fantasma ritirate: (\d+)", r.stdout or "")
    if r.returncode != 0 or not m:
        raise ValueError(f"portiere.py --fantasmi: {(r.stderr or r.stdout or 'nessuna uscita').strip()[-200:]}")
    esegui_raccoglitore(raccogli_portiere)
    return int(m.group(1))


# ---------------------------------------------------------------- file che cambiano
# Ogni 2 s si guardano le date dei file che dicono «è cambiato qualcosa» fuori dal server.
# Solo stat(): nessun file si apre. Se una firma cambia, la versione sale; per sincronia e
# prese si rilegge anche il dato, così la pagina lo trova già nuovo.
LAVORI_ATTIVI_DIR = HOME / ".ai-memory" / "global" / "lavori" / "attivi"
_FIRME = {}


def _firma(percorsi):
    fuori = []
    for p in percorsi:
        try:
            fuori.append((str(p), p.stat().st_mtime))
        except OSError:
            pass
    return tuple(sorted(fuori))


def _scritto_da_noi(firma, chiave):
    """Vero se il file più recente della firma è stato scritto prima dell'ultimo tocca(chiave) del server:
    è una scrittura nostra (spazi.salva, scrivi_atomico, modifica_pannello), che ha già svegliato le pagine.
    Così una scrittura del server non dà due eventi; una scrittura esterna (mtime dopo l'ultimo tocco) sì."""
    ultimo = max((m for _, m in firma), default=0)
    return ultimo <= ULTIMO_TOCCO.get(chiave, 0)


def sorveglia_file():
    missioni_f = [d / n for d in MISSIONI_DIR.iterdir() if d.is_dir() for n in ("stato.json", "agenti.json")] \
        if MISSIONI_DIR.is_dir() else []
    attivi = list(LAVORI_ATTIVI_DIR.glob("*.json")) if LAVORI_ATTIVI_DIR.is_dir() else []
    firme = {"missioni": _firma(missioni_f), "claude_ora": _firma([AGENTE / "backtalk" / ".jarvis_status"]),
             "memoria": _firma([AGENTE / "sincro" / "ultimo.json"]), "portiere": _firma([LAVORI_ATTIVI_DIR, *attivi])}
    # 02/10/2026: se task.py non si carica, salta solo la firma delle scadenze (prima saltavano tutte le altre)
    try:
        firme["scadenze"] = _firma([REGISTRO_140, SCADENZE_PERSONALI,
                                    *(_task_mod().nota(date.today() - timedelta(days=i)) for i in range(4))])
    except Exception:  # noqa: BLE001
        firme["scadenze"] = _firma([REGISTRO_140, SCADENZE_PERSONALI])
    # 02/10/2026 (audit menu, P8): anche .claude/agents/_archivio, così la riga grigia «Ripristina» compare subito
    firme["spazi"] = _firma([f for c in _cartelle_agenti()
                             for f in (c, *c.glob("*.md"), c / "_archivio", *(c / "_archivio").glob("*.md"))])
    # 02/10/2026 (audit menu, P3): i file di stato del menu, scritti anche da OneDrive, dal PC dell'amministrazione
    # o da uno script. Le scritture del server stesso hanno già il loro tocca(): vedi _scritto_da_noi() sotto.
    firme["spazi_file"] = _firma([spazi.FILE, GRUPPI_ARCHIVIO, TOMBE_FILE])
    firme["pannello"] = _firma([PANNELLO_FILE])
    # 2026-10-05 (fonte unica): i fili arrivati dall'altra macchina (fonte_vps.py) svegliano la chat
    _fr = fili.cartella().parent / "fili-remoti"
    firme["fili_remoti"] = _firma([f for _o, c in fili.cartelle_remote() for f in c.glob("*.json")]) if _fr.is_dir() else ()
    # 2026-10-03 (prestazioni): la chat a voce (backtalk/chat.jsonl, letta da /api/chat/storia) sveglia il flusso
    # con «chat_voce»: la pagina la rilegge allora, invece di chiederla ogni 2 s
    firme["chat_voce"] = _firma([QUI.parent / "backtalk" / "chat.jsonl",
                                 # 2026-10-05: e la copia della chat a voce dell'altra macchina (chat_ponte.py)
                                 QUI.parent / "backtalk" / "remoti" / ("mac" if SU_LINUX else "vps") / "chat.jsonl"])
    if attivita:            # 2026-10-02: una riga nuova nel registro delle attività sveglia il flusso (chiave «attivita»)
        f = attivita.file_del_giorno()
        try:
            firme["attivita"] = (str(f), f.stat().st_size)
        except OSError:
            firme["attivita"] = (str(f), 0)
        # 2026-10-05 (lavagna viva): anche le righe arrivate dall'altra macchina (attivita_ponte.py, remoti/)
        try:
            firme["attivita"] += tuple((x.name, x.stat().st_size) for x in attivita.file_remoti(2))
        except OSError:
            pass
    for chiave, firma in firme.items():
        prima = _FIRME.get(chiave)
        _FIRME[chiave] = firma
        if prima is None or prima == firma:
            continue          # il primo giro prende le misure e basta
        if chiave == "missioni":
            tocca("missioni", "agenti_attivi")
        elif chiave in ("claude_ora", "scadenze", "spazi", "attivita", "chat_voce"):
            tocca(chiave)
        elif chiave == "fili_remoti":
            emetti_flusso("fili", {"remoti": True})
        elif chiave in ("spazi_file", "pannello"):
            evento_sse = "spazi" if chiave == "spazi_file" else "pannello"
            if not _scritto_da_noi(firma, evento_sse):
                tocca(evento_sse)
        if chiave == "missioni":
            threading.Thread(target=fine_catena, daemon=True).start()
        elif chiave == "memoria":
            threading.Thread(target=esegui_raccoglitore, args=(raccogli_memoria,), daemon=True).start()
        elif chiave == "portiere":
            threading.Thread(target=esegui_raccoglitore, args=(raccogli_portiere,), daemon=True).start()


# ---------------------------------------------------------------- sentinella (2026-09-26, rifatta alle 17:07)
# Richiesta dell'utente: «la sentinella si attiva ogni 15 minuti; se ci sono problemi lo dice a Jarvis,
# che si attiva con tutti gli agenti per risolvere e ripulire lo stato. Telegram e la VPS sono in
# ascolto: si controllano e si riavviano se cadono, non si chiudono. Le sessioni ferme anomale si
# chiudono.» Ogni 60 s uno script (nessun modello) confronta le anomalie con quelle del giro prima
# e le pubblica. Al massimo ogni 15 minuti, se ci sono anomalie non ancora passate a Jarvis, AGISCE:
#   1. la pulizia da script (strumenti/sentinella.py: prese fantasma, recapiti orfani, sessioni
#      ferme da più di 4 ore fuori dagli ascoltatori, Telegram Mac e VPS col guardiano);
#   2. rilegge il quadro e scrive «Ultimo rapporto» con rapporto_sentinella(): al massimo 5 righe
#      da una tabella fissa (cosa vuol dire, gravità, a chi tocca), solo Python.
# 2026-09-26 17:35, l'utente: «la sentinella deve lavorare solo in Python per non usare crediti e
# liberare Jarvis e gli LLM». Dalle 17:07 alle 17:35 il punto 2 lanciava `claude -p` in modo lavoro
# su Sonnet; prima ancora chiedeva a Haiku cinque righe di parere. L'opzione del modello è tolta.
# «segnalate» tiene le anomalie già riferite: finché restano uguali non si riscrive il rapporto
# (salvo il giro forzato dal pannello); se una sparisce e poi torna, si riferisce di nuovo.
SENTINELLA = {"prima": None, "ultima_azione": 0.0, "segnalate": set(),
              "rapporto": "", "rapporto_ts": None, "pulizia": "", "pulizia_ts": None}
SENTINELLA_LOCK = threading.Lock()
SENTINELLA_OGNI_AZIONE = 15 * 60


def quadro_anomalie():
    """chiave -> {tipo, chiave, testo}: tutto quello che oggi non torna, letto dai dati già raccolti."""
    st = STATO.get()
    fuori = {}

    def metti(tipo, chiave, testo):
        fuori[chiave] = {"tipo": tipo, "chiave": chiave, "testo": testo[:300]}

    for n in (st.get("portiere") or {}).get("da_guardare") or []:
        if n.get("del_pannello"):
            continue
        chi = n.get("pid") or ",".join(n.get("chiavi") or []) or n.get("agente") or "?"
        nome = f" ({n['nome']})" if n.get("nome") else ""
        testo = (f"{n['etichetta']}: {n['testo']}" if n.get("etichetta")
                 else f"{n.get('tipo')}{nome}: {n.get('perche')}")
        metti("portiere", f"portiere:{n.get('tipo')}:{chi}", testo)
    b = battito()
    if not b.get("acceso", True):
        metti("sincronia", "sincronia:battito", f"battito della memoria fermo: {b.get('perche')}")
    for p in b.get("progetti") or []:
        if p.get("semaforo") in ("🟡", "🔴"):
            metti("sincronia", f"sincronia:{p.get('progetto')}:{p['semaforo']}",
                  f"{p['semaforo']} {p.get('progetto')}: {p.get('esito')}")
    for r in salute()["raccoglitori"]:
        if r.get("errore") and r["nome"] != "sentinella":
            metti("salute", f"salute:{r['nome']}", f"{r['nome']}: {r['errore']}")
    with LAVORI_LOCK:
        # uno Stop dell'utente (fermato, SIGTERM = 143/-15) non è un'anomalia
        errori = [dict(x) for x in LAVORI.values() if x.get("stato") == "errore"
                  and not x.get("fermato") and x.get("codice") not in (143, -15)]
    for lav in errori:
        metti("lavoro", f"lavoro:{lav['id']}", f"lavoro in errore: {lav.get('titolo')} (codice {lav.get('codice')})")
    if MISSIONI_DIR.is_dir():
        for d in MISSIONI_DIR.iterdir():
            # 27/09/2026: lo stato calcolato (una missione morta in «attende conferma» è interrotta)
            if d.is_dir() and leggi_missione(d)["stato"] == "attende conferma":
                metti("missione", f"missione:{d.name}", f"missione {d.name} attende una conferma dell'utente")
    # Telegram Mac e VPS sono «in ascolto»: giù è un'anomalia (il guardiano riavvia, la sentinella controlla)
    if _sentinella_mod:
        for dove in ("mac", "vps"):
            t = (st.get("telegram") or {}).get(dove)
            if not isinstance(t, dict):
                continue
            if t.get("errore"):
                metti("telegram", f"telegram:{dove}", f"Telegram {dove.upper()}: {t['errore'][:120]}")
            elif not t.get("spento") and not _sentinella_mod.telegram_vivo(t) and not _sentinella_mod.telegram_giovane(t):
                metti("telegram", f"telegram:{dove}", f"Telegram {dove.upper()}: bot non agganciato")
    return fuori


def rapporto_sentinella(anomalie_nuove, rientrate=()):
    """Il rapporto della sentinella, solo Python (2026-09-26 17:35): la tabella fissa sta in
    strumenti/sentinella.py (TABELLA, una sola fonte anche per il giro di launchd); qui si
    aggiunge chi è il capogruppo di ogni progetto, da spazi.json."""
    capi = {}
    try:
        for sp in spazi.carica():
            for pr in sp["progetti"]:
                if pr.get("capogruppo"):
                    capi[pr["nome"]] = pr["capogruppo"]
    except Exception:  # noqa: BLE001 — senza spazi.json le 🟡 vanno a Jarvis
        pass
    return _sentinella_mod.rapporto(list(anomalie_nuove), list(rientrate), capi)


def _pubblica_sentinella(nuove=None):
    with SENTINELLA_LOCK:
        prima = SENTINELLA["prima"] or {}
        vecchio = STATO.get().get("sentinella") or {}
        STATO.set("sentinella", {
            "acceso": bool(config_caldo("sentinella", True)), "quando_ts": SENTINELLA.get("quando_ts"),
            "anomalie": sorted(prima.values(), key=lambda a: a["da_ts"]),
            "nuove": vecchio.get("nuove", 0) if nuove is None else nuove,
            "ogni_azione_min": SENTINELLA_OGNI_AZIONE // 60,
            "ultima_azione_ts": SENTINELLA["ultima_azione"] or None,
            "ultima_pulizia": SENTINELLA["pulizia"], "ultima_pulizia_ts": SENTINELLA["pulizia_ts"],
            "modello": "",          # dal 2026-09-26 17:35 nessun modello: il rapporto è Python
            "ultimo_rapporto": SENTINELLA["rapporto"], "ultimo_rapporto_ts": SENTINELLA["rapporto_ts"]})


def sentinella(forzato=False):
    if not forzato and not config_caldo("sentinella", True):
        _pubblica_sentinella(0)
        return
    if "portiere" not in STATO.get():
        return            # il portiere non ha ancora fatto il primo giro: il quadro sarebbe monco
    ora = time.time()
    adesso = quadro_anomalie()
    with SENTINELLA_LOCK:
        prima = SENTINELLA["prima"]
        primo_giro = prima is None
        prima = prima or {}
        for k, a in adesso.items():
            a["da_ts"] = prima[k]["da_ts"] if k in prima else ora
        nuove = [] if primo_giro else [a for k, a in adesso.items() if k not in prima]
        sparite = [] if primo_giro else [a for k, a in prima.items() if k not in adesso]
        SENTINELLA["prima"] = adesso
        SENTINELLA["quando_ts"] = ora
        SENTINELLA["segnalate"] &= set(adesso)      # quello che è rientrato si potrà segnalare di nuovo
        da_segnalare = set(adesso) - SENTINELLA["segnalate"]
        # il giro forzato dal pannello scrive sempre il rapporto; quello del ciclo solo se c'è
        # qualcosa di non ancora riferito e sono passati 15 minuti. Anche la copia di prova
        # scrive il rapporto (è Python), ma lì la pulizia si salta.
        agisci = (_sentinella_mod is not None and config_caldo("sentinella", True)
                  and (forzato or (bool(da_segnalare)
                                   and ora - SENTINELLA["ultima_azione"] >= SENTINELLA_OGNI_AZIONE)))
        if agisci:
            SENTINELLA["ultima_azione"] = ora
    if primo_giro and adesso:
        evento(f"sentinella: {len(adesso)} anomalie presenti all'avvio")
    for a in nuove:
        evento(f"sentinella · nuova: {a['testo'][:120]}")
    for a in sparite:
        evento(f"sentinella · rientrata: {a['testo'][:120]}")
    _pubblica_sentinella(len(nuove))
    if agisci:
        _sentinella_agisce(sparite, tutte=forzato)


def _sentinella_agisce(rientrate=(), tutte=False):
    """Prima la pulizia da script, poi il quadro riletto, poi il rapporto in Python.
    tutte=True (giro forzato): il rapporto elenca tutte le anomalie aperte, non solo le nuove."""
    if PROVA:
        riga = "copia di prova: pulizia saltata"
    else:
        try:
            riga = _sentinella_mod.righe_pulizia(_sentinella_mod.pulisci(2))
        except Exception as e:  # noqa: BLE001
            riga = f"pulizia non riuscita: {e}"
    with SENTINELLA_LOCK:
        SENTINELLA.update(pulizia=riga[:600], pulizia_ts=time.time())
    evento("sentinella · pulizia: " + riga[:200])
    for f in (raccogli_portiere, raccogli_agenti, raccogli_telegram):
        esegui_raccoglitore(f)
    ora = time.time()
    adesso = quadro_anomalie()
    with SENTINELLA_LOCK:
        prima = SENTINELLA["prima"] or {}
        for k, a in adesso.items():
            a["da_ts"] = prima[k]["da_ts"] if k in prima else ora
        SENTINELLA["prima"] = adesso
        SENTINELLA["quando_ts"] = ora
        SENTINELLA["segnalate"] &= set(adesso)
        restano = list(adesso.values()) if tutte else [a for k, a in adesso.items()
                                                       if k not in SENTINELLA["segnalate"]]
        SENTINELLA["segnalate"] |= set(adesso)
    testo = rapporto_sentinella(sorted(restano, key=lambda a: a["da_ts"]), rientrate)
    with SENTINELLA_LOCK:
        SENTINELLA.update(rapporto=testo[:3000], rapporto_ts=time.time())
    _pubblica_sentinella()
    evento(f"sentinella: rapporto scritto ({len(restano)} anomalie, solo Python)")


# ---------------------------------------------------------------- comunicazioni (2026-09-26 sera)
# l'utente: «la lavagna deve mostrare in tempo reale cosa comunicano gli agenti e a chi» (contratto,
# punto 11). Ogni 2 s si rimettono insieme da quattro fonti già scritte da altri, senza doppioni:
#   .jarvis_status   Jarvis → sottoagente (lancio) e sottoagente → Jarvis (fine);
#   missioni         registro.log: «→ Agent: tipo: descrizione» è il lancio dell'orchestratore,
#                    «◆ tipo consegnato|errore: …» (consegna() di missione.py) è la risposta;
#   lavori chat      l'utente → interlocutore, poi interlocutore → l'utente con la risposta;
#   sentinella       sentinella → jarvis con il rapporto.
# STATO.set confronta con prima: se cambia (una nuova, o una che finisce) la versione sale.
_REGISTRI_CACHE = {}      # percorso -> (mtime, comunicazioni)
_RISPOSTE_CACHE = {}      # id lavoro -> prima riga della risposta


def _corto(testo, n=140):
    testo = " ".join(str(testo or "").split())
    return testo if len(testo) <= n else testo[:n - 1] + "…"


def _com(ts, da, a, testo, tipo, stato, id_):
    return {"ts": ts, "da": da, "a": a, "testo": _corto(testo), "tipo": tipo, "stato": stato, "id": id_}


def _stato_com(valore):
    return "errore" if valore == "errore" else "finito" if valore in ("finito", "consegnato", "chiusa") else "in corso"


def _com_jarvis():
    d = leggi_json(AGENTE / "backtalk" / ".jarvis_status", {})
    fuori = []
    for x in d.get("agenti") or []:
        if not x.get("id") or not x.get("ts"):
            continue
        chi = _nodo_bus(x.get("nodo")) or x.get("tipo") or "general-purpose"
        stato = _stato_com(x.get("stato"))
        # 27/09/2026: come claude_ora, oltre 30 minuti senza gancio di fine non è più «in corso»
        if stato == "in corso" and time.time() - float(x["ts"] or 0) > 1800:
            stato = "finito"
        fuori.append(_com(x["ts"], "jarvis", chi, x.get("descrizione"), "lancio", stato, f"j:{x['id']}"))
        if stato != "in corso" and x.get("fine"):
            fuori.append(_com(x["fine"], chi, "jarvis", f"{stato}: {x.get('descrizione', '')}", "risposta",
                              stato, f"j:{x['id']}:fine"))
    return fuori


def _com_missione(d):
    registro = d / "registro.log"
    try:
        mtime = registro.stat().st_mtime
    except OSError:
        return []
    conf = leggi_json(d / "missione.json", {})
    st = leggi_json(d / "stato.json", {}).get("stato")
    # missione finita o col processo morto: niente resta «in corso» (l'utente, 27/09/2026: le bolle
    # «orchestratore · App Android → ceo-risto» restavano accese per ore a missione chiusa)
    finita = st in ("chiusa", "errore") or not (conf.get("pid") and _missione_viva(conf["pid"], d))
    chiave = (mtime, finita)
    vecchio = _REGISTRI_CACHE.get(str(registro))
    if vecchio and vecchio[0] == chiave:
        return vecchio[1]
    prog = ((conf.get("progetti") or [{}])[0].get("id")) or conf.get("progetto") or d.name
    capo = f"{prog}:orchestratore"
    try:
        base = datetime.strptime(d.name[:17], "%Y-%m-%d_%H%M%S")
    except ValueError:
        base = datetime.fromtimestamp(mtime)
    righe = registro.read_text(encoding="utf-8", errors="replace").splitlines()[-600:]
    fuori, aperti, giorno, prima = [], {}, base.date(), None
    visti, rimandi = {}, {}

    def id_stabile(ts, riga):
        # 27/09/2026: id da ora + hash della riga, non dall'indice nelle ultime 600 righe (che scorre
        # a ogni riga nuova e faceva rinascere le stesse sinapsi con un id diverso)
        k = f"m:{d.name}:{int(ts)}:{hashlib.sha1(riga.encode('utf-8', 'replace')).hexdigest()[:10]}"
        visti[k] = visti.get(k, 0) + 1
        return k if visti[k] == 1 else f"{k}:{visti[k]}"

    for riga in righe:
        m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\] (.*)", riga)
        if not m:
            continue
        ora = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if prima and ora < prima:
            giorno += timedelta(days=1)          # il registro ha solo l'ora: dopo mezzanotte il giorno cambia
        prima = ora
        ts = datetime(giorno.year, giorno.month, giorno.day, *ora).timestamp()
        testo = m.group(4)
        lancio = re.match(r"→ (?:Agent|Task): ([^:]+): ?(.*)", testo)
        fine = re.match(r"◆ (\S+) (consegnato|errore): ?(.*)", testo)
        rimandato = re.match(r"⏳ (\S+) rimandato:", testo)
        if lancio and rimandi.get(lancio.group(1).strip()) and ts - rimandi[lancio.group(1).strip()][0] <= 5:
            rimandi[lancio.group(1).strip()].pop(0)     # il tetto l'aveva già negato (gancio scritto prima)
        elif lancio:
            # «[ceo-my140] …»: l'orchestratore lancia per conto di un capogruppo (missione «aggiorna catena»)
            mitt = re.match(r"\[([\w.-]+)\]\s*(.*)", lancio.group(2))
            da = capo if not mitt or mitt.group(1) == "orchestratore" else f"{prog}:{mitt.group(1)}"
            c = _com(ts, da, f"{prog}:{lancio.group(1).strip()}", mitt.group(2) if mitt else lancio.group(2),
                     "lancio", "in corso", id_stabile(ts, riga))
            aperti.setdefault(lancio.group(1).strip(), []).append(c)
            fuori.append(c)
        elif rimandato:
            # 27/09/2026: il tetto ha negato l'ultimo lancio di quel tipo. Non partirà: esce dalla coda
            # dei lanci aperti (altrimenti la prossima consegna chiudeva lui) e dalle sinapsi
            # (il gancio può scrivere prima del lancio: allora si scarta il prossimo lancio entro 5 s)
            coda = aperti.get(rimandato.group(1)) or []
            if coda and ts - coda[-1]["ts"] <= 5:
                negato = coda.pop()
                fuori = [c for c in fuori if c is not negato]
            else:
                rimandi.setdefault(rimandato.group(1), []).append(ts)
        elif testo.startswith("⇧ riepilogo:"):
            # la risalita finisce qui (l'utente, 2026-09-26 18:35): orchestratore → jarvis → utente con il riepilogo
            r = testo[len("⇧ riepilogo:"):].strip()
            k = id_stabile(ts, riga)
            fuori.append(_com(ts, "orchestratore", "jarvis", r, "risposta", "finito", k))
            fuori.append(_com(ts + 1, "jarvis", "utente", f"catena {prog}: {r}", "risposta", "finito", f"{k}:utente"))
        elif fine:
            stato = "errore" if fine.group(2) == "errore" else "finito"
            coda = aperti.get(fine.group(1)) or []
            verso = capo
            if coda:
                lanciato = coda.pop(0)
                lanciato["stato"] = stato          # il lancio di quell'esperto è chiuso
                verso = lanciato["da"]             # la risposta torna a chi l'ha mandato
            fuori.append(_com(ts, f"{prog}:{fine.group(1)}", verso, fine.group(3), "risposta", stato,
                              id_stabile(ts, riga)))
    if finita:
        for c in fuori:
            if c["stato"] == "in corso":
                c["stato"] = "errore"
                c["testo"] = _corto("missione chiusa prima della consegna · " + c["testo"])
    _REGISTRI_CACHE[str(registro)] = (chiave, fuori)
    return fuori


def _risposta_lavoro(lav):
    if lav["id"] not in _RISPOSTE_CACHE:
        try:
            testo = Path(lav["log"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            testo = ""
        testo = re.sub(r"^\(cartella: .*?\)\n\n", "", testo).strip()
        _RISPOSTE_CACHE[lav["id"]] = next((r for r in testo.splitlines() if r.strip()), "")
    return _RISPOSTE_CACHE[lav["id"]]


def raccogli_comunicazioni():
    com = _com_jarvis()
    if MISSIONI_DIR.is_dir():
        for d in MISSIONI_DIR.iterdir():
            if d.is_dir():
                com += _com_missione(d)
    with LAVORI_LOCK:
        lavori = [dict(x) for x in LAVORI.values()]
    for lav in lavori:
        cerca = re.match(r"/(memoria|brain)\b\s*(.*)", lav.get("richiesta") or "")
        if lav.get("tipo") == "comando" and cerca:
            # la ricerca nella memoria è una sinapsi anche lei: jarvis → memoria (contratto, punto 13)
            com.append(_com(lav.get("inizio_ts") or 0, "jarvis", "memoria",
                            f"/{cerca.group(1)} {cerca.group(2)}".strip(), "richiesta", _stato_com(lav.get("stato")),
                            f"l:{lav['id']}"))
        if lav.get("tipo") == "chat":
            chi = lav.get("interlocutore") or "jarvis"
            stato = _stato_com(lav.get("stato"))
            com.append(_com(lav.get("inizio_ts") or 0, "utente", chi, lav.get("richiesta"), "richiesta", stato,
                            f"l:{lav['id']}"))
            if stato != "in corso":
                com.append(_com(lav.get("fine_ts") or 0, chi, "utente", _risposta_lavoro(lav) if stato == "finito"
                                else f"errore (codice {lav.get('codice')})", "risposta", stato, f"l:{lav['id']}:fine"))
    with SENTINELLA_LOCK:
        rapporto, rapporto_ts = SENTINELLA["rapporto"], SENTINELLA["rapporto_ts"]
    if rapporto and rapporto_ts:
        com.append(_com(rapporto_ts, "sentinella", "jarvis", rapporto, "sentinella", "finito",
                        f"s:{int(rapporto_ts)}"))
    unici = {c["id"]: c for c in com}
    STATO.set("comunicazioni", sorted(unici.values(), key=lambda c: c["ts"], reverse=True)[:60])


# ---------------------------------------------------------------- attività per agente (proposta 2026-10-02)
# l'utente: «vedere nella lavagna come stanno lavorando ogni singolo agente, come richieste inviate e ricevute».
# Le sinapsi qui sopra mostrano le ultime 60 comunicazioni di tutti, per 20 secondi. Qui c'è la storia di
# ognuno (14 giorni), dal registro scritto da attivita.registra() (gancio, missioni, chat del pannello):
# ricevute e inviate, stato, durata, esito, errore, e gli avvisi sui collegamenti che non tornano.
try:
    import attivita  # noqa: E402
except Exception:  # noqa: BLE001
    attivita = None
ATT_LOCK = threading.Lock()
ATT_LETTORE = attivita.Lettore(giorni=3) if attivita else None
_ATT_INDICE = {"ts": 0, "agenti": {}, "per_nome": {}}
SPECIALI = ("utente", "jarvis", "sentinella", "memoria")


def _indice_agenti():
    """{«progetto:nome»: {comunica, progetto, capogruppo}} e {nome: [chiavi]}, riletti ogni 30 s."""
    if time.time() - _ATT_INDICE["ts"] > 30:
        agenti = {k: {"comunica": list(a.get("comunica") or []), "progetto": k.split(":", 1)[0],
                      "capogruppo": bool(a.get("capogruppo"))} for k, a in _tutti_profili()}
        per_nome = {}
        for k in agenti:
            per_nome.setdefault(k.split(":", 1)[1], []).append(k)
        # 2026-10-05 (lavagna viva): i nomi dei gruppi come li scrivono gancio e lavori.py («Azienda Due»,
        # «Patrimonio», «Azienda Uno») → i progetti; e il capogruppo di ogni progetto, in ordine
        gruppi, capi = {}, []
        try:
            for s_ in spazi.carica():
                ids = [p["id"] for p in s_["progetti"]]
                for nome in (s_.get("id"), s_.get("nome"), s_.get("cartella_nome")):
                    if nome:
                        gruppi.setdefault(_slug_gruppo(nome), set()).update(ids)
                for p in s_["progetti"]:
                    for nome in (p["id"], p.get("nome")):
                        if nome:
                            gruppi.setdefault(_slug_gruppo(nome), set()).add(p["id"])
                    if p.get("capogruppo"):
                        capi.append((p["id"], p["capogruppo"]))
        except Exception:  # noqa: BLE001 — senza spazi si risolve come prima
            pass
        _ATT_INDICE.update(ts=time.time(), agenti=agenti, per_nome=per_nome, gruppi=gruppi, capi=capi)
    return _ATT_INDICE["agenti"], _ATT_INDICE["per_nome"]


def _slug_gruppo(t):
    return re.sub(r"[^a-z0-9]+", "-", str(t or "").lower()).strip("-")


def _progetti_del_gruppo(prefisso):
    """I progetti che un prefisso indica: un id di progetto, uno spazio o un nome di gruppo, anche in parte
    («azienda-uno» → crm e sito; «jarvis» → casa). Vuoto se non indica niente."""
    g = _slug_gruppo(prefisso)
    gruppi = _ATT_INDICE.get("gruppi") or {}
    if g in gruppi:
        return set(gruppi[g]) | {prefisso}
    simili = set()
    for k, ids in gruppi.items():
        if g and len(g) >= 4 and (g in k.split("-") or ("-" + g + "-") in ("-" + k + "-")):
            simili |= ids
    return simili | {prefisso}


def risolvi_chiave(k):
    """La chiave canonica «progetto:nome» (o utente/jarvis/…, o «progetto:orchestratore»). Un nome che non
    si trova, o che sta in più progetti, diventa «?:nome»: sulla lavagna è un avviso, non un filo muto."""
    k = str(k or "?").strip()
    if k.lower() in SPECIALI:
        return k.lower()
    agenti, per_nome = _indice_agenti()
    if k in agenti or k.endswith(":orchestratore"):
        return k
    nome = k.split(":", 1)[-1]
    trovati = per_nome.get(nome) or []
    if ":" in k and not k.startswith("?:"):
        # 2026-10-05: il prefisso può essere un progetto, uno spazio o un gruppo («Azienda Due:marketing»)
        progetti = _progetti_del_gruppo(k.split(":", 1)[0])
        if nome.lower() == "capogruppo":       # «<gruppo>:capogruppo» (riunioni): il capogruppo, o Jarvis
            capo = next((f"{p}:{c}" for p, c in _ATT_INDICE.get("capi") or [] if p in progetti and f"{p}:{c}" in agenti), None)
            return capo or "jarvis"
        trovati = [x for x in trovati if x.split(":", 1)[0] in progetti] or trovati
        if not trovati:
            # stesso primo pezzo del nome nello stesso gruppo: «revisore» e «revisore-pj» del gruppo Azienda Due
            # sono azd:revisore-Azienda Due (le riunioni li chiamano così)
            radice = nome.split("-")[0].lower()
            simili = [x for x in agenti if x.split(":", 1)[0] in progetti and x.split(":", 1)[1].split("-")[0].lower() == radice]
            if len(simili) == 1:
                return simili[0]
    return trovati[0] if len(trovati) == 1 else "?:" + nome


def _schede_lavagna(lavagna):
    """{chiave: id della scheda} e i vicini (fili nei due versi) di una lavagna."""
    lav = (leggi_pannello().get("lavagne") or {}).get(lavagna) or {}
    schede = {}
    for n in lav.get("nodi") or []:
        if n.get("tipo") == "agente" and n.get("agente"):
            schede.setdefault(n["agente"], n["id"])
        elif n.get("tipo") == "nota":
            t = str(n.get("testo") or "")
            for chi, rx in (("jarvis", r"^Jarvis\b"), ("utente", r"^(l'utente|Umano)"), ("sentinella", r"^Sentinella"),
                            ("memoria", r"^Memoria$")):
                if re.match(rx, t, re.I):
                    schede.setdefault(chi, n["id"])
    vicini = {}
    for f in lav.get("fili") or []:
        vicini.setdefault(f.get("da"), set()).add(f.get("a"))
        vicini.setdefault(f.get("a"), set()).add(f.get("da"))
    return schede, vicini


def _passi(vicini, a, b, massimo=5):
    """Quanti fili servono per andare dalla scheda a alla b (None: non si arriva)."""
    visti, giro = {a}, [a]
    for n in range(1, massimo + 1):
        prossimo = []
        for x in giro:
            for y in vicini.get(x, ()):
                if y == b:
                    return n
                if y not in visti:
                    visti.add(y)
                    prossimo.append(y)
        giro = prossimo
    return None


def avvisi_collegamento(da, a, lavagna="generale", schede=None, vicini=None):
    """Perché una richiesta da → a non ha un collegamento giusto. Lista vuota: è a posto."""
    if schede is None:
        schede, vicini = _schede_lavagna(lavagna)
    agenti, _ = _indice_agenti()
    fuori = []
    for chi, ruolo in ((da, "mittente"), (a, "destinatario")):
        if chi.startswith("?:"):
            fuori.append({"tipo": f"{ruolo}-sconosciuto",
                          "testo": f"{ruolo} «{chi[2:]}» non è un agente degli spazi (nome generico o profilo non trovato)"})
    if any(x["tipo"].endswith("sconosciuto") for x in fuori):
        return fuori
    capo = lambda k: next((x for x, v in agenti.items() if v["progetto"] == k.split(":")[0] and v["capogruppo"]), k) \
        if k.endswith(":orchestratore") else k                                       # come fa la pagina
    sa, sb = schede.get(capo(da)), schede.get(capo(a))
    for chi, s in ((da, sa), (a, sb)):
        if not s and not chi.endswith(":orchestratore"):
            fuori.append({"tipo": "senza-scheda", "testo": f"«{chi}» non ha una scheda sulla lavagna «{lavagna}»"})
    if sa and sb and sa != sb:
        n = _passi(vicini, sa, sb)
        if n is None:
            fuori.append({"tipo": "senza-filo", "testo": f"nessun filo fra {da} e {a} sulla lavagna «{lavagna}»"})
        elif n > 1:
            fuori.append({"tipo": "filo-indiretto", "livello": "info",
                          "testo": f"{da} e {a} sono collegati passando per {n - 1} " + ("scheda" if n == 2 else "schede")})
    if da in agenti and a in agenti:
        nd, na = da.split(":", 1)[1], a.split(":", 1)[1]
        dice_d, dice_a = na in agenti[da]["comunica"], nd in agenti[a]["comunica"]
        if not dice_d and not dice_a:
            fuori.append({"tipo": "comunica-assente", "testo": f"né {nd} né {na} si nominano in «comunica con»"})
        elif dice_d != dice_a:
            chi_manca, dove = (nd, na) if dice_d else (na, nd)
            fuori.append({"tipo": "comunica-non-reciproco",
                          "testo": f"«comunica con» non reciproco: manca {chi_manca} nel profilo di {dove}"})
        if agenti[da]["progetto"] != agenti[a]["progetto"]:
            fuori.append({"tipo": "fuori-progetto", "livello": "info", "testo": f"richiesta fra due progetti: {agenti[da]['progetto']} → "
                                                             f"{agenti[a]['progetto']}"})
    return fuori


def attivita_righe():
    """Tutte le richieste degli ultimi 3 giorni, ricomposte e con le chiavi canoniche."""
    if not ATT_LETTORE:
        return []
    with ATT_LOCK:
        eventi = list(ATT_LETTORE.eventi())
    righe = attivita.ricomponi(eventi)
    for r in righe:
        r["da_grezzo"], r["a_grezzo"] = r["da"], r["a"]
        r["da"], r["a"] = risolvi_chiave(r["da"]), risolvi_chiave(r["a"])
    return righe


def _coperto_dal_gancio(chiave):
    """True se c'è già una richiesta aperta del gancio di Claude Code (o della chat) verso lo stesso agente:
    lavori_ponte allora non racconta la stessa presa una seconda volta."""
    a = risolvi_chiave(chiave)
    adesso = time.time()
    return any(r["a"] == a and r["stato"] in ("in corso", "al lavoro") and r.get("fonte") != "lavori"
               and adesso - (r.get("inizio") or 0) < 3600 for r in attivita_righe())


def _stato_agente(ricevute, inviate, adesso):
    if any(r["stato"] in ("in corso", "al lavoro") and not r.get("senza_risposta") for r in ricevute):
        return "al lavoro"
    ultima = max(ricevute + inviate, key=lambda r: r.get("fine") or r.get("inizio") or 0, default=None)
    if ultima and ultima["stato"] == "errore" and adesso - (ultima.get("fine") or 0) < 3600:
        return "errore"
    if any(r["stato"] in ("in corso", "al lavoro", "rimandato") for r in inviate):
        return "in attesa"
    return "fermo"


def agente_attivita(chiave, lavagna="generale", limite=200, solo_errori=False):
    chiave = risolvi_chiave(chiave) if not chiave.startswith("?:") else chiave
    adesso = time.time()
    schede, vicini = _schede_lavagna(lavagna)
    ricevute, inviate = [], []
    for r in attivita_righe():
        if r["a"] == chiave:
            ricevute.append(r)
        elif r["da"] == chiave:
            inviate.append(r)
    righe = []
    for verso, gruppo in (("ricevuta", ricevute), ("inviata", inviate)):
        for r in gruppo:
            controparte = r["da"] if verso == "ricevuta" else r["a"]
            righe.append({**r, "verso": verso, "controparte": controparte,
                          "avvisi": avvisi_collegamento(r["da"], r["a"], lavagna, schede, vicini)})
    righe.sort(key=lambda r: r["inizio"] or 0, reverse=True)
    durate = [r["durata_s"] for r in ricevute if r.get("durata_s")]
    contatori = {"ricevute": len(ricevute), "inviate": len(inviate),
                 "in_corso": sum(r["stato"] in ("in corso", "al lavoro") for r in ricevute),
                 "errori": sum(r["stato"] == "errore" for r in righe),
                 "rimandate": sum(r["stato"] == "rimandato" for r in righe),
                 "senza_risposta": sum(bool(r.get("senza_risposta")) for r in righe),
                 "con_avvisi": sum(any(x.get("livello") != "info" for x in r["avvisi"]) for r in righe),
                 "ultima_ts": max((r.get("fine") or r.get("inizio") or 0 for r in righe), default=None),
                 "durata_media_s": round(sum(durate) / len(durate), 1) if durate else None}
    if solo_errori:
        righe = [r for r in righe if r["stato"] in ("errore", "rimandato") or r.get("senza_risposta")
                 or any(x.get("livello") != "info" for x in r["avvisi"])]
    return {"agente": chiave, "lavagna": lavagna, "stato": _stato_agente(ricevute, inviate, adesso),
            "contatori": contatori, "righe": righe[:max(1, min(int(limite), 1000))], "ora_ts": adesso}


def agenti_attivita_sommario(lavagna="generale"):
    """Per ogni chiave: in corso, errori nelle ultime 24 ore, avvisi, ultima attività. Serve agli
    indicatori del menu laterale e delle schede; «sconosciuti» sono le richieste senza destinatario."""
    adesso, out, sconosciuti = time.time(), {}, {}
    schede, vicini = _schede_lavagna(lavagna)
    for r in attivita_righe():
        avvisi = [x for x in avvisi_collegamento(r["da"], r["a"], lavagna, schede, vicini) if x.get("livello") != "info"]
        for k, verso in ((r["a"], "ricevute"), (r["da"], "inviate")):
            if k.startswith("?:"):
                sconosciuti[k] = sconosciuti.get(k, 0) + 1
                continue
            s = out.setdefault(k, {"in_corso": 0, "errori_24h": 0, "avvisi": 0, "ricevute": 0, "inviate": 0, "ultima_ts": 0})
            s[verso] += 1
            if verso == "ricevute" and r["stato"] in ("in corso", "al lavoro") and not r.get("senza_risposta"):
                s["in_corso"] += 1
            if r["stato"] == "errore" and adesso - (r.get("fine") or r["inizio"] or 0) < 86400:
                s["errori_24h"] += 1
            if avvisi:
                s["avvisi"] += 1
            s["ultima_ts"] = max(s["ultima_ts"], r.get("fine") or r.get("inizio") or 0)
    return {"agenti": out, "sconosciuti": sconosciuti, "ora_ts": adesso}


def _sentinella_forzata():
    sentinella(forzato=True)


_sentinella_forzata.__name__ = "sentinella"     # stessa riga di salute del ciclo


# quale chiave di STATO scrive ogni raccoglitore: se fallisce, quella chiave si segna vecchia
CHIAVE_DI = {"raccogli_locale": "locale", "raccogli_vps": "vps", "raccogli_memoria": "memoria",
             "raccogli_telefono": "telefono", "raccogli_catena": "catena", "raccogli_claude": "claude",
             "raccogli_telegram": "telegram", "raccogli_portiere": "portiere", "sentinella": "sentinella",
             "raccogli_comunicazioni": "comunicazioni"}


# La salute dei raccoglitori (2026-09-26): per ognuno l'ultima lettura riuscita e l'ultimo
# errore. La pagina la mostra nel box «Salute» della scheda Stato.
SALUTE = {}
SALUTE_LOCK = threading.Lock()
AVVIO_TS = time.time()


def esegui_raccoglitore(funzione, ogni=None):
    """Un giro di un raccoglitore, con la salute segnata. Restituisce l'errore ('' se è andato).
    La usano ciclo() e l'aggiornamento forzato: una sola strada, una sola salute."""
    nome = funzione.__name__
    with SALUTE_LOCK:
        voce = SALUTE.setdefault(nome, {"nome": nome, "chiave": CHIAVE_DI.get(nome, ""), "ogni": ogni,
                                        "ultimo_ok_ts": None, "errore": ""})
        if ogni is not None:
            voce["ogni"] = ogni
        errore_prima = voce["errore"]
    try:
        funzione()
        errore = ""
    except Exception as e:  # noqa: BLE001
        errore = f"{type(e).__name__}: {e}"[:300]
        evento(f"errore nel leggere lo stato ({nome}): {e}")
        if nome in CHIAVE_DI:
            STATO.segna_errore(CHIAVE_DI[nome], errore)
    with SALUTE_LOCK:
        voce["errore"] = errore
        if not errore:
            voce["ultimo_ok_ts"] = time.time()
    if bool(errore) != bool(errore_prima):
        tocca("salute")
    return errore


def salute():
    with SALUTE_LOCK:
        righe = [dict(v) for v in SALUTE.values()]
    return {"raccoglitori": sorted(righe, key=lambda r: r["nome"]), "server_da_ts": AVVIO_TS, "pid": os.getpid()}


def ciclo(funzione, ogni):
    while True:
        esegui_raccoglitore(funzione, ogni)
        time.sleep(ogni)


# ---------------------------------------------------------------- lavori

LAVORI = {}
LAVORI_LOCK = threading.Lock()
# come rifare un lavoro (comando, cartella, funzione finale): sta fuori da LAVORI
# perché LAVORI finisce in JSON nella pagina e qui dentro ci sono funzioni
LAVORI_RICETTE = {}


def _breve(percorso):
    return str(percorso).replace(str(HOME), "~")


def nuovo_lavoro(titolo, cmd, cwd, dopo=None, codici_ok=(0,), info=None, env=None, turno=None, ricostruisci=None):
    """Un comando in background con il suo log in lavori/.

    info (facoltativo) dice alla pagina Lavori chi lavora e su cosa:
      chi, richiesta (il testo intero, non troncato), tipo, interlocutore (per
      riaprire il filo in Chat), rilanciabile (si può rifare con un clic).
    turno (sessione, id domanda) + ricostruisci (funzione che rifà il comando): le domande dello
    stesso filo partono una alla volta, in ordine, e il comando si costruisce solo al loro turno,
    quando la sessione della domanda precedente esiste già (memoria continua, 2026-10-01)."""
    import shlex
    info = dict(info or {})
    # 2026-10-03: il modo «approvazione» sceglie l'id prima (il gestore dei permessi deve saperlo) e legge
    # l'uscita stream-json mentre gira (flusso_attivita): vedi segui_attivita
    lid = info.get("id_lavoro") or nuovo_id_lavoro()
    flusso_attivita = bool(info.get("flusso_attivita"))
    log = LAVORI_DIR / f"{date.today().isoformat()}_{lid}.log"
    lav = {"id": lid, "titolo": titolo, "stato": "in corso", "inizio": datetime.now().strftime("%H:%M:%S"),
           "fine": None, "codice": None, "log": str(log), "inizio_ts": time.time(), "fine_ts": None,
           "chi": info.get("chi") or "", "dove": _breve(cwd), "tipo": info.get("tipo") or "",
           "richiesta": (info.get("richiesta") or shlex.join(str(x) for x in cmd))[:20000],
           "interlocutore": info.get("interlocutore") or "", "sessione": info.get("sessione") or "",
           "rilanciabile": bool(info.get("rilanciabile")), "attivita": []}
    # la chat del pannello dice anche in che modo è partita e con quale comando (senza il testo)
    for k in ("modo", "motore", "comando", "contesto"):
        if info.get(k):
            lav[k] = info[k]
    with LAVORI_LOCK:
        LAVORI[lid] = lav
        LAVORI_RICETTE[lid] = {"titolo": titolo, "cmd": cmd, "cwd": cwd, "dopo": dopo,
                               "codici_ok": codici_ok, "info": info, "env": env}
    evento(f"avviato: {titolo}")
    tocca("lavori")
    chat_con = lav["interlocutore"] if lav["tipo"] == "chat" else ""
    if chat_con:
        # 2026-10-02: la chat del pannello con un agente entra nella sua storia (l'utente → agente), e i
        # sottoagenti che quella sessione lancia risultano mandati da lui, non da «jarvis» (JARVIS_MITTENTE
        # lo legge il gancio jarvis_status.py)
        env = {**(env or ENV), "JARVIS_MITTENTE": chat_con}
        if attivita:
            attivita.registra("richiesta", f"l:{lid}", "utente", chat_con, lav["richiesta"], fonte="chat")
    with LAVORI_LOCK:
        copia = dict(lav)          # chi chiama riceve una copia: l'originale lo cambia il thread

    def esegui():
        comando = cmd
        with open(log, "w") as f:
            f.write(f"(cartella: {cwd})\n\n")
            f.flush()
            try:
                if turno:
                    with LAVORI_LOCK:
                        lav["in_coda"] = True
                    conversazione.aspetta_turno(*turno)
                    conversazione.avvia(*turno)
                    if ricostruisci:
                        comando = ricostruisci()
                    with LAVORI_LOCK:
                        lav["in_coda"] = False
                if flusso_attivita:
                    # l'uscita grezza (stream-json) va in <log>.flusso, fuori dalla pagina; il log avrà la risposta
                    with open(log.with_suffix(".flusso"), "w") as fl:
                        p = subprocess.Popen(comando, cwd=cwd, env=env or ENV, stdout=fl, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, start_new_session=True)
                        with LAVORI_LOCK:
                            lav["pid"] = p.pid
                        segui_attivita(lav, log.with_suffix(".flusso"), p)
                        codice = p.wait()
                else:
                    p = subprocess.Popen(comando, cwd=cwd, env=env or ENV, stdout=f, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                    with LAVORI_LOCK:          # /api/stato serializza i lavori da un altro thread
                        lav["pid"] = p.pid
                    codice = p.wait()
            except Exception as e:  # noqa: BLE001
                f.write(f"\nerrore: {e}\n")
                codice = 1
            if flusso_attivita:
                togli_config_mcp(comando)
                for a in approvazioni.chiudi_lavoro(lid):     # richieste rimaste senza nessuno che le aspetti
                    segnala_approvazione(a)
        if dopo:
            try:
                extra = dopo(log)
                if isinstance(extra, dict):
                    with LAVORI_LOCK:
                        lav.update({k: v for k, v in extra.items() if v})
            except Exception as e:  # noqa: BLE001
                with open(log, "a") as f:
                    f.write(f"\nerrore nel leggere la risposta: {e}\n")
        # 2026-10-07 (l'utente): uno «■ Ferma» voluto (SIGTERM, codice 143 o -15) non è un errore: niente bollino
        # rosso in chat, niente «lavoro in errore» per la sentinella. Il lavoro chiude «finito» con fermato=True.
        fermato = bool(lav.get("fermato"))
        ok = codice in codici_ok or fermato
        if turno:
            conversazione.chiudi(*turno, ok)
        with LAVORI_LOCK:
            lav.update(stato="finito" if ok else "errore", codice=codice,
                       fine=datetime.now().strftime("%H:%M:%S"), fine_ts=time.time())
        evento(f"{'fermato dall’utente' if fermato else 'finito' if ok else 'errore'}: {titolo}")
        tocca("lavori")
        if info.get("filo"):
            filo_risposta(dict(lav), ok)      # 2026-10-03: la risposta entra nell'archivio dei fili
        if chat_con and attivita:
            attivita.registra("risposta" if ok else "errore", f"l:{lid}", chat_con, "utente", titolo, fonte="chat",
                              esito=("(fermato da te)" if fermato else _risposta_lavoro(dict(lav))[:400]) if ok else "",
                              errore="" if ok else f"codice di uscita {codice}",
                              durata_s=round(time.time() - lav["inizio_ts"], 1))

    threading.Thread(target=esegui, daemon=True).start()
    return copia


def nuovo_id_lavoro():
    return datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]


ULTIMI_FILE = []          # schermo/stato (2026-10-03): gli ultimi file toccati dai lavori in approvazione


def segui_attivita(lav, flusso, p):
    """Legge <log>.flusso mentre claude scrive (stream-json) e aggiorna lav["attivita"] (ultime 50 voci,
    contratto sez. 2), con l'evento «attivita» sul flusso. Torna quando il processo è finito e il file letto.
    La lista si sostituisce, non si modifica sul posto: chi la sta serializzando ha la sua copia."""
    lettore = approvazioni.LettoreAttivita()
    pos, resto = 0, b""
    while True:
        finito = p.poll() is not None
        try:
            with open(flusso, "rb") as fh:
                fh.seek(pos)
                pezzo = fh.read()
                pos = fh.tell()
        except OSError:
            pezzo = b""
        righe = (resto + pezzo).split(b"\n")
        resto = righe.pop()
        if finito and resto:
            righe.append(resto)
            resto = b""
        for r in righe:
            for voce in lettore.riga(r.decode("utf-8", "replace")):
                vecchia = voce.pop("_sostituisce", None)
                with LAVORI_LOCK:
                    voci = [voce if v is vecchia else v for v in lav["attivita"]] if vecchia is not None else None
                    if voci is None or not any(v is voce for v in voci):
                        voci = (lav["attivita"] + [voce])[-50:]
                    lav["attivita"] = voci
                emetti_flusso("attivita", {"lavoro_id": lav["id"], "voce": voce})
        if lettore.file:
            with LAVORI_LOCK:
                ULTIMI_FILE[:] = ([x for x in ULTIMI_FILE if x not in lettore.file] + lettore.file)[-10:]
        if finito:
            return
        time.sleep(0.3)


def lavoro_in_corso():
    """2026-10-05 (Aggiorna ora): le chat, i lavori e le missioni che un riavvio del pannello interromperebbe."""
    with LAVORI_LOCK:
        out = [f"{l.get('tipo') or 'lavoro'}: {str(l.get('titolo') or '')[:60]}" for l in LAVORI.values() if l.get("stato") == "in corso"]
    try:
        out += [f"missione: {str(m.get('progetto') or m.get('id') or '')[:60]}" for m in missioni()
                if m.get("stato") not in ("chiusa", "errore", "interrotta")]
    except Exception:  # noqa: BLE001 — una cartella rotta non deve fermare l'aggiornamento
        pass
    return out


def lavoro_copia(lid):
    """Una copia del lavoro presa sotto il lock (None se non c'è)."""
    with LAVORI_LOCK:
        lav = LAVORI.get(lid)
        return dict(lav) if lav else None


def togli_lavoro(lid):
    """Toglie un lavoro dalla pagina. Il log resta in lavori/: si pulisce la lista, non la storia."""
    with LAVORI_LOCK:
        lav = LAVORI.get(lid)
        if not lav:
            raise ValueError("lavoro non trovato")
        if lav["stato"] == "in corso":
            raise ValueError("è ancora in corso: prima fermalo")
        LAVORI.pop(lid, None)
        LAVORI_RICETTE.pop(lid, None)
    return lav


def rilancia_lavoro(lid):
    r = LAVORI_RICETTE.get(lid)
    if not r or not (lavoro_copia(lid) or {}).get("rilanciabile"):
        raise ValueError("questo lavoro non si rilancia da qui")
    info = {k: v for k, v in (r["info"] or {}).items() if k != "id_lavoro"}     # un id nuovo, sempre
    return nuovo_lavoro(r["titolo"], r["cmd"], r["cwd"], dopo=r["dopo"], codici_ok=r["codici_ok"], info=info,
                        env=r.get("env"))


def agenti_crm():
    out = []
    for f in sorted((CRM / ".claude" / "agents").glob("*.md")):
        try:
            testo = spazi.leggi_testo(f)
        except OSError:
            testo = ""            # file ancora nella nuvola di OneDrive: l'agente c'è, la descrizione arriva dopo
        m = re.search(r"^description:\s*(.+)$", testo, re.M)
        desc = m.group(1).strip().strip('"').split(". ")[0][:160] if m else ""
        out.append({"id": f.stem, "descrizione": desc})
    return out


def elenco_spazi():
    """Gli spazi per la pagina: spazio → progetto → capogruppo in cima → esperti col modello.

    Fino al 23/09/2026 le missioni prendevano i progetti da projects-index.md e il
    caposquadra con un glob `ceo*.md` (che prendeva anche `vice-ceo-*`). Oggi la
    fonte è spazi.json: il capogruppo è scritto lì, non indovinato dal nome."""
    out = []
    for s in spazi.carica():
        progetti = []
        viste = set()          # cartelle già lette in questo spazio: vedi nota di _tutti_profili()
        for pr in s["progetti"]:
            gia_letta = pr["cartella"] in viste
            agenti = [{k: a[k] for k in ("nome", "modello", "capogruppo", "file", "strumenti", "tono", "umorismo", "serieta",
                                         "attivo", "comunica", "riporta_a", "aggiornato_ts")} |
                      {"descrizione": a["descrizione"].split(". ")[0][:160]}
                      for a in spazi.profili(pr["cartella"], pr.get("capogruppo"))] if pr["esiste"] and not gia_letta else []
            # 02/10/2026 (audit menu, P8): gli agenti tolti (in .claude/agents/_archivio), per la riga grigia «Ripristina».
            # NOME_AGENTE.fullmatch scarta le copie datate nome.AAAAMMGG-HHMMSS.md; chi ha di nuovo il profilo vivo non conta.
            arch_dir = Path(pr["cartella"]) / ".claude" / "agents" / "_archivio"
            vivi = {a["nome"] for a in agenti}
            archiviati = sorted(f.stem for f in arch_dir.glob("*.md")
                                if NOME_AGENTE.fullmatch(f.stem) and f.stem not in vivi) \
                if pr["esiste"] and not gia_letta and arch_dir.is_dir() else []
            if pr["esiste"]:
                viste.add(pr["cartella"])
            progetti.append({"id": pr["id"], "nome": pr["nome"], "cartella": pr["cartella"].replace(str(HOME), "~"),
                             "capogruppo": pr.get("capogruppo"), "esiste": pr["esiste"], "agenti": agenti,
                             "sezioni_memoria": pr.get("sezioni_memoria") or [], "archiviati": archiviati})
        out.append({"id": s["id"], "nome": s["nome"], "sistema": bool(s.get("sistema")), "progetti": progetti,
                    "memoria": s.get("memoria", "").replace(str(HOME), "~"), "report": s.get("report", "").replace(str(HOME), "~")})
    return out


def _file_agente_lecito(percorso):
    """Solo i file .md degli agenti che spazi.json elenca davvero: mai un path a piacere."""
    try:
        p = Path(percorso).resolve()
    except (OSError, ValueError):
        return None
    for s in spazi.carica():
        for pr in s["progetti"]:
            if not pr["esiste"]:
                continue
            for a in spazi.profili(pr["cartella"], pr.get("capogruppo")):
                if Path(a["file"]).resolve() == p:
                    return p
    return None


def scrivi_atomico(percorso, testo):
    """Scrive un file che esiste già senza mai lasciarlo a metà: file temporaneo nella stessa
    cartella, poi os.replace(). La cartella dell'utente è su OneDrive: un open(..., "w") diretto
    tronca il file e per un attimo OneDrive (o il PC dell'amministrazione) può vederlo vuoto."""
    import tempfile
    percorso = Path(percorso)
    fd, tmp = tempfile.mkstemp(prefix=f".{percorso.name}.", suffix=".tmp", dir=str(percorso.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(testo)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, percorso.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, percorso)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def riscrivi_frontmatter(testo, aggiornamenti):
    """(testo nuovo, chiavi cambiate): tocca solo le righe che cambiano davvero (spazi.py)."""
    return spazi.aggiorna_frontmatter(testo, aggiornamenti)


_MARCA_COMUNICA_INI = "<!-- comunica-con:inizio (scritto dalla lavagna del Command Center, non toccare a mano) -->"
_MARCA_COMUNICA_FINE = "<!-- comunica-con:fine -->"


def _leggi_env_valore(chiave, file=None):
    file = file or (AGENTE / ".env")
    try:
        for riga in file.read_text().splitlines():
            if riga.startswith(chiave + "="):
                return riga.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def manda_telegram_utente(testo):
    """Avvisa l'utente su Telegram (bot Jarvis) di un cambiamento fatto dalla
    lavagna: un collegamento creato o tolto, deciso da lui col mouse, non un
    log da andare a leggere. Se manca il token o la chat, non fa niente — non
    deve mai bloccare il salvataggio del profilo per un avviso mancato. Se
    Telegram rifiuta la richiesta (token scaduto, per esempio) lo scrive
    comunque nel registro eventi: fallisce silenzioso verso l'utente, mai
    silenzioso e basta — altrimenti un token rotto non si nota più."""
    token = _leggi_env_valore("TELEGRAM_JARVIUTENTE_TOKEN")
    chat_id = _leggi_env_valore("TELEGRAM_UTENTE_CHAT_ID")
    if not token or not chat_id:
        evento("notifica Telegram non mandata: manca TELEGRAM_JARVIUTENTE_TOKEN o TELEGRAM_UTENTE_CHAT_ID in .env")
        return
    try:
        dati = json.dumps({"chat_id": chat_id, "text": testo}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=dati, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except urllib.error.HTTPError as e:
        evento(f"notifica Telegram rifiutata ({e.code}): il token del bot potrebbe essere scaduto o revocato")
    except (urllib.error.URLError, OSError) as e:
        evento(f"notifica Telegram non mandata: {e}")


def notifica_utente(testo, titolo="Avviso", chi="jarvis"):
    """2026-10-05 (decisione dell'utente): gli avvisi vanno nel filo «Notifiche Jarvis» della chat, non su Telegram.
    Sulla VPS (la fonte) si scrive qui; sul Mac si passa alla VPS con strumenti/notifica.py (ssh), che usa
    Telegram solo se la VPS non risponde. Mai bloccante: chiamala in un thread."""
    try:
        if sys.platform.startswith("linux"):
            r = fili.notifica(chi, titolo, testo)
            if (CFG.get("notifiche") or {}).get("telegram_copia"):
                manda_telegram_utente(f"{titolo}\n\n{testo}")
            return r
        if sys.platform == "win32":
            return manda_telegram_utente(testo)
        out = subprocess.run([sys.executable, str(STRUMENTI_JARVIS / "notifica.py"), "manda", "--chi", chi,
                              "--titolo", titolo, "--testo", testo], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            evento(f"notifica non arrivata nel filo: {(out.stdout or out.stderr).strip()[:160]}")
    except Exception as e:  # noqa: BLE001
        evento(f"notifica non mandata ({type(e).__name__}: {str(e)[:120]})")


def aggiorna_comunica_con(testo, nomi):
    """Sostituisce (o toglie, se nomi è vuoto) la sezione «Comunica con» nel
    corpo del profilo, tenendo intatto il resto: quello che l'agente legge di
    sé, aggiornato subito quando l'utente lo collega a un altro nella lavagna."""
    testa, corpo = spazi.separa(testo)
    pattern = re.escape(_MARCA_COMUNICA_INI) + r".*?" + re.escape(_MARCA_COMUNICA_FINE)
    corpo_pulito = re.sub(pattern, "", corpo, flags=re.S).rstrip()
    sezione = ""
    if nomi:
        elenco = ", ".join(nomi)
        sezione = (f"\n\n{_MARCA_COMUNICA_INI}\n## Comunica con\n\n"
                   f"L'utente ha collegato questo agente ad altri nella lavagna del Command Center: "
                   f"comunica con {elenco}.\n{_MARCA_COMUNICA_FINE}")
    # il frontmatter resta com'è scritto (prima si ricostruiva e «tools:» diventava «tools: ""»); dal
    # 2026-09-26 sera cambia solo la riga «comunica», così frontmatter e sezione dicono la stessa cosa
    if testa:
        testa, _ = spazi.aggiorna_frontmatter(testa, {"comunica": ", ".join(nomi)})
    return testa + corpo_pulito + sezione + "\n"


ATTESA_CONFERMA_S = 30 * 60          # stessa attesa di missione.py: oltre, la richiesta è scaduta


def leggi_missione(d):
    conf = leggi_json(d / "missione.json", {})
    st = leggi_json(d / "stato.json", {"stato": "in avvio"})
    richieste = []
    for f in sorted((d / "richieste").glob("*.json")):
        if f.name.endswith(".risposta.json") or (d / "richieste" / f"{f.stem}.risposta.json").exists():
            continue
        try:
            if time.time() - f.stat().st_mtime > ATTESA_CONFERMA_S:
                continue              # scaduta: la missione non la aspetta più, un Sì non farebbe niente
        except OSError:
            continue
        richieste.append(leggi_json(f, {}))
    vivo = st.get("stato") in ("chiusa", "errore") or (conf.get("pid") and _missione_viva(conf["pid"], d))
    if not vivo and not conf.get("pid") and _eta_missione(d) < 60:
        # 27/09/2026: lancia_missione scrive missione.json prima col pid assente e poi col pid; in
        # quell'attimo la missione non è morta, è in avvio (un clic la archiviava come «interrotta»)
        vivo = True
        st["stato"] = "in avvio"
    if not vivo and st.get("stato") not in ("chiusa", "errore"):
        st["stato"] = "interrotta"
    if st.get("stato") in ("chiusa", "errore", "interrotta"):
        richieste = []                # a missione finita nessuno aspetta più un Sì
    albero = leggi_json(d / "agenti.json", {})
    progetti_m = conf.get("progetti") or []
    nome_prog = conf.get("progetto") or " + ".join(p["nome"] for p in progetti_m)
    return {"id": d.name, "progetto": nome_prog, "ceo": conf.get("ceo"),
            "spazio": conf.get("spazio_nome"), "capogruppi": [p.get("capogruppo") for p in progetti_m if p.get("capogruppo")],
            "modalita": conf.get("modalita"), "max_paralleli": conf.get("max_paralleli"),
            "obiettivo": conf.get("obiettivo"), "inizio": conf.get("inizio"),
            "stato": st.get("stato"), "richieste": richieste, "agenti": albero.get("agenti") or [],
            "report": conf.get("report_file") if conf.get("report_file") and Path(conf["report_file"]).exists() else ""}


def _eta_missione(d):
    """Secondi dalla nascita della missione: dal nome della cartella (AAAA-MM-GG_HHMMSS), se no dal mtime."""
    try:
        return time.time() - datetime.strptime(d.name[:17], "%Y-%m-%d_%H%M%S").timestamp()
    except ValueError:
        try:
            return time.time() - d.stat().st_mtime
        except OSError:
            return float("inf")


def _pid_vivo(pid):
    """True se un processo con quel pid esiste. PermissionError = esiste, ma non è nostro."""
    if sys.platform == "win32":
        # su Windows os.kill(pid, 0) NON controlla: termina il processo. Si guarda l'elenco dei processi.
        try:
            return int(pid) in {p for p, _ in _processi_windows()}
        except (ValueError, TypeError, OverflowError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return False


def _missione_viva(pid, cartella):
    """Il pid salvato è ancora il processo missione.py di QUESTA missione?

    Dopo un riavvio del Mac il sistema riassegna i pid: controllare solo che il pid esista
    lasciava la missione «in corso» per sempre. Si guarda il comando vero con ps."""
    if not _pid_vivo(pid):
        return False
    if sys.platform == "win32":
        comando = next((c for p, c in _processi_windows() if p == int(pid)), "")
        return "missione.py" in comando and Path(cartella).name in comando
    codice, out = sh(["ps", "-o", "command=", "-p", str(int(pid))], timeout=5)
    if codice == 124:
        return True                   # ps non ha risposto: meglio non dichiararla interrotta
    comando = out.strip()
    return codice == 0 and "missione.py" in comando and Path(cartella).name in comando


ARCHIVIO_LOCK = threading.Lock()


def archivia_missione(d):
    """Toglie la missione dal pannello: la cartella va in missioni_archivio, recuperabile.
    False se nel frattempo l'ha già spostata qualcun altro."""
    with ARCHIVIO_LOCK:
        if not d.is_dir():
            return False
        dest = ARCHIVIO_MISSIONI_DIR / d.name
        if dest.exists():
            dest = ARCHIVIO_MISSIONI_DIR / f"{d.name}_{datetime.now():%H%M%S}"
        try:
            shutil.move(str(d), str(dest))
        except FileNotFoundError:
            return False
        return True


def archivia_missioni_vecchie():
    """Una missione chiusa resta nel pannello, chiusa a tendina, per 24 ore (layout dell'utente del
    23/09/2026); poi va in archivio da sola. Gira nel suo ciclo di sfondo: fino al 26/09/2026 lo
    faceva la GET di /api/stato, e due schede aperte spostavano la stessa cartella due volte."""
    # 27/09/2026: anche «errore» e «interrotta» (stato calcolato da leggi_missione): prima restavano
    # nel pannello per sempre. L'età è l'ultima scrittura di stato.json, o della cartella se manca.
    for d in [p for p in MISSIONI_DIR.iterdir() if p.is_dir()]:
        try:
            f = d / "stato.json"
            vecchia = time.time() - (f if f.exists() else d).stat().st_mtime > 24 * 3600
        except OSError:
            continue
        if not vecchia:
            continue
        st = leggi_missione(d)["stato"]
        if st in ("chiusa", "errore", "interrotta") and archivia_missione(d):
            evento(f"missione {d.name} ({st}) archiviata dopo 24 ore")


def missioni():
    out = []
    for d in sorted((p for p in MISSIONI_DIR.iterdir() if p.is_dir()), reverse=True):
        out.append(leggi_missione(d))
    return out


def cartella_missione(mid):
    if not re.fullmatch(r"[\w-]+", mid or ""):
        raise ValueError("missione non valida")
    d = MISSIONI_DIR / mid
    if not d.is_dir():
        raise ValueError("missione non trovata")
    return d


CONFIG_FILE = QUI / "configurazione.json"
MODI_CHAT = ("lavoro", "lettura", "approvazione")     # «approvazione» dal 2026-10-03


def config_caldo(chiave, default=None):
    """Una voce di configurazione.json letta adesso, non all'avvio: l'interruttore in chat
    e quello della sentinella valgono dal clic dopo, senza riavviare il pannello."""
    return leggi_json(CONFIG_FILE, {}).get(chiave, default)


def scrivi_config(chiave, valore):
    """Cambia una sola voce di configurazione.json e lascia le altre come sono."""
    with CONFIG_LOCK:
        d = leggi_json(CONFIG_FILE, None)
        if not isinstance(d, dict):
            raise ValueError("configurazione.json manca o non è JSON valido: non la riscrivo")
        d[chiave] = valore
        scrivi_atomico(CONFIG_FILE, json.dumps(d, ensure_ascii=False, indent=2) + "\n")


CONFIG_LOCK = threading.Lock()


def modo_chat():
    """«lavoro» (default, decisione dell'utente del 2026-09-26: permessi pieni, guardia accesa), «lettura» o
    «approvazione» (2026-10-03: modalità normale, i permessi li decide l'utente dal pannello)."""
    m = config_caldo("modo_chat", "lavoro")
    return m if m in MODI_CHAT else "lavoro"


def claude_comando(richiesta, agente=None, modo=None, lavoro_id=None, sessione=None, chi=None, cwd=None):
    """claude -p per la chat del pannello, nel modo scelto (se non è detto, quello di configurazione.json).

    lavoro  = --dangerously-skip-permissions: lavora davvero. La guardia dei comandi
              (~/.claude/hooks/guardia_comandi.py) è un hook PreToolUse e vale anche col bypass.
    lettura = --permission-mode plan: legge e riferisce, non modifica.
    approvazione (2026-10-03) = --permission-mode default (esplicito: in ~/.claude/settings.json
              defaultMode è bypassPermissions) + --permission-prompt-tool verso approvazioni_mcp.py;
              --settings mette in «ask» Bash, le scritture, gli strumenti delle regole «chiedi» e «nega»
              e tutte le regole «allow» dei settings dell'utente, così decide solo il file delle regole
              (regole_permessi.py, dal 2026-10-03 sera); --output-format
              stream-json --verbose per le attività in diretta. La guardia (hook) resta accesa.
    Fino al 2026-09-26 si chiamava claude_lettura ed era sempre in plan."""
    modo = modo_sicuro(modo if modo in MODI_CHAT else modo_chat())
    if modo == "approvazione":
        conf = config_mcp_approvazioni(lavoro_id, sessione, chi or agente, cwd)
        # revisione 2 (2026-10-03): --setting-sources user = niente settings di progetto (le «allow» del CRM su
        # OneDrive, i suoi hook, le additionalDirectories); il CLAUDE.md della cartella di lavoro arriva con
        # --add-dir + CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD (provato: senza, il CLAUDE.md di progetto non si legge)
        impostazioni = {"permissions": {"ask": approvazioni.regole_ask()},
                        "env": {"CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1"}}
        cmd = ["claude", "-p", richiesta, "--permission-mode", "default", "--setting-sources", "user",
               "--permission-prompt-tool", "mcp__approvazioni__approva", "--mcp-config", str(conf),
               "--settings", json.dumps(impostazioni, ensure_ascii=False),
               "--output-format", "stream-json", "--verbose"]
        if cwd:
            cmd += ["--add-dir", str(cwd)]
            agenti = agenti_di_progetto(cwd)       # senza i settings di progetto, i suoi agenti si passano a mano
            if agenti:
                cmd += ["--agents", json.dumps(agenti, ensure_ascii=False)]
        if agente:
            cmd += ["--agent", agente]
        return cmd
    permessi = ["--dangerously-skip-permissions"] if modo == "lavoro" else ["--permission-mode", "plan"]
    cmd = ["claude", "-p", richiesta, *permessi, "--output-format", "json"]
    if agente:
        cmd += ["--agent", agente]
    return cmd


# 2026-10-05: su Linux un solo argomento sta sotto 131.072 byte (MAX_ARG_STRLEN); il CRM ne faceva 148.009 e
# Popen moriva con E2BIG, la chat con gli agenti restava muta. Il Mac regge argomenti molto più lunghi.
AGENTI_MAX_BYTE = 120_000 if sys.platform.startswith("linux") else 400_000


def agenti_di_progetto(cwd, massimo=AGENTI_MAX_BYTE):
    """Gli agenti di <cwd>/.claude/agents/*.md nella forma di --agents (revisione 2, 2026-10-03): con
    --setting-sources user claude non li carica più da solo (provato: «--agent … not found»)."""
    out, totale = {}, 0
    try:
        files = sorted((Path(cwd) / ".claude" / "agents").glob("*.md"))
    except OSError:
        return {}
    for f in files[:60]:
        try:
            testo = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", testo, re.S)
        testa, corpo = (m.group(1), m.group(2)) if m else ("", testo)
        campi = {}
        for riga in testa.splitlines():
            k, sep, v = riga.partition(":")
            if sep and re.fullmatch(r"[\w-]+", k.strip()):
                campi[k.strip()] = v.strip().strip('"').strip("'")
        nome = campi.get("name") or f.stem
        if not re.fullmatch(r"[\w.-]{1,64}", nome) or not corpo.strip():
            continue
        a = {"description": campi.get("description") or nome, "prompt": corpo.strip()}
        if campi.get("model") in ("haiku", "sonnet", "opus", "inherit"):
            a["model"] = campi["model"]
        if campi.get("tools"):
            a["tools"] = [t.strip() for t in campi["tools"].split(",") if t.strip()]
        totale += len(a["prompt"]) + len(a["description"])
        if totale > massimo:
            break
        out[nome] = a
    return out


def config_mcp_approvazioni(lavoro_id=None, sessione=None, chi=None, cwd=None):
    """Il --mcp-config del gestore dei permessi, in un file 0600 nella cartella delle approvazioni (fuori
    da git e da OneDrive). Un file per lavoro: lo si ricostruisce uguale al turno della domanda e si
    cancella a lavoro finito (togli_config_mcp). Niente token né segreti: solo a chi appartiene la richiesta."""
    d = approvazioni.cartella() / "mcp"
    d.mkdir(mode=0o700, exist_ok=True)
    nome = re.sub(r"[^\w-]", "", str(lavoro_id or "")) or uuid.uuid4().hex
    env = {"CC_LAVORO_ID": str(lavoro_id or ""), "CC_SESSIONE": str(sessione or ""), "CC_AGENTE": str(chi or "Jarvis"),
           "CC_APPROVAZIONI_DIR": str(approvazioni.cartella()), "CC_CONFIG": str(CONFIG_FILE)}
    if cwd:
        env["CC_CWD"] = str(cwd)
    for k in ("CC_APPROVAZIONI_SCADENZA_S", "CC_REGOLE_FILE", "CC_REGISTRO_DIR"):    # solo le prove li mettono
        if os.environ.get(k):
            env[k] = os.environ[k]
    conf = {"mcpServers": {"approvazioni": {"type": "stdio", "command": sys.executable or "python3",
                                            "args": [str(QUI / "approvazioni_mcp.py")], "env": env}}}
    f = d / f"{nome}.json"
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as h:
        json.dump(conf, h)
    os.chmod(f, 0o600)
    return f


def togli_config_mcp(cmd):
    """Cancella il file dato a --mcp-config (se il comando ne ha uno nostro)."""
    try:
        i = list(cmd).index("--mcp-config")
        f = Path(cmd[i + 1])
        if f.parent == approvazioni.cartella() / "mcp":
            f.unlink(missing_ok=True)
    except (ValueError, IndexError, OSError):
        pass


def comando_breve(cmd, richiesta):
    """Il comando lanciato, con il testo della richiesta sostituito: si vede il modo, non il testo."""
    import shlex
    cmd = list(cmd)
    for i in range(1, len(cmd)):         # le regole «ask» del modo approvazione sono lunghe: non servono a leggere
        if cmd[i - 1] == "--settings":
            cmd[i] = "<regole ask>"
    return shlex.join("<richiesta>" if (x == richiesta or (len(str(x)) > 40 and str(x).endswith(richiesta)))
                      else str(x) for x in cmd)[:400]


# ---------------------------------------------------------------- pannello a tre colonne
# Layout stile un'app esterna del 24/09/2026: gruppi della colonna agenti, aspetto degli
# agenti (emoji e colore) e lavagna (schede e dipendenze). È solo disposizione:
# niente segreti, quindi può stare qui, su OneDrive, e vale anche per il PC.

PANNELLO_FILE = QUI / "pannello.json"
PANNELLO_LOCK = threading.Lock()
PANNELLO_STORIA = QUI / "pannello-storia"       # le ultime 50 versioni, per tornare indietro
LIMITI_PANNELLO = {"lavagne": 200, "nodi": 1000, "fili": 2000}
_ID = r"[\w .:@#+-]{1,120}"


def _testo(v, massimo=200):
    return str(v or "")[:massimo]


def _lista(v):
    return v if isinstance(v, list) else []


def _diz(v):
    return v if isinstance(v, dict) else {}


def _num(v, default=0.0):
    """float finito o ValueError (NaN e infinito non sono JSON validi per la pagina)."""
    x = float(default if v is None else v)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("numero non finito")
    return x


def pulisci_pannello(d):
    """Tiene solo le chiavi note, con tipi e misure giuste: la pagina scrive, il
    server non si fida. 27/09/2026: un tipo sbagliato (lista al posto di oggetto, testo al posto
    di lista) si scarta invece di dare 500."""
    if not isinstance(d, dict):
        raise ValueError("pannello: serve un oggetto")
    gruppi = []
    for g in _lista(d.get("gruppi"))[:40]:
        if not isinstance(g, dict) or not re.fullmatch(_ID, str(g.get("id", ""))):
            continue
        gruppi.append({"id": g["id"], "nome": _testo(g.get("nome"), 60) or "Gruppo",
                       "chiuso": bool(g.get("chiuso")),
                       "agenti": [a for a in _lista(g.get("agenti"))[:200]
                                  if isinstance(a, str) and re.fullmatch(_ID, a)]})
    aspetto = {}
    for k, v in list(_diz(d.get("aspetto")).items())[:400]:
        if re.fullmatch(_ID, str(k)) and isinstance(v, dict):
            colore = str(v.get("colore") or "")
            aspetto[k] = {"emoji": _testo(v.get("emoji"), 8),
                          "colore": colore if re.fullmatch(r"#[0-9a-fA-F]{6}", colore) else "",
                          "nome": _testo(v.get("nome"), 60).strip(), "nota": _testo(v.get("nota"), 400)}
    def pulisci_lavagna(lav):
        lav = _diz(lav)
        nodi = []
        if len(_lista(lav.get("nodi"))) > LIMITI_PANNELLO["nodi"]:
            raise ValueError(f"lavagna: più di {LIMITI_PANNELLO['nodi']} schede, non salvo per non perderne")
        for n in _lista(lav.get("nodi")):
            if not isinstance(n, dict) or not re.fullmatch(_ID, str(n.get("id", ""))):
                continue
            try:
                x, y = _num(n.get("x", 0)), _num(n.get("y", 0))
            except (TypeError, ValueError):
                continue
            nodi.append({"id": n["id"], "tipo": "nota" if n.get("tipo") == "nota" else "agente",
                         "agente": _testo(n.get("agente"), 120), "testo": _testo(n.get("testo"), 2000),
                         "x": max(-50000, min(50000, x)), "y": max(-50000, min(50000, y))})
        ids = {n["id"] for n in nodi}
        fili = []
        if len(_lista(lav.get("fili"))) > LIMITI_PANNELLO["fili"]:
            raise ValueError(f"lavagna: più di {LIMITI_PANNELLO['fili']} fili, non salvo per non perderne")
        for f in _lista(lav.get("fili")):
            if isinstance(f, dict) and f.get("da") in ids and f.get("a") in ids and f["da"] != f["a"]:
                fili.append({"da": f["da"], "a": f["a"]})
        vista = _diz(lav.get("vista"))
        try:
            vista = {"x": _num(vista.get("x", 0)), "y": _num(vista.get("y", 0)),
                     "zoom": max(.05, min(2.5, _num(vista.get("zoom", 1))))}
        except (TypeError, ValueError):
            vista = {"x": 0, "y": 0, "zoom": 1}
        # le bolle delle sinapsi spostate dall'utente (2026-09-26): chiave agente -> scostamento
        bolle = {}
        for k, v in list(_diz(lav.get("bolle")).items())[:200]:
            if re.fullmatch(_ID, str(k)) and isinstance(v, dict):
                try:
                    bolle[k] = {"dx": max(-4000, min(4000, _num(v.get("dx", 0)))),
                                "dy": max(-4000, min(4000, _num(v.get("dy", 0))))}
                except (TypeError, ValueError):
                    continue
        return {"nodi": nodi, "fili": fili, "vista": vista, "bolle": bolle, "titolo": _testo(lav.get("titolo"), 80)}

    # una lavagna per gruppo (decisione dell'utente del 25/09/2026): dati vecchi con
    # una sola "lavagna" diventano la lavagna "generale", non si perdono.
    lavagne_in = d.get("lavagne")
    if not isinstance(lavagne_in, dict):
        lavagne_in = {"generale": _diz(d.get("lavagna"))}
    lavagne = {}
    if len(lavagne_in) > LIMITI_PANNELLO["lavagne"]:
        raise ValueError(f"più di {LIMITI_PANNELLO['lavagne']} lavagne: non salvo per non perderne")
    for k, v in lavagne_in.items():
        if re.fullmatch(_ID, str(k)) or k == "generale":
            lavagne[k] = pulisci_lavagna(v if isinstance(v, dict) else {})
    if not lavagne:
        lavagne = {"generale": pulisci_lavagna({})}
    return {"gruppi": gruppi, "aspetto": aspetto, "lavagne": lavagne,
            "aggiornato": datetime.now().isoformat(timespec="seconds")}


def leggi_pannello():
    """Il pannello sul disco. File assente = pannello vuoto (versione 0). File illeggibile = ECCEZIONE:
    prima diventava {} e la pagina, credendolo vuoto, lo riscriveva vuoto sopra quello vero."""
    if not PANNELLO_FILE.exists():
        return {"gruppi": [], "aspetto": {}, "lavagne": {}, "versione": 0}
    d = json.loads(PANNELLO_FILE.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise ValueError("pannello.json non è un oggetto")
    d.setdefault("versione", 0)
    return d


def _versione_di(d):
    try:
        return int(d.get("versione") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _conta_nodi(d):
    return sum(len(_lista(_diz(L).get("nodi"))) for L in _diz(_diz(d).get("lavagne")).values())


def _scrivi_pannello_sotto_lock(pulito, attuale):
    """Chi chiama tiene PANNELLO_LOCK. Copia di sicurezza della versione che si sostituisce, poi scrive.
    2026-10-05 (fonte unica): sul Mac, con la VPS raggiungibile e niente modifiche locali in sospeso, scrive
    sulla VPS e pannello.json diventa la sua copia; altrimenti scrive qui e fonte_vps riporta tutto dopo."""
    remoto = _pannello_sulla_vps(pulito, attuale)
    if remoto is not None:
        return remoto
    pulito["versione"] = _versione_di(attuale) + 1
    try:
        PANNELLO_STORIA.mkdir(exist_ok=True)
        (PANNELLO_STORIA / f"pannello-v{_versione_di(attuale):07d}.json").write_text(
            json.dumps(attuale, ensure_ascii=False), encoding="utf-8")
        for vecchio in sorted(PANNELLO_STORIA.glob("pannello-v*.json"))[:-50]:
            vecchio.unlink(missing_ok=True)
    except OSError:
        pass
    scrivi_atomico(PANNELLO_FILE, json.dumps(pulito, ensure_ascii=False, indent=1))
    return pulito


def _pannello_sulla_vps(pulito, attuale):
    """Chi chiama tiene PANNELLO_LOCK. Il pannello scritto sulla VPS (e già copiato qui), o None = scrivi in locale."""
    if not fonte_vps.attiva() or fonte_vps.LAVAGNA.sporco(attuale):
        return None
    corpo = {**pulito, "versione": _versione_di(attuale), "svuota": True}   # lo svuotamento l'ha già vagliato chi chiama
    r = fonte_vps.inoltra("POST", "/api/pannello", corpo)
    if r and r[0] == 409 and isinstance(r[1], dict) and isinstance(r[1].get("pannello"), dict):
        # la VPS è andata avanti nel frattempo: fusione a tre vie e un secondo tentativo
        vps = r[1]["pannello"]
        fuso = pulisci_pannello(fonte_vps.fondi(attuale, pulito, vps))
        r = fonte_vps.inoltra("POST", "/api/pannello", {**fuso, "versione": _versione_di(vps), "svuota": True})
    if not r or r[0] != 200 or not isinstance(r[1], dict):
        if r:
            evento(f"lavagna: la VPS ha rifiutato la modifica ({r[0]}: {str((r[1] or {}).get('errore'))[:120]}), salvata sul Mac")
        return None
    fonte_vps.LAVAGNA._segna_allineato(r[1])
    return r[1]


def _copia_locale_semplice(percorso, d):
    """La copia sul Mac di aspetto e barra in alto, per quando la VPS non risponde."""
    try:
        if percorso == "/api/aspetto":
            import aspetto
            if not d.get("predefinito"):
                aspetto._scrivi({k: d[k] for k in ("tema", "avatar", "fermi", "v") if k in d})
        elif percorso == "/api/menu":
            import menu_barra
            if not d.get("predefinito"):
                menu_barra.scrivi({"ordine": d.get("ordine"), "in_barra": d.get("in_barra")})
    except Exception as e:  # noqa: BLE001 — la copia è solo un paracadute
        evento(f"fonte unica: copia locale di {percorso} non scritta ({type(e).__name__})")


def _stato_semplice_dalla_vps(percorso):
    """GET di aspetto o barra dalla VPS (sul Mac). None = leggi la copia locale. Se il Mac ha una scelta fatta
    con la VPS giù (segnata in fonte-vps.json), prima la riporta sulla VPS."""
    if not fonte_vps.attiva():
        return None
    sospesi = fonte_vps.FONTE.leggi_stato().get("sospesi") or {}
    if percorso in sospesi:
        r = fonte_vps.inoltra("POST", percorso, sospesi[percorso])
        if not r or r[0] != 200:
            return None
        sospesi.pop(percorso, None)
        fonte_vps.FONTE.metti_stato(sospesi=sospesi)
    r = fonte_vps.inoltra("GET", percorso)
    if not r or r[0] != 200 or not isinstance(r[1], dict):
        return None
    _copia_locale_semplice(percorso, r[1])
    return r[1]


def _stato_semplice_sulla_vps(percorso, corpo):
    """POST di aspetto o barra sulla VPS (sul Mac): (codice, dati) o None = scrivi in locale (e ricordalo)."""
    if not fonte_vps.attiva():
        return None
    r = fonte_vps.inoltra("POST", percorso, corpo)
    if r is None:
        sospesi = fonte_vps.FONTE.leggi_stato().get("sospesi") or {}
        sospesi[percorso] = {**(sospesi.get(percorso) or {}), **corpo} if isinstance(corpo, dict) else corpo
        fonte_vps.FONTE.metti_stato(sospesi=sospesi)
        return None
    if r[0] == 200 and isinstance(r[1], dict):
        _copia_locale_semplice(percorso, r[1])
    return r


def _specchio_pannello(d):
    """fonte_vps: pannello.json del Mac = il pannello della VPS, così com'è (versione compresa)."""
    scrivi_atomico(PANNELLO_FILE, json.dumps(d, ensure_ascii=False, indent=1))


def applica_ops_pannello(d, ops):
    """Le modifiche per scheda (stesse regole di applicaOps() in app.js): ogni operazione tocca solo
    quello che nomina, così due schede del browser che spostano schede diverse non si cancellano."""
    lavagne = d.setdefault("lavagne", {})
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("operazione: serve un oggetto")
        t, k = op.get("op"), str(op.get("lavagna") or "")
        if t == "gruppi":
            d["gruppi"] = _lista(op.get("gruppi"))
        elif t == "aspetto":
            asp = d.setdefault("aspetto", {})
            if op.get("valore") is None:
                asp.pop(str(op.get("chiave")), None)
            else:
                asp[str(op.get("chiave"))] = _diz(op.get("valore"))
        elif t == "togli_lavagna":
            lavagne.pop(k, None)
        elif t in ("nodi", "togli_nodi", "fili_aggiungi", "fili_togli", "vista", "bolle", "titolo"):
            if not re.fullmatch(_ID, k):
                raise ValueError("lavagna: id non valido")
            L = lavagne.setdefault(k, {"nodi": [], "fili": [], "vista": {"x": 0, "y": 0, "zoom": 1}})
            L.setdefault("nodi", [])
            L.setdefault("fili", [])
            if t == "nodi":
                per_id = {n.get("id"): n for n in L["nodi"] if isinstance(n, dict)}
                for n in _lista(op.get("nodi")):
                    if not isinstance(n, dict):
                        continue
                    if n.get("id") in per_id:
                        per_id[n["id"]].update(n)
                    elif n.get("tipo") == "agente" and any(z.get("agente") == n.get("agente") for z in L["nodi"]):
                        continue            # due schede del browser hanno messo lo stesso agente: una scheda sola
                    else:
                        L["nodi"].append(dict(n))
                        per_id[n.get("id")] = L["nodi"][-1]
            elif t == "togli_nodi":
                via = {str(x) for x in _lista(op.get("ids"))}
                L["nodi"] = [n for n in L["nodi"] if n.get("id") not in via]
                L["fili"] = [f for f in L["fili"] if f.get("da") not in via and f.get("a") not in via]
            elif t == "fili_aggiungi":
                ci = {(f.get("da"), f.get("a")) for f in L["fili"]}
                for f in _lista(op.get("fili")):
                    if isinstance(f, dict) and (f.get("da"), f.get("a")) not in ci:
                        L["fili"].append({"da": f.get("da"), "a": f.get("a")})
                        ci.add((f.get("da"), f.get("a")))
            elif t == "fili_togli":
                via = {(f.get("da"), f.get("a")) for f in _lista(op.get("fili")) if isinstance(f, dict)}
                L["fili"] = [f for f in L["fili"] if (f.get("da"), f.get("a")) not in via]
            else:                                   # vista, bolle, titolo: si sostituiscono
                L[t] = op.get(t)
        else:
            raise ValueError(f"operazione sconosciuta: {t}")
    return d


def modifica_pannello(ops, base=None):
    """POST /api/pannello/modifica: applica le operazioni sul pannello ATTUALE (non su quello che la
    scheda aveva letto) e risponde con il pannello intero, così la pagina prende anche le modifiche altrui."""
    if not isinstance(ops, list) or not ops:
        raise ValueError("ops: serve una lista non vuota")
    if len(ops) > 500:
        raise ValueError("troppe operazioni in una volta")
    if fonte_vps.attiva():
        with PANNELLO_LOCK:
            sporco = fonte_vps.LAVAGNA.sporco(leggi_pannello())
        r = None if sporco else fonte_vps.inoltra("POST", "/api/pannello/modifica", {"ops": ops, "base": base})
        if r and r[0] == 200 and isinstance(r[1], dict) and isinstance(r[1].get("pannello"), dict):
            fonte_vps.LAVAGNA.ricevuto(r[1]["pannello"])
            tocca("pannello")
            return r[1]
        if r and r[0] == 400:
            raise ValueError(str((r[1] or {}).get("errore") or "modifica rifiutata dalla VPS"))
    with PANNELLO_LOCK:
        attuale = leggi_pannello()
        nuovo = pulisci_pannello(applica_ops_pannello(json.loads(json.dumps(attuale)), ops))
        if _conta_nodi(attuale) and not _conta_nodi(nuovo):
            raise ValueError("rifiuto di svuotare tutte le lavagne in un colpo solo")
        pulito = _scrivi_pannello_sotto_lock(nuovo, attuale)
    tocca("pannello")
    return {"versione": pulito["versione"], "pannello": pulito,
            "base_superata": isinstance(base, int) and base < _versione_di(attuale)}


class PannelloVecchio(Exception):
    """27/09/2026: il POST porta una versione più vecchia di quella salvata (scheda rimasta indietro)."""
    def __init__(self, attuale):
        super().__init__("il pannello è cambiato da un'altra scheda: ricarico quello attuale")
        self.attuale = attuale


def scrivi_pannello(d, versione=None):
    """Salva il pannello e alza il contatore «versione» (27/09/2026). Con versione (quella che la
    scheda ha letto) più vecchia di quella sul disco: PannelloVecchio, niente scritto. versione=None =
    come prima, senza controllo (pagine che non la mandano ancora)."""
    if versione is None:
        raise ValueError("manca la versione letta: ricarica la pagina (niente sovrascritture alla cieca)")
    pulito = pulisci_pannello(d)
    with PANNELLO_LOCK:
        attuale = leggi_pannello()
        if versione < _versione_di(attuale):
            raise PannelloVecchio(attuale)
        if _conta_nodi(attuale) and not _conta_nodi(pulito) and not d.get("svuota"):
            raise ValueError("rifiuto di svuotare tutte le lavagne: manda «svuota»: true se è voluto")
        pulito = _scrivi_pannello_sotto_lock(pulito, attuale)
    tocca("pannello")
    return pulito


# ---------------------------------------------------------------- chat con Jarvis o con un agente
# Il motore scelto (comando_motore), nel modo della chat (lavoro/lettura). Una conversazione = un
# id di sessione scelto dalla pagina: con Claude la prima domanda usa --session-id, le altre
# --resume; gli altri motori danno un id loro, che sessioni_motori.json lega a quello della pagina.

UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def trova_agente(progetto_id, nome):
    """(cartella del progetto, profilo) di un agente di spazi.json, o ValueError."""
    for s in spazi.carica():
        for p in s["progetti"]:
            if p["id"] != progetto_id:
                continue
            if not p["esiste"]:
                raise ValueError(f"cartella di {p['nome']} non trovata")
            for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                if a["nome"] == nome:
                    return Path(p["cartella"]), a
            raise ValueError(f"{nome}: agente non trovato in {p['nome']}")
    raise ValueError("progetto sconosciuto")


def filo_risposta(lav, ok):
    """La risposta di un lavoro di chat nell'archivio dei fili (fili.py): lo stesso testo che la pagina
    mostra (il log senza la riga «(cartella: …)»). Un errore qui non ferma niente: si dice e basta."""
    try:
        testo = Path(lav["log"]).read_text(encoding="utf-8", errors="replace")
        testo = re.sub(r"^\(cartella: [^\n]*\)\n\n?", "", testo)
        if not testo.strip() and lav.get("fermato"):
            testo = "(fermato da te)"
        fili.risposta(lav["sessione"], lav["id"], testo, ok, motore=lav.get("motore") or "",
                      log_nome=Path(lav["log"]).name, interlocutore=lav.get("interlocutore") or "")
    except Exception as e:  # noqa: BLE001
        evento(f"archivio dei fili: risposta non salvata ({type(e).__name__}: {e})"[:200])


def chiedi(dati, tipo="chat", titolo=None, filo=False):
    """filo=True (2026-10-03) solo per la chat della pagina (azione «chiedi»): domanda e risposta
    entrano nell'archivio dei fili. Le richieste interne (skill da «/», controllo scadenze) no:
    hanno una sessione usa e getta e sposterebbero gli altri dispositivi su un filo che l'utente non vede."""
    testo = (dati.get("testo") or "").strip()
    if not testo:
        raise ValueError("scrivi qualcosa")
    if len(testo) > 20000:
        raise ValueError("messaggio troppo lungo (massimo 20.000 caratteri)")
    sessione = (dati.get("sessione") or "").strip().lower()
    if not re.fullmatch(UUID_RE, sessione):
        raise ValueError("sessione non valida")
    dal_ponte = dati.get("_dal_ponte") is True
    if conversazione.e_reset(testo):
        # comando esplicito: l'unico modo in cui un filo si azzera (memoria continua, 2026-10-01)
        conversazione.azzera(sessione)
        nuova = str(uuid.uuid4())
        evento(f"filo {sessione[:8]} azzerato per comando esplicito, nuovo filo {nuova[:8]}")
        messaggio = "Nuova conversazione: il filo di prima è chiuso, riparto da zero."
        if filo:
            ag = (dati.get("agente") or "").strip()
            speciale = (dati.get("filo") or "").strip()
            try:
                fili.reset(nuova, speciale if speciale in fili.SPECIALI else
                           f"{dati.get('progetto')}:{ag}" if ag else "jarvis", messaggio)
            except Exception as e:  # noqa: BLE001
                evento(f"archivio dei fili: reset non salvato ({type(e).__name__})")
        return {"reset": True, "sessione": nuova, "messaggio": messaggio}
    agente = (dati.get("agente") or "").strip()
    cwd, chi, profilo = AGENTE, "Jarvis", None
    coda = contesto_box(dati.get("contesto"))
    # 2026-10-05 (notifiche): una risposta dell'utente nel filo «Notifiche Jarvis» o «Postino» porta in coda le
    # ultime notifiche (il report numerato del Postino, le bozze, gli avvisi di Jarvis).
    # 2026-10-05 13:20 (l'utente: «comunico con il postino, mentre con Jarvis continuo a lavorare»): nel filo
    # «postino» risponde l'agente postino (~/.claude/agents/postino.md, --agent postino), con la sua sessione.
    speciale = (dati.get("filo") or "").strip()
    if speciale:
        if speciale not in fili.SPECIALI:
            raise ValueError("filo sconosciuto")
        agente = ""
        coda += contesto_notifiche(sessione, speciale)
        if speciale == "postino":
            profilo = profilo_postino()
            chi = "Postino"
    elif not agente and filo:
        coda += contesto_avvisi(sessione)    # 2026-10-05 15:05: gli avvisi arrivati nella chat di Jarvis dall'ultima domanda
    modo = modo_sicuro(modo_chat())    # 2026-10-05: dal sito come dal Mac (fino al 03/10 qui «lavoro» diventava «approvazione»)
    motore = motore_richiesto(dati)      # 2026-09-26: il motore scelto risponde davvero (vedi comando_motore)
    if agente:
        cwd, profilo = trova_agente(dati.get("progetto"), agente)
        chi = profilo["nome"]
    ask_id = uuid.uuid4().hex[:8]
    # 2026-10-03: in «approvazione» l'id del lavoro si sceglie prima (il gestore dei permessi lo scrive nella scheda)
    approva = modo == "approvazione" and motore == "claude"
    lid = nuovo_id_lavoro() if approva else None
    conversazione.accoda(sessione, ask_id, testo)    # in sospeso finché non è il suo turno

    def costruisci():
        # al turno della domanda: lo stato del filo in testa, e --resume se la precedente ha scritto la sessione
        testa = conversazione.intestazione(sessione, ask_id)
        conversazione.pulisci_interrotte(sessione)
        return comando_motore(motore, testa + testo + coda, modo, sessione=sessione, agente=profilo,
                              lavoro_id=lid, cwd=cwd)

    cmd = comando_motore(motore, testo + coda, modo, sessione=sessione, agente=profilo, lavoro_id=lid, cwd=cwd)
    titolo = titolo or f"Chat {chi}: " + testo[:50] + ("…" if len(testo) > 50 else "")
    # «richiesta» resta il testo dell'utente (la pagina lo rimette nel filo della chat); il contesto
    # del box sta a parte, in «contesto», e nel comando è in coda al testo
    info = {"chi": chi, "tipo": tipo, "richiesta": testo, "sessione": sessione,
            "interlocutore": speciale or (f"{dati.get('progetto')}:{chi}" if agente else "jarvis"),
            "modo": modo, "motore": motore, "comando": comando_breve(cmd, testo + coda),
            "contesto": coda.strip()}
    if filo:
        # l'id del lavoro si sceglie qui: la domanda entra nell'archivio PRIMA che il lavoro possa finire
        info.update(id_lavoro=lid or nuovo_id_lavoro(), filo=True)
        try:
            fili.domanda(sessione, info["interlocutore"], testo, info["id_lavoro"], box=coda and _testo(
                (dati.get("contesto") or {}).get("titolo") or "", 80), motore=motore)
        except Exception as e:  # noqa: BLE001  (l'archivio non ferma mai la chat)
            evento(f"archivio dei fili: domanda non salvata ({type(e).__name__}: {e})"[:200])
    if approva:
        info.update(id_lavoro=lid, flusso_attivita=True)
        dopo = risposta_flusso(motore, sessione)
    elif modo == "approvazione":
        info["modo"] = "lettura"
        dopo = risposta_motore(motore, sessione, nota=f"(Modo approvazione: {MOTORI_NOME[motore]} non ha il gestore "
                                                      "dei permessi, quindi ha lavorato in sola lettura.)")
    else:
        dopo = risposta_motore(motore, sessione)
    return {"lavoro": nuovo_lavoro(titolo, cmd, cwd, dopo=dopo, info=info,
                                   env=env_motore(motore), turno=(sessione, ask_id), ricostruisci=costruisci)}


def specchia_notifiche():
    """Sul Mac (2026-10-05): i fili «Notifiche Jarvis» e «Postino» vivono sulla VPS (la fonte, Mac spento compreso);
    qui se ne tiene uno specchio nell'archivio locale, così la chat del Mac li mostra. Ogni 20 s, solo lettura
    sulla VPS (notifica.py esporta). Le domande fatte dal Mac in quei fili restano solo qui."""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "vps-tuo", "python3",
                            "/root/jarvis/strumenti/notifica.py", "esporta"], capture_output=True, text=True, timeout=40)
    except (subprocess.TimeoutExpired, OSError):
        return                       # VPS giù o rete assente: si riprova al giro dopo, senza riempire gli eventi
    if r.returncode != 0 or not r.stdout.strip():
        return
    try:
        dati = json.loads(r.stdout.strip().splitlines()[-1])
    except ValueError:
        return
    for f in dati.get("fili") or []:
        try:
            fili.specchia(f)
        except Exception as e:  # noqa: BLE001
            evento(f"specchio delle notifiche: {type(e).__name__}: {str(e)[:100]}")


def controlla_launchd_errori():
    """Sul Mac (2026-10-05, l'utente: «un lavoro automatico che finisce in errore deve mandare una notifica di Jarvis
    con la causa breve»): i com.jarvis.* fermi con uscita diversa da 0 → notifica.py controlla-launchd."""
    try:
        subprocess.run([sys.executable, str(STRUMENTI_JARVIS / "notifica.py"), "controlla-launchd"],
                       capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        pass


def profilo_postino():
    """Il profilo dell'agente che risponde nella chat Postino: ~/.claude/agents/postino.md (agente globale, lo
    trova anche claude --agent postino). Se il file manca sulla macchina, risponde Jarvis come prima."""
    f = HOME / ".claude" / "agents" / "postino.md"
    return {"nome": "postino", "file": str(f)} if f.exists() else None


def contesto_avvisi(sessione):
    """2026-10-05 15:05 (l'utente: «nella chat principale riporti tutto quello che stiamo facendo»): gli avvisi (errori,
    salvataggi, avanzamenti) compaiono nella chat di Jarvis come messaggi suoi. Se l'utente scrive dopo che ne sono
    arrivati, Jarvis li riceve in coda alla domanda (al massimo 3, arrivati dopo l'ultimo messaggio del filo).
    '' se non ce ne sono."""
    try:
        d = fili.leggi(sessione)
        dopo = max([m.get("ts") or 0 for m in (d or {}).get("messaggi") or []] or [time.time() - 3600])
        altra = fili.sessione_corrente("notifiche-jarvis")
        nuovi = fili.contesto_notifiche(altra, 3, classe="avviso", dopo=dopo) if altra else []
    except Exception:  # noqa: BLE001
        return ""
    if not nuovi:
        return ""
    parti = ["\n\n[Avvisi arrivati in questa chat dall'ultimo messaggio (li hai mandati tu come notifiche automatiche):]"]
    for m in nuovi:
        parti.append(f"--- {m.get('ora', '')} · {m.get('titolo') or ''}\n{str(m.get('testo') or '')[:1500]}")
    return "\n".join(parti)


def contesto_notifiche(sessione, speciale):
    """Il contesto di una risposta nel filo delle notifiche: le ultime 3 notifiche (titolo, ora, testo, dati) e la
    regola della posta dell'utente. Nella chat Postino anche le ultime 2 del filo «notifiche-jarvis» (2026-10-05: la
    pagina le mostra unite). Al massimo ~16.000 caratteri."""
    try:
        # 2026-10-05 15:05: la chat Postino contiene solo i report (fili.classifica); gli avvisi stanno da Jarvis
        solo = "report" if speciale == "postino" else None
        ultime = fili.contesto_notifiche(sessione, 3, classe=solo)
        if speciale == "postino":
            altra = fili.sessione_corrente("notifiche-jarvis")
            if altra and altra != sessione:
                ultime = sorted(ultime + fili.contesto_notifiche(altra, 2, classe="report"), key=lambda m: m.get("ts") or 0)
    except Exception:  # noqa: BLE001
        ultime = []
    nome = fili.SPECIALI.get(speciale, speciale)
    parti = [f"\n\n[l'utente risponde nel filo «{nome}» della chat del Command Center · {datetime.now():%Y-%m-%d %H:%M}. "
             f"Le ultime notifiche arrivate in questa chat (mittente · ora · titolo), dalla più vecchia:]"]
    for m in ultime:
        dati = json.dumps(m.get("dati"), ensure_ascii=False, separators=(",", ":"), default=str) if m.get("dati") else ""
        if len(dati) > 6000:
            dati = dati[:5999] + "…"
        parti.append(f"--- {m.get('mittente') or nome} · {m.get('ora', '')} · {m.get('titolo') or ''}\n{str(m.get('testo') or '')[:3000]}"
                     + (f"\n(dati: {dati})" if dati else ""))
    if not ultime:
        parti.append("(nessuna notifica nel filo)")
    parti.append("(Regole: «la 1», «il 3» sono i numeri dell'ultimo report qui sopra; usa il codice casella·uid della voce. "
                 "La posta si tocca con python3 strumenti/posta.py: azione, bozza, invia-bozza … --si, rispondi. "
                 "Si spedisce SOLO con un «invia» esplicito dell'utente su quella bozza o su quel numero; dopo l'invio la "
                 "bozza va nel Cestino (invia-bozza lo fa da solo). Rispondi breve e dì cosa hai fatto davvero.)")
    return "\n".join(parti)


def contesto_box(contesto):
    """Il dato del box da cui l'utente ha chiesto (contratto, punto 5): in coda al testo, con data e
    ora del Mac, json compatto al massimo di 4000 caratteri. '' se non c'è."""
    if not isinstance(contesto, dict) or not contesto:
        return ""
    titolo = _testo(contesto.get("titolo") or contesto.get("box") or "?", 80)
    dati = json.dumps(contesto.get("dati"), ensure_ascii=False, separators=(",", ":"), default=str)
    if len(dati) > 4000:
        dati = dati[:3999] + "…"
    return (f"\n\n[Dal Command Center · box «{titolo}» · {datetime.now():%Y-%m-%d %H:%M}]\n{dati}\n"
            "(Se serve lavoro su più progetti, delega ai capigruppo e agli specialisti con lo strumento "
            "Agent e riferisci.)")


# ---------------------------------------------------------------- skill e richieste frequenti (2026-09-26)
# l'utente: «mancano tutti i comandi / nella chat oltre i 5 principali, e gli spunti si devono aggiornare in
# base alle richieste ripetitive». Il catalogo elenca le skill e i comandi che Claude Code conosce; le
# richieste della chat si contano in frequenti.json e le 8 più ripetute diventano gli spunti.
SKILLS_CACHE = {"ts": 0.0, "voci": []}
SKILLS_LOCK = threading.Lock()
FREQUENTI_FILE = QUI / "frequenti.json"
FREQUENTI_LOCK = threading.Lock()


def _voce_skill(file_md, nome, origine):
    try:
        campi, corpo = spazi.frontmatter(file_md.read_text(encoding="utf-8"))
    except OSError:
        return None
    nome = nome or campi.get("name") or file_md.parent.name
    descrizione = " ".join(str(campi.get("description") or "").split())
    if not descrizione:     # un comando senza frontmatter: la prima riga di testo
        descrizione = next((r.strip("# ").strip() for r in corpo.splitlines() if r.strip()), "")
    return {"id": f"/{nome}", "nome": nome, "descrizione": descrizione[:140], "origine": origine}


def _plugin_installati():
    """(nome del plugin, cartella) dei plugin installati, da installed_plugins.json.
    Nota: in ~/.claude/plugins/*/skills/ non c'è niente; i plugin stanno in cache/<fonte>/<nome>/<versione>."""
    d = leggi_json(HOME / ".claude" / "plugins" / "installed_plugins.json", {})
    # solo quelli accesi in ~/.claude/settings.json: un plugin spento non si invoca con la barra
    accesi = leggi_json(HOME / ".claude" / "settings.json", {}).get("enabledPlugins") or {}
    for chiave, installazioni in (d.get("plugins") or {}).items():
        if accesi.get(chiave) is not True:
            continue
        for inst in installazioni or []:
            cartella = Path(inst.get("installPath") or "")
            if cartella.is_dir():
                yield chiave.split("@")[0], cartella
                break


def skills():
    """Le skill e i comandi con la barra che Jarvis può usare. Cache di 5 minuti: sono ~100 file."""
    with SKILLS_LOCK:
        if time.time() - SKILLS_CACHE["ts"] < 300:
            return SKILLS_CACHE["voci"]
    voci = []
    for radice, origine in ((HOME / ".claude", "utente"), (AGENTE / ".claude", "jarvis")):
        voci += [_voce_skill(f, None, origine) for f in sorted(radice.glob("skills/*/SKILL.md"))]
        voci += [_voce_skill(f, f.stem, origine) for f in sorted(radice.glob("commands/*.md"))]
    for plugin, cartella in _plugin_installati():
        voci += [_voce_skill(f, f"{plugin}:{f.parent.name}", "plugin") for f in sorted(cartella.glob("skills/*/SKILL.md"))]
        voci += [_voce_skill(f, f"{plugin}:{f.stem}", "plugin") for f in sorted(cartella.glob("commands/*.md"))]
    visti, fuori = set(), []
    for v in voci:
        if v and v["id"].lower() not in visti and not v["nome"].split(":")[-1].startswith("_"):     # la prima vince: utente, poi jarvis, poi plugin
            visti.add(v["id"].lower())
            fuori.append(v)
    with SKILLS_LOCK:
        SKILLS_CACHE.update(ts=time.time(), voci=fuori)
    return fuori


def _normalizza(testo):
    return " ".join(str(testo or "").lower().split())[:200]


def _leggi_frequenti():
    d = leggi_json(FREQUENTI_FILE, {})
    return d if isinstance(d, dict) else {}


def conta_frequente(testo):
    """Una richiesta in più (senza il contesto del box: chi chiama passa il testo dell'utente).
    Le voci viste una volta sola e più vecchie di 30 giorni si scartano qui."""
    chiave = _normalizza(testo)
    if not chiave:
        return
    ora = time.time()
    with FREQUENTI_LOCK:
        d = _leggi_frequenti()
        v = d.get(chiave) or {"conta": 0, "prima_ts": ora}
        v.update(conta=v["conta"] + 1, ultima_ts=ora)
        d[chiave] = v
        d = {k: x for k, x in d.items() if x.get("conta", 0) > 1 or ora - x.get("ultima_ts", ora) < 30 * 86400}
        if not FREQUENTI_FILE.exists():
            FREQUENTI_FILE.write_text("{}")
        scrivi_atomico(FREQUENTI_FILE, json.dumps(d, ensure_ascii=False, indent=1))
    tocca("frequenti")


def frequenti(n=8):
    with FREQUENTI_LOCK:
        d = _leggi_frequenti()
    righe = sorted(d.items(), key=lambda kv: (-kv[1].get("conta", 0), -kv[1].get("ultima_ts", 0)))[:n]
    return [{"testo": k, "conta": v.get("conta", 0), "ultima_ts": v.get("ultima_ts")} for k, v in righe]


def togli_frequente(testo):
    chiave = _normalizza(testo)
    with FREQUENTI_LOCK:
        d = _leggi_frequenti()
        if chiave not in d:
            raise ValueError("richiesta non trovata fra le frequenti")
        d.pop(chiave)
        scrivi_atomico(FREQUENTI_FILE, json.dumps(d, ensure_ascii=False, indent=1))
    tocca("frequenti")


# I comandi diretti della chat: script già scritti, in sola lettura, niente modello.
BRAIN_PY = HOME / ".claude" / "skills" / "aggiorna-memoria" / "strumenti" / "brain.py"   # «brain» fusa qui il 26/09


def comando_diretto(dati):
    nome = dati.get("nome")
    arg = (dati.get("arg") or "").strip()[:200]
    info = {"chi": "script", "tipo": "comando", "rilanciabile": True,
            "richiesta": f"/{nome} {arg}".strip()}
    if nome == "memoria":
        if not arg:
            raise ValueError("scrivi cosa cercare, per esempio: /memoria tunnel vps")
        cmd = [sys.executable, str(AGENTE / "strumenti" / "cerca_memoria.py"), arg]
        return {"lavoro": nuovo_lavoro(f"/memoria {arg}", cmd, AGENTE, info=info)}
    if nome == "brain":
        cartella = AGENTE
        if dati.get("progetto"):
            p = next((p for s in spazi.carica() for p in s["progetti"] if p["id"] == dati["progetto"]), None)
            if not p or not p["esiste"]:
                raise ValueError("progetto sconosciuto o cartella non trovata")
            cartella = Path(p["cartella"])
        cmd = [sys.executable, str(BRAIN_PY), str(cartella)]
        return {"lavoro": nuovo_lavoro(f"/brain {cartella.name}", cmd, cartella, info=info)}
    if nome == "lavori":
        # esito 3 = c'è qualcuno al lavoro: è una risposta, non un errore
        cmd = [sys.executable, str(AGENTE / "strumenti" / "lavori.py"), "chi"]
        return {"lavoro": nuovo_lavoro("/lavori", cmd, AGENTE, codici_ok=(0, 3), info=info)}
    if nome == "verifica":
        cmd = [sys.executable, str(AGENTE / "sincro" / "controlla.py")]
        # esce 1 quando c'è una riga gialla: non è un errore
        return {"lavoro": nuovo_lavoro("/verifica", cmd, AGENTE, codici_ok=(0, 1), info=info)}
    # una skill o un comando di Claude Code: diventa una richiesta normale a Jarvis, nel modo della chat,
    # e Claude Code esegue la skill (2026-09-26)
    elenco = skills()
    voce = next((v for v in elenco if v["id"].lower() == f"/{nome or ''}".lower()), None)
    if voce:
        return chiedi({"testo": f"{voce['id']} {arg}".strip(), "sessione": str(uuid.uuid4())})
    import difflib
    simili = difflib.get_close_matches(str(nome or ""), ["memoria", "brain", "lavori", "verifica"] +
                                       [v["id"][1:] for v in elenco], n=3, cutoff=0.4)
    raise ValueError("comando sconosciuto: usa /memoria, /brain, /lavori, /verifica o una skill"
                     + (" · forse: " + ", ".join("/" + x for x in simili) if simili else ""))


# ---------------------------------------------------------------- desktop della VPS
# Il desktop XFCE della VPS (display :10: Chrome, terminale, Claude Code, i progetti)
# dentro il pannello. Nessuna porta nuova su internet (decisione del 24/09/2026, dopo
# aver tolto il terminale pubblico): x11vnc sulla VPS ascolta solo su 127.0.0.1:5910,
# qui si apre un tunnel SSH con la chiave che il Mac già usa, e websockify serve noVNC
# solo a questo Mac. La password del desktop la chiede noVNC: il pannello non la tiene.

VPS_LOCALE = HOME / ".locale-onedrive" / "jarvis-cc"          # venv e noVNC, fuori da OneDrive
VPS_WEBSOCKIFY = VPS_LOCALE / "venv" / "bin" / "websockify"
VPS_NOVNC = VPS_LOCALE / "noVNC-1.6.0"
VPS_PORTA_TUNNEL, VPS_PORTA_WEB = 15910, 6080
VPS_URL = (f"http://127.0.0.1:{VPS_PORTA_WEB}/vnc.html?autoconnect=1&reconnect=1"
           "&reconnect_delay=3000&resize=scale&show_dot=1&path=websockify")


def vps_password():
    """La password del desktop sta nel Portachiavi del Mac (voce «jarvis-cc-vps-desktop»),
    non su OneDrive: così noVNC entra senza chiederla (richiesta dell'utente del 24/09/2026)."""
    c, out = sh(["security", "find-generic-password", "-s", "jarvis-cc-vps-desktop",
                 "-a", "vps-tuo", "-w"], timeout=5)
    return out.strip() if c == 0 else ""


def vps_desktop_stato():
    import urllib.parse
    pronto = VPS_WEBSOCKIFY.exists() and (VPS_NOVNC / "vnc.html").exists()
    tunnel, ponte = bool(pid_su_porta(VPS_PORTA_TUNNEL)), bool(pid_su_porta(VPS_PORTA_WEB))
    pw = vps_password()
    # l'indirizzo con la password gira solo fra questo Mac e sé stesso (127.0.0.1, con il token)
    url = VPS_URL + ("&password=" + urllib.parse.quote(pw, safe="") if pw else "")
    return {"installato": pronto, "tunnel": tunnel, "ponte": ponte, "acceso": tunnel and ponte,
            "url": url, "vps": VPS, "password_salvata": bool(pw)}


# «Apri fuori»: una scheda del browser con l'indirizzo che contiene la password finiva nella
# cronologia di Chrome, e con la sincronizzazione accesa usciva dal Mac. Ora la scheda apre
# /vps-fuori/<gettone>: gettone monouso, vale 60 secondi, e la pagina mette noVNC in un riquadro.
# Nella cronologia resta solo l'indirizzo col gettone, già bruciato.
VPS_FUORI = {}
VPS_FUORI_LOCK = threading.Lock()


def vps_fuori_gettone():
    tok = secrets.token_urlsafe(24)
    ora = time.time()
    with VPS_FUORI_LOCK:
        for k in [k for k, scade in VPS_FUORI.items() if scade < ora]:
            VPS_FUORI.pop(k, None)
        VPS_FUORI[tok] = ora + 60
    return f"/vps-fuori/{tok}"


def vps_fuori_pagina(tok):
    """L'HTML della scheda «fuori», o None se il gettone non vale (usato, scaduto, inventato)."""
    import html
    with VPS_FUORI_LOCK:
        scade = VPS_FUORI.pop(tok, None)
    if not scade or scade < time.time():
        return None
    url = vps_desktop_stato()["url"]
    return ("<!doctype html><html lang=\"it\"><head><meta charset=\"utf-8\"><title>VPS · Jarvis</title>"
            "<meta name=\"referrer\" content=\"no-referrer\"><style>html,body{margin:0;height:100%;background:#141414}"
            "iframe{border:0;width:100%;height:100%;display:block}</style></head><body>"
            f"<iframe src=\"{html.escape(url, quote=True)}\" allow=\"clipboard-read; clipboard-write\"></iframe>"
            "</body></html>")


def vps_desktop(acceso):
    if not acceso:
        termina(pid_su_porta(VPS_PORTA_WEB) + pid_su_porta(VPS_PORTA_TUNNEL))
        evento("desktop della VPS scollegato dal pannello")
        return {"messaggio": "desktop della VPS scollegato", **vps_desktop_stato()}
    st = vps_desktop_stato()
    if not st["installato"]:
        raise ValueError(f"mancano websockify o noVNC in {VPS_LOCALE}")
    if not VPS:
        raise ValueError("nessuna VPS in configurazione.json")
    if not st["tunnel"]:
        avvia_staccato(["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
                        "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=10",
                        "-L", f"127.0.0.1:{VPS_PORTA_TUNNEL}:127.0.0.1:5910", VPS],
                       HOME, LAVORI_DIR / "vps-tunnel.log")
    if not st["ponte"]:
        avvia_staccato([str(VPS_WEBSOCKIFY), "--web", str(VPS_NOVNC),
                        f"127.0.0.1:{VPS_PORTA_WEB}", f"127.0.0.1:{VPS_PORTA_TUNNEL}"],
                       VPS_LOCALE, LAVORI_DIR / "vps-websockify.log")
    for _ in range(30):
        st = vps_desktop_stato()
        if st["acceso"]:
            break
        time.sleep(0.5)
    if not st["acceso"]:
        raise ValueError("il collegamento non parte: guarda lavori/vps-tunnel.log e vps-websockify.log")
    evento("desktop della VPS collegato al pannello")
    return {"messaggio": "desktop della VPS collegato", **st}


# ---------------------------------------------------------------- terminale nel pannello
# Un terminale vero (xterm.js di ttyd) dentro il pannello: bash/zsh del Mac, dentro
# tmux così la sessione sopravvive a un ricaricamento, oppure `ssh vps-tuo`.
# 🔴 Il terminale pubblico (ttyd sulla VPS) è stato tolto il 24/09/2026: era una shell
# da root raggiungibile da internet. Qui ttyd NON apre nessuna porta TCP: ascolta su un
# socket UNIX in una cartella 0700 fuori da OneDrive, e lo raggiunge solo questo server
# (127.0.0.1:7777) come proxy, per chi ha il cookie che rilascia /api/terminale — che a
# sua volta vuole il token X-Token della pagina. In più ttyd chiede una basic-auth con
# una password nuova a ogni avvio del Command Center, che conosce solo il proxy.
# La VPS non si tocca: dal Mac parte una normale connessione SSH in uscita.

# la copia di prova ha i suoi socket: con quelli del pannello vero, accendere un terminale fermava il suo ttyd
TERM_DIR = VPS_LOCALE / "terminale" / ("prova" if PROVA else "")
TERM_UTENTE = "jarvis"
TERM_PASSWORD = secrets.token_urlsafe(24)       # mai scritta su disco, cambia a ogni avvio
TERM_COOKIE = secrets.token_urlsafe(32)
TERM_SESSIONE_TMUX = ["tmux", "-L", "jarvis-cc"]
TERM_PROC = {}
TERM_LOCK = threading.Lock()
TERM_TEMA = json.dumps({"background": "#141414", "foreground": "#f0f0f0", "cursor": "#599ce7",
                        "cursorAccent": "#141414", "selectionBackground": "rgba(89,156,231,.35)",
                        "black": "#1f1f1f", "brightBlack": "#5a5a5a", "blue": "#599ce7", "brightBlue": "#7fb3ee",
                        "green": "#3fa266", "brightGreen": "#5cc285", "yellow": "#e5b454", "brightYellow": "#f0ca7a",
                        "red": "#e34671", "brightRed": "#f06a90", "magenta": "#9386f2", "brightMagenta": "#b0a6f7",
                        "cyan": "#5fb3b3", "brightCyan": "#7fcccc", "white": "#d8d8d8", "brightWhite": "#ffffff"})


def _term_socket(modo):
    return TERM_DIR / f"{modo}.sock"


def _term_comando(modo):
    if modo == "mac":
        # una sessione tmux tutta sua (-L jarvis-cc): il mouse acceso qui non tocca gli altri tmux dell'utente
        return TERM_SESSIONE_TMUX + ["new-session", "-A", "-s", "mac", "-c", str(HOME),
                                     ";", "set", "-g", "mouse", "on", ";", "set", "-g", "history-limit", "50000",
                                     ";", "set", "-g", "status", "off"]
    if modo == "vps":
        if not VPS:
            raise ValueError("nessuna VPS in configurazione.json")
        return ["ssh", "-t", "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=10", VPS]
    raise ValueError("terminale: serve mac o vps")


def _term_vivo(modo):
    p = TERM_PROC.get(modo)
    return bool(p and p.poll() is None and _term_socket(modo).exists())


def terminale_stato():
    ttyd = shutil.which("ttyd", path=PATH_ENV)
    return {"installato": bool(ttyd), "vps": VPS,
            "modi": {m: {"acceso": _term_vivo(m), "url": f"/term/{m}/"} for m in ("mac", "vps")}}


def _ssh_vps_orfani():
    """Le `ssh -t … <VPS>` del terminale VPS rimaste senza il loro ttyd.

    🔴 Il 2026-09-26 otto di queste erano vive da ore con padre 1 (launchd), ognuna con una bash
    aperta sulla VPS: il portiere le vedeva come «ABUSIVO vps-shell». Il ttyd era morto e loro no.
    Si prendono SOLO i processi con il comando identico a quello di _term_comando("vps") e con
    padre 1: un terminale acceso ha per padre il suo ttyd, e i tunnel (`ssh -L … -N`) o le altre
    ssh dell'utente hanno un comando diverso, quindi restano fuori."""
    if not VPS:
        return []
    atteso = " ".join(_term_comando("vps"))
    _, out = sh(["ps", "-axo", "pid=,ppid=,command="], timeout=8)
    fuori = []
    for riga in out.splitlines():
        parti = riga.split(None, 2)
        if len(parti) == 3 and parti[1] == "1" and parti[2].strip() == atteso:
            fuori.append(int(parti[0]))
    return fuori


def _term_uccidi_orfani(modo):
    """Un ttyd rimasto da un Command Center precedente ha la password vecchia: si ferma.
    Per la VPS si chiudono anche le ssh rimaste senza ttyd (vedi _ssh_vps_orfani)."""
    for pid in processi(f"ttyd -i {_term_socket(modo)}"):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if modo == "vps":
        if processi(f"ttyd -i {_term_socket(modo)}"):
            time.sleep(1)                  # il ttyd appena fermato lascia orfana la sua ssh un attimo dopo
        orfani = _ssh_vps_orfani()
        for pid in orfani:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if orfani:
            evento(f"terminale VPS: chiuse {len(orfani)} ssh rimaste senza ttyd ({', '.join(map(str, orfani))})")


# Il terminale VPS tiene aperta una shell sulla VPS: per il portiere è la risorsa «vps-shell».
# Dal 2026-09-26 la chiave si prende all'accensione e si rende allo spegnimento, così non risulta
# più «ABUSIVO». Stesso registro di tutti (strumenti/lavori.py), agente fisso del pannello.
AGENTE_TERMINALE = "command-center-terminale"


def _lavori(*argomenti):
    # la sessione del registro è quella di questo server: prendo e finito trovano lo stesso file
    env = {**ENV, "CLAUDE_SESSION_ID": f"command-center-{os.getpid()}"}
    try:
        r = subprocess.run([sys.executable, str(AGENTE / "strumenti" / "lavori.py"), *argomenti],
                           capture_output=True, text=True, timeout=30, env=env, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def chiave_vps_shell(prendi):
    if prendi:
        base = ["prendo", "Jarvis", "terminale VPS dal Command Center", "--agente", AGENTE_TERMINALE,
                "--risorse", "vps-shell", "--max-min", "480"]
        codice, out = _lavori(*base)
        if codice == 3 and "chiavi sono già in mano" not in out:
            codice, out = _lavori(*base, "--insisto")    # c'è qualcuno su «Jarvis»: è un pezzo diverso
    else:
        codice, out = _lavori("finito", "terminale VPS chiuso", "--agente", AGENTE_TERMINALE)
    if codice != 0:
        evento(f"terminale VPS: chiave vps-shell {'non presa' if prendi else 'non resa'}: {out.strip()[-160:]}")
    return codice == 0


def terminale_avvia(modo):
    cmd_dentro = _term_comando(modo)
    ttyd = shutil.which("ttyd", path=PATH_ENV)
    if not ttyd:
        raise ValueError("ttyd non è installato: brew install ttyd")
    with TERM_LOCK:
        if not _term_vivo(modo):
            TERM_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(TERM_DIR, 0o700)
            _term_uccidi_orfani(modo)
            _term_socket(modo).unlink(missing_ok=True)
            titolo = "Jarvis · Mac" if modo == "mac" else f"Jarvis · VPS ({VPS})"
            cmd = [ttyd, "-i", str(_term_socket(modo)), "-W", "-O", "-c", f"{TERM_UTENTE}:{TERM_PASSWORD}",
                   "-b", f"/term/{modo}", "-w", str(HOME), "-T", "xterm-256color", "-P", "20",
                   "-t", "fontSize=13", "-t", "fontFamily=SF Mono, Menlo, ui-monospace, monospace",
                   "-t", "lineHeight=1.2", "-t", "cursorBlink=true", "-t", "disableLeaveAlert=true",
                   "-t", "disableResizeOverlay=true", "-t", f"titleFixed={titolo}",
                   "-t", f"theme={TERM_TEMA}", *cmd_dentro]
            # le variabili di una sessione Claude Code non passano: `claude` lanciato qui è una sessione nuova
            env = {k: v for k, v in ENV.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE"))}
            env.update(TERM="xterm-256color", LANG=env.get("LANG") or "it_IT.UTF-8")
            log = open(LAVORI_DIR / f"terminale-{modo}.log", "ab")
            TERM_PROC[modo] = subprocess.Popen(cmd, cwd=HOME, env=env, stdout=log, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, start_new_session=True)
            log.close()
            for _ in range(40):
                if _term_socket(modo).exists():
                    break
                time.sleep(0.1)
            if not _term_vivo(modo):
                raise ValueError(f"il terminale non parte: guarda lavori/terminale-{modo}.log")
            evento(f"terminale {modo.upper()} acceso nel pannello")
            if modo == "vps":
                chiave_vps_shell(True)
    return {"messaggio": f"terminale {modo.upper()} pronto", **terminale_stato()}


def terminale_ferma(modo):
    if modo not in ("mac", "vps"):
        raise ValueError("terminale: serve mac o vps")
    with TERM_LOCK:
        p = TERM_PROC.pop(modo, None)
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                p.kill()
        _term_uccidi_orfani(modo)
        _term_socket(modo).unlink(missing_ok=True)
    if modo == "vps" and p is not None:      # rende la chiave solo se il terminale c'era
        chiave_vps_shell(False)
    evento(f"terminale {modo.upper()} spento")
    nota = " · la sessione tmux del Mac resta: riaprendo la ritrovi" if modo == "mac" else ""
    return {"messaggio": f"terminale {modo.upper()} spento" + nota, **terminale_stato()}


def terminale_chiudi_sessione():
    """Chiude davvero la shell del Mac (la sessione tmux), con quello che c'era dentro."""
    terminale_ferma("mac")
    sh(TERM_SESSIONE_TMUX + ["kill-session", "-t", "mac"], timeout=5)
    evento("sessione del terminale del Mac chiusa")
    return {"messaggio": "sessione del Mac chiusa: la prossima volta riparte pulita", **terminale_stato()}


def terminale_ferma_tutti():
    for m in list(TERM_PROC):
        try:
            terminale_ferma(m)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- azioni

def interruttore(nome, acceso):
    if sys.platform == "win32" and nome in ("voce", "volto"):
        # ramo windows: voce = talk_to_jarvis_windows.py, volto = l'orb; programmi del desktop, non pagine
        script, etichetta = (SCRIPT_VOCE_WIN, "Voce (Shift destro)") if nome == "voce" else (SCRIPT_ORB_WIN, "Orb di Jarvis")
        if acceso:
            if not processi(script):
                avvia_windows(script)
        else:
            termina(processi(script))
        time.sleep(0.6)   # il tempo di far partire o chiudere il processo prima di rileggerlo
        _PROC_WIN["ts"] = 0
        threading.Thread(target=raccogli_locale_pesante, daemon=True).start()
        return f"{etichetta} " + ("acceso" if acceso else "spento")
    if sys.platform == "win32" and nome in ("mani", "telefono", "schermo_telefono"):
        raise ValueError(f"{nome}: non disponibile sul PC Windows")
    if nome == "voce" and SU_LINUX:     # 2026-10-05: sulla VPS accende o spegne il ponte voce del telefono
        c, out = sh(["docker", "start" if acceso else "stop", VOCE_VPS_CONTENITORE], timeout=60)
        if c != 0:
            raise ValueError(f"voce: docker non risponde ({(out or '').strip()[-160:]})")
        threading.Thread(target=raccogli_locale, daemon=True).start()
        return "voce accesa (ponte del telefono sulla VPS)" if acceso else "voce spenta (ponte del telefono fermo)"
    if nome == "voce":  # tornata per decisione dell'utente del 19/09/2026 22:09, sempre a tasto
        if acceso:
            apri_nel_terminale(AGENTE / "avvio" / "Talk to Jarvis.command")
            return "voce: apro la finestra di Jarvis a voce (parli tenendo Command destro)"
        termina(processi("backtalk.main") + processi("fullstack-agent/start.sh"))
        chiudi_finestre_terminale("Talk to Jarvis")
        return "voce spenta, finestra chiusa"
    if nome in PEZZI_PAGINA:
        cartella, porta, pagina = PEZZI_PAGINA[nome]
        if acceso:
            ACCESO_IL[nome] = time.time()    # PRIMA di avviare: il controllo periodico non deve spegnerlo
            PAGINA_ASSENTE.pop(nome, None)
            if not pid_su_porta(porta):
                # --no-open: la scheda la apre il pannello, una sola (il Volto ne apriva una sua)
                avvia_staccato(["python3", "server.py"] + (["--no-open"] if nome == "volto" else []),
                               AGENTE / cartella, LAVORI_DIR / f"{nome}.log")
                for _ in range(20):
                    if pid_su_porta(porta):
                        break
                    time.sleep(0.5)
                if not pid_su_porta(porta):
                    raise ValueError(f"{nome}: il server non parte, guarda {LAVORI_DIR / (nome + '.log')}")
            ACCESO_IL[nome] = time.time()    # l'attesa per la scheda riparte da adesso
            schede = schede_locali() or set()
            if nome == "volto":              # la pagina del volto scelto in ai-visualizer.json
                faccia = leggi_json(AGENTE / cartella / "ai-visualizer.json", {}).get("face") or ""
                if faccia and (AGENTE / cartella / "faces" / faccia / "index.html").exists():
                    pagina = f"faces/{faccia}/"
            if nome != "volto" and porta not in schede:   # niente schede doppie; il volto sta nel pannello, non si apre nel browser
                sh(["open", f"http://127.0.0.1:{porta}/{pagina}"], timeout=10)
            threading.Thread(target=raccogli_locale_pesante, daemon=True).start()
            return f"{NOME_PEZZO[nome]} acceso"
        spegni_pezzo(nome, "dal pannello")
        threading.Thread(target=raccogli_locale_pesante, daemon=True).start()
        return f"{NOME_PEZZO[nome]} spento, scheda chiusa"
    if nome == "telefono":
        if acceso:
            if not fidata():
                raise ValueError("La cartella di Jarvis non è ancora fidata: apri «Chat with Jarvis» e scegli «Yes, I trust this folder».")
            apri_nel_terminale(AGENTE / "avvio" / "Jarvis sul telefono.command")
            return "telefono: apro la finestra di Remote Control"
        termina(processi("claude remote-control"))
        chiudi_finestre_terminale("Jarvis sul telefono")
        return "telefono scollegato, finestra chiusa"
    if nome == "schermo_telefono":
        if acceso:
            avvia_staccato(["scrcpy", "--window-title", "Android dell'utente", "--always-on-top",
                            "--stay-awake", "--window-width", "420", "--window-height", "900"],
                           HOME, LAVORI_DIR / "scrcpy.log")
            return "schermo del telefono: apro lo specchio"
        termina(processi("scrcpy"))
        return "schermo del telefono spento"
    if nome in ("telegram_mac", "telegram_vps"):
        dove = nome.split("_")[1]
        c, out = guardia(dove, "accendi" if acceso else "spegni")
        if c != 0:
            raise ValueError(f"Telegram {dove.upper()}: {out.strip()[:200] or 'il guardiano non risponde'}")
        threading.Thread(target=raccogli_telegram, daemon=True).start()
        return f"Telegram {dove.upper()} " + ("acceso: si aggancia entro un minuto" if acceso else "spento, il guardiano lo lascia spento")
    raise ValueError(f"interruttore sconosciuto: {nome}")


# 27/09/2026: tutte le chiavi di CHIAVE_DI, cioè ogni ↻ della «Salute» (prima claude, comunicazioni,
# telefono, telegram e sentinella rispondevano «aggiorna: serve …»). «locale» rifà anche il giro leggero.
AGGIORNABILI = {"catena": ("raccogli_catena",), "memoria": ("raccogli_memoria",), "vps": ("raccogli_vps",),
                "locale": ("raccogli_locale", "raccogli_locale_pesante"), "agenti": ("raccogli_agenti",),
                "portiere": ("raccogli_portiere",), "claude": ("raccogli_claude",),
                "comunicazioni": ("raccogli_comunicazioni",), "telefono": ("raccogli_telefono",),
                "telegram": ("raccogli_telegram",), "sentinella": ("_sentinella_forzata",),
                "tutto": ("raccogli_locale_pesante", "raccogli_telefono", "raccogli_vps", "raccogli_memoria",
                          "raccogli_catena", "raccogli_claude", "raccogli_telegram", "raccogli_agenti",
                          "raccogli_portiere")}


def aggiorna_adesso(cosa):
    """Lancia subito i raccoglitori di «cosa», ognuno nel suo thread, e aspetta al massimo 60 s in
    tutto (contratto, punto 6). Chi non ha finito continua da solo e si dice."""
    nomi = AGGIORNABILI.get(cosa)
    if not nomi:
        raise ValueError("aggiorna: serve " + ", ".join(AGGIORNABILI))
    esiti, fili = {}, []
    for nome in nomi:
        f = globals()[nome]
        t = threading.Thread(target=lambda f=f, nome=nome: esiti.__setitem__(nome, esegui_raccoglitore(f)),
                             daemon=True)
        t.start()
        fili.append((nome, t))
    scadenza = time.time() + 60
    for _, t in fili:
        t.join(max(0, scadenza - time.time()))
    in_corso = [n for n, t in fili if t.is_alive()]
    errori = [f"{n}: {e}" for n, e in esiti.items() if e]
    msg = "aggiornato: " + cosa
    if errori:
        msg += " · errori: " + "; ".join(errori)[:300]
    if in_corso:
        msg += " · ancora in corso: " + ", ".join(in_corso)
    evento(f"aggiornamento forzato: {cosa}" + (" (con errori)" if errori else ""))
    return {"messaggio": msg, "errori": errori, "in_corso": in_corso}


MISSIONE_ASCOLTA = ("in avvio", "in corso", "attende conferma", "attende istruzioni")
ATTESA_CHIUSURA_S = 60


def _chiudi_a_forza(d):
    """27/09/2026: dopo il file «chiudi», missione.py ha 60 s per chiudersi da sola. Se il suo processo
    è ancora vivo: SIGTERM al gruppo, poi SIGKILL, poi stato.json = chiusa. Gira in un thread."""
    fine = time.time() + ATTESA_CHIUSURA_S
    while time.time() < fine:
        time.sleep(2)
        if leggi_json(d / "stato.json", {}).get("stato") in ("chiusa", "errore"):
            return
        pid = leggi_json(d / "missione.json", {}).get("pid")
        if pid and not _missione_viva(pid, d):
            break
    pid = leggi_json(d / "missione.json", {}).get("pid")
    if leggi_json(d / "stato.json", {}).get("stato") in ("chiusa", "errore"):
        return
    if pid and _missione_viva(pid, d):
        if PROVA:
            evento(f"missione {d.name} non si è chiusa in {ATTESA_CHIUSURA_S} s (copia di prova: non la fermo)")
            return
        if sys.platform == "win32":
            sh(["taskkill", "/PID", str(int(pid)), "/T", "/F"], timeout=15)   # il processo e i suoi figli
            _PROC_WIN["ts"] = 0
        for segnale, attesa in (() if sys.platform == "win32" else ((signal.SIGTERM, 10), (signal.SIGKILL, 5))):
            try:
                gruppo = os.getpgid(int(pid))
                if gruppo == int(pid):          # start_new_session: il gruppo è suo, figli compresi
                    os.killpg(gruppo, segnale)
                else:
                    os.kill(int(pid), segnale)
            except (ProcessLookupError, PermissionError, ValueError):
                break
            limite = time.time() + attesa
            # _missione_viva e non _pid_vivo: un figlio ucciso resta zombie finché non è raccolto
            while time.time() < limite and _missione_viva(pid, d):
                time.sleep(1)
            if not _missione_viva(pid, d):
                break
        evento(f"missione {d.name} fermata a forza: non si era chiusa in {ATTESA_CHIUSURA_S} s")
    if leggi_json(d / "stato.json", {}).get("stato") not in ("chiusa", "errore"):
        try:
            scrivi_atomico(d / "stato.json", json.dumps(
                {"stato": "chiusa", "aggiornato": datetime.now().isoformat(timespec="seconds"),
                 "chiusa_da": "pannello"}, ensure_ascii=False))
        except OSError as e:
            evento(f"missione {d.name}: stato.json non scritto ({e})")
    tocca("missioni", "agenti_attivi")


def lancia_missione(spazio, scelti, obiettivo, modalita, massimo, genere=None, extra=None):
    """Una missione: uno spazio, uno o più progetti, un processo missione.py con gli esperti dentro.
    «genere» (2026-09-26 sera): "aggiorna_catena" per l'aggiornamento degli agenti dalla lavagna."""
    if not PY_SDK.exists():
        raise ValueError("Manca il Python con claude_agent_sdk: " + str(PY_SDK) + (
            " (crealo con: python -m venv .venv && .venv\\Scripts\\pip install claude-agent-sdk)" if sys.platform == "win32" else ""))
    mid = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    while (MISSIONI_DIR / mid).exists():       # «tutti gli spazi» ne lancia più d'una nello stesso secondo
        time.sleep(1)
        mid = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    d = MISSIONI_DIR / mid
    d.mkdir()
    titolo = re.sub(r"[^\w\s-]", "", " ".join(obiettivo.split()[:7]), flags=re.U).strip()[:60] or "missione"
    report_dir = Path(spazio["report"])
    report_dir.mkdir(parents=True, exist_ok=True)
    # 02/10/2026 (l'utente): un solo report vivo per progetto, aggiornato a ogni missione, non un file per giro.
    # Le missioni di catena (lavoro di manutenzione) hanno il loro report datato come prima.
    if genere == "aggiorna_catena":
        report_file = report_dir / f"{date.today():%Y-%m-%d} {titolo}.md"
        if report_file.exists():
            report_file = report_dir / f"{date.today():%Y-%m-%d} {datetime.now():%H%M} {titolo}.md"
    else:
        report_dir = report_dir / scelti[0]["nome"]          # Report/<progetto>/Stato <progetto>.md
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"Stato {scelti[0]['nome']}.md"
    altre = [p["cartella"] for p in scelti[1:]]
    conf = {"spazio": spazio["id"], "spazio_nome": spazio["nome"], "obiettivo": obiettivo,
            "progetti": [{k: p.get(k) for k in ("id", "nome", "cartella", "capogruppo")} for p in scelti],
            "cwd": scelti[0]["cartella"], "modalita": modalita, "max_paralleli": massimo,
            "memoria": spazio["memoria"], "report": str(report_dir),
            "report_file": str(report_file),
            "inizio": datetime.now().strftime("%d/%m %H:%M"),
            "add_dirs": altre + [str(x) for x in (VAULT, report_dir) if x.exists()]}
    if genere:
        conf["genere"] = genere
    conf.update(extra or {})
    (d / "missione.json").write_text(json.dumps(conf, ensure_ascii=False, indent=2))
    with open(d / "processo.log", "ab") as f:
        p = subprocess.Popen([str(PY_SDK), str(QUI / "missione.py"), str(d)], cwd=conf["cwd"],
                             env={**ENV, "JARVIS_STATUS_MUTO": "1"},   # le missioni hanno il loro registro: niente doppioni nel bus dei ganci
                             stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             **({"creationflags": 0x08000000 | 0x00000200} if sys.platform == "win32"   # senza finestra, gruppo suo
                                else {"start_new_session": True}))
    conf["pid"] = p.pid
    _PROC_WIN["ts"] = 0      # Windows: il prossimo controllo rilegge i processi e vede subito la missione
    scrivi_atomico(d / "missione.json", json.dumps(conf, ensure_ascii=False, indent=2))
    chi = f"{spazio['nome']} · " + ", ".join(p["nome"] for p in scelti)
    evento(f"missione {modalita} affidata a {chi}: {obiettivo[:80]}")
    return {"missione": mid, "messaggio": f"Missione affidata: {chi}"}


def azione(dati):
    gettone = DAL_PONTE.set(dati.get("_dal_ponte") is True)
    try:
        if DAL_PONTE.get():
            controlla_dal_ponte(dati)
        return _azione(dati)
    finally:
        DAL_PONTE.reset(gettone)


def controlla_dal_ponte(dati):
    """Quello che da internet non si fa (ValueError = 400). Dal 2026-10-04, per decisione dell'utente, niente:
    dal sito e dal telefono si fa tutto quello che si fa dal Mac (l'accesso lo tiene il login di cc-ponte,
    la guardia dei comandi resta accesa sugli irreversibili). Il vecchio elenco resta sotto, spento."""
    return None
    tipo, cosa = dati.get("tipo"), dati.get("cosa")
    if tipo == "modo_chat" and dati.get("modo") == "lavoro":
        raise ValueError("dal sito no: il modo «lavoro» salta i permessi")
    if tipo == "agente" and cosa in ("crea", "salva_casa", "crea_squadra"):
        raise ValueError("dal sito no: cambia istruzioni persistenti degli agenti")
    if tipo == "agente" and cosa == "crea_gruppo" and (dati.get("crea_capogruppo") or dati.get("squadra_ceo")
                                                       or any(dati.get(k) for k in CAMPI_ISTRUZIONI)):
        raise ValueError("dal sito no: il capogruppo e la squadra si creano dal Mac")
    if tipo == "istruzione":
        conf = leggi_json(cartella_missione(dati.get("missione")) / "missione.json", {})
        if conf.get("modalita") != "lettura" and not conf.get("chiedi_tutto"):
            raise ValueError("dal sito no: la missione lavora senza chiedere all'utente")
    if tipo == "rilancia":
        r = LAVORI_RICETTE.get(dati.get("id")) or {}
        if any(x in ("--dangerously-skip-permissions", "bypassPermissions") for x in (r.get("cmd") or [])):
            raise ValueError("dal sito no: quel lavoro partiva con i permessi saltati")


def _azione(dati):
    tipo = dati.get("tipo")
    if tipo == "interruttore":
        msg = interruttore(dati.get("nome"), bool(dati.get("acceso")))
        evento(msg)
        threading.Thread(target=raccogli_locale, daemon=True).start()
        return {"messaggio": msg}
    if tipo == "android":
        cosa = dati.get("cosa")
        if cosa == "associa":
            ind, codice = dati.get("indirizzo", "").strip(), dati.get("codice", "").strip()
            if not re.fullmatch(r"[\d.]+:\d+", ind) or not re.fullmatch(r"\d{6}", codice):
                raise ValueError("Servono indirizzo:porta di associazione e il codice a 6 cifre")
            c, out = sh(["adb", "pair", ind, codice], timeout=30)
            msg = out.strip() or ("associato" if c == 0 else "associazione non riuscita")
        elif cosa == "collega":
            ind = dati.get("indirizzo", "").strip()
            if not re.fullmatch(r"[\d.]+:\d+", ind):
                raise ValueError("Serve indirizzo:porta di «Debug wireless» (non quella di associazione)")
            msg = sh(["adb", "connect", ind], timeout=20)[1].strip()
        elif cosa == "scollega":
            msg = sh(["adb", "disconnect"], timeout=10)[1].strip() or "scollegato"
        else:
            raise ValueError("azione android sconosciuta")
        evento(f"android: {msg}")
        threading.Thread(target=raccogli_locale_pesante, daemon=True).start()
        return {"messaggio": msg}
    if tipo == "tecnico":
        # Il banco di collaudo dell'app Android. Sta qui e non sul telefono per
        # decisione dell'utente del 20/09/2026: nell'app ci va solo quello che serve
        # a chi la usa. Nessuna di queste azioni tocca lo schermo del telefono.
        cosa = dati.get("cosa")
        if cosa == "debug":
            ok, msg = tecnico.imposta_debug(bool(dati.get("acceso")))
        elif cosa == "riavvia":
            ok, msg = tecnico.riavvia()
            msg = "App riavviata" if ok else f"Non riavviata: {msg}"
        else:
            raise ValueError("azione tecnica sconosciuta")
        evento(f"tecnico: {msg}")
        return {"messaggio": msg, "ok": ok}
    if tipo == "portfolio_carica_giornata":
        if sys.platform == "win32":
            raise ValueError("Portfolio è dell'utente e vive sul Mac: su questo PC non c'è")
        cartella_portfolio = (HOME / "Library" / "CloudStorage" / "OneDrive" /
                               "Jarvis Brain" / "Progetti" / "Vita personale" / "portfolio")
        venv_python = HOME / ".locale-onedrive" / "portfolio-venv" / "bin" / "python3"
        script = cartella_portfolio / "dati" / "scripts" / "carica_giornata.py"
        if not venv_python.exists() or not script.exists():
            raise ValueError("manca il venv o lo script di Portfolio: cartella spostata?")
        return {"lavoro": nuovo_lavoro("Portfolio: carica Daily Confirmation",
                                       [str(venv_python), str(script)], cartella_portfolio,
                                       info={"chi": "portfolio", "tipo": "script", "rilanciabile": True})}
    if tipo == "verifica":
        v = VERIFICHE.get(dati.get("id"))
        if not v:
            raise ValueError("verifica sconosciuta")
        return {"lavoro": nuovo_lavoro(v["nome"], v["cmd"], v["cwd"],
                                       info={"chi": "verifica", "tipo": "verifica", "rilanciabile": True})}
    if tipo == "agente" and dati.get("cosa"):
        return azione_agente(dati)
    if tipo == "agente":
        nome = dati.get("id")
        if nome not in {a["id"] for a in agenti_crm()}:
            raise ValueError("agente sconosciuto")
        richiesta = (dati.get("richiesta") or "").strip() or PROMPT_AGENTE
        return {"lavoro": nuovo_lavoro(f"Agente {nome}", claude_comando(richiesta, nome, modo="lettura"), CRM, dopo=solo_risposta,
                                       info={"chi": nome, "tipo": "agente", "richiesta": richiesta, "rilanciabile": True})}
    if tipo == "jarvis":
        richiesta = (dati.get("richiesta") or "").strip()
        if not richiesta:
            raise ValueError("Scrivi cosa deve controllare Jarvis")
        titolo = "Jarvis: " + (richiesta[:60] + ("…" if len(richiesta) > 60 else ""))
        return {"lavoro": nuovo_lavoro(titolo, claude_comando(richiesta, modo="lettura"), AGENTE, dopo=solo_risposta,
                                       info={"chi": "Jarvis", "tipo": "jarvis", "richiesta": richiesta,
                                             "interlocutore": "jarvis", "rilanciabile": True})}
    if tipo == "missione":
        # una missione = uno spazio + uno o più progetti + obiettivo + tetto al parallelo +
        # modalità. Un solo processo: missione.py, con gli esperti come sottoagenti dentro.
        obiettivo = (dati.get("obiettivo") or "").strip()
        if not obiettivo:
            raise ValueError("Scrivi l'obiettivo")
        spazio, scelti = spazi.trova(dati.get("spazio"), dati.get("progetti"))
        modalita = "lavoro" if dati.get("modalita") == "lavoro" else "lettura"
        try:
            massimo = min(10, max(1, int(dati.get("max_paralleli") or 5)))
        except (TypeError, ValueError):
            raise ValueError("Esperti in parallelo: un numero da 1 a 10")
        return lancia_missione(spazio, scelti, obiettivo, modalita, massimo)   # 2026-10-04: dal sito come dal Mac, niente chiedi_tutto
    if tipo == "conferma":
        d = cartella_missione(dati.get("missione"))
        rid = dati.get("richiesta", "")
        if not re.fullmatch(r"\w+", rid) or not (d / "richieste" / f"{rid}.json").exists():
            raise ValueError("richiesta non trovata")
        # 27/09/2026: un Sì a una missione finita o morta non lo legge nessuno: si rifiuta
        st = leggi_missione(d)["stato"]
        if st not in MISSIONE_ASCOLTA:
            raise ValueError(f"la missione è «{st}»: non aspetta più conferme")
        if (d / "richieste" / f"{rid}.risposta.json").exists():
            raise ValueError("a questa richiesta hai già risposto")
        ok = bool(dati.get("ok"))
        # atomico: missione.py legge il file appena compare, non deve mai trovarlo a metà
        scrivi_atomico(d / "richieste" / f"{rid}.risposta.json",
                       json.dumps({"ok": ok, "nota": (dati.get("nota") or "")[:1000]}, ensure_ascii=False))
        evento(("approvato" if ok else "rifiutato") + f" nella missione {d.name}")
        return {"messaggio": "approvato" if ok else "rifiutato"}
    if tipo == "istruzione":
        d = cartella_missione(dati.get("missione"))
        testo = (dati.get("testo") or "").strip()
        if not testo:
            raise ValueError("Scrivi l'istruzione")
        st = leggi_missione(d)["stato"]
        if st not in MISSIONE_ASCOLTA:
            raise ValueError(f"la missione è «{st}»: non legge più istruzioni")
        (d / "messaggi").mkdir(exist_ok=True)
        # atomico anche qui: missione.py prende i *.txt appena compaiono (il temporaneo è .tmp)
        scrivi_atomico(d / "messaggi" / f"{datetime.now():%H%M%S%f}.txt", testo)
        return {"messaggio": "istruzione inviata"}
    if tipo == "chiudi_missione":
        d = cartella_missione(dati.get("missione"))
        if leggi_missione(d)["stato"] in ("interrotta", "errore", "chiusa"):
            archivia_missione(d)
            evento(f"missione {d.name} tolta dal pannello dall'utente")
            return {"messaggio": "missione tolta dal pannello"}
        (d / "chiudi").touch()
        evento(f"missione {d.name} chiusa dall'utente")
        threading.Thread(target=_chiudi_a_forza, args=(d,), daemon=True).start()
        return {"messaggio": "chiudo la missione: resta nel pannello, chiusa, per 24 ore"}
    if tipo == "telefono":
        cosa = dati.get("cosa")
        if cosa in ("centralino_avvia", "centralino_ferma"):
            azione_sh = "avvia" if cosa.endswith("avvia") else "ferma"
            codice, out = sh(["bash", str(TELEFONO / "centralino.sh"), azione_sh], timeout=90)
            msg = out.strip().splitlines()[-1] if out.strip() else f"centralino: {azione_sh}"
        elif cosa in ("ponte_locale", "ponte_gemini"):
            script = "ponte_locale.sh" if cosa == "ponte_locale" else "ponte.sh"
            porta = 9093 if cosa == "ponte_locale" else 9092
            if dati.get("acceso"):
                if pid_su_porta(porta):
                    msg = "già acceso"
                else:
                    apri_nel_terminale(TELEFONO / script)
                    msg = "apro la finestra del ponte vocale (ci mette un minuto a scaldarsi)"
            else:
                termina(pid_su_porta(porta))
                chiudi_finestre_terminale(script)
                msg = "ponte spento, finestra chiusa"
        elif cosa == "chiama":
            numero = re.sub(r"[^0-9+]", "", dati.get("numero", ""))
            incarico = (dati.get("incarico") or "").strip()
            chi = (dati.get("chi") or "").strip()[:80]
            if len(numero) < 6:
                raise ValueError("Numero non valido")
            if len(incarico) < 10:
                raise ValueError("Scrivi l'incarico: cosa deve chiedere Jarvis")
            if not dati.get("conferma"):
                raise ValueError("Conferma la chiamata prima di avviarla")
            if not (pid_su_porta(9093) or pid_su_porta(9092)):
                raise ValueError("Accendi prima un motore vocale (voce locale o Gemini)")
            lav = nuovo_lavoro(f"Chiamata a {chi or numero}",
                               ["bash", str(TELEFONO / "chiama.sh"), numero, chi, incarico], TELEFONO,
                               info={"chi": "telefono", "tipo": "chiamata", "richiesta": f"{numero} · {incarico}"})
            evento(f"chiamata avviata verso {numero}")
            return {"lavoro": lav, "messaggio": f"Chiamo {numero}"}
        elif cosa == "risposta":
            valore = "1" if dati.get("acceso") else "0"
            ast(f"database put jarvis rispondi {valore}")
            msg = ("Jarvis risponde alle chiamate in arrivo" if valore == "1"
                   else "Jarvis non risponde: squillano gli altri telefoni")
        else:
            raise ValueError("azione telefono sconosciuta")
        evento(f"telefono: {msg}")
        threading.Thread(target=raccogli_telefono, daemon=True).start()
        return {"messaggio": msg}
    if tipo == "comando":
        c = COMANDI_RAPIDI.get(dati.get("id"))
        if not c:
            raise ValueError("comando sconosciuto")
        return {"lavoro": nuovo_lavoro(c["nome"], claude_comando(c["richiesta"], modo="lettura"), AGENTE, dopo=solo_risposta,
                                       info={"chi": "Jarvis", "tipo": "comando rapido", "richiesta": c["richiesta"],
                                             "interlocutore": "jarvis", "rilanciabile": True})}
    if tipo == "apri_percorso_sincronia":
        percorso = dati.get("percorso", "")
        leciti = set()
        for p in battito().get("progetti", []):
            for k in ("memoria_file", "lavoro_file"):
                if p.get(k):
                    leciti.add(p[k])
        if percorso not in leciti:
            raise ValueError("percorso non riconosciuto")
        sh(["open", percorso], timeout=10)
        return {"messaggio": "aperto"}
    if tipo == "apri_cartella":
        # 30/09/2026 (l'utente): ogni scheda della lavagna ha il suo link per entrare a controllare. Si apre il
        # primo percorso che esiste fra quelli proposti, purché stia dentro la casa dell'utente; un file si rivela nel Finder.
        for cand in (dati.get("percorsi") or [])[:6]:
            q = spazi.percorso(str(cand))
            try:
                q = q.resolve() if q else None
            except OSError:
                q = None
            if not q or not q.exists():
                continue
            try:
                q.relative_to(HOME.resolve())
            except ValueError:
                raise ValueError("solo percorsi dentro la casa dell'utente")
            sh(["open", "-R", str(q)] if q.is_file() else ["open", str(q)], timeout=10)
            return {"messaggio": f"aperto: {q.name}"}
        raise ValueError("cartella non trovata")
    if tipo == "apri":
        quale = dati.get("id")
        if quale not in APRI_RAPIDO:
            raise ValueError("indirizzo sconosciuto")
        bersaglio = APRI_RAPIDO[quale] or str(TELEFONO / "GUIDA.md")
        sh(["open", bersaglio], timeout=10)
        return {"messaggio": f"aperto: {quale}"}
    if tipo == "chat":
        apri_nel_terminale(AGENTE / "avvio" / "Chat with Jarvis.command")
        return {"messaggio": "apro la chat con Jarvis"}
    if tipo == "scegli_allegato":
        script = 'POSIX path of (choose file with prompt "Scegli un file per Jarvis" default location (path to desktop))'
        codice, out = sh(["osascript", "-e", script], timeout=120)
        if codice != 0:
            script2 = 'POSIX path of (choose folder with prompt "Scegli una cartella per Jarvis" default location (path to desktop))'
            codice, out = sh(["osascript", "-e", script2], timeout=120)
        if codice != 0:
            return {"percorso": None, "messaggio": "nessun file scelto"}
        return {"percorso": out.strip(), "messaggio": "allegato: " + out.strip()}
    if tipo == "chat_incarico":
        testo = (dati.get("testo") or "").strip()
        allegato = (dati.get("allegato") or "").strip()
        if not testo and not allegato:
            raise ValueError("scrivi un compito o allega qualcosa")
        corpo = testo
        if allegato:
            corpo += ("\n\n" if corpo else "") + f"File o cartella allegata: {allegato}"
        f = LAVORI_DIR / "prossimo-incarico.txt"
        scrivi_atomico(f, corpo)
        apri_nel_terminale(AGENTE / "avvio" / "Chat con incarico.command")
        evento("aperta la chat con Jarvis con un incarico pronto" + (f" e un allegato" if allegato else ""))
        return {"messaggio": "apro Jarvis con il tuo incarico"}
    if tipo == "chat_voce_manda":
        # Manda un messaggio scritto nella STESSA conversazione della voce
        # (non una chat nuova): backtalk/main.py tiene un lettore in più
        # su questo file, con la stessa coda dei messaggi digitati o
        # parlati. Se la voce non gira, il messaggio resta lì per quando
        # riparte: non si perde, non serve nessun'altra conferma.
        testo = (dati.get("testo") or "").strip()
        if not testo:
            raise ValueError("scrivi qualcosa da mandare")
        f = AGENTE / "backtalk" / ".esterno_in"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(testo.replace("\n", " ") + "\n")
        evento("mandato un messaggio scritto a Jarvis (voce)")
        # 2026-10-05: sul Mac, con la voce spenta il messaggio restava fermo in .esterno_in senza dirlo:
        # adesso la voce si accende (la finestra «Talk to Jarvis») e lo legge appena è pronta.
        if not SU_LINUX and sys.platform == "darwin" and not processi("backtalk.main"):
            interruttore("voce", True)
            return {"messaggio": "accendo la voce del Mac: il messaggio parte appena è pronta (qualche secondo)"}
        return {"messaggio": "mandato"}
    if tipo == "chat_voce_parla":
        # 2026-10-05 (l'utente): il tasto 📞 del riquadro «Chat a voce». Sul Mac fa partire l'ascolto di backtalk per
        # UNA frase, come «Hey Jarvis» (backtalk/.ascolta_ora, letto da main.py, vale 60 s); con la voce spenta la
        # accende e l'ascolto parte appena è pronta. Sulla VPS la voce è quella del browser (voce-chat.js).
        if SU_LINUX or sys.platform != "darwin":
            return {"messaggio": "sul sito si parla dal browser", "browser": True}
        scrivi_atomico(AGENTE / "backtalk" / ".ascolta_ora", str(time.time()))
        if not processi("backtalk.main"):
            interruttore("voce", True)
            evento("chat a voce: accesa la voce del Mac per parlare")
            return {"messaggio": "accendo la voce del Mac: quando è pronta ti ascolta (parla dopo il suono)", "accesa": True}
        evento("chat a voce: ascolto della voce del Mac avviato dal pannello")
        return {"messaggio": "ti ascolto: parla, la frase parte dopo un attimo di silenzio"}
    if tipo == "ferma":
        lav = lavoro_copia(dati.get("id"))
        if lav and lav.get("pid") and lav["stato"] == "in corso":
            # 2026-10-07: segnato prima di chiudere, così l'archivio dei fili scrive «(fermato da te)» e non
            # «(nessuna risposta)» (fili.js unisce il messaggio del server sopra quello della pagina)
            with LAVORI_LOCK:
                if lav["id"] in LAVORI:
                    LAVORI[lav["id"]]["fermato"] = True
            try:
                os.killpg(lav["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
            return {"messaggio": "fermato"}
        return {"messaggio": "niente da fermare"}
    if tipo == "togli_lavoro":
        lav = togli_lavoro(dati.get("id"))
        evento(f"tolto dalla lista: {lav['titolo']}")
        return {"messaggio": "tolto dalla lista (il log resta in lavori/)"}
    if tipo == "pulisci_lavori":
        with LAVORI_LOCK:
            chiusi = [k for k, v in LAVORI.items() if v["stato"] != "in corso"]
        for k in chiusi:
            togli_lavoro(k)
        evento(f"lista dei lavori pulita: {len(chiusi)} tolti")
        return {"messaggio": f"{len(chiusi)} lavori chiusi tolti dalla lista (i log restano in lavori/)"}
    if tipo == "rilancia":
        lav = rilancia_lavoro(dati.get("id"))
        return {"lavoro": lav, "messaggio": "rilanciato: " + lav["titolo"]}
    if tipo == "mostra_log":
        lav = lavoro_copia(dati.get("id"))
        if not lav:
            raise ValueError("lavoro non trovato")
        if sys.platform.startswith("linux"):
            return {"messaggio": f"il log è sulla VPS: {lav['log']}"}
        sh(["open", "-R", lav["log"]], timeout=10)
        return {"messaggio": "log mostrato nel Finder"}
    if tipo == "terminale":
        cosa = dati.get("cosa")
        if cosa == "avvia":
            return terminale_avvia(dati.get("modo"))
        if cosa == "ferma":
            return terminale_ferma(dati.get("modo"))
        if cosa == "chiudi_sessione":
            return terminale_chiudi_sessione()
        raise ValueError("azione del terminale sconosciuta")
    if tipo == "telegram_riaggancia":
        dove = dati.get("dove")
        if dove not in ("mac", "vps"):
            raise ValueError("Telegram: serve mac o vps")
        c, out = guardia(dove, "riavvia")
        if c != 0:
            raise ValueError(f"Telegram {dove.upper()}: {out.strip()[:200] or 'il guardiano non risponde'}")
        evento(f"Telegram {dove.upper()} riagganciato dal pannello")
        threading.Thread(target=raccogli_telegram, daemon=True).start()
        return {"messaggio": f"Telegram {dove.upper()}: riaggancio, pronto entro un minuto"}
    if tipo == "sincronia_verifica":
        # Un giro del battito adesso, senza aspettare la mezz'ora.
        r = subprocess.run([sys.executable, str(AGENTE / "sincro/ogni30.py")],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise ValueError(r.stderr.strip()[-300:] or "il giro è fallito")
        threading.Thread(target=raccogli_memoria, daemon=True).start()
        threading.Thread(target=raccogli_catena, daemon=True).start()
        indietro = battito().get("indietro") or []
        evento("verifica della memoria dal pannello · indietro: %s"
               % (", ".join(indietro) or "nessuno"))
        return {"messaggio": "memoria riletta · " + (
            "da salvare: " + ", ".join(indietro) if indietro else "tutti i progetti in pari")}
    if tipo == "sincronia_comando":
        # 🔴 Il salvataggio NON parte da qui. In memoria del CRM Azienda Uno c'è
        # l'errore: MEMORIA.md scritta dal Mac e dal PC Windows nello stesso
        # quarto d'ora, via OneDrive, fa sparire un salvataggio; e «--salva» col
        # solo «--stato» ha già cancellato Fatto, Da fare e tre errori su
        # quattro. Il pannello prepara il comando e si ferma: lo lancia l'utente.
        nome = (dati.get("progetto") or "").strip()
        voci = {p["progetto"]: p for p in (battito().get("progetti") or [])}
        if nome not in voci:
            raise ValueError("progetto sconosciuto: %s" % (nome or "(vuoto)"))
        p = voci[nome]
        cart = p.get("cartella") or ""
        cmd = ('python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py "%s" --salva '
               '--stato "..." --completato "..." --dafare "..."' % cart)
        return {"messaggio": "comando pronto, lanciarlo in chat", "comando": cmd,
                "progetto": nome, "esito": p.get("esito"),
                "ore_indietro": p.get("ore_indietro"),
                "ultimo_lavoro": p.get("lavoro_file"),
                "nota": "il pannello non salva la memoria: due computer che la "
                        "riscrivono insieme su OneDrive ne perdono una versione"}
    if tipo == "aggiorna":
        return aggiorna_adesso(dati.get("cosa") or "tutto")
    if tipo == "scadenze":
        return azione_scadenze(dati)
    if tipo == "portiere":
        cosa = dati.get("cosa")
        if cosa == "ritira_fantasmi":
            n = portiere_ritira_fantasmi()
            evento(f"portiere: {n} prese fantasma ritirate dal pannello")
            return {"messaggio": f"prese fantasma ritirate: {n}", "ritirate": n}
        if cosa == "identifica":
            d = portiere_identifica(dati.get("pid"))
            evento(f"portiere: identificato il pid {d['pid']}" + (f" ({d['nome']})" if d["nome"] else ""))
            return d
        raise ValueError("portiere: serve ritira_fantasmi o identifica")
    if tipo == "modo_chat":
        modo = dati.get("modo")
        if modo not in MODI_CHAT:
            raise ValueError("modo della chat: lavoro, lettura o approvazione")
        scrivi_config("modo_chat", modo)
        evento(f"chat del pannello in modo {modo}")
        tocca("modo_chat")
        return {"modo": modo, "messaggio": f"chat in modo {modo}"}
    if tipo == "sentinella":
        cosa = dati.get("cosa")
        if cosa == "acceso":
            acceso = bool(dati.get("valore"))
            scrivi_config("sentinella", acceso)
            evento("sentinella " + ("accesa" if acceso else "spenta") + " dal pannello")
            _pubblica_sentinella()
            return {"messaggio": "sentinella " + ("accesa" if acceso else "spenta"), "acceso": acceso}
        if cosa == "giro":
            errore = esegui_raccoglitore(_sentinella_forzata)
            if errore:
                raise ValueError(f"sentinella: {errore}")
            evento("sentinella: giro forzato dal pannello")
            return {"messaggio": "giro della sentinella fatto", "sentinella": STATO.get().get("sentinella")}
        raise ValueError("sentinella: serve giro o acceso")
    if tipo == "comando_claude_code":
        cmd_id = (dati.get("id") or "").strip()
        if not cmd_id:
            raise ValueError("Specifica l'id del comando Claude Code")
        comandi = {c["id"]: c for c in (CFG.get("comandi_claude_code") or []) if c.get("id")}
        cmd = comandi.get(cmd_id)
        if not cmd:
            raise ValueError(f"Comando Claude Code non trovato: {cmd_id}")
        titolo = cmd.get("nome", cmd_id)
        diretto = (cmd.get("comando") or "").strip()
        if diretto:
            # Un comando di sistema (ps, cat, claude auth status): gira davvero e l'uscita è quella
            # letterale. Prima partiva come prompt a `claude -p` in plan: 0,22 $ a clic per un `ps`
            # (prova del 26/09/2026) e un numero riferito dal modello invece che letto.
            # Il testo viene da configurazione.json (file locale), mai dalla pagina: la pagina manda solo l'id.
            return {"lavoro": nuovo_lavoro(titolo, ["/bin/bash", "-c", diretto], HOME,
                                           info={"chi": "script", "tipo": "comando", "richiesta": diretto,
                                                 "rilanciabile": True})}
        messaggio = (cmd.get("messaggio") or "").strip()
        if not messaggio:
            raise ValueError("Comando Claude Code senza «comando» né «messaggio»")
        # sempre plan mode: il campo «piano» della configurazione non conta più (regola in testa al file).
        # Il modo della chat (2026-09-26) vale per la chat, non per i comandi preparati in configurazione.
        agente = (cmd.get("agente") or "").strip() or None
        return {"lavoro": nuovo_lavoro(titolo, claude_comando(messaggio, agente, modo="lettura"), AGENTE, dopo=solo_risposta,
                                       info={"chi": agente or "Jarvis", "tipo": "Claude Code", "richiesta": messaggio,
                                             "interlocutore": "" if agente else "jarvis", "rilanciabile": True})}
    if tipo == "approva":
        return decidi_approvazione(dati)        # 2026-10-03, contratto approvazioni sez. 1
    if tipo == "chiedi":
        fuori = chiedi(dati, filo=True)
        if not (dati.get("agente") or "").strip() and not dati.get("filo"):   # solo Jarvis; le risposte alle notifiche no
            conta_frequente(dati.get("testo"))
        return fuori
    if tipo == "comando_diretto":
        fuori = comando_diretto(dati)
        conta_frequente(f"/{dati.get('nome') or ''} {(dati.get('arg') or '').strip()}")
        return fuori
    if tipo == "frequenti":
        if dati.get("cosa") != "togli":
            raise ValueError("frequenti: serve cosa = togli")
        togli_frequente(dati.get("testo"))
        evento(f"richiesta tolta dalle frequenti: {_normalizza(dati.get('testo'))[:80]}")
        return {"messaggio": "tolta dalle frequenti", "frequenti": frequenti()}
    if tipo == "vps_desktop":
        return vps_desktop(bool(dati.get("acceso")))
    if tipo == "vps_fuori":
        if not vps_desktop_stato()["acceso"]:
            raise ValueError("prima collega il desktop della VPS")
        return {"url": vps_fuori_gettone()}
    raise ValueError(f"azione sconosciuta: {tipo}")


# ---------------------------------------------------------------- approvazioni e schermo (2026-10-03)
# Contratto: CONTRATTO-approvazioni.md (sez. 1 e 3). L'archivio sta in approvazioni.py; qui il pannello
# se ne accorge (sorveglia_approvazioni, ogni secondo), lo mostra, avvisa l'utente e scrive le decisioni.

def _connessioni():
    """strumenti/connessioni.py (2026-10-04): una sola fonte, la usa anche l'hook connessioni_guardia.py."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
    import connessioni
    return connessioni


def _piano():
    """strumenti/piano.py (2026-10-04): lo usano anche Jarvis (riga di comando) e l'hook delle connessioni."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
    import piano
    return piano


def _incarichi():
    """strumenti/incarichi.py (2026-10-04, docs/incarichi-contratto.md): la coda degli incarichi sulla VPS.
    Sul Mac la libreria passa da ssh. Solo nella copia di prova CC_INCARICHI_FINTO punta a una libreria finta."""
    finto = os.environ.get("CC_INCARICHI_FINTO") if PROVA else None
    if finto:
        import importlib.util
        if "incarichi" not in sys.modules:
            spec = importlib.util.spec_from_file_location("incarichi", finto)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules["incarichi"] = mod
        return sys.modules["incarichi"]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strumenti"))
    import incarichi
    return incarichi


_INCARICHI_POOL = {"p": None}
_INCARICHI_LOCK = threading.Lock()
INCARICHI_DA = "jarvis-utente"
INCARICHI_FASE2 = {"jarvis-giuseppe"}          # Fase 2: serve il sì di l'amministratore


def _incarichi_chiama(nome, *args, **kw):
    """Chiama la libreria su un thread a parte (l'ssh può durare qualche secondo), al massimo 20 s.
    Ritorna (codice, corpo) pronti per _invia."""
    import concurrent.futures as cf
    try:
        I = _incarichi()
    except Exception as e:  # noqa: BLE001
        return 500, {"errore": f"libreria incarichi non caricata: {type(e).__name__}: {str(e)[:120]}"}
    with _INCARICHI_LOCK:
        if _INCARICHI_POOL["p"] is None:
            _INCARICHI_POOL["p"] = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="incarichi")
        pool = _INCARICHI_POOL["p"]
    fut = pool.submit(getattr(I, nome), *args, **kw)
    try:
        return 200, fut.result(timeout=20)
    except cf.TimeoutError:
        return 502, {"errore": "VPS non raggiungibile: nessuna risposta in 20 secondi (se stavi mandando un incarico, ricarica l'elenco: potrebbe essere partito)"}
    except Exception as e:  # noqa: BLE001
        for cls, codice in (("NonTrovato", 404), ("GiaPreso", 409), ("IncaricoNonValido", 400)):
            c = getattr(I, cls, None)
            if isinstance(c, type) and isinstance(e, c):
                msg = str(e.args[0]) if e.args else str(e)
                return codice, {"errore": (msg if msg.startswith("incarico non trovato") else f"incarico non trovato: {msg}")[:200]
                                       if codice == 404 else msg}
        # nel modo remoto ogni altro errore viene dall'ssh (timeout, rifiuto, uscita senza JSON)
        return 502, {"errore": f"VPS non raggiungibile: {type(e).__name__}: {str(e)[:160]}"}


# ---------------------------------------------------------------- routine (2026-10-05, l'utente)
# La pagina «Routine» e i comandi rapidi della lavagna: tutto in routine.py. Qui solo le rotte, il collegamento
# all'ssh «su se stessa» (Command Center acceso sulla VPS) e gli avvisi sul flusso.

def _routine():
    import routine as R
    if R.AVVISA is None:
        R.SU_SE_STESSA = _ssh_su_se_stessa
        R.VPS = VPS or R.VPS

        def avvisa(cosa, dati):
            emetti_flusso("routine", {"cosa": cosa, **dati})
            if cosa in ("conferma", "avvia") and dati.get("esito") in ("ok", "errore", "rifiutato"):
                evento(f"routine {cosa}: {dati.get('id')} → {dati.get('esito')}")
        R.AVVISA = avvisa
        # 2026-10-05 14:25 (l'utente): «Salva» applica subito e lo dice a Jarvis; la «Regola» la trasforma Jarvis in script
        import routine_salva as RS

        def notifica_jarvis(titolo, testo, chiave):
            sys.path.insert(0, str(STRUMENTI_JARVIS))
            from notifica import notifica
            notifica("jarvis", titolo, testo, chiave=chiave, prova=PROVA)

        def chiedi_jarvis(testo):
            chiedi({"testo": testo, "sessione": str(uuid.uuid4())}, filo=True)

        def claude_p(prompt, modello):
            r = subprocess.run(["claude", "-p", "--model", modello, "--tools", "", "--no-session-persistence",
                                "--output-format", "text"], input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300, cwd=str(AGENTE), env=ENV)
            if r.returncode != 0:
                raise R.RoutineNonValida(f"regola: Jarvis non ha risposto ({r.returncode}): {(r.stderr or r.stdout)[-200:]}")
            return r.stdout
        RS.NOTIFICA, RS.CHIEDI, RS.CLAUDE = notifica_jarvis, chiedi_jarvis, claude_p
    return R


def _routine_gruppi_extra():
    """I gruppi della lavagna e delle riunioni: i comandi rapidi ne mostrano uno anche quando è nuovo."""
    extra = [{"id": g.get("id"), "nome": g.get("nome")} for g in (leggi_pannello().get("gruppi") or []) if isinstance(g, dict)]
    rg = leggi_json(STRUMENTI_JARVIS / "riunione_gruppi.json", {})
    extra += [{"id": k, "nome": (v or {}).get("nome") or k} for k, v in (rg.get("gruppi") or {}).items()]
    return extra


class ErroreHttp(Exception):
    """Un errore con il suo codice HTTP (404, 409…) per le azioni che non sono un 400."""
    def __init__(self, codice, messaggio):
        super().__init__(messaggio)
        self.codice = codice


_APPROV_VISTE = {}                 # id -> (stato, deciso) già annunciati sul flusso
_APPROV_LOCK = threading.Lock()
_APPROV_AVVIATO = {"fatto": False}


def segnala_approvazione(a, nuova=False):
    """Evento «approvazione» sul flusso; alla nascita con rischio medio/alto anche Telegram (non nella copia di prova)."""
    with _APPROV_LOCK:
        firma = (a.get("stato"), a.get("deciso"))
        if _APPROV_VISTE.get(a["id"]) == firma:
            return
        _APPROV_VISTE[a["id"]] = firma
    emetti_flusso("approvazione", a)
    if nuova and a.get("stato") == "attesa":
        evento(f"permesso chiesto ({a.get('rischio')}): {a.get('riepilogo', '')[:80]}")
        if a.get("rischio") in ("medio", "alto") and not PROVA:
            testo = (f"Jarvis chiede il permesso (rischio {a['rischio']}): {a.get('riepilogo', '')[:70]}\n"
                     "Approva o rifiuta dal Command Center: senza risposta scade fra 15 minuti.")
            threading.Thread(target=notifica_utente, args=(testo, "Permesso chiesto"), daemon=True).start()
    elif a.get("stato") in ("approvata", "rifiutata", "scaduta"):
        evento(f"permesso {a['stato']}: {a.get('riepilogo', '')[:80]}")


def sorveglia_approvazioni():
    """Ogni secondo: battito per il gestore dei permessi, scadenze, richieste nuove o cambiate."""
    approvazioni.batti(PORTA)
    approvazioni.scadi()
    tutte = approvazioni.tutte_pubbliche()
    if not _APPROV_AVVIATO["fatto"]:
        # primo giro: la storia di prima non si riannuncia; i file --mcp-config rimasti si tolgono
        with _APPROV_LOCK:
            for k, a in tutte.items():
                if a.get("stato") != "attesa":
                    _APPROV_VISTE[k] = (a.get("stato"), a.get("deciso"))
        for f in (approvazioni.cartella() / "mcp").glob("*.json"):
            try:
                if time.time() - f.stat().st_mtime > 86400:
                    f.unlink()
            except OSError:
                pass
        _APPROV_AVVIATO["fatto"] = True
    for k, a in tutte.items():
        with _APPROV_LOCK:
            prima = _APPROV_VISTE.get(k)
        if prima != (a.get("stato"), a.get("deciso")):
            segnala_approvazione(a, nuova=prima is None)


# revisione 3 (2026-10-04): un «sì» a una scheda di rischio ALTO vale solo in due tempi, come il secondo tocco della
# pagina: prima {"fase": "prepara"} (risponde un codice monouso valido 5 s), poi il «sì» con quel codice dopo
# ALMENO 800 ms. Un «no» passa sempre (è la direzione sicura). Non distingue un curl locale dal browser: è uno
# strato in più contro l'auto-approvazione di uno script, non una barriera (vedi registro-dev/LEGGIMI-REVISIONE-3.md).
_DUE_TEMPI = {}
_DUE_TEMPI_LOCK = threading.Lock()
DUE_TEMPI_MIN_S = 0.8
DUE_TEMPI_MAX_S = 5.0


def _prepara_due_tempi(id_):
    codice = secrets.token_hex(16)
    with _DUE_TEMPI_LOCK:
        adesso = time.monotonic()
        for k in [k for k, (_, t) in _DUE_TEMPI.items() if adesso - t > DUE_TEMPI_MAX_S]:
            del _DUE_TEMPI[k]
        _DUE_TEMPI[id_] = (codice, adesso)
    return codice


def _conferma_due_tempi(id_, codice):
    """None se va bene, altrimenti il motivo del rifiuto. Il codice si consuma comunque (monouso)."""
    with _DUE_TEMPI_LOCK:
        voce = _DUE_TEMPI.pop(id_, None)
    if not voce or not isinstance(codice, str) or not secrets.compare_digest(codice.encode(), voce[0].encode()):
        return "serve la conferma in due tempi: prima «prepara», poi il sì con il codice"
    trascorso = time.monotonic() - voce[1]
    if trascorso < DUE_TEMPI_MIN_S:
        return "conferma troppo veloce: il secondo tocco deve arrivare dopo almeno 0,8 secondi"
    if trascorso > DUE_TEMPI_MAX_S:
        return "conferma scaduta: il codice vale 5 secondi, ricomincia"
    return None


def decidi_approvazione(dati):
    """POST /api/azione tipo «approva» (contratto sez. 1). Rischio alto: «sì» in due tempi (vedi sopra)."""
    id_ = dati.get("id")
    decisione = dati.get("decisione")
    if decisione not in ("si", "no"):
        raise ValueError("decisione: si o no")
    if not isinstance(id_, str) or not re.fullmatch(r"ap_[0-9a-f]{8}", id_):
        raise ErroreHttp(404, "approvazione non trovata")
    if decisione == "si":
        attuale = approvazioni.leggi(id_)
        if not attuale:
            raise ErroreHttp(404, "approvazione non trovata")
        if attuale.get("stato") == "attesa" and approvazioni.e_troncata(attuale):
            raise ErroreHttp(409, "il comando è stato tagliato e la parte finale non si è vista: si può solo rifiutare")
        if attuale.get("rischio") == "alto" and attuale.get("stato") == "attesa":
            if dati.get("fase") == "prepara":
                return {"ok": True, "preparato": True, "codice": _prepara_due_tempi(id_),
                        "attendi_ms": int(DUE_TEMPI_MIN_S * 1000), "valido_s": int(DUE_TEMPI_MAX_S)}
            perche = _conferma_due_tempi(id_, dati.get("codice"))
            if perche:
                raise ErroreHttp(428, perche)
    try:
        a, gia = approvazioni.decidi(id_, decisione, da=dati.get("da") or "web", motivo=_testo(dati.get("motivo"), 300))
    except approvazioni.NonTrovata:
        raise ErroreHttp(404, "approvazione non trovata")
    except (approvazioni.Scaduta, approvazioni.Troncata) as e:
        raise ErroreHttp(409, str(e))
    segnala_approvazione(a)
    out = {"ok": True, "stato": a["stato"], "approvazione": a}
    if gia:
        out["gia_deciso"] = True
    return out


_SCHERMO = {"ts": 0.0, "w": None, "dati": None}
_SCHERMO_LOCK = threading.Lock()


class SchermoNonDisponibile(Exception):
    pass


def mac_bloccato():
    """True se lo schermo del Mac è bloccato (IOConsoleUsers → CGSSessionScreenIsLocked)."""
    if sys.platform != "darwin":
        return False
    import plistlib
    try:
        r = subprocess.run(["ioreg", "-n", "Root", "-d1", "-a"], capture_output=True, timeout=5)
        d = plistlib.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return False
    for u in d.get("IOConsoleUsers") or []:
        if isinstance(u, dict) and any("ScreenIsLocked" in k and v for k, v in u.items()):
            return True
    return False


def schermo_jpeg(w=800):
    """JPEG dello schermo principale largo w px, con cache di 1 s (contratto sez. 3). Solo lettura:
    screencapture -x -m (come strumenti/mac.py «guarda») e sips per rimpicciolire, niente dipendenze nuove."""
    import tempfile
    w = max(320, min(1600, int(w)))
    with _SCHERMO_LOCK:
        if _SCHERMO["dati"] and _SCHERMO["w"] == w and time.time() - _SCHERMO["ts"] < 1.0:
            return _SCHERMO["dati"]
        if sys.platform != "darwin":
            raise SchermoNonDisponibile("lo schermo si vede solo dal Mac")
        if mac_bloccato():
            raise SchermoNonDisponibile("il Mac è bloccato: lo schermo non si vede finché non lo sblocchi")
        with tempfile.TemporaryDirectory(prefix="cc-schermo-") as tmp:
            grezzo, piccolo = Path(tmp) / "s.jpg", Path(tmp) / "p.jpg"
            try:
                r = subprocess.run(["screencapture", "-x", "-m", "-t", "jpg", str(grezzo)], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise SchermoNonDisponibile(f"screencapture non ha risposto: {e}")
            if r.returncode != 0 or not grezzo.exists() or grezzo.stat().st_size == 0:
                raise SchermoNonDisponibile("cattura dello schermo non permessa: serve «Registrazione schermo» per il "
                                            "programma che lancia il Command Center (Impostazioni > Privacy e sicurezza)")
            try:
                subprocess.run(["sips", "--resampleWidth", str(w), "-s", "format", "jpeg", "-s", "formatOptions", "60",
                                str(grezzo), "--out", str(piccolo)], capture_output=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass
            dati = (piccolo if piccolo.exists() and piccolo.stat().st_size else grezzo).read_bytes()
        _SCHERMO.update(ts=time.time(), w=w, dati=dati)
        return dati


def computer_stato():
    with LAVORI_LOCK:
        ultimo = max(LAVORI.values(), key=lambda x: x.get("inizio_ts") or 0, default=None)
        file = list(ULTIMI_FILE)[-10:]
    return {"schermo": sys.platform == "darwin" and not mac_bloccato(),
            "ultimo_lavoro": ultimo["id"] if ultimo else None, "ultimi_file": file[::-1]}


# ---------------------------------------------------------------- http

TIPI = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png", ".webmanifest": "application/manifest+json"}


class Gestore(BaseHTTPRequestHandler):
    server_version = "JarvisCC"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORTA}", f"localhost:{PORTA}")

    def _da_locale(self):
        """La richiesta arriva da questo Mac (non da un contenitore o dalla rete)."""
        return (self.client_address or ("",))[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _invia(self, codice, corpo, tipo="application/json; charset=utf-8", intestazioni=()):
        # 2026-10-03 (prestazioni da internet, condizionale.py): per gli indirizzi con ETag, se la pagina
        # ha già questi dati (If-None-Match) si risponde 304 senza corpo. Arriva qui solo dopo i controlli
        # di Host e token di _do_get: un 304 non salta nessun controllo. Cache-Control resta no-store.
        if condizionale and codice == 200 and self.command == "GET" and not isinstance(corpo, bytes):
            tag = condizionale.etag_di(self.path.split("?")[0], corpo)
            if tag:
                intestazioni = (*intestazioni, ("ETag", tag))
                if condizionale.coincide(self.headers.get("If-None-Match"), tag):
                    self.send_response(304)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Frame-Options", "DENY")
                    for k, v in intestazioni:
                        self.send_header(k, v)
                    self.end_headers()
                    return
        dati = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in intestazioni:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    def _cookie_terminale_ok(self):
        from http.cookies import SimpleCookie
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001
            return False
        v = c.get("cc_term")
        return bool(v) and secrets.compare_digest(v.value, TERM_COOKIE)

    def _proxy_terminale(self, modo):
        """Passa la richiesta (pagina, token o websocket) al ttyd di quel modo sul suo
        socket UNIX, aggiungendo la basic-auth che conosce solo questo server."""
        import base64
        import socket
        origine = self.headers.get("Origin")
        if origine and origine not in (f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"):
            return self._invia(403, {"errore": "origine non ammessa"})
        if not self._cookie_terminale_ok():
            return self._invia(403, {"errore": "apri il terminale dal pannello"})
        if not _term_vivo(modo):
            return self._invia(503, {"errore": "terminale spento: accendilo dal pannello"})
        su = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            su.connect(str(_term_socket(modo)))
        except OSError as e:
            return self._invia(502, {"errore": f"terminale non raggiungibile: {e}"})
        ws = self.headers.get("Upgrade", "").lower() == "websocket"
        righe = [f"{self.command} {self.path} HTTP/1.1"]
        for k, v in self.headers.items():
            if k.lower() not in ("authorization", "cookie", "connection", "keep-alive", "proxy-connection"):
                righe.append(f"{k}: {v}")
        chiave = base64.b64encode(f"{TERM_UTENTE}:{TERM_PASSWORD}".encode()).decode()
        righe += [f"Authorization: Basic {chiave}", "Connection: Upgrade" if ws else "Connection: close"]
        self.close_connection = True

        def giu():     # ttyd → browser
            try:
                while True:
                    d = su.recv(65536)
                    if not d:
                        break
                    self.connection.sendall(d)
            except OSError:
                pass
            finally:
                for s in (su, self.connection):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        try:
            su.sendall(("\r\n".join(righe) + "\r\n\r\n").encode("latin-1"))
            if not ws:
                giu()
                return
            t = threading.Thread(target=giu, daemon=True)
            t.start()
            while True:     # browser → ttyd
                d = self.rfile.read1(65536)
                if not d:
                    break
                su.sendall(d)
        except OSError:
            pass
        finally:
            try:
                su.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            su.close()

    def _flusso(self):
        """Server-Sent Events (contratto, punto 1): un messaggio a ogni versione nuova, un battito
        ogni 15 s. Tiene il suo thread finché la pagina resta aperta; se la pagina se ne va, la
        prima scrittura fallisce (BrokenPipe) e il thread esce."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        mia = versione()

        def manda(testo):
            self.wfile.write(testo.encode())
            self.wfile.flush()

        try:
            # «sa» (2026-10-03): cosa sa fare questo server, così la pagina rallenta i suoi giri solo se
            # gli avvisi esistono davvero (chat_voce) e chiede lo stato a pezzi solo se c'è (parti)
            sa = ["chat_voce", "parti"] if condizionale else ["chat_voce"]
            manda(f"data: {json.dumps({'versione': mia, 'chiavi': [], 'ts': time.time(), 'sa': sa})}\n\n")
            while True:
                with VERSIONE_COND:
                    VERSIONE_COND.wait_for(lambda: VERSIONE["n"] > mia, timeout=15)
                    nuova = VERSIONE["n"] > mia
                if not nuova:
                    manda(": battito\n\n")
                    continue
                time.sleep(0.25)       # i cambi a raffica (un lavoro che parte = 3 tocchi) diventano un messaggio
                with VERSIONE_COND:
                    n = VERSIONE["n"]
                    chiavi = sorted({c for v, c in VERSIONE_STORIA if v > mia})
                    con_nome = [(nm, d) for v, nm, d in FLUSSO_EVENTI if v > mia]
                mia = n
                msg = {'versione': n, 'chiavi': chiavi, 'ts': time.time()}
                pezzi = stato_spinto(chiavi)
                if pezzi is not None:
                    msg["stato"] = pezzi
                manda(f"data: {json.dumps(msg, ensure_ascii=False)}\n\n")
                for nm, d in con_nome:      # 2026-10-03: «approvazione» e «attivita» (EventSource.addEventListener)
                    manda(f"event: {nm}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_GET(self):
        """Un errore dentro una GET risponde 500 con il motivo, invece di chiudere la connessione
        muta (la pagina diceva «non risponde» anche per un difetto minuscolo)."""
        try:
            return self._do_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            evento(f"errore nella richiesta {self.path.split('?')[0]}: {e}")
            import traceback
            traceback.print_exc()          # in lavori/server.log: dove nasce l'errore, non solo il messaggio
            try:
                self._invia(500, {"errore": f"{type(e).__name__}: {e}"})
            except OSError:
                pass

    def _do_get(self):
        if not self._host_ok():
            return self._invia(403, {"errore": "host non ammesso"})
        percorso = self.path.split("?")[0]
        m = re.match(r"/term/(mac|vps)(/|$)", percorso)
        if m:
            return self._proxy_terminale(m.group(1))
        if percorso in ("/", "/index.html"):
            threading.Thread(target=avvia_orb, args=("pagina",), daemon=True).start()
            html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._invia(200, html.encode(), TIPI[".html"])
        # web app installabile: il service worker deve stare alla radice per
        # controllare tutta la pagina, il manifest accanto
        if percorso in ("/sw.js", "/manifest.webmanifest"):
            f = STATIC / percorso[1:]
            return self._invia(200, f.read_bytes(), TIPI[f.suffix])
        m = re.fullmatch(r"/assistenza/coordinate/([0-9a-f]{16})", percorso)
        if m:
            # 30/09/2026: la pagina da stampare con le coordinate del bonifico, solo dopo la scelta delle ore
            A = _assistenza_mod
            if not A or not assistenza_attiva_conf():
                return self._invia(404, {"errore": "non trovato"})
            try:
                return self._invia(200, A.pagina_coordinate(m.group(1)).encode(), TIPI[".html"])
            except A.ErroreAssistenza as e:
                return self._invia(404, {"errore": str(e)})
        m = re.fullmatch(r"/vps-fuori/([\w-]{20,64})", percorso)
        if m:
            pagina = vps_fuori_pagina(m.group(1))
            if pagina is None:
                return self._invia(403, "<p>Indirizzo scaduto: riapri il desktop dal pannello.</p>".encode(),
                                   TIPI[".html"])
            return self._invia(200, pagina.encode(), TIPI[".html"], intestazioni=[("Referrer-Policy", "no-referrer")])
        if percorso.startswith("/static/"):
            f = (STATIC / percorso[len("/static/"):]).resolve()
            if STATIC in f.parents and f.is_file():
                return self._invia(200, f.read_bytes(), TIPI.get(f.suffix, "application/octet-stream"))
            return self._invia(404, {"errore": "non trovato"})
        if percorso == "/api/computer/schermo":
            # 2026-10-03 (contratto sez. 3): un <img> non manda intestazioni, quindi come /api/flusso il token
            # vale anche in ?token=. Solo lettura, cache di 1 s.
            q = parse_qs(urlsplit(self.path).query)
            tok = self.headers.get("X-Token") or (q.get("token") or [""])[0]
            if not secrets.compare_digest(tok.encode(), TOKEN.encode()):
                return self._invia(403, {"errore": "token scaduto: il Command Center è ripartito", "token_scaduto": True})
            try:
                w = int((q.get("w") or ["800"])[0])
            except ValueError:
                return self._invia(400, {"errore": "w: una larghezza in pixel fra 320 e 1600"})
            try:
                return self._invia(200, schermo_jpeg(w), "image/jpeg")
            except SchermoNonDisponibile as e:
                return self._invia(503, {"errore": str(e)})
        if percorso == "/api/flusso":
            # EventSource non manda intestazioni: solo qui il token vale anche in ?token=
            tok = self.headers.get("X-Token") or (parse_qs(urlsplit(self.path).query).get("token") or [""])[0]
            if not secrets.compare_digest(tok.encode(), TOKEN.encode()):
                return self._invia(403, {"errore": "token scaduto: il Command Center è ripartito", "token_scaduto": True})
            return self._flusso()
        if self.headers.get("X-Token") != TOKEN:
            # il token cambia a ogni avvio: la pagina che lo vede se ne accorge e si ricarica da sola
            return self._invia(403, {"errore": "token scaduto: il Command Center è ripartito", "token_scaduto": True})
        if percorso == "/api/pannello":
            return self._invia(200, leggi_pannello())
        if percorso == "/api/aggiornamento":
            # c'è una versione nuova del software su GitHub? (aggiornamento.py, controllo ogni 10 minuti)
            import aggiornamento
            return self._invia(200, aggiornamento.stato("forza" in parse_qs(urlsplit(self.path).query)))
        if percorso == "/api/github":
            # i repository dell'utente (01/10/2026): gh in cache 5 minuti, ?forza=1 rilegge subito
            import repo_github
            try:
                return self._invia(200, repo_github.elenco("forza" in parse_qs(urlsplit(self.path).query)))
            except Exception as e:
                return self._invia(500, {"errore": f"elenco repo non letto: {e}"})
        if percorso == "/api/motore":
            return self._invia(200, stato_motori())
        if percorso == "/api/approvazioni":
            return self._invia(200, approvazioni.elenco())          # 2026-10-03, contratto sez. 1
        if percorso == "/api/registro":
            # 2026-10-03 (CONTRATTO-registro.md): l'elenco unico di cosa Jarvis ha fatto o tentato, con la regola
            import registro
            try:
                return self._invia(200, registro.elenco_da_query(parse_qs(urlsplit(self.path).query)))
            except registro.RichiestaNonValida as e:
                return self._invia(400, {"errore": str(e)})
        if percorso == "/api/connessioni":
            # 2026-10-04: i servizi a tre posizioni (consentito / chiedi / spento), strumenti/connessioni.py
            try:
                return self._invia(200, _connessioni().stato_pubblico())
            except Exception as e:  # noqa: BLE001
                return self._invia(500, {"errore": f"connessioni non lette: {type(e).__name__}: {str(e)[:120]}"})
        if percorso == "/api/aspetto":
            # 2026-10-04: tema e avatar uguali su ogni dispositivo (aspetto.py)
            import aspetto
            remoto = _stato_semplice_dalla_vps("/api/aspetto")
            return self._invia(200, remoto if remoto is not None else aspetto.leggi())
        if percorso == "/api/menu":
            # 2026-10-04: la barra in alto, ordine e voci in «Altro» scelti dall'utente (menu_barra.py)
            try:
                import menu_barra
                remoto = _stato_semplice_dalla_vps("/api/menu")
                return self._invia(200, remoto if remoto is not None else menu_barra.leggi())
            except Exception as e:  # noqa: BLE001
                return self._invia(500, {"errore": f"menu non letto: {type(e).__name__}: {str(e)[:120]}"})
        if percorso == "/api/piani":
            # 2026-10-04: i piani approvati una volta, con la conferma finale (strumenti/piano.py)
            try:
                P = _piano()
                return self._invia(200, {"piani": [P.pubblico(p) for p in P.elenco()[:30]]})
            except Exception as e:  # noqa: BLE001
                return self._invia(500, {"errore": f"piani non letti: {type(e).__name__}: {str(e)[:120]}"})
        if percorso == "/api/incarichi":
            # 2026-10-04: la coda degli incarichi sulla VPS (strumenti/incarichi.py, via ssh dal Mac)
            return self._invia(*_incarichi_chiama("stato_pubblico"))
        if percorso in ("/api/routine", "/api/routine/log"):
            # 2026-10-05 (l'utente): le routine di VPS (systemd e cron) e Mac (launchd), routine.py; cache di 45 s
            q = parse_qs(urlsplit(self.path).query)
            try:
                R = _routine()
                if percorso == "/api/routine/log":
                    return self._invia(200, R.log((q.get("id") or [""])[0]))
                d = R.elenco("forza" in q, _routine_gruppi_extra())
                d["registro"] = R.ultime_righe_registro(20)
                return self._invia(200, d)
            except KeyError:
                return self._invia(404, {"errore": "routine non trovata"})
            except Exception as e:  # noqa: BLE001
                return self._invia(500, {"errore": f"routine non lette: {type(e).__name__}: {str(e)[:160]}"})
        if percorso == "/api/registro/regole":
            import registro                                          # le regole del file, in sola lettura, e le proposte
            return self._invia(200, registro.regole_e_proposte())
        if percorso == "/api/fili":
            # 2026-10-03: i fili di chat, dal più recente; 2026-10-05 (fonte unica): anche quelli dell'altra macchina
            return self._invia(200, fili.elenco_unito())
        m = re.fullmatch(r"/api/fili/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", percorso)
        if m:
            d = fili.leggi_unito(m.group(1))
            return self._invia(200, d) if d else self._invia(404, {"errore": "filo non trovato"})
        if percorso == "/api/computer/stato":
            return self._invia(200, computer_stato())                # 2026-10-03, contratto sez. 3
        if percorso == "/api/vps-desktop":
            return self._invia(200, vps_desktop_stato())
        if percorso == "/api/terminale":
            # il cookie apre /term/ solo a questa pagina (che ha il token): HttpOnly, solo stesso sito
            return self._invia(200, terminale_stato(), intestazioni=[
                ("Set-Cookie", f"cc_term={TERM_COOKIE}; Path=/term/; HttpOnly; SameSite=Strict")])
        if percorso == "/api/stato":
            s = STATO.get()
            with EVENTI_LOCK:
                s["eventi"] = list(EVENTI[:25])
            with LAVORI_LOCK:
                # per inizio vero: l'id è HHMMSS e dopo mezzanotte i lavori nuovi finivano in fondo, tagliati
                s["lavori"] = [dict(x) for x in sorted(LAVORI.values(), key=lambda x: x.get("inizio_ts") or 0,
                                                       reverse=True)[:20]]
            s["missioni"] = missioni()
            s["agenti_attivi"] = agenti_attivi()
            s["claude_ora"] = claude_ora()
            s["ora"] = datetime.now().isoformat(timespec="seconds")
            s["ora_ts"] = time.time()
            s["versione"] = versione()
            s["salute"] = salute()
            s.setdefault("portiere", {})
            s.setdefault("comunicazioni", [])
            s["modo_chat"] = modo_chat()
            # 2026-10-03: ?parti=… (condizionale.py) = solo le sezioni cambiate rispetto a quelle che la pagina ha
            q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if condizionale and "parti" in q:
                s = condizionale.stato_a_pezzi(s, q["parti"][0])
            return self._invia(200, s)
        if percorso == "/api/assistenza/tecnico/stato":
            # lato tecnico (2026-09-29): solo con la chiave privata su questo Mac e solo da 127.0.0.1
            T = assistenza_tecnico()
            if not T or not self._da_locale():
                return self._invia(404, {"errore": "non trovato"})
            # «tunnel»: c'è la chiave ssh del tecnico (2026-10-02), quindi si può aprire un tunnel sulla VPS
            return self._invia(200, {"disponibile": True, "emessi": T.emessi(20),
                                     "tunnel": bool(getattr(T, "f_chiave_tecnico", None) and T.f_chiave_tecnico().is_file())})
        if percorso == "/api/assistenza/stato":
            return self._invia(200, assistenza_stato())
        if percorso == "/api/scadenze":
            dati = scadenze()
            chiuse = (parse_qs(urlsplit(self.path).query).get("chiuse") or [""])[0]
            if chiuse:
                try:
                    giorni = max(1, min(90, int(chiuse)))
                except ValueError:
                    return self._invia(400, {"errore": "chiuse: un numero di giorni"})
                try:
                    dati["chiuse"] = scadenze_chiuse(giorni)
                except Exception as e:  # noqa: BLE001
                    dati["chiuse"] = []
                    dati["errori"]["chiuse"] = f"{type(e).__name__}: {e}"[:300]
            return self._invia(200, dati)
        if percorso in ("/api/agente-attivita", "/api/agenti-attivita"):
            # attività per agente (2026-10-02): ?agente=crm:ceo-ai&lavagna=generale&limite=200&errori=1
            q = parse_qs(urlsplit(self.path).query)
            lavagna = (q.get("lavagna") or ["generale"])[0]
            if not attivita:
                return self._invia(503, {"errore": "attivita.py non c'è: il registro delle attività è spento"})
            if percorso == "/api/agenti-attivita":
                return self._invia(200, agenti_attivita_sommario(lavagna))
            chi = (q.get("agente") or [""])[0].strip()
            if not chi:
                return self._invia(400, {"errore": "manca ?agente=progetto:nome"})
            try:
                limite = int((q.get("limite") or ["200"])[0])
            except ValueError:
                limite = 200
            return self._invia(200, agente_attivita(chi, lavagna, limite, (q.get("errori") or ["0"])[0] == "1"))
        if percorso == "/api/agenti/modifiche":
            return self._invia(200, modifiche_pendenti())
        if percorso == "/api/lavagna/verifica":
            return self._invia(200, lavagna_verifica())
        if percorso == "/api/agenti/allineamento":
            lavagna = (parse_qs(urlsplit(self.path).query).get("lavagna") or ["generale"])[0]
            try:
                return self._invia(200, allineamento(lavagna))
            except ValueError as e:          # 27/09/2026: lavagna inesistente = 404, non 500
                return self._invia(404, {"errore": str(e)})
        if percorso == "/api/spazi":
            # 27/09/2026: anche i gruppi tolti, per il «ripristina» della pagina
            arch = leggi_json(GRUPPI_ARCHIVIO, {})
            # 02/10/2026: «archivio_mancante» = la cartella _archivio-… non c'è più: si può solo eliminare
            archiviati = sorted(({"progetto": k, "nome": (v.get("voce") or {}).get("nome") or k,
                                  "spazio": v.get("spazio") or "", "ts": v.get("ts"),
                                  "archivio_mancante": bool(v.get("archivio")) and not (Path(v["archivio"]) / "agents").is_dir()}
                                 for k, v in (arch.items() if isinstance(arch, dict) else []) if isinstance(v, dict)),
                                key=lambda g: -(g["ts"] or 0))
            return self._invia(200, {"spazi": elenco_spazi(), "gruppi_archiviati": archiviati,
                                     "squadre": {k: dict(v) for k, v in SQUADRA_STATO.items()}})
        if percorso == "/api/nota-di-casa":
            nome = (parse_qs(urlsplit(self.path).query).get("nome") or [""])[0]
            try:
                return self._invia(200, nota_di_casa(nome))
            except ValueError as e:
                return self._invia(404, {"errore": str(e)})
        if percorso == "/api/cartelle-progetto":
            q = parse_qs(urlsplit(self.path).query)
            try:
                return self._invia(200, cartelle_progetto((q.get("spazio") or [""])[0], (q.get("base") or [""])[0]))
            except ValueError as e:
                return self._invia(404, {"errore": str(e)})
        if percorso == "/api/scegli-cartella":
            try:
                return self._invia(200, {"cartella": scegli_cartella()})
            except ValueError as e:
                return self._invia(501, {"errore": str(e)})
        if percorso == "/api/agente-profilo":
            f = _file_agente_lecito((parse_qs(urlsplit(self.path).query).get("file") or [""])[0])
            if not f:
                return self._invia(404, {"errore": "agente non trovato"})
            campi, corpo = spazi.frontmatter(f.read_text(encoding="utf-8"))
            return self._invia(200, {"description": campi.get("description", ""), "model": campi.get("model", ""),
                                     "tools": campi.get("tools", ""), "corpo": corpo})
        m = re.fullmatch(r"/api/missione/([\w-]+)/agente/(\w+)", percorso)
        if m:
            try:
                d = cartella_missione(m.group(1))
            except ValueError as e:
                return self._invia(404, {"errore": str(e)})
            riga = next((a for a in leggi_json(d / "agenti.json", {}).get("agenti", []) if a.get("id") == m.group(2)), None)
            if not riga:
                return self._invia(404, {"errore": "sottoagente non trovato"})
            try:
                esito = (d / "esiti" / f"{m.group(2)}.md").read_text()[-60000:]
            except OSError:
                esito = riga.get("esito", "")
            return self._invia(200, {**riga, "esito_intero": esito})
        m = re.fullmatch(r"/api/missione/([\w-]+)", percorso)
        if m:
            try:
                d = cartella_missione(m.group(1))
            except ValueError as e:
                return self._invia(404, {"errore": str(e)})
            try:
                registro = (d / "registro.log").read_text()[-60000:]
            except OSError:
                registro = ""
            return self._invia(200, {**leggi_missione(d), "registro": registro})
        if percorso == "/api/tecnico":
            # Sta fuori dallo stato generale apposta: interroga il telefono con
            # adb e ci mette qualche secondo. Chi guarda il pannello del cliente
            # non deve pagarlo.
            return self._invia(200, {"telefono": tecnico.stato(), "log": tecnico.log_ponte(30)})
        if percorso == "/api/chat/storia":
            # La conversazione a voce con Jarvis: ultime 150 battute, sola lettura. 2026-10-05 (l'utente: il riquadro
            # «non è collegato alla chat a voce»): sono DUE conversazioni, la voce del Mac (backtalk) e quella
            # della VPS (jarvis-agent: telefono e sito). Si vedono tutte e due, con l'origine di ogni battuta
            # (chat_ponte.py le porta da una macchina all'altra); «macchina» dice dove va un «Manda» da qui.
            import chat_ponte
            try:
                loc = STATO.uno("locale")
            except KeyError:
                loc = {}
            return self._invia(200, {"battute": chat_ponte.storia(QUI.parent / "backtalk", SU_LINUX),
                                     "macchina": "vps" if SU_LINUX else "mac",
                                     "voce": bool(loc.get("voce")), "voce_stato": loc.get("voce_stato") or ""})
        if percorso == "/api/catalogo":
            comandi_cc = [{"id": c["id"], "nome": c["nome"], "descrizione": c["descrizione"],
                          "categoria": c.get("categoria", "custom")}
                         for c in (CFG.get("comandi_claude_code") or [])]
            return self._invia(200, {
                "verifiche": [{"id": k, "nome": v["nome"], "descrizione": v["descrizione"]} for k, v in VERIFICHE.items()],
                "agenti": agenti_crm(),
                "spazi": elenco_spazi(),
                "comandi": [{"id": k, "nome": v["nome"], "descrizione": v["descrizione"]}
                            for k, v in COMANDI_RAPIDI.items()],
                "comandi_claude_code": comandi_cc,
                "collegamenti": [{"id": k, "nome": k.replace("_", " ").capitalize()} for k in APRI_RAPIDO],
                "skills": skills(),
                "frequenti": frequenti(),
            })
        m = re.fullmatch(r"/api/lavoro/([\w-]+)", percorso)
        if m:
            lav = lavoro_copia(m.group(1))
            if not lav:
                return self._invia(404, {"errore": "lavoro non trovato"})
            try:
                testo = Path(lav["log"]).read_text()[-40000:]
            except OSError:
                testo = ""
            return self._invia(200, {**lav, "testo": testo})
        return self._invia(404, {"errore": "non trovato"})

    def do_POST(self):
        origine = self.headers.get("Origin")
        if not self._host_ok() or \
                (origine and origine not in (f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}")):
            return self._invia(403, {"errore": "richiesta non ammessa"})
        if self.headers.get("X-Token") != TOKEN:
            return self._invia(403, {"errore": "token scaduto: il Command Center è ripartito", "token_scaduto": True})
        try:
            lunghezza = int(self.headers.get("Content-Length", 0))
            if lunghezza > 400_000:
                return self._invia(413, {"errore": "richiesta troppo grande"})
            corpo = json.loads(self.rfile.read(lunghezza) or b"{}")
            if self.path == "/api/pannello":
                # 27/09/2026, contratto: {"versione": n} nel corpo = la versione letta dalla scheda;
                # se sul disco ce n'è una più nuova → 409 {errore, conflitto: true, pannello: <attuale>}.
                # Senza «versione» si salva come prima.
                v = corpo.get("versione") if isinstance(corpo, dict) else None
                if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                    return self._invia(400, {"errore": "versione: un numero intero"})
                if v is None:
                    return self._invia(428, {"errore": "manca la versione letta: ricarica la pagina"})
                try:
                    return self._invia(200, scrivi_pannello(corpo, versione=v))
                except PannelloVecchio as e:
                    return self._invia(409, {"errore": str(e), "conflitto": True, "pannello": e.attuale})
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
            if self.path == "/api/pannello/modifica":
                # salvataggio per scheda (audit 02/10/2026): niente 409, le operazioni si applicano al pannello attuale
                try:
                    return self._invia(200, modifica_pannello(corpo.get("ops"), corpo.get("base")))
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
            if self.path == "/api/aggiorna":
                # il pulsante «Aggiorna ora» (2026-10-05): avanti veloce da GitHub se serve, poi riavvio staccato del
                # pannello dopo la risposta. Con chat o missioni in corso chiede prima («forza»: riavvia lo stesso).
                import aggiornamento
                return self._invia(200, aggiornamento.applica(forza=corpo.get("forza") is True, occupato=lavoro_in_corso()))
            if self.path == "/api/connessioni":
                # solo dal Mac: dal sito (ponte) la politica di permesso non si cambia
                # 2026-10-05 (l'utente): dal sito si scrive come dal Mac, il blocco «X-CC-Ponte» è tolto
                C = _connessioni()
                try:
                    sid = str(corpo.get("id") or "")
                    if "stato" in corpo:
                        C.imposta(sid, str(corpo.get("stato")), origine="pagina")
                    elif "via_minuti" in corpo:
                        m = corpo.get("via_minuti")
                        if isinstance(m, bool) or not isinstance(m, int):
                            return self._invia(400, {"errore": "via_minuti: un numero intero"})
                        C.via(sid, m, origine="pagina")
                    elif corpo.get("chiudi") is True:
                        C.chiudi(sid, origine="pagina")
                    else:
                        return self._invia(400, {"errore": "serve «stato», «via_minuti» o «chiudi»"})
                except KeyError:
                    return self._invia(404, {"errore": "servizio sconosciuto"})
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
                return self._invia(200, C.stato_pubblico())
            if self.path == "/api/aspetto":
                import aspetto            # anche dal sito: è solo l'aspetto (tema e avatar), non cambia nessun permesso
                try:
                    try:   # chi scrive: una riga per scrittura (serve a capire i rimbalzi fra dispositivi)
                        with open(aspetto.CARTELLA / "aspetto.log", "a", encoding="utf-8") as _lg:
                            _lg.write(f"{time.strftime('%H:%M:%S')} ponte={self.headers.get('X-CC-Ponte') == '1'} "
                                      f"ua={(self.headers.get('User-Agent') or '')[:70]!r} dati={json.dumps(corpo)[:120]}\n")
                    except OSError:
                        pass
                    r = _stato_semplice_sulla_vps("/api/aspetto", corpo)
                    if r is not None:
                        return self._invia(*r)
                    return self._invia(200, aspetto.scrivi(corpo))
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
            if self.path == "/api/menu":
                # 2026-10-05 (l'utente): dal sito si scrive come dal Mac, il blocco «X-CC-Ponte» è tolto
                import menu_barra
                try:
                    r = _stato_semplice_sulla_vps("/api/menu", corpo)
                    if r is not None:
                        return self._invia(*r)
                    return self._invia(200, menu_barra.scrivi(corpo))
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
            if self.path == "/api/piani":
                # solo dal Mac: approvare un piano apre le finestre dei servizi, dal sito non si fa
                # 2026-10-05 (l'utente): dal sito si scrive come dal Mac, il blocco «X-CC-Ponte» è tolto
                P = _piano()
                azione_x = str(corpo.get("azione") or "")
                try:
                    funzione = {"approva": P.approva, "rifiuta": P.rifiuta, "conferma-finale": P.conferma_finale,
                                "ferma": P.ferma}.get(azione_x)
                    if not funzione:
                        return self._invia(400, {"errore": "azione: approva, rifiuta, conferma-finale o ferma"})
                    funzione(str(corpo.get("id") or ""), origine="pagina")
                except P.NonTrovato:
                    return self._invia(404, {"errore": "piano non trovato"})
                except P.PianoNonValido as e:
                    return self._invia(409, {"errore": str(e)})
                return self._invia(200, {"piani": [P.pubblico(p) for p in P.elenco()[:30]]})
            if self.path == "/api/routine":
                # 2026-10-05 (l'utente): «avvia» e «avvia-molte» senza conferma; «prepara» non tocca niente e torna il
                # comando esatto; «conferma» esegue SOLO con il codice del «prepara» (doppio passo nella pagina)
                if not isinstance(corpo, dict):
                    return self._invia(400, {"errore": "serve un oggetto JSON"})
                R = _routine()
                chi = "sito" if self.headers.get("X-CC-Ponte") == "1" else "pagina"
                azione_x = str(corpo.get("azione") or "")
                try:
                    if azione_x == "avvia":
                        return self._invia(200, R.avvia(corpo.get("id"), chi=chi))
                    if azione_x == "avvia-molte":
                        return self._invia(200, R.avvia_molte(corpo.get("ids"), chi=chi))
                    if azione_x == "prepara":
                        return self._invia(200, R.prepara(corpo, chi=chi))
                    if azione_x == "conferma":
                        if corpo.get("conferma") is not True:
                            return self._invia(428, {"errore": "serve la conferma esplicita: «Conferma ed esegui»"})
                        return self._invia(200, R.conferma(corpo.get("prep"), corpo.get("codice"), chi=chi))
                    if azione_x == "annulla":
                        return self._invia(200, R.annulla(corpo.get("prep")))
                    import routine_salva as RS
                    import routine_orari as RO
                    try:
                        if azione_x == "salva":            # 2026-10-05 14:25 (l'utente): applica subito, verifica, ripristina
                            return self._invia(200, RS.salva(corpo, chi=chi))
                        if azione_x == "anteprima":
                            return self._invia(200, RS.anteprima(corpo))
                        if azione_x == "scrivi-script":
                            return self._invia(200, RS.scrivi_script(corpo))
                        if azione_x == "descrivi":
                            return self._invia(200, RS.descrivi(corpo))
                    except RO.PianoNonValido as e:
                        return self._invia(400, {"errore": str(e)})
                    return self._invia(400, {"errore": "azione: avvia, avvia-molte, salva, anteprima, scrivi-script, descrivi"})
                except R.NonTrovata:
                    return self._invia(404, {"errore": "routine non trovata"})
                except R.RoutineNonValida as e:
                    return self._invia(428 if azione_x == "conferma" else 400, {"errore": str(e)})
            if self.path == "/api/incarichi":
                # solo dal Mac: dal sito (ponte) gli incarichi non si mandano e non si annullano
                # 2026-10-05 (l'utente): dal sito si scrive come dal Mac, il blocco «X-CC-Ponte» è tolto
                if not isinstance(corpo, dict):
                    return self._invia(400, {"errore": "serve un oggetto JSON"})
                azione_x = str(corpo.get("azione") or "")
                if azione_x == "nuovo":
                    a = str(corpo.get("a") or "").strip()
                    testo = corpo.get("testo")
                    tipo = str(corpo.get("tipo") or "domanda")
                    if a in INCARICHI_FASE2:
                        return self._invia(400, {"errore": "Fase 2: serve il sì di l'amministratore"})
                    if not re.fullmatch(r"[a-z0-9-]{1,40}", a):
                        return self._invia(400, {"errore": "a: il nome di un agente (minuscole, cifre, trattini)"})
                    if not isinstance(testo, str) or not testo.strip():
                        return self._invia(400, {"errore": "testo: scrivi cosa chiedi"})
                    if len(testo) > 4000:
                        return self._invia(400, {"errore": "testo: al massimo 4000 caratteri"})
                    if tipo not in ("domanda", "lavoro", "messaggio"):
                        return self._invia(400, {"errore": "tipo: domanda, lavoro o messaggio"})
                    return self._invia(*_incarichi_chiama("nuovo", INCARICHI_DA, a, testo, tipo=tipo))
                if azione_x == "annulla":
                    iid = str(corpo.get("id") or "")
                    if not iid or len(iid) > 64:
                        return self._invia(400, {"errore": "id: manca l'incarico da annullare"})
                    return self._invia(*_incarichi_chiama("annulla", iid, INCARICHI_DA))
                return self._invia(400, {"errore": "azione: nuovo o annulla"})
            if self.path == "/api/motore":
                risposta, codice = imposta_motore((corpo.get("motore") or "").strip())
                return self._invia(codice, risposta)
            if self.path == "/api/agente-profilo":
                # 2026-10-05 (l'utente): dal sito si scrive come dal Mac, il blocco «X-CC-Ponte» è tolto
                f = _file_agente_lecito(corpo.get("file", ""))
                if not f:
                    return self._invia(404, {"errore": "agente non trovato"})
                prima = f.read_text(encoding="utf-8")
                nuovo, cambiate = riscrivi_frontmatter(prima, {
                    "description": corpo.get("description"), "model": corpo.get("model"), "tools": corpo.get("tools"),
                    **campi_come_parla(corpo)})
                if not cambiate or nuovo == prima:
                    return self._invia(200, {"messaggio": "niente da salvare: il profilo è già così", "cambiate": []})
                scrivi_atomico(f, nuovo)
                evento(f"profilo aggiornato: {f.stem} ({', '.join(cambiate)})")
                registra_modifica("attivo" if cambiate == ["attivo"] else "profilo", _progetto_di_file(f), f.stem,
                                  da="scheda")
                tocca("spazi")              # menu laterale di tutte le schede subito, senza aspettare il sorvegliante
                return self._invia(200, {"messaggio": "salvato nel profilo vero", "cambiate": cambiate})
            if self.path == "/api/agente-comunica":
                f = _file_agente_lecito(corpo.get("file", ""))
                if not f:
                    return self._invia(404, {"errore": "agente non trovato"})
                # 27/09/2026: solo nomi d'agente veri (finivano nel profilo e nel frontmatter così
                # come arrivavano) e lettura+scrittura sotto AGENTI_LOCK, come la lavagna
                comunica = corpo.get("comunica") or []
                if not isinstance(comunica, list):
                    return self._invia(400, {"errore": "comunica: serve una lista di nomi"})
                nomi = list(dict.fromkeys(str(x).strip() for x in comunica
                                          if len(str(x).strip()) <= 80 and NOME_AGENTE.fullmatch(str(x).strip())))[:30]
                with AGENTI_LOCK:
                    prima = f.read_text(encoding="utf-8")
                    nuovo = aggiorna_comunica_con(prima, nomi)
                    if nuovo != prima:
                        scrivi_atomico(f, nuovo)
                if nuovo == prima:
                    return self._invia(200, {"messaggio": "comunicazioni già aggiornate"})
                # un filo fatto o tolto sulla lavagna: nel registro con i soli nomi cambiati
                prima_nomi = spazi.comunica_di(*spazi.frontmatter(prima))
                diversi = sorted(set(nomi) ^ set(prima_nomi))
                if diversi:
                    registra_modifica("filo", _progetto_di_file(f), f.stem, con=diversi)
                evento(f"{f.stem}: collegamenti aggiornati nel profilo ({len(nomi)})")
                return self._invia(200, {"messaggio": "comunicazioni aggiornate nel profilo"})
            if self.path == "/api/notifica-utente":
                testo = _testo(corpo.get("testo"), 500)
                if testo:
                    threading.Thread(target=notifica_utente, args=(testo, "Lavagna"), daemon=True).start()
                    evento(testo)
                return self._invia(200, {"messaggio": "notificato"})
            if self.path == "/api/notifica":
                # 2026-10-05: report e avvisi di Jarvis e del Postino nei loro fili (strumenti/notifica.py).
                # Solo da questa macchina: dal sito (cc-ponte) non passa, la tabella dei POST non lo contiene.
                if not self._da_locale():
                    return self._invia(403, {"errore": "solo da questa macchina"})
                if corpo.get("togli_prove") is True:
                    return self._invia(200, {"ok": True, "tolti": fili.togli_notifiche(solo_prova=True)})
                try:
                    r = fili.notifica(corpo.get("chi"), _testo(corpo.get("titolo"), 120), str(corpo.get("testo") or "")[:60000],
                                      dati=corpo.get("dati") if isinstance(corpo.get("dati"), (dict, list)) else None,
                                      prova=corpo.get("prova") is True, chiave=str(corpo.get("chiave") or ""),
                                      tipo=str(corpo.get("tipo") or ""), routine=_testo(corpo.get("routine"), 80))
                except ValueError as e:
                    return self._invia(400, {"errore": str(e)})
                evento(f"notifica di {fili.SPECIALI[r['interlocutore']]}: {_testo(corpo.get('titolo') or corpo.get('testo'), 80)}"
                       + (" (prova)" if corpo.get("prova") is True else ""))
                return self._invia(200, {"ok": True, "sessione": r["sessione"], "id": r["id"],
                                         "interlocutore": r["interlocutore"], "classe": r.get("classe"),
                                         "telegram_copia": bool((CFG.get("notifiche") or {}).get("telegram_copia"))})
            if self.path.startswith("/api/assistenza/tecnico/"):
                # 2026-09-29: lato tecnico (l'utente). Esiste solo con la chiave privata su questo Mac e
                # solo da 127.0.0.1; altrimenti 404, come se non ci fosse. La chiave non esce mai.
                T = assistenza_tecnico()
                if not T or not self._da_locale():
                    return self._invia(404, {"errore": "non trovato"})
                try:
                    if self.path == "/api/assistenza/tecnico/codice":
                        try:
                            minuti = int(corpo.get("minuti"))
                            scade_ore = float(corpo.get("scade_ore") or 48)
                        except (TypeError, ValueError):
                            return self._invia(400, {"errore": "minuti e scadenza devono essere numeri"})
                        if str(corpo.get("minuti")).strip() not in (str(minuti), f"{minuti}.0"):
                            return self._invia(400, {"errore": "i minuti devono essere un numero intero"})
                        v = T.emetti(corpo.get("cliente"), minuti, scade_ore=scade_ore,
                                     ricarica=corpo.get("ricarica") is True)
                        evento(f"assistenza: codice da {v['minuti']} minuti emesso (…{v['id'][-6:]})")
                        return self._invia(200, {"emesso": v, "emessi": T.emessi(20)})
                    if self.path == "/api/assistenza/tecnico/collegati":
                        T.apri_terminale(corpo.get("ssh"))
                        evento("assistenza: Terminale aperto verso il cliente (tmate)")
                        return self._invia(200, {"messaggio": "Terminale aperto"})
                    # 2026-10-02: tunnel sulla VPS. apri = UNA riga in authorized_keys di «assistenza» legata
                    # alla porta della richiesta + Terminale con ssh -J; chiudi = CHIUDI del tecnico.
                    if self.path == "/api/assistenza/tecnico/tunnel-apri":
                        # 2026-10-02 sera: richiesta v2 = anche lo schermo. «Collegati» apre Terminale e Schermo
                        # condiviso insieme; solo_schermo=true è il pulsante «Solo schermo».
                        solo = corpo.get("solo_schermo") is True
                        v = T.apri_tunnel(corpo.get("richiesta"), cliente=_testo(corpo.get("cliente"), 60), terminale=not solo)
                        cosa = " e ".join(x for x, s in (("Terminale", v.get("terminale")), ("Schermo condiviso", v.get("schermo"))) if s)
                        evento(f"assistenza: tunnel aperto sulla VPS (porta {v['porta']}), {cosa or 'niente'} verso il cliente")
                        return self._invia(200, {"messaggio": f"Tunnel aperto: {cosa} avviati" if cosa else "Tunnel aperto", **v,
                                                 "sessioni": T.stato_tunnel()})
                    if self.path == "/api/assistenza/tecnico/tunnel-chiudi":
                        v = T.chiudi_tunnel(str(corpo.get("porta") or corpo.get("id") or ""))
                        evento(f"assistenza: CHIUDI del tecnico, tunnel della porta {v.get('porta')} tolto")
                        return self._invia(200, {"messaggio": "Sessione chiusa sulla VPS", "chiusa": v,
                                                 "sessioni": T.stato_tunnel()})
                    if self.path == "/api/assistenza/tecnico/tunnel-stato":
                        return self._invia(200, {"sessioni": T.stato_tunnel()})
                except T.A.ErroreAssistenza as e:
                    return self._invia(400, {"errore": str(e)})
                except subprocess.TimeoutExpired:
                    return self._invia(500, {"errore": "la VPS o il Terminale non hanno risposto in tempo"})
                return self._invia(404, {"errore": "non trovato"})
            if self.path.startswith("/api/assistenza/"):
                # 2026-09-29: assistenza a distanza a pagamento, spenta di default
                A = _assistenza_mod
                if not assistenza_attiva_conf():
                    # spenta: non fa niente, salvo chiudere una sessione rimasta aperta (lo STOP vale sempre)
                    if self.path == "/api/assistenza/stop" and A and A.stato().get("attiva"):
                        A.ferma_sessione("fermata dal cliente")
                        evento("assistenza: sessione fermata dal cliente")
                    return self._invia(200, {"abilitata": False})
                if self.path == "/api/assistenza/stop":
                    s = A.ferma_sessione("fermata dal cliente")
                    evento("assistenza: sessione fermata dal cliente")
                    return self._invia(200, s)
                try:
                    if self.path == "/api/assistenza/codice":
                        s = A.accredita(str(corpo.get("codice") or ""))
                        evento(f"assistenza: ricarica accreditata, credito {s['credito_min']} minuti")
                        return self._invia(200, s)
                    if self.path == "/api/assistenza/ordine":
                        s = A.crea_ordine(corpo.get("ore"))
                        evento(f"assistenza: ordine di {s['ore']} ore preparato (rif. {s['rif'][:6].upper()})")
                        return self._invia(200, s)
                    if self.path == "/api/assistenza/avvia":
                        s = A.avvia_sessione(corpo.get("consenso") is True)
                        evento("assistenza: sessione avviata con il consenso del cliente")
                        return self._invia(200, s)
                except A.ErroreAssistenza as e:
                    return self._invia(400, {"errore": str(e)})
                return self._invia(404, {"errore": "non trovato"})
            if self.path == "/api/azione":
                # proposta 2026-10-03 (cc-ponte tappa 3): una richiesta arrivata da internet porta «X-CC-Ponte: 1»
                # (lo mette il ponte). Toglie e non dà: il modo «lavoro» diventa «approvazione», le missioni
                # «lavoro» chiedono all'utente ogni strumento non di lettura. La pagina non può dare se stessa il segno
                # al contrario: senza intestazione tutto resta com'è oggi.
                if isinstance(corpo, dict):
                    corpo.pop("_dal_ponte", None)
                    if self.headers.get("X-CC-Ponte") == "1":
                        corpo["_dal_ponte"] = True
                try:
                    return self._invia(200, azione(corpo))
                except ErroreHttp as e:          # 2026-10-03: approva → 404 / 409 (contratto sez. 1)
                    return self._invia(e.codice, {"errore": str(e)})
            # /api/chat (API Anthropic o Gemini diretti, senza vault né agenti) tolto il 2026-09-26:
            # nessuna pagina lo chiamava. La chat passa da «chiedi» e da /api/claude-code.
            elif self.path == "/api/claude-code":
                # Riceve: {"messaggio": "...", "agente": "..."}; risponde: {"successo", "output", "codice", "modo"}.
                # Il modo è quello della chat (modo_chat in configurazione.json, dal 2026-09-26: «lavoro»
                # = --dangerously-skip-permissions con la guardia accesa, «lettura» = plan). Il client non
                # lo decide: il campo «piano» del payload si ignora. (/api/terminal, che eseguiva
                # qualunque comando con shell=True, e /api/grafo-json, che nessuna pagina chiamava, sono
                # stati tolti il 26/09/2026.)
                messaggio = (corpo.get("messaggio") or "").strip()
                agente = (corpo.get("agente") or "").strip() or None
                if not messaggio:
                    return self._invia(400, {"errore": "messaggio vuoto"})
                if agente and not re.fullmatch(r"[\w.-]{1,80}", agente):
                    return self._invia(400, {"errore": "agente non valido"})
                modo = modo_chat()
                modo = modo_sicuro(modo)             # 2026-10-05: dal sito come dal Mac (era «approvazione»)
                motore = motore_richiesto(corpo)     # 2026-09-26: anche qui il motore scelto, non sempre claude
                cmd_cc = comando_motore(motore, messaggio, modo, agente=agente, cwd=AGENTE)
                try:
                    result = subprocess.run(cmd_cc, capture_output=True,
                                            text=True, timeout=120, env=env_motore(motore), cwd=str(AGENTE),
                                            stdin=subprocess.DEVNULL)
                    grezzo = result.stdout if result.returncode == 0 else (result.stdout or "") + (result.stderr or "")
                    risposta = estrai_risposta(result.stdout or "", motore)[0]
                    output = risposta if risposta is not None else grezzo
                    return self._invia(200, {"successo": result.returncode == 0, "output": output[:10000],
                                             "codice": result.returncode, "modo": modo, "motore": motore,
                                             "modello": "piano" if modo == "lettura" or (modo == "approvazione" and motore != "claude")
                                             else modo})
                except subprocess.TimeoutExpired:
                    return self._invia(200, {"successo": False, "output": "Comando scaduto (>120s)",
                                             "codice": -1, "errore": "timeout"})
                finally:
                    togli_config_mcp(cmd_cc)            # modo «approvazione»: il --mcp-config temporaneo
            else:
                return self._invia(404, {"errore": "non trovato"})
        except (ValueError, KeyError) as e:
            return self._invia(400, {"errore": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._invia(500, {"errore": str(e)})


# ---------------------------------------------------------------- assistenza a distanza (2026-09-29)
# Spenta di default: senza «abilitata»: true in assistenza.json gli endpoint rispondono
# {abilitata: false} e non fanno niente. Lo STOP però funziona sempre.

def assistenza_attiva_conf():
    return bool(_assistenza_mod) and _assistenza_mod.config().get("abilitata") is True


def assistenza_stato():
    if not _assistenza_mod:
        return {"abilitata": False, "errore": "modulo assistenza mancante (strumenti/assistenza.py)"}
    if not assistenza_attiva_conf():
        return {"abilitata": False}
    return _assistenza_mod.stato()


def assistenza_tick():
    """Ciclo ogni 20 s: scala i blocchi di 15 minuti in anticipo, chiude a credito finito."""
    if not _assistenza_mod:
        return
    fatto = _assistenza_mod.tick()
    if fatto:
        evento(fatto)


def assistenza_chiudi_uscendo():
    """Pannello chiuso = niente banner: la sessione condivisa non resta aperta senza che si veda."""
    if _assistenza_mod:
        try:
            _assistenza_mod.ferma_sessione("Command Center chiuso")
        except Exception:  # noqa: BLE001
            pass


def main():
    try:     # 2026-10-05: la versione del codice con cui parte il pannello (aggiornamento.py: «Aggiorna ora» = riavvio)
        import aggiornamento
        aggiornamento.segna_avvio()
    except Exception as e:  # noqa: BLE001
        print(f"aggiornamento: versione di avvio non letta ({e})")
    conversazione.riavvio()          # le domande rimaste a metà col pannello spento diventano «interrotte»
    try:
        fili.riavvio()               # e nell'archivio dei fili le loro attese diventano «Risposta persa»
    except Exception as e:  # noqa: BLE001
        print(f"archivio dei fili: riavvio non riuscito ({e})")
    cicli = [(raccogli_locale, 5), (raccogli_locale_pesante, 15), (archivia_missioni_vecchie, 300),
             (raccogli_telefono, 10),
             (raccogli_vps, 60), (raccogli_telegram, 20), (guardia_mac, 60), (raccogli_memoria, 120),
             (raccogli_catena, 120), (raccogli_claude, 300), (raccogli_agenti, 20),
             (aggiorna_cruscotto, 120), (aggiorna_mappa_agenti, 1800),
             (raccogli_portiere, 20), (sorveglia_file, 2), (sentinella, 60), (raccogli_comunicazioni, 2),
             (assistenza_tick, 20), (sorveglia_approvazioni, 1)]
    if PROVA:
        # la copia di prova legge e basta: niente note nel vault, niente missioni spostate, niente Telegram
        via = {archivia_missioni_vecchie, guardia_mac, aggiorna_cruscotto, aggiorna_mappa_agenti}
        cicli = [(f, o) for f, o in cicli if f not in via]
    if sys.platform == "darwin" and (not PROVA or os.environ.get("CC_FONTE_VPS") == "1") \
            and os.environ.get("CC_FONTE_VPS") != "0" \
            and (CFG.get("fonte_vps") is True or (CFG.get("fonte_vps") is None and fonte_vps.configurato())):
        # 2026-10-05 (l'utente, «procedi»): lavagna, fili, aspetto e barra hanno una sola fonte, la VPS (fonte_vps.py)
        try:
            fonte_vps.avvia(leggi_pannello, _specchio_pannello, PANNELLO_LOCK, evento, fili.cartella(), fili.AVVISA)
            evento("fonte unica: lavagna, chat, aspetto e barra si leggono e si scrivono sulla VPS")
        except Exception as e:  # noqa: BLE001
            evento(f"fonte unica non partita: {type(e).__name__}: {str(e)[:120]}")
    if sys.platform == "darwin" and not PROVA:
        cicli.append((specchia_notifiche, 20))     # 2026-10-05: i fili delle notifiche, dalla VPS
        cicli.append((controlla_launchd_errori, 300))   # e i lavori automatici del Mac finiti in errore
    if sys.platform == "darwin" and os.environ.get("CC_FONTE_VPS") != "0" \
            and (CFG.get("fonte_vps") is True or (CFG.get("fonte_vps") is None and fonte_vps.configurato())):
        # 2026-10-06: «00 Cruscotto» e le note degli agenti le scrive solo la VPS (sempre accesa); il Mac le legge da OneDrive
        cicli = [(f, o) for f, o in cicli if f not in (aggiorna_cruscotto, aggiorna_mappa_agenti)]
    if sys.platform == "win32":
        # ramo windows: niente centralino né guardia di Telegram (tmux); senza vault niente note generate
        via = {raccogli_telefono, guardia_mac}
        if not CFG.get("vault"):
            via |= {aggiorna_cruscotto, aggiorna_mappa_agenti}
        cicli = [(f, o) for f, o in cicli if f not in via]
    for funzione, ogni in cicli:
        threading.Thread(target=ciclo, args=(funzione, ogni), daemon=True).start()
    evento("Command Center avviato" + (" (copia di prova)" if PROVA else ""))
    if not PROVA or os.environ.get("CC_INCARICHI_PONTE") == "1":
        try:       # 2026-10-04: gli incarichi della coda diventano eventi della lavagna (incarichi_ponte.py)
            import incarichi_ponte
            incarichi_ponte.avvia()
        except Exception as e:  # noqa: BLE001 — la lavagna funziona anche senza
            evento(f"incarichi_ponte non partito: {type(e).__name__}: {str(e)[:100]}")
        # 2026-10-05 (lavagna viva): le prese di lavori.py diventano eventi (lavori_ponte.py), e sul Mac il
        # registro viaggia verso la VPS e ritorno in pochi secondi (attivita_ponte.py)
        try:
            import lavori_ponte
            lavori_ponte.avvia(coperto=_coperto_dal_gancio)
        except Exception as e:  # noqa: BLE001
            evento(f"lavori_ponte non partito: {type(e).__name__}: {str(e)[:100]}")
        try:
            import attivita_ponte
            attivita_ponte.avvia()
        except Exception as e:  # noqa: BLE001
            evento(f"attivita_ponte non partito: {type(e).__name__}: {str(e)[:100]}")
        try:     # 2026-10-05: la chat a voce del Mac e quella della VPS (telefono, sito) viaggiano in pochi secondi
            import chat_ponte
            chat_ponte.avvia(QUI.parent / "backtalk")
        except Exception as e:  # noqa: BLE001
            evento(f"chat_ponte non partito: {type(e).__name__}: {str(e)[:100]}")
    if not PROVA:
        # il server del volto e del grafo sinapsi parte con il pannello: il grafo è dentro la Home
        # (su Windows il volto è l'orb: lo accende avvia_orb qui sotto; ai-visualizer non c'è)
        if sys.platform != "win32":
            threading.Thread(target=lambda: interruttore("volto", True), daemon=True).start()
        threading.Thread(target=avvia_orb, args=("partenza",), daemon=True).start()
        # i terminali della VPS rimasti dal Command Center di prima (vedi _ssh_vps_orfani)
        if sys.platform != "win32":
            threading.Thread(target=lambda: _term_uccidi_orfani("vps"), daemon=True).start()
    srv = ServerVeloce((HOST, PORTA), Gestore)
    # il terminale vive quanto il pannello: chiuso il Command Center, ttyd si ferma
    import atexit
    atexit.register(terminale_ferma_tutti)
    atexit.register(assistenza_chiudi_uscendo)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"Command Center su http://127.0.0.1:{PORTA}  (Ctrl-C per fermare)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
