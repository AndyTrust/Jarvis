#!/usr/bin/env python3
"""Prova di missione.py senza missioni vere (27/09/2026): una cartella finta in /tmp, messaggi
dell'SDK costruiti a mano, un client finto che resta appeso in uscita.

    ~/my-agent/backtalk/.venv/bin/python prova_missione.py     esce con 1 se un caso è sbagliato
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

QUI = Path(__file__).resolve().parent
DIR = Path(tempfile.mkdtemp(prefix="prova-missione-"))
(DIR / "missione.json").write_text(json.dumps({
    "spazio_nome": "Prova", "progetti": [], "obiettivo": "prova", "modalita": "lavoro",
    "cwd": str(DIR), "report": str(DIR), "report_file": str(DIR / "report.md"), "memoria": ""}))
sys.argv = ["missione.py", str(DIR)]
sys.path.insert(0, str(QUI))
import missione as M  # noqa: E402
from claude_agent_sdk import (TaskNotificationMessage, TaskStartedMessage, TaskUpdatedMessage,  # noqa: E402
                              ToolResultBlock, UserMessage)

sbagli = 0


def controlla(nome, vero):
    global sbagli
    if not vero:
        sbagli += 1
    print(("ok       " if vero else "SBAGLIATO ") + nome)


def stato():
    return json.loads((DIR / "stato.json").read_text())["stato"]


def lancia(tid, tipo="esperto"):
    M.agente(tid, {"subagent_type": tipo, "description": "x"})
    asyncio.run(M.gancio_agent({"tool_use_id": tid, "tool_input": {"subagent_type": tipo}}, tid, None))


# 3. breve(): stesso default della consegna
controlla("breve senza subagent_type dice general-purpose",
          M.breve("Agent", {"description": "d"}) == "general-purpose: d")

# 6. il risultato di un lancio in sottofondo si scarta, una consegna vera che dice «launched» no
lancia("t1")
M.tratta(UserMessage(content=[ToolResultBlock(tool_use_id="t1", content=[{"type": "text", "text":
         "Async agent launched successfully. (This tool result is internal metadata)"}])]))
controlla("lancio in sottofondo: resta «lavora»", M.AGENTI["t1"]["stato"] == "lavora")
lancia("t2")
M.tratta(UserMessage(content=[ToolResultBlock(tool_use_id="t2", content="I launched the checks: all green.")]))
controlla("consegna sincrona «I launched…»: consegnato", M.AGENTI["t2"]["stato"] == "consegnato")

# 2a. notifica con tool_use_id=None: si ritrova dal task_id
lancia("t3")
M.tratta(TaskStartedMessage(subtype="task_started", data={}, task_id="k3", description="", uuid="u",
                            session_id="s", tool_use_id="t3"))
M.tratta(TaskNotificationMessage(subtype="task_notification", data={}, task_id="k3", status="completed",
                                 output_file="", summary="fatto tutto", uuid="u", session_id="s", tool_use_id=None))
controlla("notifica senza tool_use_id: consegnato", M.AGENTI["t3"]["stato"] == "consegnato"
          and "fatto tutto" in M.AGENTI["t3"]["esito"])

# 2b. completed solo in TaskUpdatedMessage: dopo l'attesa si consegna col testo del patch
lancia("t4")
M.tratta(TaskStartedMessage(subtype="task_started", data={}, task_id="k4", description="", uuid="u",
                            session_id="s", tool_use_id="t4"))
M.tratta(TaskUpdatedMessage(subtype="task_updated", data={}, task_id="k4",
                            patch={"status": "completed", "result": "esito dal patch"}, status="completed"))
M.consegne_tardive()
controlla("completed senza notifica: prima dell'attesa resta «lavora»", M.AGENTI["t4"]["stato"] == "lavora")
M.ATTESA_NOTIFICA_S = 0
M.consegne_tardive()
controlla("completed senza notifica: dopo l'attesa consegnato", M.AGENTI["t4"]["stato"] == "consegnato"
          and "esito dal patch" in M.AGENTI["t4"]["esito"])
# se poi arriva la notifica vera, non si consegna due volte
M.tratta(TaskNotificationMessage(subtype="task_notification", data={}, task_id="k4", status="completed",
                                 output_file="", summary="doppio", uuid="u", session_id="s", tool_use_id="t4"))
controlla("notifica dopo la consegna tardiva: nessun doppione", "doppio" not in M.AGENTI["t4"]["esito"])
# se la notifica arriva in tempo, la consegna tardiva non parte
M.ATTESA_NOTIFICA_S = 30
lancia("t5")
M.tratta(TaskStartedMessage(subtype="task_started", data={}, task_id="k5", description="", uuid="u",
                            session_id="s", tool_use_id="t5"))
M.tratta(TaskUpdatedMessage(subtype="task_updated", data={}, task_id="k5", patch={"status": "completed"},
                            status="completed"))
M.tratta(TaskNotificationMessage(subtype="task_notification", data={}, task_id="k5", status="completed",
                                 output_file="", summary="esito vero", uuid="u", session_id="s", tool_use_id="t5"))
controlla("completed poi notifica: esito della notifica", "esito vero" in M.AGENTI["t5"]["esito"]
          and "t5" not in M.FINITI_SENZA_NOTIFICA)


# 5. due conferme insieme: «in corso» solo quando sono finite tutte e due
async def due_conferme():
    M.ATTESA_CONFERMA_S = 5
    a = asyncio.create_task(M.conferma("Bash", {"command": "git push"}, None))
    b = asyncio.create_task(M.conferma("Bash", {"command": "git push --tags"}, None))
    await asyncio.sleep(0.3)
    ids = sorted(f.stem for f in M.RICHIESTE.glob("*.json") if not f.name.endswith(".risposta.json"))
    (M.RICHIESTE / f"{ids[0]}.risposta.json").write_text(json.dumps({"ok": True}))
    await asyncio.sleep(1.5)
    intanto = stato()
    (M.RICHIESTE / f"{ids[1]}.risposta.json").write_text(json.dumps({"ok": False}))
    await asyncio.gather(a, b)
    return intanto, stato()


intanto, dopo = asyncio.run(due_conferme())
controlla(f"una conferma su due: ancora «attende conferma» (è «{intanto}»)", intanto == "attende conferma")
controlla(f"tutte e due risposte: «in corso» (è «{dopo}»)", dopo == "in corso")


# 8. il client che non si chiude: dopo il tetto si va avanti
class ClientAppeso:
    async def disconnect(self):
        await asyncio.Event().wait()


M.CHIUSURA_CLIENT_S = 1
inizio = time.monotonic()
asyncio.run(M.chiudi_client(ClientAppeso()))
controlla("client appeso: chiudi_client torna entro il tetto", time.monotonic() - inizio < 3)

# 4. chiusura dopo un'eccezione: agenti «lavora» chiusi, stato «errore»
lancia("t6")
M.chiudi_missione(RuntimeError("caduta finta"))
s = json.loads((DIR / "stato.json").read_text())
controlla("eccezione: stato «errore» con il messaggio", s["stato"] == "errore" and "caduta finta" in s["errore"])
controlla("eccezione: l'agente rimasto «lavora» va in errore", M.AGENTI["t6"]["stato"] == "errore")

import shutil  # noqa: E402
shutil.rmtree(DIR, ignore_errors=True)
print(f"sbagliati: {sbagli}")
sys.exit(1 if sbagli else 0)
