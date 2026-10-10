"""Quando una missione deve chiedere conferma all'utente.

Regola dell'utente del 19/09/2026: nel pannello missioni si chiede solo quando serve.
Passano da sole le letture, le ricerche, i lanci di agenti e le modifiche ai file
dentro il progetto e i vault. Chiede sempre quello che non si disfa: cancellare,
spostare, pubblicare, deploy, scrivere sulla VPS o nei database, mandare
messaggi, installare, toccare segreti e regole, scrivere fuori dal progetto.

motivo(tool, input, radici) -> None se passa, se no una parola che dice perché.
"""
import re
import shlex
import sys
from pathlib import Path

STRUMENTI_LIBERI = {"Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "WebSearch",
                    "WebFetch", "Agent", "Task", "ToolSearch", "Skill", "TaskOutput", "SendMessage"}
STRUMENTI_FILE = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# strumenti MCP: passano solo quelli che leggono
MCP_LETTURA = re.compile(r"^(get|list|search|read|query|count|aggregate|fetch|resolve|help|"
                         r"status|filter|guide|suggest)[-_]", re.I)

# file che non si toccano senza l'utente, anche dentro il progetto
FILE_DELICATI = re.compile(r"(^|/)(\.env[^/]*|\.ssh/.*|settings(\.local)?\.json|CLAUDE\.md|"
                           r"\.git/.*|.*\.(pem|key|p12))$")

# un nome in posizione di comando: all'inizio o dopo ; & | ( e a capo
COMANDO = r"(?:^|[;&|(]\s*|\n\s*)(?:\S*/)?"

# comandi Bash: (motivo, espressione). Si controlla tutto il testo del comando.
PERICOLOSI = [
    ("cancella", r"\b(rm|rmdir|shred|truncate|unlink|srm)\b|\bdd\s+\S*of=|find\b[^|;&]*-delete"),
    ("sposta", r"(^|[;&|(]\s*)mv\s"),
    ("git", r"\bgit\s+(push|reset|clean|checkout|restore|rebase|stash\s+(drop|clear)|branch\s+-[dD]|filter-)"),
    ("sistema", r"\b(sudo|launchctl|crontab|kill|pkill|killall|shutdown|reboot|chown|diskutil)\b"),
    ("installa", r"\b(brew|pip3?|npm|pnpm|yarn|gem|apt(-get)?)\s+(install|uninstall|remove|upgrade|publish)\b"),
    ("pubblica", COMANDO + r"(vercel|netlify|firebase|rsync|scp)\b|deploy[/_.]|"
                 r"copia_e_installa|installa_\w+\.sh"),
    ("messaggi", COMANDO + r"(sendmail|mail|osascript|adb|scrcpy)\b|chiama\.sh|telefono/|"
                 r"\bgh\s+(pr|issue|release|repo|api|gist)\s+(create|comment|merge|close|edit|delete|review)|"
                 r"\bgh\s+api\b.*-X\s*(POST|PUT|PATCH|DELETE)"),
    # le mani sul Mac: clic, tasti e app passano; AppleScript libero, Comandi rapidi e
    # chiusura di un'app (lavoro non salvato) chiedono
    ("mac", r"mac\.py\s+(applescript|scorciatoia|esci)\b"),
    ("segreti", r"\bsecurity\s+(dump|find|add|delete)|\.env\b"),
    ("web in scrittura", r"\b(curl|wget|http)\b.*(\s-X\s*(POST|PUT|PATCH|DELETE)|\s(-d|--data\S*|-F|--form|-T|--upload-file)\s)"),
    ("modifica sul posto", r"\b(sed|perl)\s+(-\w*\s+)*-i"),
]
# sulla VPS e in Docker si legge liberamente, si chiede se il comando scrive
REMOTO = re.compile(r"\b(ssh|docker)\b")
SQL_SCRITTURA = re.compile(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|"
                           r"COPY|VACUUM)\b", re.I)
SCRITTURA_REMOTA = re.compile(
    r"odoo\s+shell|\s-u\s+\w|\b(restart|stop|start|kill|rm|rmi|up|down|pull|build|run|prune|"
    r"systemctl|apt|mv|cp|chmod|tee|caddy|reload)\b|(?<![0-9&<])>(?!\s*/dev/null|&[12])")
# redirezioni verso un file: si guarda dove scrivono
# 27/09/2026: il nome può avere spazi scritti «L'utente\ Brain»: prima si fermava alla «\»
# e «cat > …/l'utente\ Brain/…/agenti.md» risultava «fuori dal progetto»
REDIREZIONE = re.compile(r"(?<![0-9&<])(?:[12]?>>?|\|\s*tee(?:\s+-a)?)\s*(?!&[12])(['\"]?)"
                         r"((?:\\.|[^\s;&|()'\"\\])+)\1")

# 27/09/2026: il corpo di un heredoc che alimenta cat/tee è un DATO (il testo di un file),
# non un comando: «adb» o «git push» scritti in una nota non chiedono più conferma.
# Se l'heredoc alimenta un interprete (python3 << EOF, bash << EOF, ssh … << EOF) il corpo
# è codice e si guarda tutto, come prima.
HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2")
SCRIVE_DATI = {"cat", "tee"}
INTERPRETE = r"(?:(?:ba|z|da|k|fi)?sh|python[\d.]*|node|deno|bun|ruby|perl|php|osascript|lua|source)"
# comandi che eseguono un testo che hanno come argomento o da una pipe: con questi il testo
# fra virgolette e i corpi degli heredoc restano da guardare
ESEGUE_TESTO = re.compile(
    r"\b(?:ba|z|da|k|fi)?sh\s+(?:-\w+\s+)*-\w*c|"                          # bash -c "…"
    r"\b(?:python[\d.]*|node|deno|bun|ruby|perl|php|osascript|lua)\s+(?:-\S+\s+)*-\w*[ce]\b|"
    r"\|\s*(?:\S*/)?" + INTERPRETE + r"\b|"                                 # … | bash
    r"(?:^|[;&|(\s])(?:eval|ssh|xargs|watch|parallel|su|source|exec)\s|"
    r"(?:^|[;&|(]\s*)\.\s")


def _senza_virgolette(comando, forte=False):
    """Toglie il testo fra virgolette (un '>' dentro una regex di grep non scrive
    niente), ma lascia quello dopo > o tee, che è il nome del file.
    forte (27/09/2026): lascia anche le virgolette doppie con dentro $( o `, che eseguono."""
    def via(m):
        prima = comando[:m.start()].rstrip()
        if prima.endswith((">", "tee", "-a")):
            return m.group(0)
        if forte and m.group(0).startswith('"') and ("$(" in m.group(0) or "`" in m.group(0)):
            return m.group(0)
        return "''"
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", via, comando)


def _heredoc(comando):
    """Le righe del comando divise in (riga, heredoc aperti su quella riga, corpi).
    Ogni heredoc è (match, righe del corpo, riga di chiusura o None)."""
    righe, fuori, i = comando.split("\n"), [], 0
    while i < len(righe):
        riga = righe[i]
        i += 1
        aperti = []
        for m in HEREDOC.finditer(riga):
            corpo, chiusura = [], None
            while i < len(righe):
                r = righe[i]
                i += 1
                if (r.lstrip("\t") if m.group(1) else r) == m.group(3):
                    chiusura = r
                    break
                corpo.append(r)
            aperti.append((m, corpo, chiusura))
        fuori.append((riga, aperti))
    return fuori


def _heredoc_di_dati(riga, m, resto):
    """Vero se l'heredoc che comincia in m alimenta cat/tee e il file scritto non viene eseguito."""
    pezzi = re.split(r"(\$\(|`|[;&|(])", riga[:m.start()])
    parole = pezzi[-1].split()
    if not parole or parole[0].rsplit("/", 1)[-1] not in SCRIVE_DATI:
        return False
    if len(pezzi) > 1 and pezzi[-2] in ("$(", "`"):
        # cat dentro $( ): è un dato solo se fa da argomento di un altro comando (git commit -m "$(cat …)")
        davanti = "".join(pezzi[:-2]).rstrip().rstrip('"').rstrip()
        if not davanti or davanti.endswith((";", "&", "|", "(", "$(", "`")):
            return False
    # l'uscita di cat va in una pipe (cat << EOF | python3): non è un dato
    if re.search(r"(?<!\|)\|(?![|]|\s*tee\b)", riga[m.end():]):
        return False
    # il file scritto poi si esegue (cat > x.sh << EOF … bash x.sh, chmod +x x.sh, ./x.sh)
    scritti = [d for _, d in REDIREZIONE.findall(riga)] + re.findall(r"\btee\s+(?:-a\s+)?(\S+)", riga)
    for dest in scritti:
        nome = re.escape(dest.replace("\\", "").strip("'\"").rsplit("/", 1)[-1])
        if re.search(r"(?:\b" + INTERPRETE + r"|\bchmod|\.)\s+(?:-\S+\s+)*(?:\S*/)?" + nome + r"\b|"
                     r"(?:^|[;&|(]\s*)\S*/" + nome + r"\b", resto, re.M):
            return False
    return True


def _senza_corpi_di_dati(comando):
    """(testo senza i corpi degli heredoc di dati, vero se tutti gli heredoc erano di dati).
    Tutto intero se il comando esegue del testo (bash -c, python3 -c, eval, ssh, | bash)."""
    righe = _heredoc(comando)
    if ESEGUE_TESTO.search(_senza_virgolette("\n".join(r for r, _ in righe), forte=True)):
        return comando, False
    fuori, tutto_dati = [], True
    for n, (riga, aperti) in enumerate(righe):
        fuori.append(riga)
        resto = "\n".join(r for r, _ in righe[n:])
        for m, corpo, chiusura in aperti:
            if not _heredoc_di_dati(riga, m, resto):
                tutto_dati = False
                fuori += corpo
            if chiusura is not None:
                fuori.append(chiusura)
    return "\n".join(fuori), tutto_dati


def _da_guardare(comando):
    """Il testo su cui si cercano i comandi pericolosi (27/09/2026): senza i corpi degli heredoc
    di dati e senza il testo fra virgolette, salvo che ci sia del codice (vedi sopra)."""
    testo, tutto_dati = _senza_corpi_di_dati(comando)
    if tutto_dati:
        return _senza_virgolette(testo, forte=True)
    # codice (python3 << EOF, bash -c): le virgolette restano, e si guarda anche una copia senza
    # punteggiatura, così subprocess.run(["git", "push"]) si legge «git push»
    return testo + "\n" + re.sub(r"[\"',\[\]()]+", " ", testo)


def _profili_con_sed(comando, radici_ok):
    """Missione catena (27/09/2026): vero se il comando è fatto solo di `cd` e di `sed -i` con
    sostituzioni semplici (s/…/…/) sui profili .claude/agents/*.md dentro le radici."""
    try:
        lex = shlex.shlex(comando, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        parole = list(lex)
    except ValueError:
        return False
    segmenti, pezzo = [], []
    for p in parole:
        if p in ("&&", ";"):
            segmenti.append(pezzo)
            pezzo = []
        elif p and set(p) <= set("&|;<>()"):
            return False                           # pipe, redirezioni, sottoshell: si guarda tutto
        else:
            pezzo.append(p)
    segmenti.append(pezzo)
    base, file_visti = Path.cwd(), 0
    for seg in filter(None, segmenti):
        if seg[0] == "cd" and len(seg) == 2:
            base = base / Path(seg[1]).expanduser()
            continue
        if seg[0] != "sed":
            return False
        script, file_, sul_posto, k = [], [], False, 1
        while k < len(seg):
            p = seg[k]
            if p == "-i":
                sul_posto = True
                if k + 1 < len(seg) and (seg[k + 1] == "" or seg[k + 1].startswith(".")):
                    k += 1                         # il suffisso della copia (sed -i '' su macOS)
            elif p.startswith("-i") and not p.startswith("--"):
                sul_posto = True
            elif p in ("-e", "--expression") and k + 1 < len(seg):
                script.append(seg[k + 1])
                k += 1
            elif p in ("-E", "-r", "--regexp-extended"):
                pass
            elif p.startswith("-"):
                return False                       # -f file, -n, … : non è una sostituzione semplice
            elif not script:
                script.append(p)
            else:
                file_.append(p)
            k += 1
        if not sul_posto or not script or not file_:
            return False
        if not all(SOSTITUZIONE.fullmatch(s.strip()) for s in script):
            return False
        for f in file_:
            percorso = base / Path(f).expanduser()
            if not (percorso.suffix == ".md" and percorso.parent.name == "agents"
                    and percorso.parent.parent.name == ".claude" and _dentro(percorso, radici_ok)):
                return False
            file_visti += 1
    return file_visti > 0


# s<d>cerca<d>sostituisci<d>[flag], anche più d'una separate da «;». Niente w (scrive altri file) né e (esegue)
SOSTITUZIONE = re.compile(r"s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1[gIi0-9p]*(?:\s*;\s*s(.)(?:\\.|(?!\2).)*\2"
                          r"(?:\\.|(?!\2).)*\2[gIi0-9p]*)*")


def _dentro(percorso, radici):
    try:
        p = Path(percorso).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return any(p == r or r in p.parents for r in radici)


def radici(cwd, altre=()):
    """Le cartelle dove si scrive senza chiedere: il progetto, my-agent e i vault."""
    base = Path.home() / "my-agent"
    candidati = [Path(cwd), base, *map(Path, altre), Path("/tmp"), Path("/private/var/folders")]
    vault = base / "vault"
    if vault.is_dir():
        candidati += list(vault.iterdir())
    # La memoria condivisa (~/.jarvis/percorsi.json, chiave «memoria»): senza questa riga ogni nota di memoria
    # scritta da una missione in modo «lavoro» chiedeva conferma come «fuori dal progetto».
    try:
        import json as _json
        _m = _json.loads((Path.home() / ".jarvis" / "percorsi.json").read_text(encoding="utf-8")).get("memoria")
        candidati.append(Path(_m).expanduser() if _m else Path.home() / "Jarvis-Memoria")
    except (OSError, ValueError):
        candidati.append(Path.home() / "Jarvis-Memoria")
    fuori = []
    for c in candidati:
        try:
            fuori.append(c.expanduser().resolve())
        except (OSError, RuntimeError):
            pass
    return fuori


def motivo(tool, inp, radici_ok, catena=False):
    """catena (27/09/2026): missione «aggiorna catena», i profili .claude/agents/*.md dentro le
    radici si correggono anche con `sed -i` senza chiedere (Write/Edit e cat > passano già)."""
    inp = inp or {}
    if tool in STRUMENTI_LIBERI:
        return None
    if tool.startswith("mcp__"):
        return None if MCP_LETTURA.match(tool.split("__")[-1]) else "servizio esterno"
    if tool in STRUMENTI_FILE:
        percorso = inp.get("file_path") or inp.get("notebook_path") or ""
        if FILE_DELICATI.search(str(Path(percorso).expanduser())):
            return "file delicato"
        return None if _dentro(percorso, radici_ok) else "fuori dal progetto"
    if tool != "Bash":
        return "strumento non previsto"
    comando = inp.get("command", "")
    if catena and _profili_con_sed(comando, radici_ok):
        return None
    testo = _da_guardare(comando)
    senza_dati = _senza_corpi_di_dati(comando)[0]
    for nome, espressione in PERICOLOSI:
        # i segreti si cercano anche fra virgolette (cat "$HOME/.env"), non nei corpi di dati
        dove = senza_dati if nome == "segreti" else testo
        if re.search(espressione, dove, re.I | re.M):
            return nome
    # 27/09/2026: senza i corpi degli heredoc di dati (una nota che parla di ssh non scrive sulla VPS,
    # un «> citazione» in una nota non è una redirezione). ssh vero fa restare tutto (ESEGUE_TESTO).
    if REMOTO.search(senza_dati) and (SQL_SCRITTURA.search(senza_dati) or SCRITTURA_REMOTA.search(senza_dati)):
        return "scrive sulla VPS"
    for _, destinazione in REDIREZIONE.findall(_senza_virgolette(senza_dati)):
        destinazione = re.sub(r"\\(.)", r"\1", destinazione)        # «Memoria\ condivisa» -> «Memoria condivisa»
        if destinazione != "/dev/null" and not _dentro(destinazione, radici_ok):
            return "fuori dal progetto"
    return None


# ---------------------------------------------------------------- modalità lettura
# Missione «lettura» (23/09/2026): gli esperti leggono e riferiscono. Si scrive solo
# il report della missione e la cartella della missione stessa (le radici passate a
# motivo_lettura). Tutto quello che motivo() giudica irreversibile si nega senza
# chiedere, e in più si negano i comandi che scrivono in locale.
SCRITTURA_LOCALE = re.compile(
    COMANDO + r"(mkdir|touch|cp|ln|chmod|install|patch|tee)\b|"
    r"\bgit\s+(add|commit|mv|rm|tag|merge|pull|fetch|clone|apply|am|cherry-pick|revert|init|config|stash)\b|"
    r"\b(npm|pnpm|yarn)\s+(run|exec|ci)\b|\bnpx\b")
# script che scrivono per mestiere ma che la missione deve poter usare anche in lettura:
# il badge (lavori.py prendo/finito), la memoria (cerca_memoria.py), il PDF del report
AMMESSI_LETTURA = re.compile(r"strumenti/(lavori|cerca_memoria|report_pdf)\.py\b")


def motivo_lettura(tool, inp, radici_report):
    """None se in modalità lettura lo strumento può partire, se no il motivo."""
    inp = inp or {}
    if tool in STRUMENTI_FILE:
        percorso = inp.get("file_path") or inp.get("notebook_path") or ""
        if _dentro(percorso, radici_report) and not FILE_DELICATI.search(str(Path(percorso).expanduser())):
            return None
        return "sola lettura"
    if tool != "Bash":
        return motivo(tool, inp, radici_report)
    comando = inp.get("command", "")
    perche = motivo(tool, inp, radici_report)
    if perche:
        return perche
    if SCRITTURA_LOCALE.search(_senza_virgolette(_senza_corpi_di_dati(comando)[0])) and not AMMESSI_LETTURA.search(comando):
        return "sola lettura"
    return None
