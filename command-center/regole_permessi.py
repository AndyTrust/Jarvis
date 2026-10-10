#!/usr/bin/env python3
"""Le regole di permesso del modo «approvazione», come DATI in un file (2026-10-03).

Idea presa da OpenBot (decisione dell'utente del 2026-10-03): la politica di permesso non sta nel codice
ma in un file leggibile e modificabile, ~/.locale-onedrive/jarvis-cc/regole-permessi.json (fuori da
git e da OneDrive, 0600). Contratto: command-center/CONTRATTO-registro.md.

Come si valuta una richiesta (strumento + ingresso di Claude Code):
  - prima i SEGRETI, che nessuna regola scavalca (revisione 2 del 2026-10-03, F1):
      «nega» per i file che il modello non deve leggere mai (conf.json del ponte, credenziali di Codex,
      Gemini e Claude, history della shell): rifiuto senza scheda;
      «chiedi» con rischio ALTO per tutti gli altri segreti (.env, chiavi, .ssh, .aws, Keychain, cookie
      del browser, il file delle regole, l'archivio delle approvazioni, …) e per le cartelle nascoste
      della home e ~/Library (lista bianca: ~/.claude, ~/.ai-memory, ~/.locale-onedrive, ~/Library/CloudStorage);
    vale per Read/Write/Edit/Glob/Grep (path, pattern, glob) e per OGNI percorso dentro un comando Bash
    (~, $HOME, ${HOME}, .., relativi, collegamenti risolti, caratteri jolly, graffe, codice fra virgolette);
  - poi le regole del file, in ordine: la PRIMA che corrisponde decide;
  - nessuna corrispondenza = «chiedi» (fail closed).
  «consenti» passa da solo, «chiedi» fa la scheda, «nega» rifiuta SENZA scheda e Claude riceve il motivo.

Paletti che nessuna «consenti» scavalca (una «consenti» che li tocca semplicemente non corrisponde):
  - un segreto (vedi sopra);
  - un Bash composto o strano: ; & | < > ` $ ( ) { } * ? [ ] ! \\ e caratteri di controllo, --output (anche
    abbreviato), -o, git -c, --ext-diff, /dev/*, tail -f, ~utente, =comando, oltre 4000 caratteri;
    git branch solo come elenco (F2);
  - una scrittura sul file delle regole, sull'archivio, sul registro, in ~/.claude, in .git, nei file di
    avvio della shell, in ~/Library/LaunchAgents;
  - WebFetch: solo https, senza credenziali nell'indirizzo, porta standard, mai IP, localhost o reti locali.

Il file si valida in modo severo (F7, F8): niente regex (solo glob semplici con tetti), nessuna «consenti»
troppo larga. File non valido, simlink o scrivibile da altri: non si carica; vale l'ultimo valido o il
predefinito; l'errore va nel registro. Mai «consenti» per errore.

Solo libreria standard.
"""
import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import shlex
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import approvazioni as A

HOME = Path.home()
HOME_S = os.path.realpath(str(HOME))
AZIONI = ("consenti", "chiedi", "nega")
RISCHI = ("basso", "medio", "alto")
CHIAVI_REGOLA = {"id", "descrizione", "strumento", "corrispondenza", "azione", "rischio", "nota"}
CHIAVI_CORR = {"segreti", "comando_inizia", "percorso_glob", "url_dominio"}
MAX_REGOLE = 200
MAX_BYTE = 256 * 1024
MAX_COMANDO = 20000            # oltre, nessuna analisi: chiedi con rischio alto
MAX_COMANDO_AUTO = 4000        # oltre, mai «consenti» (la scheda mostra 4000 caratteri)
MAX_CANDIDATI = 2000
MAX_GLOB = 300
REGISTRO_MAX_BYTE = 5 * 1024 * 1024
ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,47}")
STRUMENTO_RE = re.compile(r"\*|[A-Za-z_][\w.:-]{0,99}")
DOMINIO_RE = re.compile(r"(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}")
STRUMENTI_SCRIVONO = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
STRUMENTI_PERCORSO = {"Read", "Glob", "Grep", "LS", "NotebookRead"} | STRUMENTI_SCRIVONO
_LOCK = threading.Lock()
_CACHE = {"firma": None, "caricate": None}


class RegoleNonValide(ValueError):
    pass


# ---------------------------------------------------------------- dove stanno i file

def cartella_dati():
    return HOME / ".locale-onedrive" / "jarvis-cc"


def file_regole():
    """CC_REGOLE_FILE serve alle prove (cartella temporanea)."""
    return Path(os.environ.get("CC_REGOLE_FILE") or cartella_dati() / "regole-permessi.json")


def file_ultimo_valido():
    f = file_regole()
    return f.with_name(f.stem + ".ultimo-valido.json")


def cartella_registro():
    """CC_REGISTRO_DIR serve alle prove. Qui scrivono le regole (regole.jsonl) e la guardia (guardia.jsonl)."""
    c = Path(os.environ.get("CC_REGISTRO_DIR") or cartella_dati() / "registro")
    try:
        c.mkdir(parents=True, exist_ok=True)
        os.chmod(c, 0o700)
    except OSError:
        pass
    return c


def _assoluto(p):
    return os.path.realpath(os.path.expanduser(str(p)))


def percorsi_protetti():
    """Dove una regola non può mai consentire una scrittura né una lettura automatica."""
    out = [file_regole(), file_ultimo_valido(), A.cartella(), cartella_registro(), cartella_dati()]
    return [_assoluto(p) for p in out]


# ---------------------------------------------------------------- i percorsi: lista BIANCA (revisione 3, 2026-10-04)
# Prima della revisione 3 c'era una lista NERA di segreti noti: tutto il resto passava (anche
# ~/.locale-onedrive/segreti-dal-vault, le trascrizioni in ~/.claude/projects, ~/Jarvis/../cc-ponte/conf.json).
# Adesso:
#   «nega»     credenziali che il modello non legge mai (sotto);
#   «segreto»  file e cartelle di segreti, ANCHE dentro le cartelle sicure: chiedi con rischio alto;
#   None       dentro una cartella SICURA (progetti di codice, vault, /tmp): lettura automatica;
#   «privato»  tutto il resto della home e di ~/.locale-onedrive: chiedi con rischio alto (una regola «consenti»
#              dell'utente con un percorso_glob preciso può aprire una cartella in più).
# Ogni confronto è SENZA maiuscole (il disco del Mac non le distingue) e si fa sia sul percorso risolto in modo
# fisico (realpath del percorso grezzo: ~/Jarvis/.. è ~/.locale-onedrive, non la home) sia su quello scritto.
SEGRETI_NEGA = [
    "~/.locale-onedrive/cc-ponte/conf.json", "~/.locale-onedrive/cc-ponte/conf.json.*", "~/.codex/auth.json",
    "~/.gemini/oauth_creds.json", "~/.claude.json", "~/.claude.json.*", "~/.claude/.credentials*",
    "~/.config/claude/.credentials*", "~/.zsh_history", "~/.bash_history", "~/.*_history", "~/.zsh_sessions/**",
    "~/.local/share/fish/fish_history", "~/.ssh/id_*", "~/.ssh/*_rsa", "~/.ssh/*_ed25519", "~/.ssh/*_ecdsa",
    "/var/lib/cc-ponte/**", "/etc/cc-ponte/**",
]
# cartelle e file di segreti: chiedi con rischio alto (valgono anche dentro le cartelle sicure)
SEGRETI_CHIEDI = [
    "~/.locale-onedrive/cc-ponte", "~/.locale-onedrive/cc-ponte/**", "~/.locale-onedrive/jarvis-cc",
    "~/.locale-onedrive/jarvis-cc/**", "~/.locale-onedrive/segreti-dal-vault", "~/.locale-onedrive/segreti-dal-vault/**",
    "~/.locale-onedrive/chiavi-app-android", "~/.locale-onedrive/chiavi-app-android/**", "~/.claude/projects",
    "~/.claude/projects/**", "~/.claude/history.jsonl", "~/.claude/file-history/**", "~/.claude/session-env/**",
    "~/.claude/shell-snapshots/**", "~/.claude/paste-cache/**", "~/.ssh", "~/.ssh/**", "~/.aws", "~/.aws/**",
    "~/.codex", "~/.codex/**", "~/.gemini", "~/.gemini/**", "~/.config/gh", "~/.config/gh/**", "~/.config/gcloud/**",
    "~/.kube/**", "~/.gnupg/**", "~/.docker/config.json", "~/.netrc", "~/.npmrc", "~/.pypirc", "~/.pgpass",
    "~/.git-credentials", "~/.segreti-archivio/**", "~/Library/Keychains/**", "~/Library/Cookies/**",
    "/**/segreti-*/**", "/**/chiavi-*/**", "/**/.env*/**", "/**/claude/projects/**", "/**/.claude/projects/**",
    "/**/ripristino/sistema/**", "/**/ripristino/claude/settings*", "/**/ripristino/claude/projects/**",
]
# nomi di file che sono segreti ovunque stiano (anche nei progetti)
NOMI_SEGRETI = re.compile(
    r"^(\.env.*|.*\.env|.*\.env\..*|.*\.(pem|key|p12|pfx|jks|keystore|kdbx|ovpn|ppk|gpg|asc|dump)|keystore.*|"
    r"id_(rsa|ed25519|ecdsa|dsa)(?!.*\.pub$).*|.*credential.*|.*secret.*|.*token.*|auth\.json|oauth_creds.*|"
    r"google-lettura\.json|assistenza\.json|keystore\.properties|.*\.keychain(-db)?|login data.*|cookies(-journal)?|"
    r"\.netrc|\.npmrc|\.pypirc|\.pgpass|\.git-credentials|.*_history|conf\.json\.bak.*|settings\.json\.bak.*|"
    r"service[-_]account.*\.json|.*segret.*|.*chiav.*\.(json|txt|properties)|.*password.*|ssh_host_.*_key|master\.passwd|"
    r"shadow|sudoers.*)$", re.I)
# le cartelle SICURE: lettura automatica (fuori dai segreti sopra)
SICURE = [
    "~/Jarvis/**", "~/.locale-onedrive/Jarvis/**", "~/prodotto-uno/**", "~/my-agent/**",
    "~/Library/CloudStorage/OneDrive/Jarvis Brain/Progetti/**",
    "~/Library/CloudStorage/OneDrive/Jarvis Brain/Memoria/**",
    "~/Library/CloudStorage/OneDrive/CRM Azienda Uno/**",
    "~/.ai-memory/**", "~/.claude/CLAUDE.md", "~/.claude/agents/**", "~/.claude/skills/**", "~/.claude/hooks/**",
    "~/.claude/commands/**", "~/CLAUDE.md",
    "/tmp/**", "/private/tmp/**", "/private/var/folders/*/*/T/**", "/var/folders/*/*/T/**",
]


def _comp(p):
    return [x for x in p.split("/") if x]


def _espandi_glob(g):
    g = os.path.expanduser(g)
    if g.startswith("~"):
        g = HOME_S + g[1:]
    return g


class GlobSicuro:
    """Glob sui percorsi senza regex: «**» (un componente intero) = zero o più cartelle, * e ? dentro un
    componente (fnmatch, che con pochi * non esplode). Confronto a programmazione dinamica: O(P × C).
    maiuscole=False: confronto senza maiuscole (casefold) su glob e percorso."""

    def __init__(self, g, maiuscole=True):
        self.testo = g
        g = _espandi_glob(g)
        if not g.startswith("/"):
            raise RegoleNonValide(f"glob «{g}»: deve cominciare con / o ~")
        if len(g) > MAX_GLOB:
            raise RegoleNonValide(f"glob troppo lungo (massimo {MAX_GLOB} caratteri)")
        self.maiuscole = maiuscole
        if not maiuscole:
            g = g.casefold()
        self.parti = _comp(g)
        if len(self.parti) > 64:
            raise RegoleNonValide("glob con troppe cartelle")
        if sum(1 for x in self.parti if x == "**") > 2:
            raise RegoleNonValide("glob con più di due «**»")
        for x in self.parti:
            if "**" in x and x != "**":
                raise RegoleNonValide(f"glob «{g}»: «**» deve essere una cartella intera (…/**/…)")
            if x.count("*") > 4:
                raise RegoleNonValide(f"glob «{g}»: troppi * in «{x}»")
        self.fisso = self.letterale()
        self.fisso_slash = self.fisso.rstrip("/") + "/"

    def letterale(self):
        """Il prefisso senza caratteri jolly (la cartella da cui parte il glob)."""
        out = []
        for x in self.parti:
            if any(c in x for c in "*?["):
                break
            out.append(x)
        return "/" + "/".join(out)

    def corrisponde(self, percorso):
        if not self.maiuscole:
            percorso = percorso.casefold()
        if not (percorso == self.fisso or percorso.startswith(self.fisso_slash) or self.fisso == "/"):
            return False
        c = _comp(percorso)[:256]
        P, n = self.parti, len(c)
        ok = [False] * (n + 1)
        ok[0] = True
        for p in P:
            nuovo = [False] * (n + 1)
            if p == "**":
                acceso = False
                for j in range(n + 1):
                    acceso = acceso or ok[j]
                    nuovo[j] = acceso
            else:
                jolly = any(ch in p for ch in "*?[")
                for j in range(n):
                    if ok[j] and (fnmatch.fnmatchcase(c[j], p) if jolly else c[j] == p):
                        nuovo[j + 1] = True
            ok = nuovo
            if not any(ok):
                return False
        return ok[n]


def _globs(lista):
    out = []
    for g in lista:
        out.append(GlobSicuro(g, maiuscole=False))
        # anche il bersaglio vero di un collegamento (~/Jarvis → ~/.locale-onedrive/Jarvis)
        fisso = _espandi_glob(g)
        radice = fisso.split("/**")[0].split("/*")[0]
        if not radice.startswith("/") or radice == "/":
            continue
        try:
            vera = os.path.realpath(radice)
        except (OSError, ValueError):
            vera = radice
        if vera != radice:
            out.append(GlobSicuro(vera + fisso[len(radice):], maiuscole=False))
    return out


_GLOB_NEGA = _globs(SEGRETI_NEGA)
_GLOB_CHIEDI = _globs(SEGRETI_CHIEDI)
_GLOB_SICURE = _globs(SICURE)
# la memoria di Claude per progetto (MEMORY.md e le note): è la memoria di lavoro degli agenti, non un segreto.
# Restano segreti le trascrizioni (*.jsonl) e ogni file con un nome da segreto (2026-10-04, l'utente: «niente letture inutili»)
MEMORIA_CLAUDE = ["~/.claude/projects/*/memory", "~/.claude/projects/*/memory/**"]
_GLOB_MEMORIA = _globs(MEMORIA_CLAUDE)


def _dentro(p, cartella):
    p, cartella = p.casefold(), cartella.casefold()
    return p == cartella or p.startswith(cartella.rstrip("/") + "/")


def _vale(globs, q):
    return any(g.corrisponde(q) for g in globs)


def _candidati(p):
    """Il percorso scritto (normalizzato) e quello vero (realpath sul percorso GREZZO: i collegamenti si
    seguono prima dei .., come fa la shell; per un percorso che non esiste si risolve il genitore che c'è)."""
    out = {os.path.normpath(p)}
    try:
        out.add(os.path.realpath(p))
    except (OSError, ValueError):
        pass
    return out


def classe_percorso(p):
    """«nega», «segreto», «privato» o None per un percorso ASSOLUTO GREZZO (non normalizzato)."""
    if not p:
        return None
    if len(_CLASSI) > 20000:
        _CLASSI.clear()
    if p not in _CLASSI:
        _CLASSI[p] = _classe_percorso(p)
    return _CLASSI[p]


_CLASSI = {}


def _classe_percorso(p):
    peggiore = None
    for q in _candidati(p):
        peggiore = _peggio(peggiore, _classe_uno(q))
        if peggiore == "nega":
            return "nega"
    return peggiore


def _classe_uno(q):
    if _vale(_GLOB_NEGA, q):
        return "nega"
    base = os.path.basename(q.rstrip("/"))
    if _vale(_GLOB_MEMORIA, q) and not NOMI_SEGRETI.match(base or "") and not base.endswith(".jsonl"):
        return None
    if (_vale(_GLOB_CHIEDI, q) or NOMI_SEGRETI.match(base or "")
            or any(_dentro(q, x) for x in percorsi_protetti())):
        return "segreto"
    if any(NOMI_SEGRETI.match(c) for c in _comp(q)[:-1] if c.startswith((".env", "segreti", "chiavi"))):
        return "segreto"
    if _vale(_GLOB_SICURE, q):
        return None
    if _dentro(q, HOME_S):
        return "privato"
    return None


_ANTENATI = None


def _antenati_segreti():
    """Le cartelle da cui partono i glob dei segreti: una ricerca che le contiene li legge."""
    global _ANTENATI
    if _ANTENATI is None:
        out = set()
        for g in _GLOB_NEGA + _GLOB_CHIEDI:
            if g.fisso != "/":
                out.add(g.fisso)
        _ANTENATI = sorted(out)
    return _ANTENATI


def classe_ambito(cartella):
    """Una ricerca (Grep/Glob) dentro `cartella`: tocca segreti se la cartella è un segreto o li contiene;
    è «privata» se è fuori dalle cartelle sicure o ne contiene una non sicura."""
    peggiore = classe_percorso(cartella)
    if peggiore in ("nega", "segreto"):
        return peggiore
    for vera in _candidati(cartella):
        for a in _antenati_segreti():
            if _dentro(a, vera):
                return "segreto"
        # una ricerca che parte sopra le cartelle sicure (la home, OneDrive) le supera: privata
        if _dentro(HOME_S, vera) or (_dentro(vera, HOME_S) and not _vale(_GLOB_SICURE, vera.rstrip("/") + "/x")):
            peggiore = _peggio(peggiore, "privato")
    return peggiore


def _peggio(a, b):
    ordine = {None: 0, "privato": 1, "segreto": 2, "nega": 3}
    return a if ordine[a] >= ordine[b] else b


def _espandi_parola(t, cwd):
    """Una parola di un comando → percorso assoluto GREZZO (niente normpath: i .. si risolvono dopo, sul disco)."""
    t = t.strip().strip("'\"")
    t = t.replace("${HOME}", HOME_S).replace("$HOME", HOME_S)
    if t.startswith("~") and not (t == "~" or t.startswith("~/")):
        return None
    if t == "~" or t.startswith("~/"):
        t = HOME_S + t[1:]
    if not t:
        return None
    if not t.startswith("/"):
        t = (cwd or HOME_S).rstrip("/") + "/" + t
    return t


_GRAFFE = re.compile(r"\{([^{}]*,[^{}]*)\}")


def _graffe(t, n=0):
    m = _GRAFFE.search(t)
    if not m or n > 3:
        return [t]
    out = []
    for alt in m.group(1).split(",")[:16]:
        out += _graffe(t[:m.start()] + alt + t[m.end():], n + 1)
    return out[:64]


_SOTTO_PERCORSI = re.compile(r"(?:~|\$\{?HOME\}?|\.\.?)?/[^\s'\"`;|&<>(),]+|~(?=[\s'\"`;|&<>(),]|$)")


def classe_parola(t, cwd):
    """La classe peggiore fra i percorsi che una parola può nominare (graffe, jolly, git show rev:percorso,
    e le parole senza / che esistono nella cartella di lavoro)."""
    peggiore = None
    pezzi = {t}
    if "=" in t:
        pezzi.add(t.split("=", 1)[1])
    if ":" in t and not t.startswith(("http:", "https:")):
        pezzi.add(t.split(":", 1)[1])                    # git show HEAD:percorso, scp host:percorso
    # un percorso semplice con gli spazi («…/Jarvis Brain/Progetti/Azienda Uno/x») è UN percorso: i frammenti tagliati sugli spazi
    # («/Progetti/azienda») non esistono e finivano «privati», cioè rischio alto per ogni comando sul vault (2026-10-04)
    intero = t.strip("'\"")
    if not (" " in intero and re.fullmatch(r"[~/][^;|&<>`$(){}*?\[\]\n]*", intero)):
        pezzi |= set(_SOTTO_PERCORSI.findall(t))
    for pezzo in pezzi:
        for v in _graffe(pezzo):
            v = v.strip("'\"")
            base = os.path.basename(v.rstrip("/"))
            if NOMI_SEGRETI.match(base or ""):
                peggiore = _peggio(peggiore, "segreto")
            percorso = v.startswith(("/", "~", "$", ".")) or "/" in v
            if not percorso:
                # una parola qualunque: è un percorso solo se c'è davvero nella cartella di lavoro
                if not v or v.startswith("-") or len(v) > 255:
                    continue
                try:
                    if not os.path.lexists(os.path.join(cwd or HOME_S, v)):
                        continue
                except (OSError, ValueError):
                    continue
            p = _espandi_parola(v, cwd)
            if not p:
                peggiore = _peggio(peggiore, "privato")      # ~utente
                continue
            if any(c in p for c in "*?["):
                fisso = p
                while any(c in fisso for c in "*?["):
                    fisso = os.path.dirname(fisso)
                peggiore = _peggio(peggiore, classe_ambito(fisso))
                if NOMI_SEGRETI.match(os.path.basename(p).replace("*", "x").replace("?", "x")):
                    peggiore = _peggio(peggiore, "segreto")
            else:
                peggiore = _peggio(peggiore, classe_percorso(p))
            if peggiore == "nega":
                return peggiore
    return peggiore


def _parole(cmd):
    try:
        lx = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>()")
        lx.whitespace_split = True
        lx.commenters = ""
        return list(lx)
    except ValueError:
        return cmd.split()


LOCALE_CC = re.compile(r"(127\.\d+\.\d+\.\d+|localhost|\[?::1\]?|0\.0\.0\.0|\[::\])(:\d+)?", re.I)


def classe_richiesta(strumento, ingresso, cwd=None):
    """La classe peggiore dei percorsi che la richiesta tocca: «nega», «segreto», «privato», «troppo» o None."""
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    cwd = cwd or HOME_S
    if strumento == "Bash":
        cmd = str(ingresso.get("command") or "")
        if len(cmd) > MAX_COMANDO:
            return "troppo"
        parole = _parole(cmd)
        if len(parole) > MAX_CANDIDATI:
            return "troppo"
        peggiore = None
        if re.search(r"\bgit\b[^;&|\n]*\b(log|whatchanged)\b[^;&|\n]*\s(-p|-u|--patch|--full-diff)\b", cmd) or \
                re.search(r"\bgit\b[^;&|\n]*\bshow\s+(?!-)\S", cmd):
            peggiore = "privato"               # la storia git può contenere segreti messi per sbaglio: rischio alto
        if LOCALE_CC.search(cmd):
            peggiore = "segreto"              # il Command Center in locale (auto-approvazione): sempre chiedi, rischio alto
        for t in parole:
            peggiore = _peggio(peggiore, classe_parola(t, cwd))
            if peggiore == "nega":
                return "nega"
        return peggiore
    peggiore = None
    p = A._percorso_ingresso(ingresso)
    if strumento in ("Grep", "Glob", "LS"):
        base = _espandi_parola(str(ingresso.get("path") or cwd), cwd)
        peggiore = _peggio(peggiore, classe_ambito(base) if base else None)
        for campo in ("glob", "pattern" if strumento == "Glob" else None):
            if campo and ingresso.get(campo):
                for v in _graffe(str(ingresso[campo])):
                    if NOMI_SEGRETI.match(os.path.basename(v.replace("*", "x").replace("?", "x"))):
                        peggiore = _peggio(peggiore, "segreto")
                    piena = _espandi_parola(v if v.startswith(("/", "~")) else (base or cwd).rstrip("/") + "/" + v, cwd)
                    if piena:
                        fisso = piena
                        while any(c in fisso for c in "*?["):
                            fisso = os.path.dirname(fisso)
                        peggiore = _peggio(peggiore, classe_ambito(fisso))
    elif p:
        q = _espandi_parola(str(p), cwd)
        peggiore = _peggio(peggiore, classe_percorso(q) if q else "privato")
    elif strumento == "WebFetch" and LOCALE_CC.search(str(ingresso.get("url") or "")):
        peggiore = "segreto"
    return peggiore


def tocca_segreti(strumento, ingresso, cwd=None):
    return classe_richiesta(strumento, ingresso, cwd) in ("nega", "segreto", "troppo")


# ---------------------------------------------------------------- scritture mai automatiche

AVVIO_SHELL = {".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".bash_login"}


# l'utente, 2026-10-04: «devo poter scrivere in ~/.claude e operare su hook, cache e chat vecchie tramite Jarvis». Interruttore: la parola
# «claude» nel file ~/.locale-onedrive/jarvis-cc/segreti_con_conferma (solo la VPS; l'agente non può scriverlo: sta in jarvis-cc).
# Aperto tutto ~/.claude TRANNE il nucleo: i file che sono la guardia stessa (settings, credenziali, hook di guardia), perché scriverli
# vuol dire poter spegnere tutti i controlli.
FLAG_LIBERO = Path(os.environ.get("CC_FLAG_LIBERO") or Path.home() / ".locale-onedrive" / "jarvis-cc" / "segreti_con_conferma")
NUCLEO_CLAUDE = re.compile(r"(^|/)(settings(\.local)?\.json[^/]*|\.credentials[^/]*|\.claude\.json[^/]*|hooks/guardia_[^/]*|hooks/connessioni_guardia[^/]*)$", re.I)
NUCLEO_CLAUDE_TESTO = re.compile(r"settings(\.local)?\.json|\.credentials|\.claude\.json|hooks/guardia_|guardia_(comandi|avvio)|connessioni_guardia", re.I)


def flag_parola(parola):
    try:
        return parola in FLAG_LIBERO.read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _claude_aperto_per(q):
    base = (HOME_S + "/.claude").casefold()
    ql = q.casefold()
    return (ql == base or ql.startswith(base + "/")) and not NUCLEO_CLAUDE.search(q) and ".git" not in [x.casefold() for x in _comp(q)]


def scrittura_protetta(p):
    """p è il percorso GREZZO (con i .., non normalizzato): si controllano il percorso scritto e quello vero."""
    if not p:
        return True
    if flag_parola("claude"):
        cands = _candidati(os.path.expanduser(str(p)))
        if cands and all(_claude_aperto_per(q) for q in cands):
            return False
    for q in _candidati(os.path.expanduser(str(p))):
        c = [x.casefold() for x in _comp(q)]
        ql = q.casefold()
        if ".git" in c or ql.startswith((HOME_S + "/.claude").casefold()) or ql.startswith((HOME_S + "/Library/LaunchAgents").casefold()):
            return True
        if os.path.dirname(ql) == HOME_S.casefold() and os.path.basename(ql) in AVVIO_SHELL:
            return True
        if any(_dentro(q, x) for x in percorsi_protetti()):
            return True
    return classe_percorso(os.path.expanduser(str(p))) in ("nega", "segreto", "privato")


# ---------------------------------------------------------------- Bash: un comando singolo che legge soltanto

_META = re.compile(r"[;&|<>`$\n\r\\(){}*?\[\]!\x00-\x08\x0b-\x1f\x7f]")
GIT_BRANCH_ELENCO = {"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--list", "-l", "--show-current",
                     "--no-color", "--color", "--column", "--no-column", "--sort", "--contains", "--no-contains",
                     "--merged", "--no-merged", "--points-at", "-i", "--ignore-case", "--omit-empty"}


def _git_branch_elenco(parti):
    """git branch solo come elenco (F2): opzioni di elenco e, dopo --list/--contains/--merged…, i loro argomenti."""
    args = parti[2:]
    lista = any(a in ("--list", "-l") for a in args)
    vuole_valore = {"--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort"}
    i = 0
    while i < len(args):
        a = args[i]
        nome = a.split("=", 1)[0]
        if nome in GIT_BRANCH_ELENCO:
            if nome in vuole_valore and "=" not in a:
                i += 1                      # il suo argomento
        elif a.startswith("-"):
            return False
        elif not lista:
            return False                    # un nome senza --list crea un ramo
        i += 1
    return True


_GIT_PERICOLOSO = re.compile(r"(?im)^\s*(fsmonitor|external|textconv|pager|command|sshcommand|askpass|editor|"
                             r"gitproxy|helper|clean|smudge|process)\s*=|^\s*\[\s*(filter|include|includeif)\b")


def _cartella_git(cwd):
    d = os.path.realpath(cwd or HOME_S)
    for _ in range(64):
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return g
        if os.path.isfile(g):                    # worktree: «gitdir: …»
            try:
                riga = Path(g).read_text(encoding="utf-8", errors="replace").strip()
                if riga.startswith("gitdir:"):
                    return os.path.realpath(os.path.join(d, riga[7:].strip()))
            except OSError:
                return None
            return None
        nuova = os.path.dirname(d)
        if nuova == d:
            return None
        d = nuova
    return None


def git_sicuro(cmd, cwd):
    """git automatico solo se le configurazioni che legge (repo, worktree, utente) non fanno eseguire codice
    (core.fsmonitor, diff.external, textconv, pager, filter, include…: revisione 3, R2). Gli altri comandi: sì."""
    try:
        parti = shlex.split(cmd)
    except ValueError:
        return False
    if not parti or os.path.basename(parti[0]) != "git":
        return True
    if any(p in ("-C", "--git-dir", "--work-tree", "--exec-path", "--namespace") or p.startswith(("--git-dir=", "--work-tree=", "--exec-path"))
           for p in parti[1:]):
        return False
    if any(os.environ.get(k) for k in ("GIT_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_EXTERNAL_DIFF")):
        return False
    file_conf = [HOME / ".gitconfig", HOME / ".config" / "git" / "config"]
    g = _cartella_git(cwd)
    if g:
        file_conf += [Path(g) / "config", Path(g) / "config.worktree"]
        comune = Path(g) / "commondir"
        if comune.exists():
            try:
                file_conf.append(Path(os.path.realpath(os.path.join(g, comune.read_text().strip()))) / "config")
            except OSError:
                return False
    for f in file_conf:
        try:
            if f.exists() and _GIT_PERICOLOSO.search(f.read_text(encoding="utf-8", errors="replace")[:200000]):
                return False
        except OSError:
            return False
    return True


def bash_semplice(cmd):
    """Le cautele della lista automatica, più quelle della revisione 2: un comando solo, niente metacaratteri
    né caratteri di controllo, niente --output (anche abbreviato) né -o, niente file di segreti, niente
    /dev/*, tail -f, ~utente, =comando, git -c / --ext-diff, git branch che non sia un elenco."""
    cmd = (cmd or "").strip()
    if not cmd or len(cmd) > MAX_COMANDO_AUTO or _META.search(cmd):
        return False
    try:
        parti = shlex.split(cmd)
    except ValueError:
        return False
    if not parti:
        return False
    for p in parti:
        nome = p.split("=", 1)[0]
        if p == "-o" or nome.startswith("--output") or (len(nome) >= 5 and "--output".startswith(nome)):
            return False
        if nome in ("--ext-diff", "--textconv", "--files0-from", "--exec", "--upload-pack", "--receive-pack", "--no-index"):
            return False
        if p.startswith("/dev/") or p.startswith("=") or (p.startswith("~") and not (p == "~" or p.startswith("~/"))):
            return False
        if ".." in p.split("/") or p == "..":
            return False                          # un comando automatico non risale le cartelle (revisione 3, F1)
        if A.e_file_segreto(p):
            return False
    prog = os.path.basename(parti[0])
    if prog == "tail" and any(p in ("-f", "-F", "--follow", "--retry") or (p.startswith("-") and not p.startswith("--")
                                                                              and ("f" in p or "F" in p)) for p in parti[1:]):
        return False
    if prog == "date" and any(p in ("-f", "--file") or p.startswith("--file=") for p in parti[1:]):
        return False
    if prog == "git":
        if any(p == "-c" or p.startswith("--config-env") or p.startswith("--exec-path") for p in parti[1:]):
            return False
        sub = parti[1] if len(parti) > 1 else ""
        # la storia può contenere segreti messi per sbaglio: niente patch intere né blob (revisione 3, F3)
        if sub in ("log", "whatchanged") and any(p in ("-p", "-u", "--patch", "--full-diff") or p.startswith(("-p", "--patch", "-U"))
                                                 for p in parti[2:]):
            return False
        if sub == "show" and any(not p.startswith("-") for p in parti[2:]) \
                and not any(p in ("--stat", "--name-only", "--name-status", "--shortstat", "-s", "--no-patch") for p in parti[2:]):
            return False
        if len(parti) > 1 and parti[1] == "branch" and not _git_branch_elenco(parti):
            return False
    return True


# ---------------------------------------------------------------- WebFetch

DOMINI_DOCUMENTAZIONE = ["github.com", "docs.github.com", "anthropic.com", "docs.anthropic.com", "docs.claude.com",
                         "pypi.org", "npmjs.com", "www.npmjs.com", "*.wikipedia.org", "docs.python.org",
                         "developer.mozilla.org", "developer.apple.com"]


def url_sicuro(url):
    """https, porta standard, niente credenziali, mai IP né nomi locali."""
    try:
        u = urlsplit(str(url or "").strip())
        host = (u.hostname or "").rstrip(".").lower()
        porta = u.port
    except ValueError:
        return None
    if u.scheme != "https" or not host or u.username or u.password or (porta not in (None, 443)):
        return None
    if "@" in u.netloc or "%" in host or host.isdigit() or re.fullmatch(r"[0-9a-fx.:]+", host):
        return None
    try:
        ipaddress.ip_address(host.strip("[]"))
        return None
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".arpa")):
        return None
    return host


PERCORSI_WEB_VIETATI = re.compile(r"(^|/)(search|login|logout|session|sessions|signup|join|new|edit|settings|"
                                  r"oauth|authorize|redirect|special:\w*|index\.php)(/|$)", re.I)


def url_documentazione(url):
    """Per i domini consentiti da soli (revisione 3, F4): niente query string, niente frammento, niente credenziali,
    percorso fino a 200 caratteri e mai pagine di ricerca, accesso, modifica o API (i dati usciranno nella URL)."""
    host = url_sicuro(url)
    if not host:
        return None
    try:
        u = urlsplit(str(url).strip())
    except ValueError:
        return None
    if u.query or u.fragment or "?" in str(url) or "#" in str(url) or len(u.path) > 200:
        return None
    if host.endswith("github.com") and re.search(r"(^|/)api(/|$)", u.path, re.I):
        return None                                # niente API di GitHub (revisione 3, F4)
    if PERCORSI_WEB_VIETATI.search(u.path) or "%" in u.path or "//" in u.path or ".." in u.path.split("/") \
            or re.search(r"[\s\\]", str(url)):
        return None
    return host


def dominio_in(host, domini):
    for d in domini:
        if d.startswith("*."):
            if host.endswith(d[1:]):
                return True
        elif host == d:
            return True
    return False


# ---------------------------------------------------------------- il file predefinito

def regole_predefinite(conf=None):
    """La lista automatica di approvazioni.py (approvazioni_auto, o il default) senza WebFetch e WebSearch,
    più una regola per i siti di documentazione (revisione 2, F1)."""
    conf = conf or A.config_auto(os.environ.get("CC_CONFIG") or None)
    strumenti = [s for s in conf.get("strumenti", []) if s not in ("Bash", "WebFetch", "WebSearch")]
    regole = [{
        "id": "segreti",
        "descrizione": "File di segreti (.env, chiavi, .ssh, credenziali, history): mai da soli",
        "strumento": "*",
        "corrispondenza": {"segreti": True},
        "azione": "chiedi",
        "rischio": "alto",
        "nota": ("Vale per i percorsi di Read/Write/Edit/Glob/Grep e per ogni percorso di un comando Bash. Alcuni file "
                 "(credenziali del ponte, di Codex, Gemini e Claude, history) sono negati sempre, senza scheda."),
    }]
    if strumenti:
        regole.append({"id": "strumenti-lettura", "descrizione": "Strumenti che leggono soltanto", "strumento": strumenti,
                       "azione": "consenti", "nota": "Fuori dai segreti e dalle cartelle nascoste della home."})
    if conf.get("bash"):
        regole.append({"id": "bash-sola-lettura", "descrizione": "Comandi Bash singoli che leggono soltanto",
                       "strumento": "Bash", "corrispondenza": {"comando_inizia": list(conf["bash"])}, "azione": "consenti",
                       "nota": ("Vale solo per un comando singolo che comincia con queste parole: niente ; && | > $( ) né "
                                "caratteri jolly; git branch solo come elenco.")})
    regole.append({"id": "web-documentazione", "descrizione": "Pagine di documentazione su siti noti", "strumento": "WebFetch",
                   "corrispondenza": {"url_dominio": list(DOMINI_DOCUMENTAZIONE)}, "azione": "consenti",
                   "nota": "Solo https e solo questi siti; il resto del web e WebSearch chiedono (la ricerca può contenere dati)."})
    return {
        "versione": 1,
        "_leggimi": ("Regole di permesso del modo «approvazione». La PRIMA regola che corrisponde decide; "
                     "nessuna corrispondenza = chiedi. azione: consenti | chiedi | nega. I segreti chiedono (o sono negati) "
                     "sempre. Il Command Center rilegge il file a ogni richiesta. Se il file non è valido vale l'ultimo "
                     "valido. Contratto: ~/Jarvis/command-center/CONTRATTO-registro.md"),
        "regole": regole,
    }


# ---------------------------------------------------------------- validazione (F7, F8)

def _testo(v, nome, n=500, vuoto_ok=True):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise RegoleNonValide(f"{nome}: serve un testo")
    if len(v) > n:
        raise RegoleNonValide(f"{nome}: troppo lungo (massimo {n} caratteri)")
    if not vuoto_ok and not v.strip():
        raise RegoleNonValide(f"{nome}: vuoto")
    return v


def _lista_testi(v, nome, n=300):
    lst = [v] if isinstance(v, str) else v
    if not isinstance(lst, list) or not lst or len(lst) > 200:
        raise RegoleNonValide(f"{nome}: serve un testo o una lista di testi (da 1 a 200)")
    for x in lst:
        _testo(x, nome, n, vuoto_ok=False)
    return list(lst)


PROGRAMMI_MAI_CONSENTITI = {
    "rm", "mv", "cp", "dd", "sudo", "su", "doas", "eval", "exec", "env", "xargs", "find", "awk", "gawk", "sed", "tee",
    "chmod", "chown", "curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "socat", "telnet", "docker", "kubectl",
    "launchctl", "crontab", "kill", "killall", "pkill", "open", "osascript", "npx", "command", "nohup", "time", "watch",
    "truncate", "shred", "ln", "install", "mkfs", "diskutil", "security", "defaults", "pmset", "shutdown", "reboot", "halt",
    "bash", "sh", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "source", ".",
}
INTERPRETI = {"python", "python3", "python2", "perl", "ruby", "node", "deno", "bun", "php", "lua", "Rscript", "julia", "pwsh"}
SECONDE_PAROLE_VIETATE = {"push", "reset", "clean", "rebase", "filter-branch", "filter-repo", "config", "update-ref",
                          "reflog", "gc", "publish", "unpublish", "rm", "delete", "remote", "submodule", "stash", "restore",
                          "checkout", "switch", "merge", "cherry-pick", "revert", "am", "apply", "worktree", "api", "release"}


def _prefisso_consentibile(p):
    try:
        parti = shlex.split(p)
    except ValueError:
        return f"«{p}» non si legge come comando"
    if not parti:
        return f"«{p}» è vuoto"
    if _META.search(p):
        return f"«{p}» contiene caratteri della shell"
    prog = os.path.basename(parti[0])
    if prog in PROGRAMMI_MAI_CONSENTITI:
        return f"«{prog}» non si consente mai da solo (può cancellare, scrivere o eseguire altro)"
    if prog in INTERPRETI and (len(parti) < 2 or parti[1].startswith("-")):
        return f"«{p}»: un interprete si consente solo con uno script preciso (non -c/-e né da solo)"
    if prog in ("git", "gh", "npm", "pnpm", "yarn", "pip", "pip3", "brew", "uv", "cargo", "go"):
        if len(parti) < 2:
            return f"«{prog}» da solo è troppo largo: scrivi anche il sottocomando"
        if parti[1] in SECONDE_PAROLE_VIETATE:
            return f"«{prog} {parti[1]}» non si consente mai da solo"
    return None


def _glob_scrittura_ok(g):
    """Una «consenti» di scrittura (o di uno strumento MCP) vale solo dentro cartelle precise."""
    fisso = g.letterale()
    c = _comp(fisso)
    if _dentro(fisso, HOME_S):
        sotto = _comp(fisso[len(HOME_S):])
        if len(sotto) < 2:
            return "la cartella è troppo larga (serve almeno ~/cartella/sottocartella/…)"
        if sotto[0].startswith(".") or (sotto[0] == "Library" and sotto[1:2] != ["CloudStorage"]):
            return "cartelle nascoste della home e ~/Library non si consentono"
        if sotto[0] == "Library" and len(sotto) < 4:
            return "dentro OneDrive serve una cartella precisa (~/Library/CloudStorage/<onedrive>/<cartella>/…)"
    elif not (fisso.startswith(("/tmp/", "/private/tmp/")) and len(c) >= 2):
        return "fuori dalla home si consentono solo cartelle sotto /tmp"
    if any(x in (".git", ".claude", ".ssh") for x in g.parti):
        return ".git, .claude e .ssh non si consentono"
    if classe_ambito(fisso) in ("nega", "segreto"):
        return "la cartella contiene segreti"
    return None


def _valida_regola(r, i, visti):
    if not isinstance(r, dict):
        raise RegoleNonValide(f"regola {i + 1}: serve un oggetto")
    estranee = {k for k in r if k not in CHIAVI_REGOLA and not k.startswith("_")}
    if estranee:
        raise RegoleNonValide(f"regola {i + 1}: campi sconosciuti {sorted(estranee)}")
    rid = r.get("id")
    if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
        raise RegoleNonValide(f"regola {i + 1}: id mancante o non valido (minuscole, cifre, - _ . fino a 48)")
    if rid in visti or rid in ("predefinita", "segreti-mai", "troppo-lungo", "troppe-in-attesa"):
        raise RegoleNonValide(f"regola «{rid}»: id ripetuto o riservato")
    visti.add(rid)
    dove = f"regola «{rid}»"
    strumenti = _lista_testi(r.get("strumento"), f"{dove}, strumento", 100)
    if any(not STRUMENTO_RE.fullmatch(s) for s in strumenti):
        raise RegoleNonValide(f"{dove}: strumento non valido (un nome di Claude Code o «*»)")
    azione = r.get("azione")
    if azione not in AZIONI:
        raise RegoleNonValide(f"{dove}: azione deve essere consenti, chiedi o nega")
    rischio = r.get("rischio")
    if rischio is not None and rischio not in RISCHI:
        raise RegoleNonValide(f"{dove}: rischio deve essere basso, medio o alto")
    corr = r.get("corrispondenza", {})
    if corr is None:
        corr = {}
    if not isinstance(corr, dict):
        raise RegoleNonValide(f"{dove}: corrispondenza deve essere un oggetto")
    estranee = {k for k in corr if k not in CHIAVI_CORR and not k.startswith("_")}
    if estranee:
        raise RegoleNonValide(f"{dove}: corrispondenza con campi sconosciuti {sorted(estranee)} "
                              "(dal 2026-10-03 niente regex: comando_inizia, percorso_glob, url_dominio, segreti)")
    c = {}
    if "segreti" in corr:
        if corr["segreti"] is not True:
            raise RegoleNonValide(f"{dove}: segreti vale solo true")
        if azione == "consenti":
            raise RegoleNonValide(f"{dove}: una regola sui segreti non può consentire")
        c["segreti"] = True
    if "comando_inizia" in corr:
        prefissi = _lista_testi(corr["comando_inizia"], f"{dove}, comando_inizia")
        for p in prefissi:
            try:
                if not shlex.split(p):
                    raise ValueError
            except ValueError:
                raise RegoleNonValide(f"{dove}: comando_inizia «{p}» non si legge come comando") from None
            if azione == "consenti":
                perche = _prefisso_consentibile(p)
                if perche:
                    raise RegoleNonValide(f"{dove}: {perche}")
        c["comando_inizia"] = prefissi
    if "percorso_glob" in corr:
        c["percorso_glob"] = [GlobSicuro(g) for g in _lista_testi(corr["percorso_glob"], f"{dove}, percorso_glob", MAX_GLOB)]
    if "url_dominio" in corr:
        domini = [d.lower() for d in _lista_testi(corr["url_dominio"], f"{dove}, url_dominio", 253)]
        for d in domini:
            if not DOMINIO_RE.fullmatch(d):
                raise RegoleNonValide(f"{dove}: url_dominio «{d}» non valido (esempio.it o *.esempio.it)")
        c["url_dominio"] = domini
    if ("comando_inizia" in c) and not set(strumenti) & {"Bash", "*"}:
        raise RegoleNonValide(f"{dove}: comando_inizia vale solo per Bash")
    if ("url_dominio" in c) and not set(strumenti) <= {"WebFetch"}:
        raise RegoleNonValide(f"{dove}: url_dominio vale solo per WebFetch")
    if azione == "consenti":
        if "*" in strumenti:
            raise RegoleNonValide(f"{dove}: «consenti» su tutti gli strumenti («*») è troppo larga")
        if "Bash" in strumenti and "comando_inizia" not in c:
            raise RegoleNonValide(f"{dove}: «consenti» su Bash richiede comando_inizia")
        if "WebSearch" in strumenti:
            raise RegoleNonValide(f"{dove}: WebSearch non si consente da solo (la ricerca può contenere dati)")
        if "WebFetch" in strumenti and "url_dominio" not in c:
            raise RegoleNonValide(f"{dove}: «consenti» su WebFetch richiede url_dominio")
        scrive = [s for s in strumenti if s in STRUMENTI_SCRIVONO or s.startswith("mcp__")]
        if scrive:
            if "percorso_glob" not in c:
                raise RegoleNonValide(f"{dove}: «consenti» su {', '.join(scrive)} richiede percorso_glob")
            for g in c["percorso_glob"]:
                perche = _glob_scrittura_ok(g)
                if perche:
                    raise RegoleNonValide(f"{dove}: percorso_glob «{g.testo}»: {perche}")
        for g in c.get("percorso_glob", []):
            fisso = g.letterale()
            if fisso in ("/", HOME_S) or classe_ambito(fisso) in ("nega", "segreto") or classe_percorso(fisso) in ("nega", "segreto") \
                    or (classe_percorso(fisso) == "privato" and not set(strumenti) <= LETTURE):
                raise RegoleNonValide(f"{dove}: percorso_glob «{g.testo}» comprende tutta la home, la radice, segreti o "
                                      "cartelle private")
    return {"id": rid, "descrizione": _testo(r.get("descrizione"), f"{dove}, descrizione"),
            "strumento": strumenti, "corr": c, "corrispondenza": corr, "azione": azione, "rischio": rischio,
            "nota": _testo(r.get("nota"), f"{dove}, nota")}


def valida(dati):
    """Lista delle regole pronte. RegoleNonValide con un messaggio chiaro."""
    if not isinstance(dati, dict):
        raise RegoleNonValide("il file deve contenere un oggetto JSON con «regole»")
    estranee = {k for k in dati if k not in ("versione", "regole", "nota") and not k.startswith("_")}
    if estranee:
        raise RegoleNonValide(f"campi sconosciuti {sorted(estranee)}")
    if dati.get("versione", 1) != 1:
        raise RegoleNonValide("versione: questo Command Center conosce solo la 1")
    regole = dati.get("regole")
    if not isinstance(regole, list):
        raise RegoleNonValide("«regole» deve essere una lista")
    if len(regole) > MAX_REGOLE:
        raise RegoleNonValide(f"troppe regole (massimo {MAX_REGOLE})")
    visti = set()
    return [_valida_regola(r, i, visti) for i, r in enumerate(regole)]


def _leggi_e_valida(f, controlla_file=True):
    if controlla_file:
        st = os.lstat(f)
        if stat.S_ISLNK(st.st_mode):
            raise RegoleNonValide("il file delle regole è un collegamento simbolico: non si segue")
        if not stat.S_ISREG(st.st_mode):
            raise RegoleNonValide("il file delle regole non è un file normale")
        if st.st_uid != os.getuid():
            raise RegoleNonValide("il file delle regole non è di questo utente")
        if st.st_mode & 0o022:
            raise RegoleNonValide("il file delle regole è scrivibile da altri utenti (serve 0600)")
    else:
        st = os.stat(f)
    if st.st_size > MAX_BYTE:
        raise RegoleNonValide(f"file troppo grande ({st.st_size} byte, massimo {MAX_BYTE})")
    testo = Path(f).read_text(encoding="utf-8")
    try:
        dati = json.loads(testo)
    except ValueError as e:
        raise RegoleNonValide(f"JSON non valido: {e}") from None
    return valida(dati), testo


# ---------------------------------------------------------------- caricamento

def _scrivi_privato(f, testo):
    f = Path(f)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(testo)
    os.replace(tmp, f)
    os.chmod(f, 0o600)


def _crea_se_manca(f):
    """Crea il file con il predefinito se manca, senza mai sovrascriverne uno esistente (O_EXCL)."""
    if os.path.lexists(f):
        return
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(json.dumps(regole_predefinite(), ensure_ascii=False, indent=2) + "\n")


class Caricate:
    def __init__(self, regole, origine, errore=None):
        self.regole, self.origine, self.errore = regole, origine, errore


def carica(registra_errori=True):
    """Le regole in vigore. Cache sul file (mtime, dimensione, inode, modo): rilette solo se il file cambia."""
    f = file_regole()
    try:
        _crea_se_manca(f)
    except OSError:
        pass
    try:
        st = os.lstat(f)
        firma = (str(f), st.st_mtime_ns, st.st_size, st.st_ino, st.st_mode)
    except OSError:
        firma = (str(f), None)
    with _LOCK:
        if _CACHE["firma"] == firma and _CACHE["caricate"] is not None:
            return _CACHE["caricate"]
    try:
        if firma[1] is None:
            raise RegoleNonValide("il file delle regole non c'è e non si può creare")
        regole, testo = _leggi_e_valida(f)
        c = Caricate(regole, "file")
        try:
            uv = file_ultimo_valido()
            if not uv.exists() or uv.read_text(encoding="utf-8") != testo:
                _scrivi_privato(uv, testo)
        except OSError:
            pass
    except (RegoleNonValide, OSError, UnicodeDecodeError) as e:
        errore = str(e) if isinstance(e, RegoleNonValide) else f"file non leggibile ({type(e).__name__})"
        c = None
        try:
            regole, _ = _leggi_e_valida(file_ultimo_valido())
            c = Caricate(regole, "ultimo valido", errore)
        except (RegoleNonValide, OSError, UnicodeDecodeError):
            c = Caricate(valida(regole_predefinite()), "predefinite", errore)
        if registra_errori:
            _registra_errore_file(errore, firma)
    with _LOCK:
        _CACHE["firma"], _CACHE["caricate"] = firma, c
    return c


def _registra_errore_file(errore, firma):
    """Una riga nel registro per ogni versione rotta del file (non a ogni richiesta)."""
    impronta = hashlib.sha1(repr(firma).encode()).hexdigest()[:16]
    segno = cartella_registro() / "regole-errore-visto"
    try:
        if segno.read_text() == impronta:
            return
    except OSError:
        pass
    registra({"ts": int(time.time()), "tipo": "errore_file", "esito": "fallito", "regola": None,
              "riepilogo": A.pulisci("File delle regole non valido: " + errore, 300),
              "origine": "ultimo valido" if file_ultimo_valido().exists() else "predefinite"})
    try:
        _scrivi_privato(segno, impronta)
    except OSError:
        pass


# ---------------------------------------------------------------- corrispondenza

def _segmenti(cmd):
    """I comandi semplici di una riga composta (per «chiedi»/«nega»: basta che UNO corrisponda)."""
    out = []
    for pezzo in re.split(r"[;&|\n\r]+|\$\(|`|\(|\)", cmd or ""):
        try:
            p = shlex.split(pezzo.strip())
        except ValueError:
            p = pezzo.split()
        while p and re.fullmatch(r"[A-Za-z_]\w*=\S*", p[0]):     # VAR=valore davanti
            p = p[1:]
        if p and p[0] in ("sudo", "command", "exec", "nohup", "time"):
            p = p[1:]
        if p:
            out.append(p)
    return out


def _prefisso(seg, prefisso, cwd):
    try:
        r = [A._norma_token(p, cwd) for p in shlex.split(prefisso)]
    except ValueError:
        return False
    norm = [A._norma_token(p, cwd) for p in seg]
    return bool(r) and norm[:len(r)] == r


def _percorso_assoluto(p, cwd):
    q = _espandi_parola(str(p), cwd)
    if not q:
        return ""
    try:
        return os.path.realpath(q)
    except (OSError, ValueError):
        return q


def corrisponde(regola, strumento, ingresso, cwd=None, classe=None):
    """La regola vale per questa richiesta? (i paletti di «consenti» si controllano in valuta)."""
    if "*" not in regola["strumento"] and strumento not in regola["strumento"]:
        return False
    c = regola["corr"]
    cmd = str(ingresso.get("command") or "") if strumento == "Bash" else None
    if c.get("segreti") and classe not in ("nega", "segreto", "privato"):
        return False
    if "comando_inizia" in c:
        if cmd is None:
            return False
        if regola["azione"] == "consenti":
            if not A.bash_sola_lettura(cmd, cwd, c["comando_inizia"]):
                return False
        elif not any(_prefisso(seg, p, cwd) for seg in _segmenti(cmd) for p in c["comando_inizia"]):
            return False
    if "percorso_glob" in c:
        p = A._percorso_ingresso(ingresso)
        if not p:
            return False
        grezzo = _espandi_parola(str(p), cwd) or ""
        if not any(g.corrisponde(q) for g in c["percorso_glob"] for q in _candidati(grezzo)):
            return False
    if "url_dominio" in c:
        host = url_documentazione(ingresso.get("url"))
        if not host or not dominio_in(host, c["url_dominio"]):
            return False
    return True


LETTURE = {"Read", "Glob", "Grep", "LS", "NotebookRead"}


def _consenti_possibile(strumento, ingresso, cwd, classe, regola=None):
    """I paletti: segreti e cartelle private, Bash composti o strani, scritture protette, URL non sicuri.
    Una cartella «privata» (fuori dalle sicure) si apre solo con una regola di LETTURA con un percorso_glob preciso."""
    if classe == "privato" and regola is not None and strumento in LETTURE and "percorso_glob" in regola["corr"]:
        classe = None
    if classe is not None:
        return False
    if strumento == "Bash" and not git_sicuro(str(ingresso.get("command") or ""), cwd):
        return False
    if strumento == "Bash" and not bash_semplice(str(ingresso.get("command") or "")):
        return False
    if strumento in STRUMENTI_SCRIVONO and scrittura_protetta(_espandi_parola(str(A._percorso_ingresso(ingresso) or ""), cwd)):
        return False
    if strumento == "WebFetch" and not url_documentazione(ingresso.get("url")):
        return False
    if strumento == "WebSearch":
        return False
    return True


# ---------------------------------------------------------------- valutazione

def valuta(strumento, ingresso, cwd=None, caricate=None):
    """{azione, regola, rischio, nota, descrizione, origine, errore_file}. Mai un'eccezione: un errore = chiedi."""
    try:
        ingresso = ingresso if isinstance(ingresso, dict) else {}
        strumento = str(strumento or "")
        c = caricate or carica()
        classe = classe_richiesta(strumento, ingresso, cwd)
        if classe == "nega" and strumento == "Bash":
            try:                      # VPS, «apri ssh» (l'utente, 2026-10-04): chiavi SSH con JARVIS_CONFERMATO=1 e interruttore
                import conformita as _K
                if _K._ssh_con_conferma(str(ingresso.get("command") or ""), cwd):
                    classe = "segreto"
            except Exception:  # noqa: BLE001
                pass
        if classe == "nega":
            return {"azione": "nega", "regola": "segreti-mai", "rischio": "alto",
                    "nota": ("Questo file contiene credenziali che il modello non deve leggere mai (accesso del sito, "
                             "Codex, Gemini, Claude o la history della shell)."),
                    "descrizione": "", "origine": c.origine, "errore_file": c.errore}
        rischio_base = "alto" if classe in ("segreto", "troppo", "privato") else A.rischio(strumento, ingresso, cwd)
        for r in c.regole:
            if r["azione"] == "consenti" and not _consenti_possibile(strumento, ingresso, cwd, classe, r):
                continue
            if corrisponde(r, strumento, ingresso, cwd, classe):
                rischio = "alto" if classe else (r["rischio"] or rischio_base)
                return {"azione": r["azione"], "regola": r["id"], "rischio": rischio, "nota": r["nota"],
                        "descrizione": r["descrizione"], "origine": c.origine, "errore_file": c.errore}
        if classe == "troppo":
            return {"azione": "chiedi", "regola": "troppo-lungo", "rischio": "alto",
                    "nota": f"Comando oltre {MAX_COMANDO} caratteri: non si analizza, si chiede all'utente.", "descrizione": "",
                    "origine": c.origine, "errore_file": c.errore}
        return {"azione": "chiedi", "regola": "segreti" if classe in ("segreto", "privato") else "predefinita",
                "rischio": rischio_base, "nota": "Nessuna regola consente questa richiesta: si chiede all'utente.",
                "descrizione": "", "origine": c.origine, "errore_file": c.errore}
    except Exception as e:  # noqa: BLE001 — mai consentire per errore
        return {"azione": "chiedi", "regola": "predefinita", "rischio": "alto", "nota": f"errore nelle regole: {type(e).__name__}",
                "descrizione": "", "origine": "errore", "errore_file": str(e)[:200]}


def messaggio_nega(d, riepilogo=""):
    """Il testo che Claude riceve per un «nega»: la regola, la sua nota, e di non riprovare."""
    nota = f" {A.pulisci(d.get('nota') or d.get('descrizione') or '', 300)}" if (d.get("nota") or d.get("descrizione")) else ""
    cosa = f" ({riepilogo})" if riepilogo else ""
    return (f"Permesso negato dalla regola «{d.get('regola')}» del file delle regole dell'utente{cosa}.{nota} "
            "Non riprovare la stessa azione e non cercare strade diverse per ottenerla: se serve davvero, chiedi all'utente.")


# gli strumenti che devono SEMPRE passare dal gestore dei permessi (revisione 2, R2): senza «ask» Claude Code
# consente da solo le letture nella cartella di lavoro e nelle additionalDirectories
SEMPRE_DAL_GESTORE = ["Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch"]


def strumenti_da_chiedere(caricate=None):
    """Gli strumenti da mettere nelle regole «ask» di claude: quelli di SEMPRE_DAL_GESTORE e i nomi delle
    regole «chiedi» e «nega» (non «*»)."""
    out = list(SEMPRE_DAL_GESTORE)
    try:
        c = caricate or carica()
        for r in c.regole:
            if r["azione"] in ("chiedi", "nega"):
                out += [s for s in r["strumento"] if s != "*"]
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- registro delle decisioni prese da una regola

def registra(evento):
    """Una riga JSON in registro/regole.jsonl. Non blocca mai: un errore di scrittura si ignora."""
    try:
        f = cartella_registro() / "regole.jsonl"
        try:
            if f.stat().st_size > REGISTRO_MAX_BYTE:
                os.replace(f, f.with_suffix(".jsonl.1"))
        except OSError:
            pass
        riga = (json.dumps(evento, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, riga)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001
        pass


def registra_decisione(d, strumento, ingresso, lavoro_id=None, agente=None):
    """consenti → permesso, nega → rifiutato. Solo testi brevi e senza segreti (niente anteprime)."""
    if d.get("azione") not in ("consenti", "nega"):
        return
    ingresso = ingresso if isinstance(ingresso, dict) else {}
    registra({"ts": int(time.time()), "tipo": "decisione", "esito": "permesso" if d["azione"] == "consenti" else "rifiutato",
              "regola": d.get("regola"), "strumento": str(strumento)[:80], "riepilogo": A.pulisci(A.riepilogo(strumento, ingresso), 160),
              "rischio": d.get("rischio"), "lavoro_id": lavoro_id or None, "agente": str(agente or "Jarvis")[:80],
              "origine": d.get("origine")})


# ---------------------------------------------------------------- per la vista «Regole»

def _corr_pubblica(r):
    return {k: v for k, v in r["corrispondenza"].items() if not k.startswith("_")}


def descrivi():
    """Le regole in vigore, in forma da mostrare (sola lettura)."""
    c = carica()
    return {"regole": [{"id": r["id"], "descrizione": r["descrizione"], "strumento": r["strumento"],
                        "corrispondenza": _corr_pubblica(r), "azione": r["azione"], "rischio": r["rischio"], "nota": r["nota"]}
                       for r in c.regole],
            "origine": c.origine, "errore": c.errore, "file": A.breve_percorso(file_regole()),
            "ultima": "nessuna corrispondenza = chiedi"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--controlla":
        c = carica(registra_errori=False)
        print(f"file: {file_regole()}\norigine: {c.origine}\nregole: {len(c.regole)}")
        if c.errore:
            print(f"ERRORE nel file: {c.errore}")
            sys.exit(1)
    elif len(sys.argv) > 1 and sys.argv[1] == "--rigenera":
        # riscrive il file col predefinito di adesso, tenendo una copia di quello di prima (0600)
        f = file_regole()
        if os.path.lexists(f):
            copia = f.with_name(f.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
            _scrivi_privato(copia, Path(f).read_text(encoding="utf-8", errors="replace"))
            print(f"copia del file di prima: {copia}")
            os.unlink(f)
        _crea_se_manca(f)
        c = carica(registra_errori=False)
        print(f"file riscritto: {f}\norigine: {c.origine}\nregole: {[r['id'] for r in c.regole]}")
        sys.exit(1 if c.errore else 0)
    else:
        print("uso: python3 regole_permessi.py --controlla | --rigenera")
