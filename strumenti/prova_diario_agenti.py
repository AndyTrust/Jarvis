#!/usr/bin/env python3
"""Prove di diario_agenti.py su un CRM finto in una cartella temporanea (niente OneDrive vero, niente quaderni veri).
  python3 strumenti/prova_diario_agenti.py        esce con 1 se qualcosa non torna (Mac e PC)"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
sys.path.insert(0, str(Path.home() / "Jarvis" / "strumenti"))
import diario_agenti as d   # noqa: E402
import quaderno             # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="prova-diario-"))
crm = tmp / "CRM finto"
(crm / ".claude" / "agents").mkdir(parents=True)
(crm / ".claude" / "agents" / "analista-prova.md").write_text("---\nname: analista-prova\n---\n", encoding="utf-8")
os.environ["JARVIS_MACCHINA"] = "PCPROVA"
esiti = []


def v(nome, ok):
    esiti.append(ok)
    print(("✅ " if ok else "🔴 ") + nome)


def trascrizione(nome, compito, resoconto):
    p = tmp / f"{nome}.jsonl"
    righe = [{"type": "user", "message": {"role": "user", "content": compito}},
             {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": resoconto}]}}]
    p.write_text("\n".join(json.dumps(r) for r in righe), encoding="utf-8")
    return str(p)


comp = "Controlla le chiusure di ieri in sola lettura. Registro: lavori.py prendo ... --agente analista-prova"
reso = "Chiusure al 2026-10-04 complete, 2 per giorno.\nDA SALVARE: g140_chiusura ha sede_id, non sede\nERRORE DA SALVARE: non usare ssh dalla VPS"
ev = {"hook_event_name": "SubagentStop", "agent_type": "general-purpose",
      "agent_transcript_path": trascrizione("a", comp, reso)}

# 1. agente del CRM: quaderno e registro
r = d.scrivi(ev, crm, quaderno)
q = crm / ".claude" / "memoria" / "agenti" / "analista-prova.md"
log = crm / "_CONDIVISO-AGENTI" / "registro" / "PCPROVA.log"
v("nome ricavato da --agente", r.get("chi") == "analista-prova")
v("2 righe nel quaderno + 1 di diario", r.get("quaderno") == 3 and "sede_id" in q.read_text(encoding="utf-8"))
v("errore nella sezione giusta", "## Errori commessi da non ripetere\n- " in q.read_text(encoding="utf-8"))
riga = log.read_text(encoding="utf-8").strip().splitlines()[-1]
v("riga di registro nel formato condiviso", riga.split(" | ")[1:3] == ["PCPROVA", "analista-prova"] and " | FINE Controlla" in riga)
v("esito = prima riga del resoconto senza marche", "Chiusure al 2026-10-04" in riga and "DA SALVARE" not in riga)

# 2. stesso lavoro di nuovo: niente doppioni
r2 = d.scrivi(ev, crm, quaderno)
v("quaderno senza doppioni", r2.get("quaderno") == 0)
v("registro senza doppione entro 15 minuti", r2.get("registro") is False and len(log.read_text().splitlines()) == 1)

# 3. agente che non è del CRM: niente
r3 = d.scrivi({"hook_event_name": "SubagentStop", "agent_type": "Explore",
               "agent_transcript_path": trascrizione("b", "cerca file --agente programmatore-windows", "fatto")}, crm, quaderno)
v("agente fuori dal CRM ignorato", r3.get("fatto") == "niente")

# 4. sezione diario (in quaderno.py dal 2026-10-05): una riga con data e ora assolute
v("quaderno.py ha la sezione «diario»", any(k == "diario" for k, _ in quaderno.SEZIONI))
ev4 = {"hook_event_name": "SubagentStop", "agent_type": "analista-prova",
       "last_assistant_message": "Margini di settembre ricalcolati."}
d.scrivi(ev4, crm, quaderno)
testo_q = q.read_text(encoding="utf-8")
import re as _re                                                      # noqa: E402
v("riga di diario con ora assoluta (ISO con fuso) e macchina",
  _re.search(r"## Diario\n(- .+\n)*- \d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})? · \d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2} PCPROVA · ", testo_q) is not None)

# 5. gancio vero: stdin JSON, JARVIS_CRM, uscita 0 anche con evento rotto
amb = dict(os.environ, JARVIS_CRM=str(crm), JARVIS_REPO=str(QUI.parent))   # la cartella con strumenti/quaderno.py
p = subprocess.run([sys.executable, str(QUI / "diario_agenti.py")], input="non è json", text=True, env=amb)
v("evento rotto: esce con 0", p.returncode == 0)
p = subprocess.run([sys.executable, str(QUI / "diario_agenti.py")], text=True, env=amb,
                   input=json.dumps({"hook_event_name": "Stop", "stop_hook_active": True}))
v("stop_hook_active: non fa niente ed esce con 0", p.returncode == 0)

# 5b. --da-utente (impostazioni utente del Mac): dentro il CRM tace, fuori scrive
(tmp / "collegamento").symlink_to(crm) if hasattr(os, "symlink") and sys.platform != "win32" else None
ev5 = {"hook_event_name": "SubagentStop", "agent_type": "analista-prova",
       "cwd": str((tmp / "collegamento" / "sotto") if (tmp / "collegamento").exists() else crm / "sotto"),   # come ~/OneDrive sul Mac
       "last_assistant_message": "Prova da utente dentro il CRM."}
righe_prima = len(log.read_text(encoding="utf-8").splitlines())
p = subprocess.run([sys.executable, str(QUI / "diario_agenti.py"), "--da-utente"], text=True, env=amb, input=json.dumps(ev5))
v("--da-utente dentro il CRM: niente doppione", p.returncode == 0 and "Prova da utente" not in q.read_text(encoding="utf-8"))
ev5["cwd"] = str(tmp)
p = subprocess.run([sys.executable, str(QUI / "diario_agenti.py"), "--da-utente"], text=True, env=amb, input=json.dumps(ev5))
v("--da-utente fuori dal CRM: scrive il diario", "Prova da utente" in q.read_text(encoding="utf-8"))

# 6. lucchetto senza fcntl
v("diario_agenti non importa fcntl né msvcrt", "import fcntl" not in (QUI / "diario_agenti.py").read_text()
  and "import msvcrt" not in (QUI / "diario_agenti.py").read_text())

print(f"\n{sum(esiti)}/{len(esiti)} prove passate")
sys.exit(0 if all(esiti) else 1)
