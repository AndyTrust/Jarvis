#!/usr/bin/env python3
"""Prova di conferme.py: casi scritti a mano, poi le azioni vere delle missioni passate.

    python3 prova_conferme.py        esce con 1 se un caso a mano è sbagliato
"""
import glob
import re
import sys
from collections import Counter
from pathlib import Path

from conferme import motivo, motivo_lettura, radici

QUI = Path(__file__).resolve().parent
R = radici(Path.home() / "my-agent")
PSQL = "ssh vps-tuo \"docker exec -i crm1-odoo-db sh -c 'psql -U \\$POSTGRES_USER -d db1 -At'\" <<'SQL' 2>&1\n"
B = "Bash"

CASI = [
    (B, "rm -rf vault/x", "cancella"),
    (B, "git push origin main", "git"),
    (B, "git status && git diff --stat", None),
    (B, 'ssh vps-tuo "docker restart crm1-odoo"', "scrive sulla VPS"),
    (B, PSQL + "SELECT count(*) FROM res_users;\nSQL", None),
    (B, PSQL + "UPDATE res_users SET active=false;\nSQL", "scrive sulla VPS"),
    (B, 'ssh vps-tuo "docker exec -i crm1-odoo odoo shell -d db1" <<\'PY\'', "scrive sulla VPS"),
    (B, "ssh vps-tuo 'docker ps; df -h; docker logs --tail 50 crm1-odoo 2>&1'", None),
    (B, 'cd ~/my-agent && python3 strumenti/task.py add "x" 2>&1 | tail', None),
    (B, 'python3 strumenti/report_pdf.py "vault/Jarvis Brain/04 Report/X/X - Report.md" && open x.pdf', None),
    (B, "cd /tmp && pdftoppm -r 60 -png -f 1 -l 2 x.pdf /tmp/rp/p", None),
    (B, "echo ciao > /etc/hosts", "fuori dal progetto"),
    (B, "echo ciao > note.txt", None),
    (B, 'ls $(pwd); f=$(find . -name x 2>/dev/null); cat "$f" | head', None),
    (B, 'grep -rn -e "Chiudere Vercel" vault', None),
    (B, "grep -oE '<form[^>]{0,200}>' /tmp/x.html | sort -u", None),
    (B, 'echo x > "/etc/hosts"', "fuori dal progetto"),
    (B, "echo x | tee -a '" + str(Path.home()) + "/Desktop/y.txt'", "fuori dal progetto"),
    (B, "vercel deploy --prod", "pubblica"),
    (B, "security dump-keychain | grep gmail", "segreti"),
    (B, "grep -i smtp ~/.env.Azienda Uno", "segreti"),
    (B, "./telefono/chiama.sh 070123", "messaggi"),
    (B, "osascript -e 'tell app \"Finder\" to delete x'", "messaggi"),
    (B, "curl -s -X POST https://api.x.com -d a=1", "web in scrittura"),
    (B, "curl -s https://crm.esempio.it/cruscotto | head", None),
    (B, "bash cruscotto/deploy/copia_e_installa.sh", "pubblica"),
    (B, "sed -i '' s/a/b/ f.md", "modifica sul posto"),
    (B, "sed -n 1,40p f.md", None),
    (B, "pip install requests", "installa"),
    (B, "mv a b", "sposta"),
    (B, "kill 123", "sistema"),
    ("Edit", "~/my-agent/vault/Jarvis Brain/04 Report/Azienda Uno/x.md", None),
    ("Edit", "~/Library/CloudStorage/OneDrive/Jarvis Brain/Memoria/Vita personale/Jarvis/Fatti/x.md", None),
    ("Write", "~/my-agent/.env", "file delicato"),
    ("Edit", "~/my-agent/CLAUDE.md", "file delicato"),
    ("Edit", "~/my-agent/.claude/settings.json", "file delicato"),
    ("Write", "~/Desktop/x.txt", "fuori dal progetto"),
    ("WebSearch", "", None),
    ("Agent", "", None),
    ("SendMessage", "", None),
    ("mcp__claude_ai_Gmail__send_message", "", "servizio esterno"),
    ("mcp__claude_ai_Gmail__search_threads", "", None),
    ("mcp__claude_ai_Pienissimo_Ma__get-revenue-summary", "", None),
    ("AskUserQuestion", "", "strumento non previsto"),
    # 27/09/2026: corpi degli heredoc di dati e testo fra virgolette non sono comandi
    (B, "cat > /tmp/android-collaudo.md << 'EOF'\n# Collaudo\nadb shell input tap 1 2\nscrcpy\nEOF", None),
    (B, "cat > /tmp/nota.md <<EOF\ngit push origin main\nrm -rf x\nssh vps-tuo docker restart db1\n"
        "> citazione\nvercel deploy --prod\nEOF", None),
    (B, "cat > /tmp/x.md << 'EOF'\nadb shell\nEOF\nadb shell ls", "messaggi"),      # adb vero dopo la chiusura
    (B, "python3 << 'EOF'\nimport subprocess\nsubprocess.run(['git', 'push'])\nEOF", "git"),
    (B, "python3 <<EOF\nimport os\nos.system(\"git push\")\nEOF", "git"),
    (B, "bash <<EOF\ngit push\nEOF", "git"),
    (B, "cat <<EOF | bash\ngit push\nEOF", "git"),
    (B, "cat > /tmp/x.sh <<'EOF'\ngit push\nEOF\nbash /tmp/x.sh", "git"),
    (B, "cat > /tmp/x.sh <<'EOF'\ngit push\nEOF\nchmod +x /tmp/x.sh && /tmp/x.sh", "git"),
    (B, "\"$(cat <<'EOF'\ngit push\nEOF\n)\"", "git"),
    (B, "git commit -m \"$(cat <<'EOF'\nfix: tolto rm e git push dal registro\nEOF\n)\"", None),
    (B, 'grep -i "adb"', None),
    (B, 'grep -rn "adb\\|scrcpy" docs/', None),
    (B, 'git log --grep "rm -rf"', None),
    (B, "adb shell input tap 100 200", "messaggi"),
    (B, 'bash -c "git push"', "git"),
    (B, "sh -c 'rm -rf x'", "cancella"),
    (B, "python3 -c \"import os; os.system('rm -rf x')\"", "cancella"),
    (B, 'echo "$(git push)"', "git"),
    (B, 'eval "git push"', "git"),
    (B, 'cat "$HOME/.env"', "segreti"),
    (B, "cat > " + str(Path.home()) + "/Library/CloudStorage/OneDrive/l'utente\\ Brain/x.md << 'EOF'\nciao\nEOF",
     None),
    (B, "cat > /etc/x.md << 'EOF'\nciao\nEOF", "fuori dal progetto"),
]


def ingresso(tool, testo):
    return {"command": testo} if tool == B else {"file_path": testo} if testo else {}


sbagli = 0
for tool, testo, atteso in CASI:
    trovato = motivo(tool, ingresso(tool, testo), R)
    if trovato != atteso:
        sbagli += 1
        print(f"SBAGLIATO {tool}: {testo[:80]!r} -> {trovato}, atteso {atteso}")
print(f"casi a mano: {len(CASI)}, sbagliati: {sbagli}")

# modalità lettura delle missioni per spazi (23/09/2026): si scrive solo nel report
REP = Path("/tmp/prova-report")
RL = [REP.resolve()]
LETTURA = [
    (B, "ls -la && git log --oneline -5", None),
    (B, "grep -rn 'mkdir' .", None),
    (B, "mkdir nuova", "sola lettura"),
    (B, "git commit -am x", "sola lettura"),
    (B, "echo x > note.md", "fuori dal progetto"),
    (B, f"echo x > {REP}/r.md", None),
    (B, f'python3 ~/Jarvis/strumenti/report_pdf.py "{REP}/r.md"', None),
    (B, 'python3 ~/Jarvis/strumenti/lavori.py prendo "X" "y" --agente z --insisto', None),
    (B, "rm -rf x", "cancella"),
    ("Write", f"{REP}/2026-09-23 prova.md", None),
    ("Write", str(Path.home() / "Jarvis/x.md"), "sola lettura"),
    ("Edit", str(Path.home() / "Jarvis/CLAUDE.md"), "sola lettura"),
    ("Agent", "", None),
    ("Read", "/etc/hosts", None),
]
for tool, testo, atteso in LETTURA:
    trovato = motivo_lettura(tool, ingresso(tool, testo), RL)
    if trovato != atteso:
        sbagli += 1
        print(f"SBAGLIATO lettura {tool}: {testo[:80]!r} -> {trovato}, atteso {atteso}")
print(f"casi lettura: {len(LETTURA)}, sbagliati totali: {sbagli}")

# missione catena (27/09/2026): i profili .claude/agents/*.md dentro le radici si correggono senza chiedere
AB = str(Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain")   # la stessa radice di radici()
PROF = f"{AB}/Progetti/Vita personale/.claude/agents"
CATENA = [
    ("Write", f"{PROF}/revisore-utente.md", None),
    ("Edit", f"{PROF}/revisore-utente.md", None),
    (B, f"cat > {PROF.replace(' ', chr(92) + ' ')}/revisore-utente.md << 'EOF'\n---\nnome: x\n---\nusa adb e git push\nEOF",
     None),
    (B, f'cd "{AB}/Progetti/Vita personale" && sed -i \'\' \'s/aggiornato-il: 2026-09-26/aggiornato-il: 2026-09-27/\' '
        f'./.claude/agents/revisore-utente.md', None),
    (B, f'sed -i "" "s/a/b/g" "{PROF}/x.md" "{PROF}/y.md"', None),
    # fuori dai profili, o sed che scrive altri file o esegue: chiede come prima
    (B, f'cd "{AB}/Memoria/Vita personale" && sed -i \'\' \'s/a/b/\' ./l’utente\\ Personale.md', "modifica sul posto"),
    (B, f"sed -i '' 's/a/b/w /etc/x' '{PROF}/x.md'", "modifica sul posto"),
    (B, f"sed -i '' 's/a/b/' '{PROF}/x.md' && git push", "git"),
    (B, "sed -i '' 's/a/b/' /etc/.claude/agents/x.md", "modifica sul posto"),
]
for tool, testo, atteso in CATENA:
    trovato = motivo(tool, ingresso(tool, testo), R, catena=True)
    if trovato != atteso:
        sbagli += 1
        print(f"SBAGLIATO catena {tool}: {testo[:90]!r} -> {trovato}, atteso {atteso}")
# fuori dalla catena il sed -i sui profili chiede ancora
if motivo(B, ingresso(B, f"sed -i '' 's/a/b/' '{PROF}/x.md'"), R) != "modifica sul posto":
    sbagli += 1
    print("SBAGLIATO: sed -i sui profili passa anche fuori dalla catena")
print(f"casi catena: {len(CATENA) + 1}, sbagliati totali: {sbagli}")

conta, chiede = Counter(), []
for f in sorted(glob.glob(str(QUI / "missioni/*/registro.log"))):
    for riga in open(f):
        m = re.match(r"\[[\d:]+\] → (\w+): (.*)", riga.rstrip("\n"))
        if m:
            tool, testo = m.groups()
            r = motivo(tool, ingresso(tool, testo) if tool in (B, "Edit", "Write") else {}, R)
            conta[r or "passa"] += 1
            if r:
                chiede.append(f"  [{r}] {tool}: {testo[:110]}")
print("missioni passate (radice my-agent):", dict(conta))
print("\n".join(chiede))
sys.exit(1 if sbagli else 0)
