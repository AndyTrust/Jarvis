#!/usr/bin/env python3
"""Prove della chat Postino (2026-10-05, programmatore-postino). Uso:

    python3 command-center/prove/prova_chat_postino.py

L'utente, 05/10/2026 13:20: «dentro la chat ci deve essere la chat Jarvis e la chat Postino, la stessa chat identica».
Parti:
  a) server.py (importato con CC_PROVA=1 e un archivio dei fili temporaneo): nel filo «postino» il comando di
     claude porta --agent postino e la sessione del filo; nel filo «notifiche-jarvis» e nella chat di Jarvis no;
     il contesto della chat Postino unisce le notifiche dei due fili in ordine di tempo, con il mittente
  b) app.js con node: messaggiChat() unisce i fili in ordine di ts, i messaggi senza ts restano al loro posto,
     togliMessaggio() toglie dal filo giusto
  c) i file della pagina: il pannello laterale non c'è più, le schede sì, node --check

Non lancia claude, non tocca la posta, la VPS né il Command Center vero. Ogni riga è PASS o FAIL; esito 1 se qualcosa
non passa.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CC = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="prova-postino-"))
os.environ["CC_PROVA"] = "1"
os.environ["CC_FILI_DIR"] = str(TMP / "fili")
sys.path.insert(0, str(CC))

RISULTATI = {"PASS": 0, "FAIL": 0}


def esito(nome, ok, dettaglio=""):
    tipo = "PASS" if ok else "FAIL"
    RISULTATI[tipo] += 1
    print(f"{tipo}  {nome}" + (f"  — {str(dettaglio)[:300]}" if dettaglio and not ok else ""), flush=True)
    return ok


# ---------------------------------------------------------------- a) server
import fili  # noqa: E402
import conversazione  # noqa: E402
conversazione.FILE = TMP / "conversazioni.json"      # le domande di prova non entrano nelle conversazioni vere
import server  # noqa: E402

S = "11111111-1111-4111-8111-111111111111"
prof = server.profilo_postino()
esito("profilo postino trovato in ~/.claude/agents", bool(prof) and prof["nome"] == "postino", prof)
cmd = server.comando_motore("claude", "quanti report?", "lettura", sessione=S, agente=prof)
esito("filo postino: claude --agent postino", cmd[-2:] == ["--agent", "postino"], cmd)
esito("filo postino: sessione del filo", S in cmd, cmd)
cmd_j = server.comando_motore("claude", "ciao", "lettura", sessione=S, agente=None)
esito("chat Jarvis: niente --agent", "--agent" not in cmd_j, cmd_j)
cmd_g = server.comando_motore("gemini", "ciao", "lettura", sessione=S, agente=prof)
esito("altri motori: il profilo del postino in testa", "agente postino" in cmd_g[2], cmd_g[2][:120])

t0 = time.time() - 600
fili.notifica("postino", "Report posta 07:00", "1) mail A", ts=t0)
fili.notifica("jarvis", "Report mattino", "tutto ok", ts=t0 + 60)
fili.notifica("postino", "Report posta 17:00", "1) mail B", ts=t0 + 120)
sp = fili.sessione_corrente("postino")
ctx = server.contesto_notifiche(sp, "postino")
i_a, i_j, i_b = ctx.find("Report posta 07:00"), ctx.find("Report mattino"), ctx.find("Report posta 17:00")
esito("contesto postino: unisce i due fili in ordine di tempo", -1 < i_a < i_j < i_b, ctx[:400])
esito("contesto postino: mittente visibile", "--- Jarvis ·" in ctx and "--- Postino ·" in ctx, ctx[:400])
ctx_j = server.contesto_notifiche(fili.sessione_corrente("notifiche-jarvis"), "notifiche-jarvis")
esito("contesto notifiche-jarvis: solo il suo filo", "Report posta" not in ctx_j, ctx_j[:300])

# specchia() sul Mac dopo «Ricomincia» dal Mac: le notifiche nuove della VPS entrano nel filo nuovo del Mac
ora = time.time()
N = "33333333-3333-4333-8333-333333333333"
fili.reset(N, "postino", "Nuova conversazione", ts=ora)
remoto = {"sessione": "44444444-4444-4444-8444-444444444444", "interlocutore": "postino", "creato": ora - 1000,
          "aggiornato": ora + 5, "messaggi": [
              {"id": "n-vecchia", "chi": "lui", "testo": "vecchia", "ts": ora - 900, "notifica": True},
              {"id": "q-vps", "chi": "io", "testo": "domanda fatta sul sito", "ts": ora + 1},
              {"id": "n-nuova", "chi": "lui", "testo": "nuova", "ts": ora + 5, "notifica": True}]}
fili.specchia(remoto)
ids = [m["id"] for m in fili.leggi(N)["messaggi"]]
esito("specchio dopo Ricomincia dal Mac: entra solo la notifica nuova", "n-nuova" in ids and "n-vecchia" not in ids
      and "q-vps" not in ids, ids)
esito("specchio: il filo corrente resta quello nuovo", fili.sessione_corrente("postino") == N, fili.sessione_corrente("postino"))
remoto2 = dict(remoto, sessione="55555555-5555-4555-8555-555555555555", creato=ora + 50, aggiornato=ora + 60,
               messaggi=[{"id": "n-dopo", "chi": "lui", "testo": "dopo", "ts": ora + 60, "notifica": True}])
fili.specchia(remoto2)
esito("specchio: un filo della VPS più nuovo (Ricomincia dal sito) si copia com'è",
      [m["id"] for m in fili.leggi(remoto2["sessione"])["messaggi"]] == ["n-dopo"])
sp = fili.sessione_corrente("postino")

# classifica(): l'unico punto con la regola (l'utente, 2026-10-05 15:05)
C = fili.classifica
casi = [
    (("notifiche-jarvis", "Report del mattino · 05/10"), "report"),
    (("notifiche-jarvis", "Pranzo · 05/10", "servizio-pranzo-2026-10-05"), "report"),
    (("notifiche-jarvis", "Azienda Uno · Report giornaliero del 2026-10-05 · garante MANCA QUALCOSA"), "report"),
    (("notifiche-jarvis", "Riunione patrimonio · 05/10", "riunione-patrimonio-2026-10-05"), "report"),
    (("postino", "Posta del mattino · 4 nuove"), "report"),
    (("postino", "Azienda Due — nuova mail su info"), "report"),
    (("notifiche-jarvis", "Errore: com.jarvis.pubblica-codice"), "avviso"),
    (("notifiche-jarvis", "Routine aggiornata: jarvis-verifica-routine"), "avviso"),
    (("notifiche-jarvis", "Routine creata: prova-routine"), "avviso"),
    (("notifiche-jarvis", "App Jarvis 1.1.5 pubblicata"), "avviso"),
    (("notifiche-jarvis", "Lavagna"), "avviso"),
    (("notifiche-jarvis", "Avviso"), "avviso"),
    (("postino", "Errore: jarvis-posta-smista"), "avviso"),
]
for args, atteso in casi:
    esito(f"classifica {args[1][:45]!r} → {atteso}", C(*args) == atteso, C(*args))
esito("--tipo vince sulla regola", C("notifiche-jarvis", "Errore: x", tipo="report") == "report"
      and C("postino", "Posta", tipo="avviso") == "avviso")
gruppi = TMP / "routine-gruppi.json"
gruppi.write_text('{"routine": {"vps:mia-routine": {"avvisa_postino": true}, "vps:altra": {}}}', encoding="utf-8")
os.environ["CC_ROUTINE_GRUPPI"] = str(gruppi)
esito("routine con avvisa_postino → report", C("notifiche-jarvis", "Esito di oggi", routine="mia-routine") == "report")
esito("routine senza avvisa_postino → avviso", C("notifiche-jarvis", "Esito di oggi", routine="altra") == "avviso")
esito("l'errore di una routine al Postino va a Jarvis", C("notifiche-jarvis", "Errore: mia-routine", routine="mia-routine") == "avviso")
rep_ = fili.notifica("jarvis", "Report di prova", "r", prova=True)
avv = fili.notifica("jarvis", "Routine aggiornata: x", "a", prova=True)
err = fili.notifica("jarvis", "Errore: y", "e", prova=True)
esito("notifica() scrive la classe", (rep_["classe"], avv["classe"], err["classe"]) == ("report", "avviso", "avviso"))
tel = {v["id"]: v for v in json.loads(fili.file_telefono().read_text(encoding="utf-8"))}
esito("telefono: suona per il report (scheda Postino)", tel.get(rep_["id"], {}).get("k") == "postino", tel.get(rep_["id"]))
esito("telefono: suona per l'errore (chat di Jarvis)", tel.get(err["id"], {}).get("k") == "notifiche-jarvis", tel.get(err["id"]))
esito("telefono: tace per il salvataggio di una routine", avv["id"] not in tel)
grezzo = fili.leggi(fili.sessione_corrente("notifiche-jarvis"))
esito("leggi(): classe anche alle notifiche vecchie", all(m.get("classe") in fili.CLASSI for m in grezzo["messaggi"] if m.get("notifica")))
ctx = server.contesto_notifiche(sp, "postino")
esito("contesto del Postino: senza avvisi", "Routine aggiornata" not in ctx and "Errore: y" not in ctx, ctx[:300])
SJ = "66666666-6666-4666-8666-666666666666"
fili.domanda(SJ, "jarvis", "ciao", "lav1", ts=time.time() - 30)
fili.notifica("jarvis", "Errore: dopo la domanda", "e2", prova=True)
cj = server.contesto_avvisi(SJ)
esito("chat Jarvis: gli avvisi arrivati dopo l'ultimo messaggio vanno a Jarvis", "Errore: dopo la domanda" in cj
      and "Report di prova" not in cj, cj[:300])

# chiedi() nel filo postino: il lavoro parte con --agent postino e chi = Postino (nuovo_lavoro finto: niente claude)
presi = {}
vero = server.nuovo_lavoro
server.nuovo_lavoro = lambda titolo, cmd, cwd, **kw: presi.update(titolo=titolo, cmd=cmd, info=kw.get("info")) or {"id": "finto"}
try:
    server.chiedi({"testo": "quanti report hai ricevuto oggi?", "sessione": sp, "filo": "postino", "motore": "claude"})
    esito("chiedi filo postino: --agent postino", "--agent" in presi["cmd"] and presi["cmd"][presi["cmd"].index("--agent") + 1] == "postino", presi.get("cmd"))
    esito("chiedi filo postino: titolo e interlocutore", presi["titolo"].startswith("Chat Postino") and presi["info"]["interlocutore"] == "postino", presi.get("info"))
    server.chiedi({"testo": "ciao", "sessione": "22222222-2222-4222-8222-222222222222", "motore": "claude"})
    esito("chiedi chat Jarvis: invariata", "--agent" not in presi["cmd"] and presi["info"]["interlocutore"] == "jarvis", presi.get("cmd"))
finally:
    server.nuovo_lavoro = vero

# ---------------------------------------------------------------- b) app.js con node
app = (CC / "static" / "app.js").read_text(encoding="utf-8")


def sorgente(nome):
    m = re.search(r"^function " + nome + r"\(.*?^}\n", app, re.S | re.M)
    return m.group(0) if m else ""


def costante(nome):
    m = re.search(r"^const " + nome + r" = .*?;\n", app, re.S | re.M)
    return m.group(0) if m else ""


js = """
const THREADS = {
  postino: { sessione: "p", messaggi: [ {fid:"n-1", testo:"P1", ts:100, notifica:true}, {fid:"q-1", chi:"io", testo:"domanda", ts:300},
    {fid:"a-1", testo:"risposta", ts:310}, {chi:"io", testo:"locale senza ts"} ] },
  "notifiche-jarvis": { sessione: "j", messaggi: [ {fid:"n-j1", testo:"J1", ts:200, notifica:true, classe:"report"},
    {fid:"n-j2", testo:"J2", ts:400, notifica:true, classe:"report"}, {fid:"q-x", chi:"io", testo:"vecchia domanda a Jarvis", ts:250},
    {fid:"n-e1", testo:"ERR", ts:150, notifica:true, classe:"avviso"}, {fid:"n-old", testo:"VECCHIO", ts:160, notifica:true} ] },
};
let chatCon = "postino";
const window = {};
""" + costante("FILO_POSTINO") + costante("FILI_NOTIFICHE") + costante("CLASSE_CHAT") + costante("classeDi") + costante("FILI_UNITI") + """
const filo = (k) => THREADS[k] || (THREADS[k] = { messaggi: [] });
let salvati = 0, disegni = 0;
const salvaFili = () => salvati++, disegnaMessaggi = () => disegni++;
""" + sorgente("messaggiChat") + sorgente("togliMessaggio") + """
const out = messaggiChat("postino").map((m) => m.testo);
console.log(JSON.stringify(out));
const j2 = THREADS["notifiche-jarvis"].messaggi[1];
togliMessaggio(j2);
console.log(JSON.stringify([THREADS["notifiche-jarvis"].messaggi.length, THREADS.postino.messaggi.length, salvati, disegni]));
chatCon = "jarvis"; THREADS.jarvis = { messaggi: [{ testo: "x", ts: 155 }, { testo: "y", ts: 500 }] };
console.log(JSON.stringify(messaggiChat("jarvis").map((m) => m.testo)));
THREADS.altro = { messaggi: [{ testo: "z" }] };
console.log(JSON.stringify(messaggiChat("altro") === THREADS.altro.messaggi));
"""
esito("app.js: messaggiChat e togliMessaggio presenti", bool(sorgente("messaggiChat")) and bool(sorgente("togliMessaggio")))
r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
righe = r.stdout.strip().splitlines()
esito("node esegue messaggiChat", r.returncode == 0 and len(righe) == 4, r.stderr[-300:] or r.stdout[-300:])
if len(righe) == 4:
    esito("Postino: solo i report, in ordine di tempo; avvisi e domande a Jarvis fuori",
          righe[0] == '["P1","J1","domanda","risposta","locale senza ts","J2"]', righe[0])
    esito("✕ toglie dal filo unito giusto", righe[1] == "[4,4,1,1]", righe[1])
    esito("chat Jarvis: gli avvisi (anche quelli senza classe) al loro posto, nessun report",
          righe[2] == '["ERR","x","VECCHIO","y"]', righe[2])
    esito("chat di un agente: stessa lista di prima (nessuna unione)", righe[3] == "true", righe[3])

# ---------------------------------------------------------------- c) pagina
st = CC / "static"
nj = (st / "notifiche.js").read_text(encoding="utf-8")
esito("pannello laterale «Notifiche» tolto", "notifiche-pannello" not in nj and "btn-notifiche" not in nj)
esito("schede Jarvis/Postino in testa alla chat", "chat-schede" in nj and 'insertBefore(SCHEDE, testa)' in nj)
esito("?filo=postino apre la chat Postino", 'get("filo")' in nj and "apriChat" in nj)
esito("invia: filo postino al server", 'if (k === FILO_POSTINO) corpo.filo = FILO_POSTINO' in app)
esito("testi con textContent (niente innerHTML nuovo)", "innerHTML" not in nj)
for f in ("app.js", "notifiche.js", "fili.js"):
    r = subprocess.run(["node", "--check", str(st / f)], capture_output=True, text=True)
    esito(f"node --check {f}", r.returncode == 0, r.stderr[-200:])

print(f"\n{RISULTATI['PASS']} PASS, {RISULTATI['FAIL']} FAIL")
sys.exit(1 if RISULTATI["FAIL"] else 0)
