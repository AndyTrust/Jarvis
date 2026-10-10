#!/usr/bin/env python3
"""Prove del badge di lavoro: apertura, rinnovo, scadenza, revoca, paletti duri che restano, giro."""
import os, sys, tempfile, time
from pathlib import Path
d = tempfile.mkdtemp(prefix="prova-badge-")
os.environ["CC_BADGE_DIR"] = d
os.environ["CC_CONFORMITA_CLAUDE"] = "/nonexistent"      # il modello non deve nemmeno servire
sys.path.insert(0, str(Path(__file__).resolve().parent))
import badge as B, conformita as K
ok = True
def t(nome, cond):
    global ok
    print(("ok   " if cond else "FALLITA ") + nome); ok &= bool(cond)

S = "0123abcd-0123-0123-0123-0123456789ab"
t("senza richiesta non si apre", B.apri(S, "") is None)
t("scaduto non vale", (B.apri(S, "fai X", adesso=time.time() - 3600), B.valido(S))[1] is None)
B.apri(S, "fai X")
t("aperto vale", B.valido(S) is not None)
t("l'uso rinnova", B.usa(S, adesso=time.time() + 25 * 60)["scade"] > time.time() + 50 * 60)
# decidi: con richiesta vera il privato passa col badge, senza modello
r = K.decidi("controlla le impostazioni", "Read", {"file_path": os.path.expanduser("~/.claude/settings.json")}, "alto", None, chiave_badge="s2")
t("privato + richiesta vera = badge aperto", r["esito"] == "autorizza" and r["metodo"] == "badge")
r = K.decidi("controlla", "Read", {"file_path": os.path.expanduser("~/.claude/settings.json")}, "alto", None, chiave_badge="s2")
t("secondo uso = badge valido", "valido" in r["motivo"])
# i paletti duri restano anche col badge
for nome, st, ing in [("segreto .env", "Read", {"file_path": os.path.expanduser("~/.locale-onedrive/Jarvis/.env")}),
                      ("rm -rf home", "Bash", {"command": "rm -rf ~"}),
                      ("push forzato", "Bash", {"command": "git push --force origin main"}),
                      ("scrive in .claude", "Write", {"file_path": os.path.expanduser("~/.claude/settings.json"), "content": "x"})]:
    r = K.decidi("fai X", st, ing, "alto", None, chiave_badge="s2")
    t(f"paletto duro resta: {nome}", r["esito"] == "nega" and r["metodo"] == "regola")
r = K.decidi("", "Bash", {"command": "ls /tmp"}, "alto", None, chiave_badge="s3")
t("senza richiesta e senza badge, rischio alto = no", r["esito"] == "nega")
B.apri("s4", "x"); B.apri("s5", "y")
rev, rin = B.giro({"s4"})
t("giro: s5 senza presa revocato, s4 resta", B.valido("s4") and not B.valido("s5") and rev >= 1)
t("revoca", B.revoca("s4") and not B.valido("s4"))
B.apri("s6", "z", adesso=time.time() - 4000)
rev, rin = B.giro({"s6"})
t("giro: scaduto con lavoro aperto = rinnovato", rin == 1 and B.valido("s6"))
print("TUTTO OK" if ok else "PROVE FALLITE"); sys.exit(0 if ok else 1)
