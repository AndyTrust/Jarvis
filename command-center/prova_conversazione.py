"""Prova della memoria continua del filo di chat (2026-10-01): python3 prova_conversazione.py

Usa un «claude» finto e una HOME temporanea: non tocca sessioni, memoria o Command Center veri.
Tre domande di fila nello stesso filo, senza «continua»: devono partire una alla volta,
la prima con --session-id, le altre con --resume, ognuna con lo stato del filo in testa.
Poi «Nuova conversazione» deve azzerare il filo. Esce con 0 se tutto torna."""
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

QUI = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="prova-conversazione-"))
(TMP / "home/.local/bin").mkdir(parents=True)
(TMP / "home/my-agent").mkdir()
FINTO = TMP / "home/.local/bin/claude"
FINTO.write_text('''#!/usr/bin/env python3
import sys, json, time, os
a = sys.argv[1:]
mode = sid = None
for i, x in enumerate(a):
    if x in ("--session-id", "--resume"):
        mode, sid = x, a[i + 1]
prompt = a[a.index("-p") + 1] if "-p" in a else a[-1]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"t": time.time(), "mode": mode, "sid": sid, "prompt": prompt}) + "\\n")
time.sleep(1)
d = os.path.expanduser("~/.claude/projects/x")
os.makedirs(d, exist_ok=True)
open(f"{d}/{sid}.jsonl", "a").write("{}\\n")
print(json.dumps({"result": "ok", "session_id": sid, "num_turns": 1, "total_cost_usd": 0}))
''')
FINTO.chmod(0o755)
os.environ.update(HOME=str(TMP / "home"), FAKE_LOG=str(TMP / "fake.log"), CC_PROVA="1")
sys.path.insert(0, str(QUI))
import conversazione  # noqa: E402
conversazione.FILE = TMP / "conversazioni.json"
import server  # noqa: E402
server.autenticazione_motore = lambda m, fresca=False: (True, "")

s = str(uuid.uuid4())
ids = [server.chiedi({"testo": t, "sessione": s, "motore": "claude"})["lavoro"]["id"]
       for t in ("uno: prepara il report", "due: e le scadenze?", "tre: manda all'utente")]
for _ in range(60):
    if all(server.lavoro_copia(i)["stato"] != "in corso" for i in ids):
        break
    time.sleep(0.5)
righe = [json.loads(r) for r in open(TMP / "fake.log")]
errori = []
if [r["mode"] for r in righe] != ["--session-id", "--resume", "--resume"]:
    errori.append("modi: " + str([r["mode"] for r in righe]))
if len({r["sid"] for r in righe}) != 1:
    errori.append("sessioni diverse: il contesto è stato azzerato")
if not all(righe[i + 1]["t"] >= righe[i]["t"] + 0.9 for i in range(len(righe) - 1)):
    errori.append("le domande non sono andate una alla volta")
if "scadenze" not in righe[0]["prompt"] or "uno: prepara" not in righe[1]["prompt"]:
    errori.append("manca lo stato del filo (in sospeso / già trattato)")
if [f["ok"] for f in conversazione.stato(s)["fatte"]] != [True] * 3:
    errori.append("stato finale: " + json.dumps(conversazione.stato(s)))
r = server.chiedi({"testo": "nuova conversazione", "sessione": s})
if not (r.get("reset") and conversazione.stato(s) == {} and r["sessione"] != s):
    errori.append("reset non riuscito: " + str(r))
print("TUTTO OK" if not errori else "ERRORI:\n" + "\n".join(errori))
sys.exit(1 if errori else 0)
