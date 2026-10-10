#!/usr/bin/env python3
"""Blocca i comandi distruttivi PRIMA che partano (hook PreToolUse su Bash).

Regola dell'utente del 19/09: l'irreversibile passa da lui. Finora stava solo nel
prompt, cioè dipendeva dal modello che se la ricorda. Questo hook gira anche in
bypassPermissions: gli hook non si saltano con i permessi.

Quando blocca, il modello riceve il motivo e deve chiedere all'utente. Se l'utente dice
sì, il comando si rilancia con davanti `JARVIS_CONFERMATO=1 ` (una volta sola,
scritto nel comando: così resta nel registro chi l'ha autorizzato).
Prova: python3 ~/.claude/hooks/guardia_comandi.py --prova

Revisione 2 (2026-10-03, cc-registro-opus; vedi vps/cc-ponte/REVISIONE-2-PERMESSI.md):
- è una RETE CONTRO GLI ERRORI, non una barriera contro chi vuole aggirarla: un modello che costruisce il
  comando apposta (variabili, codice generato, script scritti su file e poi lanciati) può passare;
- JARVIS_CONFERMATO=1 vale solo come assegnazione iniziale del comando (anche dopo `env`) e copre solo il
  PRIMO comando della riga: mai in un commento, in mezzo o dopo ; && |;
- l'analisi è per comandi: rm in ogni forma (--recursive, -r -f separati, ~, $HOME, ${HOME}, ~/*, graffe, ..,
  cd ~ && rm -rf X), find -delete/-exec rm, shred, dd of=, truncate, : > file, mv della home, chmod/chown -R,
  rsync --delete, git push forzato/--mirror/+ref/:ref/--delete, git clean -f in ogni forma, git branch -D o
  --delete --force, reflog expire, update-ref -d, SQL (DROP, TRUNCATE, DELETE/UPDATE senza WHERE, anche con
  commenti /**/ e maiuscole), docker rm -f/volume/prune, kill -9 -1, launchctl remove/bootout di Jarvis,
  crontab -r/-, curl/gh -X DELETE; dentro bash/sh/zsh -c, ssh host '…', eval, here-doc verso una shell, e il
  codice di python/perl/node/ruby (-c/-e o here-doc) che chiama rmtree/remove/unlink/system/subprocess;
- se non riesce a leggere l'ingresso o va in errore, BLOCCA (fallisce in sicurezza);
- oltre 20000 caratteri non analizza: blocca e chiede di spezzare il comando. Tutta l'analisi è lineare.
"""
import json
import os
import re
import shlex
import sys
import time

CASA = r"(~|\$HOME|/Users/tu)"
HOME = os.path.realpath(os.path.expanduser("~"))
MAX_COMANDO = 20000
MAX_PROFONDITA = 4

# le regole di prima che restano come seconda rete (tutte lineari); quelle di rm, git push, dd e docker down
# (che avevano «.*» o gruppi ripetuti: tempo quadratico, revisione 2 F6) sono nell'analisi per comandi
REGOLE = [
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean -f"),
    (r"\bgit\s+(filter-repo|filter-branch)\b", "riscrittura della storia git"),
    (r"\bgh\s+repo\s+(delete|archive)\b", "cancellazione o archiviazione di un repository GitHub"),
    (r"\b(mkfs|newfs_\w+|diskutil\s+(erase\w*|reformat|partitionDisk))\b", "formattazione di un disco"),
    (r"(^|[;&|]\s*|sudo\s+|ssh\s+\S+\s+['\"]?)(shutdown|reboot|halt)\b", "spegnimento o riavvio della macchina"),
    (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", "DROP in un database"),
    (r"\bTRUNCATE\s+(TABLE\s+)?\w", "TRUNCATE in un database"),
    (r"\bDELETE\s+FROM\s+\w+\s*(;|\"|'|$)", "DELETE senza WHERE"),
    (r"\bdocker\s+(system|volume|image|container)\s+prune\b", "docker prune"),
    (r"\bdocker\s+volume\s+rm\b", "cancellazione di un volume docker"),
    (r"\bchmod\s+-R\s+777\b", "chmod -R 777"),
    (r"\bcrontab\s+-r\b", "cancellazione del crontab"),
]
_FORK = re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:")
PAROLE_CHIAVE = {"do", "then", "else", "elif", "{", "!", "if", "while", "until"}
_REGOLE = [(re.compile(s, re.I), p) for s, p in REGOLE]

# cartelle che non si cancellano, non si spostano e non si svuotano senza l'utente (per nome, a qualunque profondità)
PRINCIPALI = {"utente brain", "crm Azienda Uno", "azienda_due", ".locale-onedrive", ".ssh", ".segreti-archivio", ".git",
              "segreti-dal-vault", "chiavi-app-android", "cc-ponte",
              "jarvis", "my-agent", ".claude", "jarvis-cc", "memoria", "progetti", "onedrive", "cloudstorage",
              "crm140-git", "Azienda Due", "utente personale", "Azienda Uno"}
TEMPORANEE = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders", "/dev/null")
SHELL = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
INTERPRETI = {"python", "python3", "python2", "perl", "node", "ruby", "deno", "bun", "php"}
# radici dei progetti (fisiche): non si cancellano con -r né loro né le cartelle subito sotto (revisione 3, F5)
OD = os.path.join(HOME, "Library", "CloudStorage", "OneDrive")
RADICI_PROGETTI = [(os.path.realpath(os.path.join(HOME, "Jarvis")), 1), (os.path.join(OD, "Jarvis Brain", "Progetti"), 2),
                   (os.path.join(OD, "Jarvis Brain", "Memoria"), 2), (os.path.join(OD, "CRM Azienda Uno"), 1),
                   (os.path.join(HOME, ".locale-onedrive"), 1)]
RIGENERABILI = {"node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".pytest_cache", ".cache", "tmp", "target",
                ".next", ".mypy_cache", ".ruff_cache", "coverage", "out", "log", "logs"}
NOMI_SEGRETI = re.compile(r"^(\.env.*|.*\.env|.*\.(pem|key|p12|pfx|jks|keystore|kdbx)|id_(rsa|ed25519|ecdsa|dsa).*|.*credential.*|"
                          r".*secret.*|auth\.json|oauth_creds.*|keystore\.properties|google-lettura\.json|conf\.json|"
                          r"\.netrc|\.git-credentials|.*_history|.*\.keychain(-db)?)$", re.I)
INVOLUCRI = {"sudo", "command", "builtin", "exec", "nohup", "time", "nice", "ionice", "timeout", "doas", "caffeinate", "stdbuf"}
CONFERMA = re.compile(r"^\s*(?:[A-Za-z_]\w*=\S*\s+)*(?:env\s+(?:-\S+\s+)*(?:[A-Za-z_]\w*=\S*\s+)*)?JARVIS_CONFERMATO=1\s+\S")


class Blocco(Exception):
    pass


# ---------------------------------------------------------------- lettura del comando (lineare)

def _heredoc(testo):
    """(testo senza i corpi degli here-doc, [(riga che lo riceve, corpo)]). Lineare: si scorre riga per riga."""
    righe = testo.split("\n")
    out, docs, i = [], [], 0
    while i < len(righe):
        r = righe[i]
        out.append(r)
        aperti = re.findall(r"<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2", r) if "<<" in r else []
        i += 1
        for meno, _, fine in aperti:
            corpo = []
            while i < len(righe):
                riga = righe[i]
                if (riga.strip() if meno or True else riga) == fine:
                    i += 1
                    break
                corpo.append(riga)
                i += 1
            docs.append((r, "\n".join(corpo)))
    return "\n".join(out), docs


def _segmenti(testo):
    """I comandi semplici, separati da ; & | && || a capo e dai confini di $( ) ` ( ), fuori dalle virgolette
    semplici. Ogni pezzo fra $( ) o ` ` è anche un comando a sé."""
    pezzi, cur, q, i, n = [], [], None, 0, len(testo)
    while i < n:
        c = testo[i]
        if q:
            cur.append(c)
            if c == q:
                q = None
            elif c == "\\" and q == '"' and i + 1 < n:
                cur.append(testo[i + 1])
                i += 1
            elif q == '"' and (c == "`" or (c == "$" and i + 1 < n and testo[i + 1] == "(")):
                pezzi.append("".join(cur[:-1]))     # una sostituzione dentro le virgolette doppie: anche lei è un comando
                cur = []
                if c == "$":
                    i += 1
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c == "\\" and i + 1 < n:
            cur.append(testo[i:i + 2])
            i += 1
        elif c == "&" and ((cur and cur[-1] in "<>") or (i + 1 < n and testo[i + 1] == ">")):
            cur.append(c)                             # 2>&1, &>, >&2: una redirezione, non un separatore
        elif c in ";&|\n`()" or (c == "$" and i + 1 < n and testo[i + 1] == "("):
            pezzi.append("".join(cur))
            cur = []
            if c == "$":
                i += 1
        elif c == "#" and (not cur or cur[-1] in " \t"):
            while i < n and testo[i] != "\n":       # commento fino a fine riga
                i += 1
            continue
        else:
            cur.append(c)
        i += 1
    pezzi.append("".join(cur))
    return [p.strip() for p in pezzi if p.strip()]


_REDIREZIONE = re.compile(r"^\d*(>>?|<<?|&>>?|>&|<&)")


def _parole(seg):
    """Le parole di un comando semplice, senza le redirezioni (2>&1, > file, 2>/dev/null…)."""
    try:
        grezze = shlex.split(seg, comments=False, posix=True)
    except ValueError:
        grezze = seg.replace("'", " ").replace('"', " ").split()
    out, salta = [], False
    for t in grezze:
        if salta:
            salta = False
            continue
        m = _REDIREZIONE.match(t)
        if m and not t.startswith("<<"):
            if m.end() == len(t):
                salta = True                          # l'operatore da solo: la parola dopo è il file
            continue
        out.append(t)
    return out


def _normalizza(testo):
    testo = testo.replace("\\\n", " ").replace("\r", "\n")
    # r''m e r""m sono rm; \rm è rm
    testo = re.sub(r"(?<=\w)(''|\"\")(?=\w)", "", testo)
    return testo


# ---------------------------------------------------------------- percorsi

def _espandi(t, cwd):
    """Una parola → lista di percorsi assoluti (graffe espanse, ~ e $HOME), o [] se non è un percorso."""
    t = t.replace("${HOME}", HOME).replace("$HOME", HOME)
    out = []
    for v in _graffe(t):
        if v == "~" or v.startswith("~/"):
            v = HOME + v[1:]
        elif v.startswith("~"):
            v = "/Users/" + v[1:]                     # ~utente
        if not v.startswith("/"):
            v = os.path.join(cwd, v) if cwd else v
        out.append(os.path.normpath(v) if v.startswith("/") else v)
    return out


_GRAFFE = re.compile(r"\{([^{}]*,[^{}]*)\}")


def _graffe(t, n=0):
    m = _GRAFFE.search(t)
    if not m or n > 3:
        return [t]
    out = []
    for alt in m.group(1).split(",")[:16]:
        out += _graffe(t[:m.start()] + alt + t[m.end():], n + 1)
    return out[:64]


def _temporanea(p):
    return any(p == t or p.startswith(t + "/") for t in TEMPORANEE)


def _protetto(p, parola, cwd, rm=False):
    """Perché cancellare/svuotare/spostare `p` (assoluto o relativo) va chiesto all'utente, o None.
    Una parola con una variabile che non sia $HOME non si può giudicare: si lascia passare (come prima)."""
    resto = parola.replace("${HOME}", "").replace("$HOME", "")
    if rm and re.fullmatch(r"\$\{?\w+\}?/?|\$\(.*\)|`.*`", resto.strip("'\"")):
        return "su una variabile che non si può controllare (scrivi il percorso)"
    if "$" in resto or "`" in parola:
        return None
    if parola in ("*", ".", "..", "./", "./*", "../", "../*", ".*"):
        return "su tutto o sulla cartella corrente"
    if not p.startswith("/"):
        # cartella corrente sconosciuta: si guarda solo il nome
        return "su una cartella principale (vault, CRM, Azienda Due, Jarvis, chiavi)" if p.rstrip("/").lower() in PRINCIPALI else None
    jolly = any(c in p for c in "*?[")
    base = p
    while any(c in base for c in "*?["):
        base = os.path.dirname(base)
    base = os.path.normpath(base)
    try:
        vero = os.path.realpath(base)                 # ~/Jarvis è un collegamento: si guarda anche dove porta
    except (OSError, ValueError):
        vero = base
    if vero != base:
        perche = _protetto_uno(vero, jolly)
        if perche:
            return perche
    return _protetto_uno(base, jolly)


def _protetto_uno(base, jolly):
    parti = [x for x in base.split("/") if x]
    parti = [x for x in base.split("/") if x]
    if base in (HOME, os.path.dirname(HOME)):
        return "sulla home"
    if _temporanea(base) and (base not in ("/tmp", "/private/tmp") or jolly):
        return None                                   # /tmp/qualcosa, e anche /tmp/*.png
    if base == "/" or len(parti) <= 1:
        return "sulla radice o su una cartella principale del sistema"
    if base.startswith(HOME + "/"):
        sotto = [x for x in base[len(HOME) + 1:].split("/") if x]
        if len(sotto) == 1 and not jolly and not os.path.isfile(base):
            return "su una cartella principale della home"
        if jolly and len(sotto) <= 1:
            return "su tutto il contenuto di una cartella principale"
        if sotto[0] == ".locale-onedrive" and len(sotto) <= 2:
            return "su una cartella principale (.locale-onedrive)"
        if sotto[:2] == ["Library", "CloudStorage"] and len(sotto) <= 4:
            return "su OneDrive o una sua cartella principale"
    if _temporanea(base):
        return None
    for radice, livelli in RADICI_PROGETTI:
        if base == radice:
            return "su una cartella di progetto"
        if base.startswith(radice + "/"):
            sotto = [x for x in base[len(radice) + 1:].split("/") if x]
            if (len(sotto) <= livelli and sotto[-1].lower() not in RIGENERABILI) or (jolly and len(sotto) <= livelli):
                return "su una cartella di progetto"
    nomi = [x.lower() for x in parti]
    if nomi and nomi[-1] in PRINCIPALI and not jolly:
        return "su una cartella principale (vault, CRM, Azienda Due, Jarvis, chiavi)"
    if jolly and nomi and nomi[-1] in PRINCIPALI:
        return "su tutto il contenuto di una cartella principale"
    return None


def _bersagli(args):
    """Gli argomenti che non sono opzioni (dopo -- tutti)."""
    out, fine = [], False
    for a in args:
        if not fine and a == "--":
            fine = True
        elif fine or not a.startswith("-") or a == "-":
            out.append(a)
    return out


def _corti(args):
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--") and len(a) > 1)


# ---------------------------------------------------------------- un comando semplice

def _cmd_rm(args, cwd, unlink=False):
    for t in _bersagli(args):
        if NOMI_SEGRETI.match(os.path.basename(t.strip("'\"").rstrip("/"))):
            raise Blocco("cancellazione di un file di segreti")
    if unlink:
        return
    lunghi = [a for a in args if a.startswith("--")]
    ricorsivo = "r" in _corti(args).lower() or any(a.startswith("--recursive") or a == "--dir" for a in lunghi)
    forzato = "f" in _corti(args) or "--force" in lunghi
    for t in _bersagli(args):
        for p in _espandi(t, cwd):
            perche = _protetto(p, t, cwd, rm=True)
            if not perche:
                continue
            tutto = perche.startswith(("su tutto", "sulla radice", "sulla home", "su una variabile"))
            if ricorsivo or (forzato and tutto):
                raise Blocco(f"rm ricorsivo {perche}")


def _cmd_find(args, cwd):
    distrugge = "-delete" in args
    for i, a in enumerate(args):
        if a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(args) and os.path.basename(args[i + 1]) in ("rm", "unlink", "shred", "rmdir"):
            distrugge = True
    if not distrugge:
        return
    inizi = []
    for a in args:
        if a.startswith(("-", "(", "!")):
            break
        inizi.append(a)
    filtro = any(a in ("-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-newer", "-mtime", "-mmin", "-size")
                 for a in args)
    for t in inizi or ["."]:
        if filtro and t in (".", "./") and cwd:
            continue                     # find . -name '*.pyc' -delete nella cartella di lavoro (revisione 3, F6)
        for p in _espandi(t, cwd):
            perche = _protetto(p, t, cwd)
            if perche:
                raise Blocco(f"find che cancella {perche}")


def _cmd_git(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):             # opzioni globali: -C x, -c x, --git-dir=…
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(args):
        return
    sub, resto = args[i], args[i + 1:]
    corti = _corti(resto)
    lunghi = {a.split("=", 1)[0] for a in resto if a.startswith("--")}
    if sub == "push":
        if ("f" in corti or "d" in corti or lunghi & {"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune"}
                or any(a.startswith(("+", ":")) or ":+" in a for a in _bersagli(resto))):
            raise Blocco("git push forzato, --mirror o che cancella rami")
    elif sub == "clean":
        if "f" in corti or "--force" in lunghi:
            raise Blocco("git clean -f")
    elif sub == "reset" and "--hard" in lunghi:
        raise Blocco("git reset --hard")
    elif sub in ("filter-branch", "filter-repo"):
        raise Blocco("riscrittura della storia git")
    elif sub == "branch":
        if "D" in corti or (("d" in corti or "--delete" in lunghi) and ("f" in corti or "--force" in lunghi)):
            raise Blocco("cancellazione forzata di un ramo")
    elif sub == "reflog" and resto[:1] and resto[0] in ("expire", "delete"):
        raise Blocco("git reflog expire/delete")
    elif sub == "update-ref" and ("d" in corti or "--delete" in lunghi):
        raise Blocco("git update-ref -d")


def _metodo_delete(args):
    for i, a in enumerate(args):
        if a in ("-X", "--request", "--method") and i + 1 < len(args) and args[i + 1].upper() == "DELETE":
            return True
        if re.fullmatch(r"(-X|--request=|--method=)DELETE", a, re.I):
            return True
    return False


def _locale(args):
    return any(re.search(r"//(localhost|127\.0\.0\.1|\[::1\])([:/]|$)", a) for a in args)


def _sostituisci(t, variabili):
    if "$" not in t or not variabili:
        return t
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: variabili.get(m.group(1) or m.group(2), m.group(0)), t)


def _decodifica(t):
    """«$(echo rm -rf ~)» e «$(printf 'rm -rf ~')» eseguiti da eval o bash -c: il testo stampato è il comando."""
    return re.sub(r"\$\(\s*(?:echo|printf)\s+", " ", t).replace(")", " ").replace("'", " ").replace('"', " ")


SERVIZI_JARVIS = re.compile(r"server\.py|jarvis|backtalk|sentinella|cc_ponte|missione\.py|telegram|grok|barehands|my-agent", re.I)


def _cmd_semplice(parole, cwd, prof, variabili=None):
    """Controlla UN comando semplice (già diviso in parole). Blocco con il motivo, o niente."""
    variabili = variabili or {}
    parole = parole[:1] + [_sostituisci(p, variabili) for p in parole[1:]]
    while parole and (parole[0] in PAROLE_CHIAVE or re.fullmatch(r"[A-Za-z_]\w*=.*", parole[0], re.S)):
        parole = parole[1:]
    while parole:
        w = os.path.basename(parole[0].lstrip("\\"))
        if w in INVOLUCRI:
            parole = parole[1:]
            while parole and parole[0].startswith("-"):
                parole = parole[1:] if parole[0] not in ("-n", "-u", "-g", "-s", "-k") else parole[2:]
            if w == "timeout" and parole and re.fullmatch(r"[\d.]+[smhd]?", parole[0]):
                parole = parole[1:]
        elif w == "env":
            parole = parole[1:]
            while parole and (parole[0].startswith("-") or re.fullmatch(r"[A-Za-z_]\w*=.*", parole[0])):
                parole = parole[2:] if parole[0] in ("-u", "-C", "-S") else parole[1:]
        elif w == "xargs":
            parole = parole[1:]
            while parole and parole[0].startswith("-"):
                parole = parole[2:] if parole[0] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s") else parole[1:]
        else:
            break
    if not parole:
        return
    w = os.path.basename(parole[0].lstrip("\\"))
    args = parole[1:]
    if w.startswith("$"):
        # x=rm; $x -rf ~ : un comando che è una variabile si tratta come rm se ne ha le opzioni;
        # cmd="rm -rf ~"; $cmd : il valore della variabile è il comando
        nome = re.sub(r"[${}]", "", parole[0])
        if nome in variabili:
            _analizza(variabili[nome] + " " + " ".join(args), cwd, prof + 1)
        _cmd_rm(args, cwd)
        return
    if w == "unlink":
        _cmd_rm(args, cwd, unlink=True)
    if w == "security" and args[:1] and args[0].startswith("delete-"):
        raise Blocco(f"security {args[0]}: cancella dal portachiavi")
    if w == "dscl" and any(a in ("-delete", "-create", "-change", "-passwd", "-append", "-merge") for a in args):
        raise Blocco("dscl: modifica gli utenti del Mac")
    if w == "hdiutil" and args[:1] and (args[0] in ("erase", "makehybrid") or (args[0] in ("detach", "eject") and "-force" in args)):
        raise Blocco(f"hdiutil {args[0]} forzato")
    if w in ("pkill", "killall") and any(a in ("-9", "-KILL", "-SIGKILL") or a == "KILL" for a in args) \
            and any(SERVIZI_JARVIS.search(a) for a in args if not a.startswith("-")):
        raise Blocco(f"{w} -9 di un servizio di Jarvis")
    if w == "osascript":
        for a in args:
            m = re.search(r"do\s+shell\s+script\s+(\"(?:\\.|[^\"])*\"|'[^']*')", a, re.I)
            if m:
                _analizza(m.group(1)[1:-1].replace('\\"', '"'), cwd, prof + 1)
    if w in ("rm", "grm"):
        _cmd_rm(args, cwd)
    elif w == "find":
        _cmd_find(args, cwd)
    elif w in ("shred", "srm"):
        raise Blocco("shred: cancellazione definitiva")
    elif w.startswith(("mkfs", "newfs")):
        raise Blocco("formattazione di un disco")
    elif w == "dd":
        for a in args:
            if a.startswith("of="):
                dest = _espandi(a[3:], cwd)[0] if _espandi(a[3:], cwd) else a[3:]
                if dest.startswith("/dev/") and dest != "/dev/null":
                    raise Blocco("dd su un disco")
                if not _temporanea(dest):
                    raise Blocco("dd che sovrascrive un file")
    elif w == "truncate":
        bersagli, salta = [], False
        for a in args:
            if salta:
                salta = False
            elif a in ("-s", "--size", "-r", "--reference"):
                salta = True
            elif not a.startswith("-"):
                bersagli.append(a)
        if any(not _temporanea(p) for t in bersagli for p in _espandi(t, cwd)):
            raise Blocco("truncate: svuota un file")
    elif w == "mv":
        for t in _bersagli(args)[:-1]:
            for p in _espandi(t, cwd):
                perche = _protetto(p, t, cwd)
                if perche:
                    raise Blocco(f"mv {perche}")
    elif w in ("chmod", "chown", "chgrp"):
        ricorsivo = "R" in _corti(args) or "--recursive" in args
        if w == "chmod" and ricorsivo and any(re.fullmatch(r"0?7[0-7]7|a\+\w*w\w*|[ug]*o[ug]*\+\w*w\w*|\+\w*w\w*", a) and a != "+x" for a in args):
            raise Blocco("chmod -R 777 o scrivibile da tutti")
        if ricorsivo:
            for t in _bersagli(args)[1:]:
                for p in _espandi(t, cwd):
                    perche = _protetto(p, t, cwd)
                    if perche and perche.startswith(("su tutto", "sulla radice", "sulla home", "su una cartella principale della home",
                                                     "su tutto il contenuto")):
                        raise Blocco(f"{w} -R {perche}")
    elif w == "rsync":
        if any(a.startswith("--delete") or a.startswith("--remove-source-files") for a in args):
            b = _bersagli(args)
            if b:
                dest = b[-1].split(":", 1)[-1] if re.match(r"^[\w.@-]+:", b[-1]) else b[-1]
                for p in _espandi(dest, cwd):
                    perche = _protetto(p, dest, cwd)
                    if perche:
                        raise Blocco(f"rsync --delete {perche}")
    elif w == "git":
        _cmd_git(args)
    elif w == "gh":
        if args[:2] in (["repo", "delete"], ["repo", "archive"]):
            raise Blocco("cancellazione o archiviazione di un repository GitHub")
        if args[:1] == ["api"] and _metodo_delete(args):
            raise Blocco("gh api -X DELETE")
    elif w in ("curl", "wget", "http", "https", "xh"):
        if _metodo_delete(args) and not _locale(args):
            raise Blocco("richiesta DELETE a un servizio")
    elif w in ("docker", "podman", "docker-compose"):
        a = [x for x in args if not x.startswith("--context")]
        sub = a[0] if a else ""
        if w == "docker-compose" or sub == "compose":
            rest = a[1:] if sub == "compose" else a
            if "down" in rest and any(x in ("-v", "--volumes") or x.startswith("--rmi") for x in rest):
                raise Blocco("docker compose down con i volumi")
            if "rm" in rest and ("v" in _corti(rest) or "--volumes" in rest):
                raise Blocco("docker compose rm con i volumi")
        elif sub in ("rm", "rmi") and ("f" in _corti(a[1:]) or "--force" in a):
            raise Blocco(f"docker {sub} -f")
        elif sub in ("volume", "system", "image", "container", "network", "builder") and len(a) > 1 and a[1] in ("rm", "prune", "remove"):
            raise Blocco(f"docker {sub} {a[1]}")
    elif w in ("kill", "pkill", "killall"):
        if w == "kill" and "-1" in args[1:] + args and any(x in ("-9", "-KILL", "-SIGKILL") or x == "KILL" for x in args):
            raise Blocco("kill -9 -1: ferma tutti i processi")
    elif w == "launchctl":
        if args[:1] and args[0] in ("remove", "bootout"):
            dopo = " ".join(args[1:]).lower()
            if "com.jarvis." in dopo or re.fullmatch(r"\s*(gui|user|system)(/\d+)?\s*", dopo or "x"):
                raise Blocco("launchctl che ferma i servizi di Jarvis")
    elif w == "crontab":
        if "-r" in args:
            raise Blocco("crontab cancellato")
    elif w == "osascript" and re.search(r"\b(shut\s*down|restart|log\s*out)\b", " ".join(args), re.I):
        raise Blocco("spegnimento o riavvio della macchina")
    elif w in ("shutdown", "reboot", "halt"):
        raise Blocco("spegnimento o riavvio della macchina")
    elif w == "diskutil" and args[:1] and re.match(r"(erase|reformat|partitionDisk)", args[0], re.I):
        raise Blocco("formattazione di un disco")
    elif w == "cp" and "/dev/null" in args:
        for t in _bersagli(args)[1:]:
            if not any(_temporanea(p) for p in _espandi(t, cwd)):
                raise Blocco("cp /dev/null: svuota un file")
    elif w == "tar":
        for i, a in enumerate(args):
            if a.startswith(("--to-command", "--use-compress-program", "--checkpoint-action")):
                v = a.split("=", 1)[1] if "=" in a else (args[i + 1] if i + 1 < len(args) else "")
                _analizza(v, cwd, prof + 1)
    # una shell, ssh, eval: il testo che eseguono si controlla come un comando
    if w in SHELL or w in ("su", "eval", "source", "."):
        if w == "eval":
            _analizza(" ".join(args), cwd, prof + 1)
            _analizza(_decodifica(" ".join(args)), cwd, prof + 1)
        con_c = False
        for i, a in enumerate(args):
            if (a == "-c" or (re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a) and w in SHELL)) and i + 1 < len(args):
                con_c = True
                _analizza(args[i + 1], cwd, prof + 1)
                _analizza(_decodifica(args[i + 1]), cwd, prof + 1)
        # «bash script.sh» e «source script.sh» non si aprono: gli script veri fanno apposta cose forti (rsync --delete,
        # find -delete) e leggerli bloccava il lavoro normale (misurato sui comandi veri). Restano <(…), <<< e -c.
    elif w in ("ssh", "autossh"):
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if re.fullmatch(r"-[bcDEeFIiJLlmOopQRSWw]", args[i]) else 1
        remoto = " ".join(args[i + 1:])
        if remoto:
            _analizza(remoto, None, prof + 1)
    elif w in INTERPRETI:
        for i, a in enumerate(args):
            if a in ("-c", "-e", "-E", "--eval", "-p", "--print", "-r") and i + 1 < len(args):
                _codice(args[i + 1], cwd, prof, re.sub(r"\d.*$", "", w))


# ---------------------------------------------------------------- codice di python, perl, node, ruby

_CHIAMATE_RICORSIVE = re.compile(r"(shutil\.rmtree|\brmtree|FileUtils\.(?:rm_rf|rm_r|remove_dir)|\.(?:rmSync|rmdirSync)|"
                                 r"fs(?:\.promises)?\.(?:rm|rmdir)|os\.removedirs|remove_tree|\brm_rf|\brrmdir)\s*\(")
_CHIAMATE_FILE = re.compile(r"(os\.remove|os\.unlink|\bunlink|\.unlinkSync|File\.delete|os\.rmdir|\bunlink_tree)\s*\(")
_CHIAMATE_SHELL = re.compile(r"(os\.system|os\.popen|subprocess\.\w+|\bsystem|\bexec(?:Sync)?|spawnSync|execFileSync|"
                             r"child_process\.\w+|Open3\.\w+|%x)\s*[\(\{]")
_LETTERALE = re.compile(r"(?:(?<!\w)[rRbBfFuU]{1,2})?(['\"])((?:\\.|(?!\1).){0,500})\1")


def _argomenti(codice, inizio):
    """Il testo fra la parentesi aperta in `inizio` e la sua chiusa (al massimo 600 caratteri)."""
    prof, i = 0, inizio
    fine = min(len(codice), inizio + 600)
    while i < fine:
        c = codice[i]
        if c in "([{":
            prof += 1
        elif c in ")]}":
            prof -= 1
            if prof == 0:
                return codice[inizio + 1:i]
        i += 1
    return codice[inizio + 1:fine]


def _codice(codice, cwd, prof, lingua="python"):
    for m in _CHIAMATE_RICORSIVE.finditer(codice):
        dentro = _argomenti(codice, m.end() - 1)
        letterali = [x.group(2) for x in _LETTERALE.finditer(dentro)]
        if re.search(r"expanduser|Path\.home\(\)|HOME|homedir\(\)|~", dentro):
            letterali.append("~")
        for l in letterali[:4]:
            _cmd_rm(["-rf", l], cwd)
    for m in _CHIAMATE_FILE.finditer(codice):
        dentro = _argomenti(codice, m.end() - 1)
        for l in [x.group(2) for x in _LETTERALE.finditer(dentro)][:4]:
            _cmd_rm(["-f", l], cwd)
    for m in _CHIAMATE_SHELL.finditer(codice):
        dentro = _argomenti(codice, m.end() - 1)
        letterali = [x.group(2) for x in _LETTERALE.finditer(dentro)]
        if letterali:
            testo = " ".join(letterali) if dentro.lstrip().startswith("[") else letterali[0]
            _analizza(testo, cwd, prof + 1)
    if lingua in ("perl", "ruby"):
        for m in re.finditer(r"`([^`]{1,2000})`", codice):        # perl e ruby: `comando` esegue
            _analizza(m.group(1), cwd, prof + 1)


# ---------------------------------------------------------------- SQL e testo intero

def _senza_commenti_sql(t):
    """Toglie /* … */ in tempo lineare (una regex non avida qui diventa quadratica con molti /* aperti)."""
    out, i = [], 0
    while True:
        a = t.find("/*", i)
        if a < 0:
            out.append(t[i:])
            break
        out.append(t[i:a])
        b = t.find("*/", a + 2)
        if b < 0:
            break
        out.append(" ")
        i = b + 2
    return "".join(out)


_CLIENT_SQL = re.compile(r"\b(psql|mysql|mariadb|sqlite3?|duckdb|pg_\w+|clickhouse-client|odoo|sql)\b", re.I)


def _sql(testo, sicuro_sql=False):
    if not sicuro_sql and not _CLIENT_SQL.search(testo):
        return                           # senza un client SQL «update x set» è testo, non una query
    t = _senza_commenti_sql(testo)
    t = re.sub(r"--[^\n]*", " ", t)
    for stmt in re.split(r";", t):
        s = " ".join(stmt.replace('"', " ").replace("'", " ").split())
        if re.search(r"\bdrop\s+(table|database|schema|owned|role|user)\b", s, re.I):
            raise Blocco("DROP in un database")
        if re.search(r"\btruncate\s+(table\s+)?\w", s, re.I) and re.search(r"\b(psql|mysql|sqlite3?|sql|truncate\s+table)\b", t, re.I):
            raise Blocco("TRUNCATE in un database")
        if re.search(r"\bdelete\s+from\s+[\w.]+", s, re.I) and not re.search(r"\bwhere\b", s, re.I):
            raise Blocco("DELETE senza WHERE")
        if re.search(r"\bupdate\s+[\w.]+\s+set\b", s, re.I) and not re.search(r"\bwhere\b", s, re.I):
            raise Blocco("UPDATE senza WHERE")
        if re.search(r"\balter\s+table\s+[\w.]+\s+drop\b", s, re.I):
            raise Blocco("ALTER TABLE … DROP in un database")


def _senza_virgolette(t):
    out, q = [], None
    for c in t:
        if q:
            out.append(" ")
            if c == q:
                q = None
        elif c in "'\"":
            q = c
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def _svuota_file(seg, parole, cwd):
    """: > file, > file, true > file, cat /dev/null > file: svuotano un file esistente."""
    i = 0
    while i < len(parole) and re.fullmatch(r"[A-Za-z_]\w*=.*", parole[i], re.S):
        i += 1
    primo = parole[i] if i < len(parole) else ""
    w = os.path.basename(primo)
    if primo and not (w in (":", "true") or primo.startswith(">") or (w == "cat" and parole[i + 1:i + 2] == ["/dev/null"])):
        return
    for m in re.finditer(r"(?<![<>&\d])>\|?\s*([^\s;&|<>]+)", _senza_virgolette(seg)):
        dest = m.group(1)
        if dest.startswith("&") or dest.endswith(".log") or ("$" in dest.replace("$HOME", "")):
            continue
        for p in _espandi(dest, cwd):
            if not _temporanea(p):
                raise Blocco("svuota un file con una redirezione")


def _analizza(testo, cwd, prof=0):
    if prof > MAX_PROFONDITA or not testo or not testo.strip():
        return
    testo = _normalizza(testo)
    resto, docs = _heredoc(testo)
    # il corpo di un here-doc verso cat o un file è un dato, non un comando (revisione 3, F6): si guarda il resto
    if re.search(r"base64\s+(-d\b|--decode\b|-D\b)", resto) and re.search(r"\beval\b|\|\s*(ba|z|da|k)?sh\b|\bsource\b", resto):
        raise Blocco("comando nascosto in base64 ed eseguito")
    for m2 in re.finditer(r"(?:\bsource|(?:^|[\s;&|])\.|\b(?:ba|z|da|k)?sh)\s+<\(\s*(?:echo|printf|cat\s+<<<)\s+([^)\n]{1,2000})\)", resto):
        _analizza(m2.group(1).replace("'", " ").replace('"', " "), cwd, prof + 1)
    for m2 in re.finditer(r"(?:\beval|\b(?:ba|z|da|k)?sh\s+-c)\s+[\"']?\$\(\s*(?:echo|printf)\s+([^)\n]{1,2000})\)", resto):
        _analizza(m2.group(1).replace("'", " ").replace('"', " "), cwd, prof + 1)
    m = re.search(r"\b(echo|printf)\s+([^|;&\n]+)\|\s*xargs\s+((?:-\S+\s+)*)(?:sudo\s+)?rm\s+((?:-\S+\s*)+)", resto)
    if m:
        _cmd_rm(m.group(4).split() + _parole(m.group(2)), cwd)
    if re.search(r"\blaunchctl\s+(unload|disable)\b[^\n;|&]*com\.jarvis\.", resto) and not re.search(r"\blaunchctl\s+(load|bootstrap|enable|kickstart)\b", resto):
        raise Blocco("launchctl che ferma un servizio di Jarvis (senza ricaricarlo)")
    for riga, corpo in docs:
        ricevente = os.path.basename((_parole(riga.split("<<", 1)[0].split("|")[-1].split(";")[-1].split("&&")[-1]) or [""])[0])
        if ricevente in SHELL or ricevente in ("ssh", "eval"):
            _analizza(corpo, cwd, prof + 1)
        elif ricevente in INTERPRETI:
            _codice(corpo, cwd, prof, re.sub(r"\d.*$", "", ricevente))
        elif ricevente in ("psql", "mysql", "sqlite3"):
            _sql(corpo, sicuro_sql=True)
    if _FORK.search(resto):
        raise Blocco("fork bomb")
    # «… | crontab -» sostituisce il crontab: va bene solo se il testo parte da quello di adesso (crontab -l)
    if re.search(r"\|\s*crontab\s+-(\s|$)", resto) and not re.search(r"\bcrontab\s+-l\b", resto):
        raise Blocco("crontab sostituito da zero")
    variabili = {}
    for seg in _segmenti(resto):
        parole = _parole(seg)
        if parole and all(re.fullmatch(r"[A-Za-z_]\w*=.*", x, re.S) for x in parole):
            for x in parole:
                k, v = x.split("=", 1)
                variabili[k] = v
        if "<<<" in seg:
            ricevente = os.path.basename(parole[0]) if parole else ""
            m3 = re.search(r"<<<\s*(\"(?:\\.|[^\"])*\"|'[^']*'|\S+)", seg)
            if m3 and (ricevente in SHELL or ricevente in ("eval", "source", ".")):
                _analizza(m3.group(1).strip("'\""), cwd, prof + 1)
        if parole and os.path.basename(parole[0]) == "cd":
            dest = parole[1] if len(parole) > 1 else "~"
            nuovi = _espandi(dest, cwd)
            cwd = nuovi[0] if nuovi and nuovi[0].startswith("/") else None
            continue
        if _confermato_seg(parole):
            continue                         # JARVIS_CONFERMATO=1 davanti a QUESTO comando: l'utente ha detto sì
        controllo = _senza_messaggi(seg, parole)
        for rx, perche in _REGOLE:
            if rx.search(controllo):
                raise Blocco(perche)
        _sql(controllo)
        _svuota_file(seg, parole, cwd)
        _cmd_semplice(parole, cwd, prof, variabili)


def _senza_messaggi(seg, parole):
    """Il testo di un comando senza i messaggi (git commit -m, git tag -m, gh … --title/--body): un messaggio è testo,
    non un comando (revisione 3, F6)."""
    if len(parole) < 2:
        return seg
    w = os.path.basename(parole[0])
    if not ((w == "git" and any(x in ("commit", "tag", "notes", "stash") for x in parole[1:3])) or w == "gh"):
        return seg
    out, salta = [], False
    for x in parole:
        if salta:
            salta = False
            continue
        if x in ("-m", "--message", "-F", "--file", "--title", "-t", "--body", "-b", "--notes"):
            salta = True
            continue
        if x.startswith(("--message=", "--title=", "--body=", "--notes=")) or (x.startswith("-m") and len(x) > 2):
            continue
        out.append(x)
    return " ".join(out)


def _confermato_seg(parole):
    """Il comando semplice comincia con l'assegnazione JARVIS_CONFERMATO=1 (dopo eventuali altre assegnazioni,
    parole chiave della shell come do/then, o `env`)? Solo così vale: mai come argomento, in un commento o dopo."""
    i = 0
    while i < len(parole) and parole[i] in PAROLE_CHIAVE:
        i += 1
    if i < len(parole) and os.path.basename(parole[i]) == "env":
        i += 1
        while i < len(parole) and parole[i].startswith("-"):
            i += 1
    while i < len(parole) and re.fullmatch(r"[A-Za-z_]\w*=.*", parole[i], re.S):
        if parole[i] == "JARVIS_CONFERMATO=1":
            return i + 1 < len(parole)
        i += 1
    return False


def confermato(comando):
    """JARVIS_CONFERMATO=1 vale solo come assegnazione iniziale (anche dopo `env`): mai in un commento o in mezzo."""
    return bool(CONFERMA.match(comando))


def motivo(comando, cwd=None):
    """Il motivo del blocco, o None. Il comando confermato salta il controllo solo del PRIMO comando semplice."""
    if not isinstance(comando, str):
        return "la guardia non riesce a leggere il comando"
    if len(comando) > MAX_COMANDO:
        return (f"comando troppo lungo per la guardia (oltre {MAX_COMANDO} caratteri): spezzalo o scrivi il "
                "contenuto con lo strumento Write")
    comando = comando.replace("\\ ", " ")
    try:
        _analizza(comando, cwd)
    except Blocco as b:
        return str(b)
    except RecursionError:
        return "comando troppo annidato per la guardia"
    return None


# ---------------------------------------------------------------- registro dei blocchi
# Una riga JSON per ogni comando bloccato (e per ogni comando che la guardia avrebbe bloccato ma che porta
# JARVIS_CONFERMATO=1), letta dalla pagina «Registro». Non cambia MAI la decisione.
REGISTRO = os.path.join(os.path.expanduser("~"), ".locale-onedrive", "jarvis-cc", "registro", "guardia.jsonl")
REGISTRO_MAX = 2 * 1024 * 1024
_SEGRETO = re.compile(r"(sk-ant-[\w-]+|sk-[\w-]{20,}|gh[pousr]_\w{20,}|github_pat_\w+|xox[abpr]-[\w-]+|AKIA[0-9A-Z]{16}|"
                      r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+|\b\d{8,10}:[\w-]{30,}\b)")
_VALORE = re.compile(r"(?i)((?:--?|\b)[\w.-]*(?:token|password|passwd|pwd|secret|segret|api[_-]?key|bearer|authorization|credential|cookie)[\w.-]*(?:\s*[=:]\s*|\s+))(?![$`])(\"[^\"]*\"|'[^']*'|[^\s'\"]+)")


def _comando_pulito(comando, n=300):
    """Il comando su una riga, troncato, con solo i VALORI dei segreti mascherati (mai il comando intero)."""
    c = " ".join(str(comando).split())
    c = _VALORE.sub(lambda m: m.group(1) + "«mascherato»", c)
    c = _SEGRETO.sub(lambda m: m.group(0)[:4] + "…", c)
    return c if len(c) <= n else c[:n - 1] + "…"


def registra(esito, perche, comando, dati):
    try:
        cartella = os.path.dirname(REGISTRO)
        os.makedirs(cartella, mode=0o700, exist_ok=True)
        try:
            if os.path.getsize(REGISTRO) > REGISTRO_MAX:
                os.replace(REGISTRO, REGISTRO + ".1")
        except OSError:
            pass
        riga = {"ts": int(time.time()), "esito": esito, "motivo": perche, "comando": _comando_pulito(comando),
                "sessione": str(dati.get("session_id") or "")[:12], "cwd": str(dati.get("cwd") or "")[:200]}
        fd = os.open(REGISTRO, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(riga, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def prova():
    bloccati = ["rm -rf ~", "rm -rf ~/", "rm -rf /", "rm -rf *", "sudo rm -fr $HOME",
                'rm -rf "/Users/tu/Library/CloudStorage/OneDrive"',
                "rm -r ~/Library/CloudStorage/OneDrive/l'utente\\ Brain",
                "git push --force origin main", "git push -f", "git reset --hard HEAD~1",
                "git clean -fdx", "git filter-repo --path x", "gh repo delete a/b",
                "ssh vps-tuo 'docker compose down -v'", "psql -c 'DROP TABLE x'",
                "psql -c 'DELETE FROM account_move;'", "sudo shutdown -h now", "crontab -r",
                # revisione 2
                "rm --recursive --force ~", "rm -r -f ~/Jarvis", "rm -rf ${HOME}", "rm -rf ~/*", "cd ~ && rm -rf Jarvis",
                "rm -rf ~ # JARVIS_CONFERMATO=1 ", "echo JARVIS_CONFERMATO=1 ; rm -rf ~", "true JARVIS_CONFERMATO=1 && git push -f",
                "JARVIS_CONFERMATO=1 true && rm -rf ~", "find ~ -delete", "git push --mirror", "git push origin +main",
                "git clean -d -f -x", "psql -c 'DROP/**/TABLE x'", "bash <<E\nrm -rf ~\nE", "bash -c 'rm -rf ~'",
                "python3 -c \"import shutil; shutil.rmtree('/Users/tu/Jarvis')\"", "x=rm; $x -rf ~", "r''m -rf ~",
                "docker rm -f crm1-odoo-db", "kill -9 -1", "launchctl bootout gui/501", "ssh vps-tuo 'rm -rf /opt'",
                ": > ~/Jarvis/command-center/server.py", "mv ~/Jarvis /tmp/x", "shred -u ~/.env.jarvis", "dd if=/dev/zero of=~/x"]
    permessi = ["rm -rf /tmp/claude-501/prova", "rm file.txt", "git push origin main",
                "git reset --soft HEAD~1", "ls -la ~", "psql -c 'DELETE FROM x WHERE id=1'",
                "docker compose up -d", "JARVIS_CONFERMATO=1 git push --force", "echo reboot della voce",
                "rm -rf ~/.locale-onedrive/log/vecchio",
                "rm -rf /tmp/x; echo 'Jarvis Brain/Memoria' > f",
                "python3 - <<'E'\ntesto = 'git push --force e rm -rf ~'\nE\necho fatto",
                # revisione 2: comandi normali che non devono bloccare
                "env JARVIS_CONFERMATO=1 rm -rf ~/Jarvis", "git branch --list", "rm -rf node_modules",
                "find . -name '*.pyc' -print", "python3 -c 'print(1)'", "bash -c 'ls -la'", "echo '> nota' >> log.txt",
                "docker rm vecchio", "kill -9 12345", "curl -X DELETE http://127.0.0.1:7777/api/x"]
    ok = True
    for c in bloccati:
        if not motivo(c):
            print("NON BLOCCATO:", c); ok = False
    for c in permessi:
        m = motivo(c, cwd=HOME + "/Jarvis/progetto" if "node_modules" in c else None)
        if m:
            print("BLOCCATO PER ERRORE:", c, "->", m); ok = False
    print("tutte le prove passate" if ok else "PROVE FALLITE")
    return 0 if ok else 1


def _nega(perche):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": perche}}, ensure_ascii=False))


def main(grezzo=None):
    """F7 (revisione 3): QUALUNQUE errore qui dentro blocca il comando (JSON «deny»), mai un'uscita 1 che lascia
    passare. Gli errori che impediscono perfino di caricare questo file li copre guardia_avvio.py."""
    if "--prova" in sys.argv:
        return prova()
    try:
        return _main(grezzo)
    except BaseException as e:  # noqa: BLE001
        if isinstance(e, SystemExit) and not e.code:
            raise
        _nega(f"Bloccato dalla guardia dei comandi: errore interno ({type(e).__name__}). Riprova più semplice; "
              "se serve davvero, chiedi all'utente.")
        return 0


def _main(grezzo=None):
    try:
        grezzo = sys.stdin.buffer.read() if grezzo is None else grezzo
        dati = json.loads(grezzo.decode("utf-8"))
        if not isinstance(dati, dict):
            raise ValueError("non è un oggetto")
    except Exception:
        # fallisce in sicurezza: l'hook è registrato solo per Bash, quindi è un comando che non si sa leggere
        _nega("Bloccato dalla guardia dei comandi: non riesce a leggere il comando (ingresso non valido). "
              "Riscrivilo più semplice; se serve davvero, chiedi all'utente.")
        return 0
    if dati.get("tool_name") not in (None, "Bash"):
        return 0
    comando = (dati.get("tool_input") or {}).get("command") if isinstance(dati.get("tool_input"), dict) else None
    if comando is None or comando == "":
        return 0
    cwd = dati.get("cwd") if isinstance(dati.get("cwd"), str) and dati.get("cwd").startswith("/") else None
    try:
        m = motivo(comando, cwd)
        if not m and isinstance(comando, str) and confermato(comando):
            gia = motivo(CONFERMA.sub(lambda x: x.group(0)[-1], comando, count=1), cwd)
            if gia:
                registra("permesso", gia, comando, dati)
    except Exception as e:  # noqa: BLE001 — un errore della guardia blocca, non lascia passare
        m = f"errore interno della guardia ({type(e).__name__})"
    if not m:
        return 0
    registra("rifiutato", m, comando, dati)
    _nega(f"Bloccato dalla guardia dei comandi: {m}. È irreversibile: chiedi all'utente dicendo "
          "esattamente cosa fa il comando. Solo se l'utente dice sì, rilancialo con davanti "
          "`JARVIS_CONFERMATO=1 `.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
