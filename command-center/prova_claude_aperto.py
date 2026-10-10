#!/usr/bin/env python3
"""Prove: scritture in ~/.claude e letture dei segreti con l'interruttore (parole «claude» e «libero»), nucleo sempre chiuso."""
import os, sys, tempfile
from pathlib import Path
T = Path(tempfile.mkdtemp(prefix="prova-claude-"))
os.environ["CC_FLAG_LIBERO"] = str(T / "flag")
os.environ["CC_BADGE_DIR"] = str(T / "badge")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import regole_permessi as R, conformita as K
K.FLAG_SEGRETI = T / "flag"
H = os.path.expanduser("~"); C = H + "/.claude"
ok = True
def t(nome, cond):
    global ok
    print(("ok   " if cond else "FALLITA ") + nome); ok &= bool(cond)
def nega(st, ing):
    return bool(K.paletti(st, ing, H)[0])
casi_aperti = [("Write", {"file_path": C + "/hooks/nuovo.py", "content": "x"}), ("Write", {"file_path": C + "/projects/-x/vecchia.jsonl", "content": "x"}),
               ("Edit", {"file_path": C + "/cache/a.txt", "old_string": "a", "new_string": "b"}), ("Write", {"file_path": C + "/CLAUDE.md", "content": "x"}),
               ("Bash", {"command": f"cp /tmp/a {C}/cache/b"}), ("Bash", {"command": f"rm -f {C}/projects/-x/vecchia.jsonl"}),
               ("Bash", {"command": f"python3 -c 'print(1)' > {C}/debug/log.txt"}), ("Read", {"file_path": C + "/projects/-x/vecchia.jsonl"}),
               ("Grep", {"pattern": "x", "path": C + "/projects"})]
casi_nucleo = [("Write", {"file_path": C + "/settings.json", "content": "{}"}), ("Edit", {"file_path": C + "/hooks/guardia_comandi.py", "old_string": "a", "new_string": "b"}),
               ("Write", {"file_path": C + "/.credentials.json", "content": "x"}), ("Bash", {"command": f"sed -i 's/a/b/' {C}/settings.json"}),
               ("Bash", {"command": f"cp /tmp/x {C}/hooks/guardia_avvio.py"}), ("Bash", {"command": f"echo x > {C}/hooks/connessioni_guardia.py"}),
               ("Read", {"file_path": H + "/.locale-onedrive/jarvis-cc/registro/regole.jsonl"})]
for st, ing in casi_aperti + casi_nucleo:
    assert nega(st, ing), "senza interruttore dovrebbe essere negato: %s %s" % (st, str(ing)[:60])
print("ok   senza interruttore: tutto negato (%d casi)" % (len(casi_aperti) + len(casi_nucleo)))
(T / "flag").write_text("libero, claude")
for st, ing in casi_aperti:
    t("aperto: %s %s" % (st, (ing.get("file_path") or ing.get("command") or ing.get("path"))[-50:]), not nega(st, ing))
for st, ing in casi_nucleo:
    t("CHIUSO: %s %s" % (st, (ing.get("file_path") or ing.get("command"))[-50:]), nega(st, ing))
(T / "flag").write_text("libero")
t("solo «libero»: Write in ~/.claude resta negato", nega("Write", {"file_path": C + "/hooks/nuovo.py", "content": "x"}))
print("TUTTO OK" if ok else "PROVE FALLITE"); sys.exit(0 if ok else 1)
