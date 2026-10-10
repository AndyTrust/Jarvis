#!/usr/bin/env python3
"""Prova isolata (cartelle temporanee, niente lavagna vera) di tombe e squadra del CEO.

    python3 command-center/prova_squadra.py
"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import server, spazi

tmp = Path(tempfile.mkdtemp(prefix="prova-squadra-"))
prog = tmp / "Progetto"
(prog / ".claude" / "agents").mkdir(parents=True); (prog / "README.md").write_text("# prova")
spazi_json = tmp / "spazi.json"
spazi_json.write_text(json.dumps({"spazi": [{"id": "prova", "nome": "Prova", "memoria": str(tmp / "m.md"),
    "report": str(tmp / "rep"), "progetti": [{"id": "prova", "nome": "Prova", "cartella": str(prog),
    "capogruppo": "prova-ceo", "sezioni_memoria": []}]}]}))
(tmp / "m.md").write_text("# m")
spazi.FILE = spazi_json
server.TOMBE_FILE = tmp / "agenti-tolti.json"
server.MODIFICHE_FILE = tmp / "mod.jsonl"
server.GRUPPI_ARCHIVIO = tmp / "arch.json"
server.evento = lambda *a, **k: None
server.allinea_progetto = lambda pid: [{'passo': 'finto', 'ok': True, 'dettaglio': ''}]   # niente missioni vere dalla prova
server.tocca = lambda *a, **k: None
esiti = []
def ok(nome, cond):
    esiti.append(cond); print(("✅" if cond else "❌"), nome)

ag = lambda **k: server.azione_agente({"progetto": "prova", **k})
ag(cosa="crea", nome="prova-ceo", capogruppo="", description="capo")
ag(cosa="crea", nome="dev-uno", capogruppo="prova-ceo", description="programma il codice", model="opus")
ag(cosa="crea", nome="revisore-uno", capogruppo="prova-ceo", description="revisore")
ok("creati 3 profili", len(spazi.profili(str(prog), "prova-ceo")) == 3)
ag(cosa="elimina", nome="revisore-uno")
ok("elimina: file sparito", not (prog / ".claude/agents/revisore-uno.md").exists())
ok("elimina: tomba scritta", "revisore-uno" in server.leggi_tombe().get("prova", []))
ag(cosa="togli", nome="dev-uno")
ok("togli: tomba scritta", "dev-uno" in server.leggi_tombe().get("prova", []))
ok("togli: non più fra i profili", {a["nome"] for a in spazi.profili(str(prog), "prova-ceo")} == {"prova-ceo"})
ok("togli: il capo non lo nomina più", "dev-uno" not in spazi.profili(str(prog), "prova-ceo")[0]["comunica"])
# il CEO propone di nuovo un agente tolto: la squadra lo salta
class R:  # claude finto
    returncode = 0
    stdout = json.dumps({"result": 'ecco\n```json\n[{"nome":"revisore-uno","description":"x","prove":["README.md"]},'
        '{"nome":"seo-uno","description":"ricerca","model":"opus","prove":["README.md"]},{"nome":"Nome Sbagliato","description":"y","prove":["README.md"]},'
        '{"nome":"inventato-senza-prove","description":"z","prove":["non/esiste.py"]}]\n```'})
    stderr = ""
server.subprocess.run = lambda *a, **k: R()
server.SQUADRA_STATO["prova"] = {"stato": "in corso", "messaggio": "", "creati": []}
server._squadra_in_sottofondo("prova")
nomi = {a["nome"] for a in spazi.profili(str(prog), "prova-ceo")}
ok("squadra: l'agente tolto non rientra", "revisore-uno" not in nomi)
ok("squadra: l'agente nuovo nasce", "seo-uno" in nomi)
ok("squadra: nome non valido e agente senza prove scartati", len(nomi) == 2 and "inventato-senza-prove" not in nomi)
modello = next(a["modello"] for a in spazi.profili(str(prog), "prova-ceo") if a["nome"] == "seo-uno")
ok("squadra: opus senza programmazione → sonnet", modello == "sonnet")
ok("squadra: stato fatta", server.SQUADRA_STATO["prova"]["stato"] == "fatta")
ag(cosa="crea", nome="revisore-uno", capogruppo="prova-ceo", description="lo rivoglio io")
ok("crea a mano: tomba cancellata", "revisore-uno" not in server.leggi_tombe().get("prova", []))
ag(cosa="crea", nome="nuovo-ceo", capogruppo="", description="capo nuovo", ceo=True)
testo = (prog / ".claude/agents/nuovo-ceo.md").read_text()
ok("CEO: sezione goal/squadra/modello/report nel profilo", all(x in testo for x in ("Da capogruppo del progetto", "Criterio di fatto", "agenti-tolti.json", "opus", "Stato.md", "crea_agente.py")))
ok("CEO: il profilo resta leggibile dal Command Center", any(a["nome"] == "nuovo-ceo" for a in spazi.profili(str(prog), "prova-ceo")))
sys.exit(0 if all(esiti) else 1)
