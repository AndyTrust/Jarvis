"""Gli spazi delle missioni: spazio → progetti → capogruppo ed esperti.

Una sola fonte, spazi.json, letta dal server (per la pagina) e da missione.py
(per costruire i sottoagenti). Qui si espandono i percorsi (OD = la cartella di
OneDrive, ~ = la casa) e si leggono i profili in <progetto>/.claude/agents/*.md:
frontmatter (name, description, model, tools) e corpo.

Scritto il 23/09/2026, quando le missioni sono passate da «un progetto, un
processo per agente» a «uno spazio, un processo, esperti in parallelo dentro».
"""
import json
import re
import sys
from pathlib import Path

QUI = Path(__file__).resolve().parent
import os
FILE = Path(os.environ.get("JARVIS_SPAZI") or QUI / "spazi.json")   # JARVIS_SPAZI: un altro spazi.json (prove)
# 2026-10-10: Jarvis parte da zero. Senza spazi.json non ci sono progetti (niente esempio precaricato):
# li crea strumenti/crea_progetto.py quando il proprietario ne nomina uno.
HOME = Path.home()
# su Windows OneDrive non sta sotto Library/CloudStorage ma in ~/OneDrive (ramo windows, 28/09/2026)
OD = HOME / "OneDrive" if sys.platform == "win32" else HOME / "Library" / "CloudStorage" / "OneDrive"
MODELLI = ("haiku", "sonnet", "opus")


def leggi_testo(f):
    """Legge un file di testo anche se OneDrive lo tiene solo nella nuvola (file «dataless»: lo ha modificato
    l'altro PC e qui non è ancora scaricato). Il Command Center gira sotto launchd e macOS non gli lascia
    scaricare i file di OneDrive («Resource deadlock avoided» / «Operation not permitted»: provato con cat e con
    Python, 29/09/2026), mentre dalla chat sì. Perciò ogni lettura riuscita si copia in una cache locale e,
    quando il file non si apre, si serve l'ultima copia buona invece di far cadere catalogo e lavagna."""
    import hashlib
    import time
    cache = QUI / "cache-profili" / (hashlib.sha1(str(f).encode()).hexdigest()[:16] + ".txt")
    ultimo = None
    for tentativo in range(2):
        try:
            testo = Path(f).read_text(encoding="utf-8")
            try:
                cache.parent.mkdir(exist_ok=True)
                if not cache.exists() or cache.read_text(encoding="utf-8") != testo:
                    cache.write_text(testo, encoding="utf-8")
            except OSError:
                pass
            return testo
        except OSError as e:
            if e.errno not in (1, 11, 35, 60):     # EPERM, EDEADLK, EAGAIN, ETIMEDOUT: file ancora nella nuvola
                raise
            ultimo = e
            if tentativo == 0:
                time.sleep(0.3)
    try:
        return cache.read_text(encoding="utf-8")
    except OSError:
        raise ultimo


def percorso(valore):
    if not valore:
        return None
    v = str(valore)
    if v == "OD" or v.startswith("OD/"):
        return OD / v[3:] if len(v) > 2 else OD
    if v.startswith("~"):
        return HOME / v[2:] if len(v) > 1 else HOME
    return Path(v)


_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
_CHIAVE = re.compile(r"^([\w-]+):(.*)$")
_BLOCCO = ("|", ">", "|-", ">-", "|+", ">+")


def _senza_virgolette(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            return str(json.loads(v))
        except ValueError:
            return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def _voci(blocco):
    """Le voci del frontmatter: [(chiave, prima riga, riga dopo l'ultima, valore)].

    Legge anche i valori su più righe (blocchi | e >, liste «- x», liste [a, b], testo che va
    a capo rientrato): fino al 26/09/2026 si leggeva solo la prima riga e il resto si perdeva."""
    righe = blocco.split("\n")
    voci, i = [], 0
    while i < len(righe):
        m = _CHIAVE.match(righe[i])
        if not m:
            i += 1
            continue
        j, ultima = i + 1, i + 1
        while j < len(righe) and not _CHIAVE.match(righe[j]) and (righe[j][:1] in (" ", "\t") or righe[j].startswith("- ") or righe[j] == "-" or not righe[j].strip()):
            if righe[j].strip():
                ultima = j + 1
            j += 1
        seguito = [r for r in righe[i + 1:ultima]]
        testa = m.group(2).strip()
        if testa in _BLOCCO:
            rientro = min((len(r) - len(r.lstrip()) for r in seguito if r.strip()), default=0)
            pezzi = [r[rientro:].rstrip() for r in seguito]
            valore = ("\n" if testa.startswith("|") else " ").join(pezzi).strip()
        elif not testa and any(r.strip().startswith("- ") or r.strip() == "-" for r in seguito):
            valore = ", ".join(_senza_virgolette(r.strip()[1:]) for r in seguito if r.strip().startswith("-"))
        elif testa.startswith("[") and testa.endswith("]") and not seguito:
            valore = ", ".join(_senza_virgolette(x) for x in testa[1:-1].split(",") if x.strip())
        else:
            valore = _senza_virgolette(" ".join([testa] + [r.strip() for r in seguito if r.strip()]).strip())
        voci.append((m.group(1), i, ultima, valore))
        i = ultima
    return voci


def frontmatter(testo):
    """(campi, corpo) di un profilo .md. «chiave:» senza valore vale stringa vuota."""
    testo = testo.lstrip("﻿")     # Blocco note e PowerShell 5 salvano con il BOM: senza questo l'agente sparisce
    campi, corpo = {}, testo
    m = _FM.match(testo)
    if m:
        for k, _, _, v in _voci(m.group(1)):
            campi[k] = v
        corpo = testo[m.end():]
    return campi, corpo.strip()


def valore_yaml(v):
    """Un valore su una riga sola: semplice se non serve altro, altrimenti fra virgolette JSON
    (che sono YAML valido e tengono anche gli a capo)."""
    v = str(v)
    if re.fullmatch(r"[\w.-]+(?:, ?[\w.-]+)*", v):
        return v
    return json.dumps(v, ensure_ascii=False)


# ---- «Come parli»: serietà e umorismo insieme (l'utente, 29/09/2026)
# Due manopole indipendenti, 0–3, che stanno nel frontmatter (serieta:, umorismo:, tono:) e, perché l'agente le
# senta davvero (missioni e chiamate con lo strumento Agent leggono il corpo del profilo, non il frontmatter),
# in un blocco del corpo che scrive il Command Center. Non si modifica a mano: si cambia dalla scheda dell'agente.
COME_PARLA_INIZIO = "<!-- come-parla:inizio (scritto dal Command Center dalla scheda dell'agente: serietà, umorismo e tono; non modificare a mano) -->"
COME_PARLA_FINE = "<!-- come-parla:fine -->"
SERIETA = ["leggero", "pacato", "professionale", "rigoroso"]
UMORISMO = ["nessuno", "misurato", "vivace", "sfacciato"]
_SERIETA_TESTO = [
    "registro colloquiale, senza formalità: vai al punto come parleresti a un collega",
    "registro pacato: chiaro e cordiale, senza cerimonie",
    "registro professionale: ordinato, con cifre e fonti quando servono",
    "registro rigoroso: numeri, fonti e verifiche prima di tutto, niente approssimazioni, ogni affermazione controllabile",
]
_UMORISMO_TESTO = [
    "nessuna battuta",
    "al massimo una battuta breve e asciutta, solo dove alleggerisce",
    "qualche battuta ironica, ma corta",
    "spesso ironico e brillante",
]


def _num03(v, predefinito):
    try:
        return max(0, min(3, int(str(v).strip())))
    except (TypeError, ValueError):
        return predefinito


def blocco_come_parla(tono, serieta, umorismo):
    s, u = _num03(serieta, 2), _num03(umorismo, 1)
    riga_tono = f"Tono: {tono.strip()}. " if str(tono or "").strip() else ""
    return (f"{COME_PARLA_INIZIO}\n## Come parli\n\n{riga_tono}"
            f"**Serietà {s} su 3 ({SERIETA[s]})**: {_SERIETA_TESTO[s]}. "
            f"**Umorismo {u} su 3 ({UMORISMO[u]})**: {_UMORISMO_TESTO[u]}. "
            "Le due cose stanno insieme, non si escludono: sei serio nel contenuto e, dove ci sta, leggero nel modo. "
            "L'umorismo non prende mai il posto dell'informazione, e non si scherza su soldi, errori, scadenze o dati "
            f"non verificati.\n{COME_PARLA_FINE}")


def con_come_parla(testo):
    """Il profilo con il blocco «Come parli» aggiornato dai campi del suo frontmatter (tono, serieta, umorismo).
    Se non c'è nessuno dei tre campi, il testo resta com'è."""
    m = _FM.match(testo)
    if not m:
        return testo
    campi = {k: v for k, _, _, v in _voci(m.group(1))}
    if not any(k in campi for k in ("tono", "serieta", "umorismo")):
        return testo
    blocco = blocco_come_parla(campi.get("tono", ""), campi.get("serieta"), campi.get("umorismo"))
    testa, corpo = testo[:m.end()], testo[m.end():]
    i, j = corpo.find(COME_PARLA_INIZIO), corpo.find(COME_PARLA_FINE)
    if i != -1 and j != -1 and j > i:
        corpo = corpo[:i] + blocco + corpo[j + len(COME_PARLA_FINE):]
    else:
        corpo = corpo.rstrip("\n") + "\n\n" + blocco + "\n"
    return testa + corpo


def aggiorna_frontmatter(testo, aggiornamenti):
    nuovo, cambiate = _aggiorna_frontmatter(testo, aggiornamenti)
    if any(k in cambiate for k in ("tono", "serieta", "umorismo")):
        nuovo = con_come_parla(nuovo)
    return nuovo, cambiate


def _aggiorna_frontmatter(testo, aggiornamenti):
    """(testo nuovo, chiavi cambiate). Riscrive SOLO le righe delle chiavi il cui valore cambia
    davvero; tutto il resto del file resta byte per byte com'era. None = non toccare la chiave.

    🔴 Prima si ricostruiva tutto il frontmatter da capo: «tools:» vuoto diventava «tools: ""»
    (9 profili nella prova del 26/09/2026) e i valori su più righe andavano persi."""
    richieste = {k: str(v) for k, v in aggiornamenti.items() if v is not None}
    m = _FM.match(testo)
    if not m:
        nuove = [f"{k}: {valore_yaml(v)}" if v != "" else f"{k}:" for k, v in richieste.items() if v != ""]
        if not nuove:
            return testo, []
        return "---\n" + "\n".join(nuove) + "\n---\n\n" + testo.lstrip("\n"), [k.split(":")[0] for k in nuove]
    blocco = m.group(1)
    righe = blocco.split("\n")
    voci = {k: (a, b, v) for k, a, b, v in _voci(blocco)}
    cambi = []                       # (prima riga, riga dopo, righe nuove)
    in_fondo = []
    cambiate = []
    for k, v in richieste.items():
        riga = f"{k}: {valore_yaml(v)}" if v != "" else f"{k}:"
        if k in voci:
            a, b, attuale = voci[k]
            if attuale == v:
                continue
            cambi.append((a, b, [riga]))
        elif v != "":
            in_fondo.append(riga)
        else:
            continue
        cambiate.append(k)
    if not cambiate:
        return testo, []
    for a, b, nuove in sorted(cambi, reverse=True):
        righe[a:b] = nuove
    righe += in_fondo
    inizio, fine = m.span(1)
    return testo[:inizio] + "\n".join(righe) + testo[fine:], cambiate


def separa(testo):
    """(testa, corpo): la testa è il frontmatter così com'è scritto, righe --- comprese."""
    m = _FM.match(testo)
    if not m:
        return "", testo
    return testo[:m.end()], testo[m.end():]


_MARCA_COMUNICA = re.compile(r"<!-- comunica-con:inizio.*?comunica con (.*?)\.\s*\n<!-- comunica-con:fine -->", re.S)


def comunica_di(campi, corpo):
    """Con chi comunica un agente: il frontmatter «comunica» se c'è, se no la sezione «Comunica con» del
    corpo (i profili scritti dalla lavagna prima del 2026-09-26 hanno solo quella)."""
    if campi.get("comunica"):
        return [x.strip() for x in campi["comunica"].split(",") if x.strip()]
    m = _MARCA_COMUNICA.search(corpo or "")
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


_STRUMENTO = re.compile(r"[\w*().:-]+(?:\([^)]*\))?")


def controlla_profilo(testo, nomi_esistenti, con_sezione=True):
    """None se il profilo regge, se no il motivo (2026-09-26 sera: dopo che la catena riscrive un profilo).
    Frontmatter con name, description, model (haiku/sonnet/opus) e tools leggibili; la sezione «Comunica
    con» presente (se con_sezione) e con soli nomi di agenti che esistono."""
    if not _FM.match(testo):
        return "frontmatter mancante o rotto"
    campi, corpo = frontmatter(testo)
    for k in ("name", "description", "model"):
        if not str(campi.get(k) or "").strip():
            return f"manca «{k}» nel frontmatter"
    if campi["model"].strip().lower() not in MODELLI:
        return f"model «{campi['model']}» non valido"
    if "tools" not in campi and not re.search(r"^tools:", _FM.match(testo).group(1), re.M):
        return "manca «tools» nel frontmatter"
    strani = [t for t in (campi.get("tools") or "").split(",") if t.strip() and not _STRUMENTO.fullmatch(t.strip())]
    if strani:
        return f"tools non validi: {', '.join(strani)[:80]}"
    if con_sezione and not re.search(r"^## Comunica con", corpo, re.M):
        return "manca la sezione «Comunica con»"
    ignoti = [n for n in comunica_di({}, corpo) + comunica_di(campi, "") if n not in nomi_esistenti]
    if ignoti:
        return f"«Comunica con» nomina agenti che non esistono: {', '.join(sorted(set(ignoti)))[:120]}"
    return None


def _vero(v, default=True):
    v = str(v if v is not None else "").strip().lower()
    if v in ("false", "no", "0", "off"):
        return False
    if v in ("true", "si", "sì", "yes", "1", "on"):
        return True
    return default


def profili(cartella, capogruppo=None):
    """Gli agenti di un progetto, capogruppo in cima. Ognuno: nome, descrizione,
    modello, strumenti, file, capogruppo (bool), e dal 2026-09-26 sera tono, umorismo (0–3 o None),
    attivo (default vero), comunica (lista di nomi), aggiornato_ts (mtime del file).
    Solo *.md diretti: .claude/agents/_archivio/ (gli agenti tolti dalla lavagna) resta fuori."""
    d = Path(cartella) / ".claude" / "agents"
    out = []
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            campi, corpo = frontmatter(leggi_testo(f))
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if not campi.get("description"):
            continue            # LEGGIMI e simili: non sono agenti
        nome = campi.get("name") or f.stem
        modello = (campi.get("model") or "").lower()
        strumenti = [t.strip() for t in (campi.get("tools") or "").split(",") if t.strip()]
        try:
            umorismo = max(0, min(3, int(campi.get("umorismo"))))
        except (TypeError, ValueError):
            umorismo = None
        try:
            serieta = max(0, min(3, int(campi.get("serieta"))))
        except (TypeError, ValueError):
            serieta = None
        out.append({"nome": nome, "descrizione": campi["description"],
                    "modello": modello if modello in MODELLI else "sonnet",
                    "strumenti": strumenti, "file": str(f),
                    "capogruppo": nome == capogruppo,
                    "tono": campi.get("tono") or "", "umorismo": umorismo, "serieta": serieta,
                    "attivo": _vero(campi.get("attivo")), "comunica": comunica_di(campi, corpo),
                    "riporta_a": campi.get("riporta_a") or "", "aggiornato_ts": mtime})
    # riporta_a (2026-09-26, livelli della lavagna): dal frontmatter; se manca, il primo agente del progetto
    # nominato in «Comunica con». Il capogruppo non riporta a nessuno del progetto.
    nomi = {a["nome"] for a in out}
    for a in out:
        if not a["riporta_a"] and not a["capogruppo"]:
            a["riporta_a"] = next((n for n in a["comunica"] if n in nomi and n != a["nome"]), "")
    out.sort(key=lambda a: (not a["capogruppo"], a["nome"]))
    return out


def corpo_profilo(file):
    return frontmatter(Path(file).read_text(encoding="utf-8"))[1]


def salva(dati):
    """Riscrive spazi.json (stesso formato: indent 2, a capo finale), atomico."""
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".spazi.json.", suffix=".tmp", dir=str(FILE.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(dati, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, FILE)


def carica():
    """Gli spazi con i percorsi espansi e, per ogni progetto, se la cartella c'è."""
    f = FILE
    if not f.exists():
        return []
    dati = json.loads(f.read_text(encoding="utf-8"))
    spazi = []
    for s in dati.get("spazi", []):
        progetti = []
        for p in s.get("progetti", []):
            cartella = percorso(p["cartella"])
            progetti.append({**p, "cartella": str(cartella), "esiste": bool(cartella and cartella.is_dir())})
        spazi.append({**s, "memoria": str(percorso(s.get("memoria"))),
                      "report": str(percorso(s.get("report"))), "progetti": progetti})
    return spazi


def trova(spazio_id, progetti_id):
    """(spazio, [progetti scelti]) o ValueError con il motivo in italiano."""
    s = next((x for x in carica() if x["id"] == spazio_id), None)
    if not s:
        raise ValueError("Spazio sconosciuto")
    scelti = [p for p in s["progetti"] if p["id"] in set(progetti_id or [])]
    if not scelti:
        raise ValueError("Scegli almeno un progetto dello spazio")
    manca = [p["nome"] for p in scelti if not p["esiste"]]
    if manca:
        raise ValueError("Cartella non trovata: " + ", ".join(manca))
    return s, scelti
