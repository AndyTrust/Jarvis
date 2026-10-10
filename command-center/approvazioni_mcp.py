#!/usr/bin/env python3
"""Gestore dei permessi del modo «approvazione» (2026-10-03): un server MCP su stdio con UNO strumento,
«approva», che claude chiama con --permission-prompt-tool mcp__approvazioni__approva.

Verificato il 2026-10-03 con Claude Code 2.1.288 (prova reale, vedi prove/prova_approvazioni.py):
  ingresso  {"tool_name": "Bash", "input": {...}, "tool_use_id": "toolu_…"}
  uscita    content[0].text = JSON {"behavior": "allow", "updatedInput": {...}}
                                 o {"behavior": "deny", "message": "..."}

Cosa fa (dal 2026-10-03 sera, CONTRATTO-registro.md): chiede a regole_permessi.valuta che cosa dice il
file delle regole (~/.locale-onedrive/jarvis-cc/regole-permessi.json, la prima regola che corrisponde decide,
nessuna = chiedi). «consenti» risponde subito allow, «nega» risponde subito deny con la regola e la sua nota
(nessuna scheda); entrambe lasciano una riga nel registro. «chiedi» crea l'approvazione nell'archivio
condiviso (approvazioni.py, con il campo «regola»), aspetta la decisione dell'utente
guardando l'archivio ogni 500 ms fino alla scadenza (15 minuti) e risponde allow con l'ingresso
identico, oppure deny con un messaggio chiaro. Qualunque errore, Command Center spento o scadenza:
deny. Mai allow per errore.

Dal 2026-10-04 (l'utente: «togli tutte le richieste dei permessi: Jarvis li deve autorizzare sempre e controllare
che rispettino la richiesta»): se configurazione.json ha "autorizza_jarvis": true (se manca vale true), al posto
della scheda decide conformita.decidi — paletti duri, poi il controllo che l'azione serva alla richiesta dell'utente
(il testo del turno, dall'archivio dei fili) — e la risposta torna subito. Registro: fonte «auto».

Ambiente (lo scrive server.py nel --mcp-config del lavoro):
  CC_LAVORO_ID, CC_SESSIONE, CC_AGENTE, CC_CWD   a chi appartiene la richiesta
  CC_APPROVAZIONI_DIR, CC_APPROVAZIONI_SCADENZA_S  solo per le prove
  CC_CONFIG    configurazione.json da cui leggere approvazioni_auto (default: quella accanto), usata
               solo per creare il file delle regole la prima volta
  CC_REGOLE_FILE, CC_REGISTRO_DIR   solo per le prove
Solo libreria standard.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approvazioni as A  # noqa: E402

NOME = "approvazioni"
STRUMENTO = "approva"
ATTESA_POLL_S = 0.5
_SCRIVI = threading.Lock()

SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string", "description": "lo strumento che Claude vuole usare"},
        "input": {"type": "object", "description": "l'ingresso dello strumento"},
        "tool_use_id": {"type": "string"},
    },
    "required": ["tool_name", "input"],
}


def manda(msg):
    with _SCRIVI:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def risposta_testo(mid, decisione):
    manda({"jsonrpc": "2.0", "id": mid,
           "result": {"content": [{"type": "text", "text": json.dumps(decisione, ensure_ascii=False)}]}})


def nega(messaggio):
    return {"behavior": "deny", "message": messaggio}


def autorizza_jarvis(strumento, ingresso, cwd, lavoro_id, agente, d):
    """2026-10-04 (l'utente: «togli tutte le richieste dei permessi»): con "autorizza_jarvis": true in
    configurazione.json (default true) al posto della scheda decide conformita.decidi, subito. None = la chiave è
    false: si fa la scheda come prima. Un errore qui non diventa mai un allow."""
    try:
        import conformita as K
    except Exception as e:  # noqa: BLE001 — modulo rotto: no, senza scheda (la chiave vale true per default)
        return nega(f"Permesso negato: il controllo di Jarvis non si carica ({type(e).__name__}). Dillo all'utente.")
    if not K.attiva(os.environ.get("CC_CONFIG") or None):
        return None
    rischio = "alto" if d.get("rischio") == "alto" else (d.get("rischio") or A.rischio(strumento, ingresso, cwd))
    richiesta = K.richiesta_di_utente(lavoro_id, os.environ.get("CC_SESSIONE"))
    import badge as B  # noqa: PLC0415
    esito = K.decidi(richiesta, strumento, ingresso, rischio, cwd,
                     chiave_badge=B.chiave_di(os.environ.get("CC_SESSIONE"), lavoro_id))
    K.registra(esito, strumento, ingresso, rischio, lavoro_id, agente)
    if esito.get("esito") == "autorizza":
        return {"behavior": "allow", "updatedInput": ingresso}
    return nega(f"Non rispetta la richiesta dell'utente: {esito.get('motivo') or 'nessun motivo'} "
                f"({A.riepilogo(strumento, ingresso)}). Non riprovare la stessa azione e non cercare strade diverse: "
                "se serve davvero, chiedi all'utente in chat.")


def decidi(argomenti, attesa_poll=ATTESA_POLL_S):
    """La decisione per una richiesta di permesso. Ogni errore diventa deny."""
    try:
        strumento = str(argomenti.get("tool_name") or "")
        ingresso = argomenti.get("input")
        if not strumento or not isinstance(ingresso, dict):
            return nega("Permesso negato: richiesta malformata.")
        if strumento.lower().startswith("mcp__approvazioni"):
            # revisione 3 (F8): lo strumento del gestore non si chiama come strumento normale
            return nega("Permesso negato: il gestore dei permessi non si usa come strumento.")
        cwd = os.environ.get("CC_CWD") or os.getcwd()
        lavoro_id = os.environ.get("CC_LAVORO_ID") or None
        agente = os.environ.get("CC_AGENTE") or "Jarvis"
        try:
            import regole_permessi as R
            d = R.valuta(strumento, ingresso, cwd)          # non solleva mai: un errore = «chiedi»
        except Exception:  # noqa: BLE001 — modulo mancante o rotto: si chiede all'utente, mai allow
            R, d = None, {"azione": "chiedi", "regola": "predefinita", "rischio": None}
        if d["azione"] == "consenti":
            R.registra_decisione(d, strumento, ingresso, lavoro_id, agente)
            return {"behavior": "allow", "updatedInput": ingresso}
        if d["azione"] == "nega":
            R.registra_decisione(d, strumento, ingresso, lavoro_id, agente)
            return nega(R.messaggio_nega(d, A.riepilogo(strumento, ingresso)))
        auto = autorizza_jarvis(strumento, ingresso, cwd, lavoro_id, agente, d)
        if auto is not None:
            return auto
        if not A.command_center_vivo():
            return nega("Permesso negato: il Command Center è spento e nessuno può approvare. "
                        "Riprova quando il Command Center è acceso.")
        try:
            a, _ = A.crea(strumento, ingresso, cwd=cwd, lavoro_id=lavoro_id, sessione=os.environ.get("CC_SESSIONE") or None,
                          agente=agente, regola=d.get("regola") or "predefinita", rischio_regola=d.get("rischio"))
        except A.TroppeInAttesa as e:
            if R is not None:
                R.registra_decisione({"azione": "nega", "regola": "troppe-in-attesa", "rischio": d.get("rischio"),
                                      "origine": d.get("origine")}, strumento, ingresso, lavoro_id, agente)
            return nega(f"Permesso negato: {e}. Aspetta che l'utente decida le richieste già aperte.")
        ultimo_vivo = time.time()
        while True:
            cur = A.leggi(a["id"])
            if not cur:
                return nega("Permesso negato: la richiesta di approvazione è sparita dall'archivio.")
            if cur["stato"] == "approvata":
                return {"behavior": "allow", "updatedInput": ingresso}
            if cur["stato"] == "rifiutata":
                motivo = f" Motivo: {cur['motivo']}" if cur.get("motivo") else ""
                return nega(f"L'utente ha rifiutato questa azione ({cur['riepilogo']}).{motivo} "
                            "Non riprovarla: chiedi all'utente come procedere.")
            if cur["stato"] == "scaduta":
                return nega("Permesso negato: nessuna risposta dell'utente entro il tempo massimo (richiesta scaduta).")
            if A.command_center_vivo():
                ultimo_vivo = time.time()
            elif time.time() - ultimo_vivo > A.BATTITO_MAX_S:
                return nega("Permesso negato: il Command Center si è spento mentre aspettavo la risposta dell'utente.")
            time.sleep(attesa_poll)
    except Exception as e:  # noqa: BLE001
        return nega(f"Permesso negato per un errore del gestore dei permessi: {type(e).__name__}.")


def gestisci(msg):
    metodo, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return                       # notifiche (initialized, cancelled): niente risposta
    if metodo == "initialize":
        versione = ((msg.get("params") or {}).get("protocolVersion")) or "2024-11-05"
        manda({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": versione, "capabilities": {"tools": {}},
            "serverInfo": {"name": NOME, "version": "1.0"}}})
    elif metodo == "tools/list":
        manda({"jsonrpc": "2.0", "id": mid, "result": {"tools": [{
            "name": STRUMENTO,
            "description": "Gestore dei permessi del Command Center di Jarvis: chiede all'utente se l'azione si può fare.",
            "inputSchema": SCHEMA}]}})
    elif metodo == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != STRUMENTO:
            manda({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "strumento sconosciuto"}})
            return
        # un thread per richiesta: con più strumenti in parallelo nessuna aspetta l'altra
        threading.Thread(target=lambda: risposta_testo(mid, decidi(params.get("arguments") or {})),
                         daemon=True).start()
    elif metodo == "ping":
        manda({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        manda({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"metodo non gestito: {metodo}"}})


def main():
    for riga in sys.stdin:
        riga = riga.strip()
        if not riga:
            continue
        try:
            msg = json.loads(riga)
        except ValueError:
            manda({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON non valido"}})
            continue
        if isinstance(msg, dict):
            try:
                gestisci(msg)
            except Exception as e:  # noqa: BLE001
                if msg.get("id") is not None:
                    manda({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": type(e).__name__}})


if __name__ == "__main__":
    main()
