#!/usr/bin/env python3
"""Costruisce la memoria a grafo delle regole dell'utente per il ponte jarvis-agent.

2026-10-07, agente memoria-grafo, su richiesta dell'utente: «deve usare una memoria interna a grafo
per essere più veloce nelle scelte e deve chiedere direttamente senza leggere tutto il contesto».

Le FONTI restano l'unica verità e non si toccano mai (si leggono soltanto):
  - /root/jarvis/memoria/utente-regole.md          regole e decisioni dell'utente sulla VPS
  - /root/.claude/CLAUDE.md                        istruzioni di Jarvis sulla VPS (senza la riga @import)
  - <vault>/Memoria/00 Comune/Regole di lavoro/*.md  le regole che non decadono (una per file)
Il grafo si RIGENERA da zero a ogni lancio: niente doppioni, niente modifiche a mano.

Uscita (fuori da git, accanto alla fonte): /root/jarvis/memoria/grafo/grafo.json
  nodi:  una regola o decisione per nodo (un punto elenco o un paragrafo), con id, tipo, sezione,
         titolo, data, motivo, categorie, parole chiave, testo, fonte e righe.
         Ogni titolo «## …» è un nodo «sezione»; ogni categoria è un nodo «tema».
  archi: parte_di (nodo → sezione), vale_per (nodo → tema), stesso_tema (parole chiave in comune),
         dipende_da (usa uno script/file introdotto da una regola più vecchia),
         corregge (la sezione dice «CORREGGE/correzione alla nota delle HH:MM»: vale la più nuova).
Perché JSON e non SQLite: il ponte gira su Node 20 (senza sqlite incorporato) e il grafo ha poche
centinaia di nodi: in memoria la ricerca sta sotto il millisecondo, senza dipendenze native.
La ricerca la fa server/memoria.js del ponte (strumenti MCP memoria_cerca/apri/vicini).

Uso:
  python3 costruisci_grafo_regole.py                 # rigenera il grafo
  python3 costruisci_grafo_regole.py controlla       # prova che ogni riga delle fonti sta in un nodo
  python3 costruisci_grafo_regole.py stat            # numeri del grafo
Opzioni: --uscita DIR, --regole FILE, --claude-md FILE, --regole-lavoro DIR (vuoto = salta).
Quando l'utente salva una regola nuova in utente-regole.md il ponte se ne accorge (data del file) e
rilancia questo script da solo; a mano basta lanciarlo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REGOLE = "/root/jarvis/memoria/utente-regole.md"
CLAUDE_MD = "/root/.claude/CLAUDE.md"
REGOLE_LAVORO = "/root/Library/CloudStorage/OneDrive/Jarvis Brain/Memoria/00 Comune/Regole di lavoro"
USCITA = "/root/jarvis/memoria/grafo"

STOP = set("""
a ad al alla alle allo ai agli all anche ancora che chi ci con come cosa cui da dal dalla dalle dai dagli
del della delle dei degli dell di dice dopo e ed era fa fare fatto fra già gli ha hanno ho i il in io la le
lei li lo lui ma mai me mi ne nei nel nella nelle negli nell no non o ogni oggi per perché più poi qua qui
quando quanto quella quelle quello quelli questa queste questo questi se sei si sia sono sta stai stanno
su sua sue sui sul sulla sulle suo suoi te ti tra tu tutto tutti tutta tutte un una uno va vanno vale
viene vuole essere stato stata stati state solo sempre prima tutto cosi così fino senza sotto sopra dove
utente jarvis 2026 the and for from with not this that alle dalle nelle sulle dello degli delle
""".split())

CATEGORIE = {
    "posta": ["posta", "mail", "casell", "smist", "spazzatur", "cestin", "postino", "imap", "pec", "gmail",
              "rumore", "corrispondent", "inviat", "junk", "spam"],
    "patrimonio": ["revolut", "patrimoni", "portafogli", "azion", "progetto-b", "trading", "forex", "mt4",
                   "liquidit", "borsa", "dollar", "hedge", "titol", "investiment", "salvadanai", "estratt"],
    "instinct": ["instinct"],
    "telefono": ["telefon", "android", "jarvis-agent", "invia_bozza", "whatsapp", "apk", "ponte"],
    "segreti": ["segret", "password", "env.jarvis", "credenzial", "chiav", "token", ".env"],
    "vps": ["vps", "contenitor", "docker", "systemctl", "timer", "caddy", "ufw", "servizi", "cron"],
    "github": ["github", "push", "commit", "repo", "deploy", "git"],
    "report": ["report", "pdf", "resocont", "riunion", "notific", "rapport"],
    "memoria-agenti": ["memori", "vault", "quadern", "agent", "regol", "obsidian"],
    "sito": ["sito", "command center", "jarvis-cc", "cc-ponte", "schermo", "desktop", "terminal", "lavagna"],
    "browser": ["browser", "chrome", "cloudflare", "robot", "cdp"],
    "mac": ["ssh mac", "applescript", "osascript", "sul mac", "del mac", "il mac"],
    "ordini-prenotazioni": ["deliveroo", "mcdonald", "prenotazion", "pienissimo", "ordine di cibo"],
    "lingua-voce": ["italiano", "voce", "pronunc", "parla", "scriv", "frase", "tono"],
    "sicurezza": ["guardia", "irreversibil", "conferm", "distruttiv", "jarvis_confermato", "cancell",
                  "elimin", "bloccat", "permess"],
    "crm-1": ["Azienda Uno", "db1", "odoo", "crm", "direzione"],
}

RX_TITOLO_DATA = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}|sera|mattina|pomeriggio|notte))?\s*:\s*(.*)$")
RX_DATA = re.compile(r"\b(20\d\d-\d\d-\d\d)\b|\b(\d\d)/(\d\d)/(20\d\d)\b")
RX_CITAZIONE = re.compile(r"«([^»]{6,400})»")
RX_CORREGGE = re.compile(r"(?:corregge|correzione alla nota|correzione)\b[^.\n]{0,40}?delle\s+(\d{1,2}:\d{2})", re.I)
RX_RIF = re.compile(r"`([^`\s]*?(?:[\w-]+\.(?:py|sh|mjs|js|json|md|service|timer|conf)|/[\w./-]+))`|"
                    r"\b([\w-]+\.(?:py|sh|mjs))\b")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


SUFFISSI = ("azione", "azioni", "zione", "zioni", "mente", "mento", "menti", "ando", "endo",
            "are", "ere", "ire", "ato", "ata", "ati", "ate", "ito", "ita", "iti", "ite", "uto", "uta",
            "uti", "ute", "ano", "ono", "erà", "ira")


def radice(t: str) -> str:
    """Radice italiana leggera: la STESSA regola sta in server/memoria.js (funzione radice)."""
    if len(t) < 4 or not t.isalpha():
        return t
    if len(t) == 4:  # «giro» e «gira» → «gir»
        return t[:-1] if t[-1] in "aeiou" else t
    for s in SUFFISSI:
        if t.endswith(s) and len(t) - len(s) >= 4:
            t = t[: -len(s)]
            break
    if len(t) > 4 and t[-1] in "aeiou":
        t = t[:-1]
    return t


def parole_di(testo: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9_][a-z0-9_.\-]*[a-z0-9_]|[a-z0-9]", norm(testo)):
        if t in STOP or len(t) < 3 or t.isdigit():
            continue
        out.append(radice(t))
    return out


def slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")
    return s[:n].strip("-") or "x"


def categorie_di(testo: str) -> list[str]:
    t = " " + norm(testo) + " "
    punti = {c: sum(t.count(k) for k in chiavi) for c, chiavi in CATEGORIE.items()}
    ordinate = sorted((p, c) for c, p in punti.items() if p > 0)
    ordinate.reverse()
    if not ordinate:
        return ["generale"]
    primo = ordinate[0][0]
    return [c for p, c in ordinate if p >= max(2, primo * 0.5)][:3] or [ordinate[0][1]]


def tipo_di(testo: str) -> str:
    t = norm(testo)
    if re.search(r"\b(errore|svista|era sbagliata|errore da non ripetere)\b", t):
        return "errore"
    if "trappola" in t:
        return "trappola"
    if re.match(r"^\s*[-*]\s+\*\*", testo) or "regola madre" in t:
        return "regola"
    if re.search(r"\b(mai|sempre|non si|si fa|vale per|regola|restano chius|resta |solo con|niente)\b", t):
        return "regola"
    if re.search(r"^\s*[-*]?\s*(\*\*)?fatto\b|\bfatto:", t):
        return "fatto"
    return "nota"


def motivo_di(testo: str, titolo_sezione: str) -> str:
    for fonte in (testo, titolo_sezione):
        m = RX_CITAZIONE.search(fonte)
        if m:
            return m.group(1).strip()[:240]
    m = re.search(r"\b(?:Causa|Perché|perché|Motivo)\s*:?\s*([^.\n]{10,200})", testo)
    return m.group(1).strip() if m else ""


def data_di(testo: str) -> str:
    m = RX_DATA.search(testo)
    if not m:
        return ""
    if m.group(1):
        return m.group(1)
    return f"{m.group(4)}-{m.group(3)}-{m.group(2)}"


def titolo_breve(testo: str) -> str:
    t = re.sub(r"^\s*[-*]\s+", "", testo.strip().split("\n")[0])
    m = re.match(r"\*\*(.+?)\*\*", t)
    if m:
        return m.group(1).strip(" .:")[:120]
    t = re.sub(r"[*`]", "", t)
    frase = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    return frase[:120].rstrip(" ,;:")


# ───────────────────────────── lettura delle fonti ─────────────────────────────

def blocchi(righe: list[str], inizio: int = 0):
    """Divide le righe (dopo un titolo) in blocchi: un punto elenco di primo livello con le sue
    righe di seguito, oppure un paragrafo. Restituisce [(prima_riga, ultima_riga)] 1-based."""
    out, cur = [], None
    for i in range(inizio, len(righe)):
        r = righe[i]
        n = i + 1
        if not r.strip():
            if cur:
                out.append(cur)
                cur = None
            continue
        nuovo_punto = re.match(r"^[-*]\s+|^\d+\.\s+", r) is not None
        if cur is None or nuovo_punto:
            if cur:
                out.append(cur)
            cur = [n, n]
        else:
            cur[1] = n
    if cur:
        out.append(cur)
    return out


def leggi_markdown(percorso: Path, sigla: str, salta=None, titolo_file: str | None = None):
    """Sezioni e nodi di un file markdown. salta(riga) → True per le righe da non indicizzare
    (es. l'@import di CLAUDE.md): contano comunque come «coperte» dal nodo della sezione.
    titolo_file (le «Regole di lavoro», una regola per file): il file è UNA sezione, i suoi
    sottotitoli («## Perché», «## Come si applica») restano dentro e il «Perché» diventa il motivo."""
    righe = percorso.read_text(encoding="utf-8").split("\n")
    nodi = []
    # frontmatter
    corpo_da = 0
    if righe and righe[0].strip() == "---":
        for j in range(1, len(righe)):
            if righe[j].strip() == "---":
                corpo_da = j + 1
                break
    # sezioni: i titoli ## (e il # iniziale come sezione di testa)
    rx_tit = r"^#\s" if titolo_file else r"^#{1,3}\s"
    titoli = [i for i in range(corpo_da, len(righe)) if re.match(rx_tit, righe[i])]
    if not titoli or any(righe[i].strip() for i in range(corpo_da, titoli[0])):
        titoli = [None] + titoli
    usati = set()
    for k, t in enumerate(titoli):
        fine = (titoli[k + 1] if k + 1 < len(titoli) else len(righe))
        if t is None:
            testo_tit = titolo_file or percorso.stem
            ini = corpo_da
            righe_sez = (1, corpo_da) if corpo_da else ()
        else:
            testo_tit = re.sub(r"^#+\s*", "", righe[t]).strip()
            ini = t + 1
            righe_sez = (t + 1, t + 1)
            if k == 0 and corpo_da:
                righe_sez = (1, t + 1)  # il frontmatter appartiene alla prima sezione
        m = RX_TITOLO_DATA.match(testo_tit)
        if m:
            data = m.group(1) + (" " + m.group(2) if m.group(2) else "")
            titolo = m.group(3).strip() or testo_tit
        else:
            data = data_di(testo_tit) or ""
            titolo = testo_tit
        base = f"{sigla}-" + (re.sub(r"[^0-9]", "", data)[:12] + "-" if data[:4].isdigit() else "") + slug(titolo, 28)
        if base in usati:  # stesso titolo e stessa data due volte
            base = f"{base}~{k}"
        usati.add(base)
        sez = {
            "id": base, "tipo": "sezione", "sezione": base, "titolo": titolo, "data": data,
            "testo": "\n".join(righe[righe_sez[0] - 1:righe_sez[1]]) if righe_sez else testo_tit,
            "fonte": str(percorso), "righe": list(righe_sez),
        }
        nodi.append(sez)
        figli = []
        sotto, perche = "", []
        for (a, b) in blocchi(righe[:fine], ini):
            testo = "\n".join(righe[a - 1:b])
            if a == b and re.match(r"^#{2,6}\s", righe[a - 1]):  # sottotitolo dentro la sezione
                sotto = re.sub(r"^#+\s*", "", righe[a - 1]).strip()
                sez["righe_extra"] = sez.get("righe_extra", []) + [[a, b]]
                sez.setdefault("testo_extra", []).append(testo)
                continue
            if norm(sotto) == "perche":
                perche.append(testo)
            if salta and all(salta(x) for x in righe[a - 1:b] if x.strip()):
                sez["righe_extra"] = sez.get("righe_extra", []) + [[a, b]]
                sez.setdefault("testo_extra", []).append(testo)
                continue
            figli.append({
                "id": f"{base}-{len(figli) + 1}", "tipo": tipo_di(testo), "sezione": base,
                "titolo": titolo_breve(testo), "data": data_di(testo) if not data else data,
                "testo": testo, "fonte": str(percorso), "righe": [a, b],
                **({"sotto": sotto} if sotto else {}),
            })
        # data e motivo: dal titolo della sezione se il punto non li ha
        for f in figli:
            f["motivo"] = motivo_di(f["testo"], testo_tit) or " ".join(perche).strip()[:240]
        sez["motivo"] = motivo_di(testo_tit, "") or (figli[0]["motivo"] if figli else "")
        if not sez["data"] and figli:
            sez["data"] = next((f["data"] for f in figli if f["data"]), "")
            for f in figli:
                f["data"] = f["data"] or sez["data"]
        nodi.extend(figli)
    return nodi, righe


def fonti_predefinite(args) -> list[tuple[Path, str, object, str | None]]:
    fonti = [(Path(args.regole), "R", None, None)]
    if args.claude_md and Path(args.claude_md).exists():
        fonti.append((Path(args.claude_md), "C", lambda r: r.strip().startswith("Le regole e le decisioni dell'utente su questa macchina stanno in un file") or "@/root/jarvis/memoria/utente-regole.md" in r, None))
    if args.regole_lavoro and Path(args.regole_lavoro).is_dir():
        for p in sorted(Path(args.regole_lavoro).glob("*.md")):
            fonti.append((p, "L-" + slug(p.stem, 24), None, p.stem))
    return fonti


# ───────────────────────────── archi ─────────────────────────────

def costruisci(args) -> dict:
    t0 = time.time()
    nodi, info_fonti = [], []
    for percorso, sigla, salta, tit in fonti_predefinite(args):
        n, righe = leggi_markdown(percorso, sigla, salta, tit)
        nodi.extend(n)
        st = percorso.stat()
        info_fonti.append({"percorso": str(percorso), "righe": len(righe), "mtime": st.st_mtime,
                           "sha1": hashlib.sha1(percorso.read_bytes()).hexdigest()})
    doppi = [k for k, v in Counter(n["id"] for n in nodi).items() if v > 1]
    if doppi:
        raise SystemExit(f"id doppi nel grafo: {doppi[:5]}")

    per_id = {n["id"]: n for n in nodi}
    sezioni = {n["id"]: n for n in nodi if n["tipo"] == "sezione"}
    titolo_sez = {k: v["testo"] for k, v in sezioni.items()}
    for n in nodi:
        contesto = n["testo"] + "\n" + titolo_sez.get(n["sezione"], "")
        n["categorie"] = categorie_di(contesto)
        conta = Counter(parole_di(n["testo"]))
        n["parole"] = [p for p, _ in conta.most_common(14)]

    archi = []

    def arco(da, a, tipo, peso=1.0):
        if da != a:
            archi.append({"da": da, "a": a, "tipo": tipo, "peso": round(peso, 3)})

    # temi (nodi hub)
    temi = sorted({c for n in nodi for c in n["categorie"]})
    for c in temi:
        nodo_tema = {"id": f"T-{c}", "tipo": "tema", "sezione": f"T-{c}", "titolo": f"Tema: {c}",
                     "data": "", "testo": f"Tema {c}", "fonte": "", "righe": [], "categorie": [c],
                     "parole": [radice(c)], "motivo": ""}
        nodi.append(nodo_tema)
    figli = [n for n in nodi if n["tipo"] not in ("sezione", "tema")]
    for n in figli:
        arco(n["id"], n["sezione"], "parte_di")
        for c in n["categorie"]:
            arco(n["id"], f"T-{c}", "vale_per", 0.5)
    for s in sezioni.values():
        for c in categorie_di(s["testo"] + " " + " ".join(f["testo"] for f in figli if f["sezione"] == s["id"])):
            arco(s["id"], f"T-{c}", "vale_per", 0.5)
        s["categorie"] = categorie_di(s["testo"] + " " + " ".join(f["testo"] for f in figli if f["sezione"] == s["id"]))
        s["parole"] = [p for p, _ in Counter(parole_di(s["testo"])).most_common(10)]

    # corregge: «CORREGGE la nota delle 16:57», «correzione alla nota delle 13:45»
    ordine_sez = [s for s in nodi if s["tipo"] == "sezione" and s["fonte"] == str(Path(args.regole))]
    for i, s in enumerate(ordine_sez):
        testo = s["testo"] + " " + " ".join(f["testo"] for f in figli if f["sezione"] == s["id"])
        for m in RX_CORREGGE.finditer(testo):
            ora = m.group(1).zfill(5)
            giorno = s["data"][:10]
            cand = [x for x in ordine_sez[:i] if x["data"][:10] == giorno and x["data"][11:16] == ora]
            if not cand:
                cand = [x for x in ordine_sez[:i] if x["data"][11:16] == ora]
            if cand:
                arco(s["id"], cand[-1]["id"], "corregge", 2.0)

    # dipende_da: lo stesso script/file nominato in una regola più vecchia
    primo_che_nomina = {}
    for n in figli:
        rif = set()
        for m in RX_RIF.finditer(n["testo"]):
            r = (m.group(1) or m.group(2) or "").strip()
            nome = r.rstrip("/").split("/")[-1]
            if len(nome) >= 6 and "." in nome:
                rif.add(nome)
        n["riferimenti"] = sorted(rif)
        legati = 0
        for r in sorted(rif):
            p = primo_che_nomina.get(r)
            if p is None:
                primo_che_nomina[r] = n["id"]
            elif per_id[p]["sezione"] != n["sezione"] and legati < 3:
                arco(n["id"], p, "dipende_da", 1.0)
                legati += 1

    # stesso_tema: parole chiave in comune (Jaccard) e una categoria in comune, al massimo 3 per nodo
    insiemi = {n["id"]: set(n["parole"]) for n in figli}
    for n in figli:
        cand = []
        A = insiemi[n["id"]]
        if not A:
            continue
        for m in figli:
            if m["id"] == n["id"] or m["sezione"] == n["sezione"]:
                continue
            if not set(n["categorie"]) & set(m["categorie"]):
                continue
            B = insiemi[m["id"]]
            j = len(A & B) / max(1, len(A | B))
            if j >= 0.16:
                cand.append((j, m["id"]))
        for j, mid in sorted(cand, reverse=True)[:3]:
            if not any(a["tipo"] == "stesso_tema" and {a["da"], a["a"]} == {n["id"], mid} for a in archi):
                arco(n["id"], mid, "stesso_tema", j)

    conta_tipi = Counter(n["tipo"] for n in nodi)
    conta_archi = Counter(a["tipo"] for a in archi)
    return {
        "versione": 1,
        "generato": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "generato_epoch": time.time(),
        "costruttore": str(Path(__file__).resolve()),
        "fonti": info_fonti,
        "cartella_regole_lavoro": args.regole_lavoro or "",
        "statistiche": {"nodi": len(nodi), "archi": len(archi), "tipi_nodo": dict(conta_tipi),
                        "tipi_arco": dict(conta_archi), "secondi": round(time.time() - t0, 3)},
        "nodi": nodi,
        "archi": archi,
    }


def scrivi(grafo: dict, uscita: str) -> Path:
    d = Path(uscita)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".grafo-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(grafo, f, ensure_ascii=False, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    dest = d / "grafo.json"
    os.replace(tmp, dest)  # atomico: il ponte non legge mai un file a metà
    return dest


def controlla(grafo: dict) -> int:
    """Ogni riga non vuota di ogni fonte deve stare dentro le righe di almeno un nodo,
    e il suo testo deve comparire nel testo di quel nodo (nessuna regola persa)."""
    coperte = defaultdict(set)
    testi = defaultdict(list)
    for n in grafo["nodi"]:
        if not n.get("fonte"):
            continue
        intervalli = [n["righe"]] + n.get("righe_extra", [])
        for a, b in [x for x in intervalli if x]:
            for r in range(a, b + 1):
                coperte[n["fonte"]].add(r)
        testi[n["fonte"]].append(n["testo"] + "\n" + "\n".join(n.get("testo_extra", [])))
    perse, totale = [], 0
    for f in grafo["fonti"]:
        righe = Path(f["percorso"]).read_text(encoding="utf-8").split("\n")
        tutto = "\n".join(testi[f["percorso"]])
        for i, r in enumerate(righe, 1):
            if not r.strip():
                continue
            totale += 1
            dentro = i in coperte[f["percorso"]]
            nel_testo = r.strip() in tutto or r.strip() in ("---",)
            if not (dentro and nel_testo):
                perse.append((f["percorso"], i, r[:100]))
        sha = hashlib.sha1(Path(f["percorso"]).read_bytes()).hexdigest()
        if sha != f["sha1"]:
            print(f"ATTENZIONE: {f['percorso']} è cambiato dopo la costruzione: rilancia lo script.")
    print(f"Righe non vuote nelle fonti: {totale}; righe senza nodo: {len(perse)}; "
          f"fonti: {len(grafo['fonti'])}; nodi: {grafo['statistiche']['nodi']}; archi: {grafo['statistiche']['archi']}")
    for p, i, r in perse[:30]:
        print(f"  PERSA {p}:{i}: {r}")
    return 1 if perse else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("azione", nargs="?", default="costruisci", choices=["costruisci", "controlla", "stat"])
    ap.add_argument("--uscita", default=USCITA)
    ap.add_argument("--regole", default=REGOLE)
    ap.add_argument("--claude-md", default=CLAUDE_MD)
    ap.add_argument("--regole-lavoro", default=REGOLE_LAVORO)
    args = ap.parse_args()
    if args.azione == "costruisci":
        g = costruisci(args)
        dest = scrivi(g, args.uscita)
        s = g["statistiche"]
        print(f"Grafo scritto in {dest}: {s['nodi']} nodi, {s['archi']} archi, {s['secondi']} s")
        print("  nodi:", s["tipi_nodo"])
        print("  archi:", s["tipi_arco"])
        return controlla(g)
    g = json.loads((Path(args.uscita) / "grafo.json").read_text(encoding="utf-8"))
    if args.azione == "controlla":
        return controlla(g)
    print(json.dumps(g["statistiche"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
