#!/usr/bin/env python3
"""Le impostazioni di Jarvis che non stanno nel codice: salvate nel repository, senza segreti (l'utente, 2026-10-05).
«Quando lo riscarico deve funzionare così, con colori, impronte, template, impostazioni.»

  python3 strumenti/impostazioni.py salva                 copia le impostazioni in impostazioni/<macchina>/, togliendo i segreti
  python3 strumenti/impostazioni.py salva --commit        come sopra, e se qualcosa è cambiato fa il commit (lo usa il battito)
  python3 strumenti/impostazioni.py ripristina            rimette al suo posto i file che MANCANO
  python3 strumenti/impostazioni.py ripristina --forza    anche quelli che ci sono (copia .prima-ripristino-AAAAMMGG accanto)
  python3 strumenti/impostazioni.py ripristina --prova    dice cosa farebbe, non scrive
  python3 strumenti/impostazioni.py voce-utente salva       impronta e clip della voce dell'utente → VPS /root/backup-voce-utente/
  python3 strumenti/impostazioni.py voce-utente ripristina  dalla VPS al Mac (solo quello che manca, o --forza)
  python3 strumenti/impostazioni.py elenco                cosa viene salvato e dove torna

Opzioni: --macchina NOME (predefinito: mac, windows o linux), --radice DIR (casa finta per le prove: «~» diventa DIR
e la cartella di Jarvis diventa DIR/Jarvis; vale per ripristina e voce-utente ripristina).

Il filtro dei segreti guarda ogni file prima di copiarlo: campi con nome da segreto (key, token, password, secret,
cookie, auth…) e valori che sembrano chiavi (sk-, ghp_, xox…, AIza, JWT, chiavi private, stringhe lunghe casuali).
Il valore trovato diventa "<da .env.jarvis>" e nel resoconto esce solo il NOME del campo, mai il valore.
La voce dell'utente (dati personali) non va mai su GitHub: va sulla VPS. I segreti stanno solo in .env.jarvis.
"""
import argparse
import datetime
import hashlib
import json
import math
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
JARVIS = QUI.parent
CARTELLA = JARVIS / "impostazioni"
SEGNAPOSTO = "<da .env.jarvis>"
VPS = "vps-tuo"
VPS_VOCE = "/root/backup-voce-utente/"

# nome nel repository → (dove sta davvero, cosa prendere). «~» è la casa, «@J» è la cartella di Jarvis.
# Per le cartelle si prende solo quello che corrisponde al modello.
ELENCO = [
    ("voce/backtalk.json", "@J/backtalk/backtalk.json", None),                 # voce: fish, edge, velocità, mani libere
    ("widget/ai-visualizer.json", "@J/ai-visualizer/ai-visualizer.json", None),  # faccia e badge dell'orb
    ("widget/orb_posizione.json", "@J/strumenti/orb_posizione.json", None),     # dove sta l'orb sullo schermo
    ("command-center/aspetto.json", "~/.locale-onedrive/jarvis-cc/aspetto.json", None),  # tema e colori della pagina
    ("command-center/connessioni.json", "~/.locale-onedrive/jarvis-cc/connessioni.json", None),
    ("command-center/regole-permessi.json", "~/.locale-onedrive/jarvis-cc/regole-permessi.json", None),
    ("command-center/menu-barra.json", "~/.locale-onedrive/jarvis-cc/menu-barra.json", None),
    ("command-center/badge", "~/.locale-onedrive/jarvis-cc/badge", "*"),
    ("command-center/piani", "~/.locale-onedrive/jarvis-cc/piani", "*.json"),
    # ganci, agenti e skill di ~/.claude li tiene già strumenti/sincro_claude.py in claude-config/: qui il resto
    ("claude/settings.json", "~/.claude/settings.json", None),
    ("claude/settings.local.json", "~/.claude/settings.local.json", None),
    ("claude/keybindings.json", "~/.claude/keybindings.json", None),
    ("claude/CLAUDE.md", "~/.claude/CLAUDE.md", None),
    ("claude/statusline-command.sh", "~/.claude/statusline-command.sh", None),
    ("ssh/config", "~/.ssh/config", None),                                      # solo i nomi delle macchine, mai le chiavi
]
# file che non si salvano mai, anche se un giorno finissero in una cartella dell'elenco
MAI = re.compile(r"(\.env|\.pem|\.key|id_rsa|id_ed25519|\.p12|\.jks|\.keystore|cookie|credential|token)", re.I)

VOCE_FILE = ["backtalk/impronta-utente.npy", "backtalk/impronta-utente-auto.npz"]
VOCE_CARTELLE = ["backtalk/voce-utente"]

# ───────────────────────────── il filtro dei segreti ─────────────────────────────
PAROLE_SEGRETE = {"key", "apikey", "token", "password", "passwd", "pwd", "pw", "secret", "cookie", "auth",
                  "authorization", "credential", "credentials", "bearer", "session", "scrypt", "totp", "otp"}
VALORI = [
    ("chiave sk-", re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("token GitHub", re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("token Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("chiave Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("chiave AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token bot Telegram", re.compile(r"\b\d{8,11}:[A-Za-z0-9_\-]{30,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}")),
    ("chiave privata", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)")),
    ("password in un indirizzo", re.compile(r"(?<=://)[^/\s:@'\"]+:[^@\s/'\"]+(?=@)")),
]
LUNGA = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![A-Za-z0-9+/_\-])")
INNOCUO = re.compile(r"^[a-z_+\-. ]{0,24}$|^<.*>$|^\$\{.*\}$|^[~/].*|^https?://[^@]*$")


def parti_nome(nome):
    nome = re.sub(r"([a-z])([A-Z])", r"\1_\2", str(nome))
    return {p for p in re.split(r"[^a-zA-Z0-9]+", nome.lower()) if p}


def nome_segreto(nome):
    parti = parti_nome(nome)
    return bool(parti & PAROLE_SEGRETE) or any(p.endswith(("apikey", "token", "password", "secret")) for p in parti)


def entropia(s):
    conta = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in conta.values())


def sembra_casuale(s):
    """Stringa lunga casuale (chiave in base64/esadecimale): lettere e cifre mescolate, tanta entropia."""
    if re.fullmatch(r"[0-9a-f]{32,}", s):          # esadecimale lungo (chiave, hash)
        return True
    if s.count("/") >= 3:                          # un percorso assoluto (/private/tmp/…, /Users/…)
        return False
    pezzi = [p for p in re.split(r"[-_/.]", s) if p]
    # percorsi e parole-legate-da-trattini (Cartella/Nome_FILE_2026-09-30, -Users-tu-Library): pezzi
    # corti fatti di lettere, al più con un blocco di cifre. Una chiave casuale mescola lettere e cifre in ogni pezzo.
    if len(pezzi) >= 3 and all(len(p) < 24 and (re.fullmatch(r"[A-Za-z]*[0-9]*[A-Za-z]*", p)
                                                      or re.fullmatch(r"[0-9a-f]{1,12}", p)) for p in pezzi):
        return False
    return bool(re.search(r"[0-9]", s) and re.search(r"[A-Za-z]", s)) and entropia(s) > 4.2


def pulisci_testo(s, dove, tolti, identificativo=False):
    for nome, rx in VALORI:
        if rx.search(s):
            s = rx.sub(SEGNAPOSTO, s)
            tolti.append(f"{dove} ({nome})")

    def lunga(m):
        if not identificativo and sembra_casuale(m.group(0)):
            tolti.append(f"{dove} (stringa lunga casuale)")
            return SEGNAPOSTO
        return m.group(0)
    return LUNGA.sub(lunga, s)


def pulisci_json(d, dove, tolti, chiave=""):
    if isinstance(d, dict):
        nuovo = {}
        for k, v in d.items():
            qui = f"{dove}.{k}" if dove else str(k)
            if nome_segreto(k) and isinstance(v, str) and v and not INNOCUO.match(v):
                nuovo[k] = SEGNAPOSTO
                tolti.append(qui)
            elif nome_segreto(k) and isinstance(v, (int, float)) and not isinstance(v, bool) and len(str(v)) >= 6:
                nuovo[k] = SEGNAPOSTO
                tolti.append(qui)
            else:
                nuovo[k] = pulisci_json(v, qui, tolti, str(k))
        return nuovo
    if isinstance(d, list):
        return [pulisci_json(v, f"{dove}[{i}]", tolti) for i, v in enumerate(d)]
    if isinstance(d, str):
        # «reference_id», «voice_id», «model_id»: identificativi pubblici (la voce fish), non chiavi. I modelli noti
        # (sk-, ghp_, JWT…) valgono anche qui; salta solo la regola della stringa lunga casuale.
        ident = bool(chiave) and not nome_segreto(chiave) and "id" in parti_nome(chiave)
        return pulisci_testo(d, dove, tolti, ident)
    return d


RIGA_ASSEGNA = re.compile(r"""^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.\-]*)\s*[=:]\s*)(["']?)(.+?)\3\s*$""")
PLIST = re.compile(r"(<key>([^<]+)</key>\s*<string>)([^<]*)(</string>)")


def pulisci_righe(testo, nomefile, tolti):
    def plist(m):
        if nome_segreto(m.group(2)) and m.group(3) and not INNOCUO.match(m.group(3)):
            tolti.append(f"{nomefile}: {m.group(2)}")
            return m.group(1) + SEGNAPOSTO + m.group(4)
        return m.group(0)
    testo = PLIST.sub(plist, testo)
    righe = []
    for n, riga in enumerate(testo.split("\n"), 1):
        m = RIGA_ASSEGNA.match(riga)
        if m and nome_segreto(m.group(2)) and not INNOCUO.match(m.group(4)):
            tolti.append(f"{nomefile}: {m.group(2)} (riga {n})")
            riga = f"{m.group(1)}{m.group(3)}{SEGNAPOSTO}{m.group(3)}"
        righe.append(pulisci_testo(riga, f"{nomefile} riga {n}", tolti))
    return "\n".join(righe)


def valori_env():
    """I valori delle chiavi da segreto di .env.jarvis: ultima rete, se uno di questi compare in un file si toglie."""
    try:
        righe = (Path.home() / ".env.jarvis").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    fuori = []
    for r in righe:
        if "=" in r and not r.lstrip().startswith("#"):
            k, v = r.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("\"'")
            if len(v) >= 8 and nome_segreto(k):
                fuori.append((k, v))
    return sorted(fuori, key=lambda kv: -len(kv[1]))


VALORI_ENV = None


def pulisci_file(sorgente, nome):
    """Contenuto del file senza segreti, e l'elenco dei campi tolti (solo nomi)."""
    contenuto, tolti = pulisci_file_regole(sorgente, nome)
    if contenuto is None:
        return contenuto, tolti
    global VALORI_ENV
    if VALORI_ENV is None:
        VALORI_ENV = valori_env()
    testo = contenuto.decode("utf-8")
    for k, v in VALORI_ENV:
        if v in testo:
            testo = testo.replace(v, SEGNAPOSTO)
            tolti.append(f"{nome}: valore di {k} (da .env.jarvis)")
    return testo.encode("utf-8") if testo.encode("utf-8") != contenuto else contenuto, tolti


def pulisci_file_regole(sorgente, nome):
    tolti = []
    grezzo = sorgente.read_bytes()
    try:
        testo = grezzo.decode("utf-8")
    except UnicodeDecodeError:
        return None, [f"{nome}: file binario, non salvato"]
    if sorgente.suffix == ".json":
        try:
            d = json.loads(testo)
        except ValueError:
            pass
        else:
            pulito = pulisci_json(d, nome, tolti)
            if not tolti:
                return grezzo, []           # identico all'originale: si copia così com'è, byte per byte
            return (json.dumps(pulito, ensure_ascii=False, indent=2) + "\n").encode(), tolti
    pulito = pulisci_righe(testo, nome, tolti)
    return (grezzo if not tolti else pulito.encode()), tolti


# ───────────────────────────────── percorsi ─────────────────────────────────
def macchina_predefinita():
    return {"Darwin": "mac", "Windows": "windows"}.get(platform.system(), "linux")


def vero(percorso, radice=None):
    casa = Path(radice) if radice else Path.home()
    j = (casa / "Jarvis") if radice else JARVIS
    if percorso.startswith("@J/"):
        return j / percorso[3:]
    if percorso.startswith("~/"):
        return casa / percorso[2:]
    return Path(percorso)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def oggi():
    return datetime.datetime.now().strftime("%Y%m%d")


def ora():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ───────────────────────────────── salva ─────────────────────────────────
def salva(a):
    dest = CARTELLA / a.macchina
    dest.mkdir(parents=True, exist_ok=True)
    voci, tutti_tolti, mancanti, nuovi_nomi = [], [], [], set()
    for nome, dove, modello in ELENCO:
        src = vero(dove)
        coppie = []
        if modello is None:
            if src.is_file():
                coppie.append((nome, dove, src))
            else:
                mancanti.append(dove)
        elif src.is_dir():
            for f in sorted(src.glob(modello)):
                if f.is_file() and not f.name.startswith(".") and ".bak" not in f.name and ".prima-" not in f.name:
                    coppie.append((f"{nome}/{f.name}", f"{dove}/{f.name}", f))
            if not coppie:
                voci.append({"nome": nome, "torna_in": dove, "cartella": True})
        else:
            mancanti.append(dove)
        for n, d, f in coppie:
            if MAI.search(f.name):
                tutti_tolti.append(f"{n}: nome da segreto, file non salvato")
                continue
            contenuto, tolti = pulisci_file(f, n)
            tutti_tolti += tolti
            if contenuto is None:
                continue
            fuori = dest / n
            fuori.parent.mkdir(parents=True, exist_ok=True)
            if not fuori.exists() or fuori.read_bytes() != contenuto:
                fuori.write_bytes(contenuto)
            fuori.chmod(0o600 if (f.stat().st_mode & 0o077) == 0 else 0o644)
            nuovi_nomi.add(n)
            voci.append({"nome": n, "torna_in": d, "sha256": hashlib.sha256(contenuto).hexdigest(),
                         "uguale_all_originale": not tolti, "campi_tolti": [t.split(" (")[0] for t in tolti]})
    # i file che non ci sono più alla fonte si tolgono anche dalla copia
    for vecchio in sorted(dest.rglob("*")):
        rel = vecchio.relative_to(dest).as_posix()
        if vecchio.is_file() and rel != "ELENCO.json" and rel not in nuovi_nomi:
            vecchio.unlink()
    elenco = {"_leggimi": "Scritto da strumenti/impostazioni.py salva. Ogni file torna in «torna_in» con "
                          "«impostazioni.py ripristina» (~ = casa, @J = cartella di Jarvis). Niente segreti: i valori "
                          f"tolti sono «{SEGNAPOSTO}» e vanno ripresi da .env.jarvis.",
              "macchina": a.macchina, "file": voci}
    vecchio_elenco = (dest / "ELENCO.json").read_text(encoding="utf-8") if (dest / "ELENCO.json").exists() else ""
    nuovo_elenco = json.dumps(elenco, ensure_ascii=False, indent=2) + "\n"
    if json.loads(vecchio_elenco or "{}").get("file") != voci:
        (dest / "ELENCO.json").write_text(nuovo_elenco, encoding="utf-8")
    print(f"{ora()} salvate {sum(1 for v in voci if 'sha256' in v)} impostazioni in {dest.relative_to(JARVIS)}/")
    for v in voci:
        if "sha256" in v:
            print(f"  {v['nome']:42} ← {v['torna_in']}" + ("" if v["uguale_all_originale"] else "   [segreti tolti]"))
    if mancanti:
        print("non trovati qui (saltati): " + ", ".join(mancanti))
    if tutti_tolti:
        print("FILTRO DEI SEGRETI, valori sostituiti con «%s» (solo i nomi):" % SEGNAPOSTO)
        for t in tutti_tolti:
            print("  -", t)
    else:
        print("filtro dei segreti: niente da togliere")
    if a.commit:
        return commit(dest)
    return 0


def commit(dest):
    rel = str(dest.relative_to(JARVIS))
    st = subprocess.run(["git", "-C", str(JARVIS), "status", "--porcelain", "--", rel], capture_output=True, text=True).stdout
    if not st.strip():
        print("impostazioni: niente di nuovo da committare")
        return 0
    subprocess.run(["git", "-C", str(JARVIS), "add", "-A", "--", rel], check=True)
    gl = shutil.which("gitleaks") or next((p for p in ("/opt/homebrew/bin/gitleaks", "/usr/local/bin/gitleaks") if Path(p).exists()), None)
    if not gl:
        subprocess.run(["git", "-C", str(JARVIS), "reset", "-q", "--", rel])
        print("impostazioni: gitleaks non c'è, NIENTE commit (senza il controllo non si committa)")
        return 1
    g = subprocess.run([gl, "git", str(JARVIS), "--staged", "--no-banner", "--redact"], capture_output=True, text=True)
    if g.returncode:
        subprocess.run(["git", "-C", str(JARVIS), "reset", "-q", "--", rel])
        print("impostazioni: gitleaks ha trovato qualcosa, NIENTE commit\n" + (g.stdout or g.stderr)[-800:])
        return 1
    subprocess.run(["git", "-C", str(JARVIS), "commit", "-q", "-m",
                    f"Impostazioni salvate senza segreti ({ora()})", "--", rel], check=True)
    print("impostazioni: commit fatto")
    return 0


# ─────────────────────────────── ripristina ───────────────────────────────
def ripristina(a):
    sorg = CARTELLA / a.macchina
    el = sorg / "ELENCO.json"
    if not el.exists():
        print(f"non c'è {el.relative_to(JARVIS)}: prima «salva» su una macchina che le ha.", file=sys.stderr)
        return 1
    voci = json.loads(el.read_text(encoding="utf-8"))["file"]
    messi = uguali = tenuti = 0
    segnaposto = []
    for v in voci:
        dest = vero(v["torna_in"], a.radice)
        if v.get("cartella"):
            if not a.prova:
                dest.mkdir(parents=True, exist_ok=True)
            continue
        f = sorg / v["nome"]
        if not f.is_file():
            print(f"  manca nella copia: {v['nome']}")
            continue
        if dest.exists() and dest.read_bytes() == f.read_bytes():
            uguali += 1
            continue
        if dest.exists() and not a.forza:
            tenuti += 1
            print(f"  c'è già, diverso, lo lascio (--forza per sostituirlo): {dest}")
            continue
        azione = "sostituisco" if dest.exists() else "metto"
        print(f"  {azione}: {dest}" + ("  [a secco]" if a.prova else ""))
        if not a.prova:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.copy2(dest, dest.with_name(f"{dest.name}.prima-ripristino-{oggi()}"))
            shutil.copyfile(f, dest)
            dest.chmod(f.stat().st_mode & 0o777)
        messi += 1
        if v.get("campi_tolti"):
            segnaposto.append(f"{v['torna_in']}: " + ", ".join(v["campi_tolti"]))
    print(f"ripristino {'(a secco) ' if a.prova else ''}— messi {messi}, già uguali {uguali}, lasciati {tenuti}")
    if segnaposto:
        print(f"Questi campi contengono «{SEGNAPOSTO}»: rimetti il valore da .env.jarvis:")
        for s in segnaposto:
            print("  -", s)
    return 0


# ─────────────────────────────── voce dell'utente ───────────────────────────────
def rsync(*argomenti):
    cmd = ["rsync", "-a", "--human-readable", "--stats", *argomenti]
    p = subprocess.run(cmd, capture_output=True, text=True)
    righe = [r for r in (p.stdout or "").splitlines() if r.startswith(("Number of regular files transferred", "Total transferred file size"))]
    for r in righe:
        print("   ", r)
    if p.returncode:
        print("    rsync: " + (p.stderr or "").strip()[-400:], file=sys.stderr)
    return p.returncode


def voce(a):
    if a.verso == "salva":
        subprocess.run(["ssh", VPS, f"mkdir -p {VPS_VOCE} && chmod 700 {VPS_VOCE}"], check=True)
        esito = 0
        for f in VOCE_FILE:
            if (JARVIS / f).is_file():
                print(f"→ {f}")
                esito |= rsync(str(JARVIS / f), f"{VPS}:{VPS_VOCE}")
        for c in VOCE_CARTELLE:
            if (JARVIS / c).is_dir():
                print(f"→ {c}/")
                esito |= rsync(str(JARVIS / c) + "/", f"{VPS}:{VPS_VOCE}{Path(c).name}/")
        conto = subprocess.run(["ssh", VPS, f"du -sh {VPS_VOCE}; find {VPS_VOCE} -type f | wc -l"],
                               capture_output=True, text=True).stdout.split()
        print(f"sulla VPS in {VPS_VOCE}: {' '.join(conto)}" if conto else "non riesco a contare sulla VPS")
        return esito
    # ripristina
    base = (Path(a.radice) / "Jarvis") if a.radice else JARVIS
    extra = [] if a.forza else ["--ignore-existing"]
    (base / "backtalk").mkdir(parents=True, exist_ok=True)
    esito = 0
    for f in VOCE_FILE:
        print(f"← {f}")
        p = subprocess.run(["ssh", VPS, f"test -f {VPS_VOCE}{Path(f).name}"])
        if p.returncode == 0:
            esito |= rsync(*extra, f"{VPS}:{VPS_VOCE}{Path(f).name}", str(base / f))
        else:
            print("    non c'è sulla VPS")
    for c in VOCE_CARTELLE:
        print(f"← {c}/")
        esito |= rsync(*extra, f"{VPS}:{VPS_VOCE}{Path(c).name}/", str(base / c) + "/")
    return esito


def elenco(a):
    for nome, dove, modello in ELENCO:
        print(f"  {nome:38} ⇄ {dove}" + (f"  ({modello})" if modello else ""))
    print("  voce dell'utente (solo VPS, mai GitHub): " + ", ".join(VOCE_FILE + [c + "/" for c in VOCE_CARTELLE]))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("comando", choices=["salva", "ripristina", "voce-utente", "elenco"])
    ap.add_argument("verso", nargs="?", choices=["salva", "ripristina"])
    ap.add_argument("--macchina", default=macchina_predefinita())
    ap.add_argument("--radice", help="casa finta per le prove")
    ap.add_argument("--forza", action="store_true")
    ap.add_argument("--prova", action="store_true")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    if a.comando == "voce-utente":
        if not a.verso:
            ap.error("voce-utente vuole «salva» o «ripristina»")
        return voce(a)
    return {"salva": salva, "ripristina": ripristina, "elenco": elenco}[a.comando](a)


if __name__ == "__main__":
    sys.exit(main())
