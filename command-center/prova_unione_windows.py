#!/usr/bin/env python3
"""Prova isolata dei pezzi del ramo windows entrati nel server (2026-10-02):
    python3 command-center/prova_unione_windows.py      esce con 1 se qualcosa non torna
Cartelle temporanee, OneDrive finto, niente lavagna vera, niente missioni, niente claude.
  1. «elimina_archiviato»: l'archiviato esce dall'elenco, il profilo va in _archivio/_eliminati/, la tomba resta
  2. crea_gruppo con «cartella» (percorso intero già sul PC): si collega, e non si collega due volte
  3. togli_gruppo rifiuta la cartella di Jarvis stesso
  4. processi() e _pid_vivo() sul Mac restano quelli di prima (pgrep, os.kill)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402
import spazi  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="prova-unione-windows-"))
prog = tmp / "Progetto"
(prog / ".claude" / "agents").mkdir(parents=True)
(prog / "README.md").write_text("# prova")
spazi_json = tmp / "spazi.json"
spazi_json.write_text(json.dumps({"spazi": [{"id": "prova", "nome": "Prova", "memoria": str(tmp / "m.md"),
    "report": str(tmp / "rep"), "progetti": [{"id": "prova", "nome": "Prova", "cartella": str(prog),
    "capogruppo": "ceo-prova", "sezioni_memoria": []}]}]}))
(tmp / "m.md").write_text("# m")
spazi.FILE = spazi_json
spazi.OD = tmp / "OD"                      # niente Jarvis Brain vero: la memoria dei gruppi nuovi va qui
server.TOMBE_FILE = tmp / "agenti-tolti.json"
server.MODIFICHE_FILE = tmp / "mod.jsonl"
server.GRUPPI_ARCHIVIO = tmp / "arch.json"
server.evento = lambda *a, **k: None
server.tocca = lambda *a, **k: None
server._pannello_agente_nasce = lambda *a, **k: None
server._pannello_agente_esce = lambda *a, **k: None
server._pannello_gruppo_nasce = lambda *a, **k: None
esiti = []


def ok(nome, cond, dettaglio=""):
    esiti.append(bool(cond))
    print(("✅ " if cond else "❌ ") + nome + ("" if cond else f"  [{dettaglio}]"))


ag = lambda **k: server.azione_agente({"progetto": "prova", **k})   # noqa: E731
ag(cosa="crea", nome="ceo-prova", capogruppo="", description="capo")
ag(cosa="crea", nome="dev-uno", capogruppo="ceo-prova", description="programma")
ag(cosa="togli", nome="dev-uno")
arch = prog / ".claude/agents/_archivio/dev-uno.md"
ok("1a togli: il profilo è in _archivio", arch.exists())
ag(cosa="elimina_archiviato", nome="dev-uno")
ok("1b elimina_archiviato: via da _archivio", not arch.exists())
ok("1c elimina_archiviato: copia in _archivio/_eliminati/",
   any(f.name.startswith("dev-uno.") for f in (prog / ".claude/agents/_archivio/_eliminati").glob("*.md")))
ok("1d elimina_archiviato: la tomba resta", "dev-uno" in server.leggi_tombe().get("prova", []))
try:
    ag(cosa="elimina_archiviato", nome="dev-uno")
    ok("1e un secondo elimina_archiviato dà errore", False)
except ValueError:
    ok("1e un secondo elimina_archiviato dà errore", True)

nuova = tmp / "Cartella del PC"
nuova.mkdir()
d = server.crea_gruppo({"spazio": "prova", "id": "pc", "nome": "Del PC", "cartella": str(nuova), "squadra_ceo": False})
voce = next(p for s in spazi.carica() for p in s["progetti"] if p["id"] == "pc")
ok("2a crea_gruppo con «cartella»: la voce punta alla cartella scelta", Path(voce["cartella"]).resolve() == nuova.resolve(), voce)
ok("2b il capogruppo nasce nella cartella scelta", (nuova / ".claude/agents/ceo-pc.md").exists())
ok("2c nessuna sottocartella col nome del gruppo", not (nuova / "Del PC").exists())
try:
    server.crea_gruppo({"spazio": "prova", "id": "pc2", "nome": "Doppio", "cartella": str(nuova), "squadra_ceo": False})
    ok("2d la stessa cartella non si collega due volte", False)
except ValueError as e:
    ok("2d la stessa cartella non si collega due volte", "già collegata" in str(e), e)
try:
    server.crea_gruppo({"spazio": "prova", "id": "pc3", "nome": "Relativa", "cartella": "relativa/x", "squadra_ceo": False})
    ok("2e un percorso relativo si rifiuta", False)
except ValueError:
    ok("2e un percorso relativo si rifiuta", True)

d = json.loads(spazi_json.read_text())
d["spazi"][0]["progetti"].append({"id": "jarvis-stesso", "nome": "Jarvis", "cartella": str(server.AGENTE), "sezioni_memoria": []})
spazi_json.write_text(json.dumps(d))
try:
    server.togli_gruppo("jarvis-stesso")
    ok("3  togli_gruppo rifiuta la cartella di Jarvis", False)
except ValueError as e:
    ok("3  togli_gruppo rifiuta la cartella di Jarvis", "Jarvis stesso" in str(e), e)

ok("4a processi() trova questo processo col suo schema (pgrep sul Mac)",
   sys.platform == "win32" or isinstance(server.processi("prova_unione_windows"), list))
ok("4b _pid_vivo: vivo il padre, morto un pid inesistente",
   server._pid_vivo(os.getppid()) and not server._pid_vivo(2 ** 22 + 12345))

print(f"\n{sum(esiti)}/{len(esiti)} prove passate · cartella: {tmp}")
sys.exit(0 if all(esiti) else 1)
