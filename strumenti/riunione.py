#!/usr/bin/env python3
"""La riunione giornaliera degli agenti, uguale per ogni gruppo di Jarvis.

Creato il 2026-09-30. Una riunione uguale per ogni gruppo: numeri e controlli li fa lo script, il giudizio gli agenti,
il report e il registro di nuovo lo script.

    dati ─► posizioni degli specialisti ─► controlli meccanici + revisore
         ─► verdetto del capogruppo (riunione.json) ─► un report per l'utente ─► registro strategie

Lo script NON lancia agenti. `prepara` scrive i compiti già pronti; li lancia solo la chat
master, nell'ordine scritto in LEGGIMI.md della cartella del giorno. I gruppi nascono da soli dai progetti
di command-center/spazi.json (ogni progetto con capogruppo è un gruppo: capogruppo, specialisti, Stato.md, indice
dei file); strumenti/riunione_gruppi.json serve solo a ritoccarli o ad aggiungere gruppi a mano. Nessun progetto =
nessun gruppo, senza errori.

Uso:
    python3 strumenti/riunione.py elenco
    python3 strumenti/riunione.py <gruppo> prepara [--data AAAA-MM-GG]
    python3 strumenti/riunione.py <gruppo> chiudi  [--data AAAA-MM-GG]
    python3 strumenti/riunione.py <gruppo> stato   [--data AAAA-MM-GG]
    python3 strumenti/riunione.py <gruppo> strategie
    python3 strumenti/riunione.py <gruppo> chiudi-previsione <id> <n> <realizzato> [--fonte "..."]

<n> è il numero della previsione nella scheda, da 1 (lo stampa `strategie`).
Idempotente: se riunione.json c'è già, `prepara` non rifà niente; se il report è più
recente di riunione.json, `chiudi` non riscrive.

Variabili per le prove (così non si scrive in produzione):
    RIUNIONE_RADICE        cartella delle riunioni (predefinita ~/Jarvis/riunioni)
    RIUNIONE_REPORT_DIR    dove scrivere il report al posto di Memoria/<spazio>/Report
    RIUNIONE_STRATEGIE_DIR dove stanno le schede al posto di Memoria/<spazio>/Strategie
    RIUNIONE_CONFIG        un altro file di configurazione
    RIUNIONE_OGGI          data finta AAAA-MM-GG
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
import backtest_check  # noqa: E402

OD = Path.home() / "Library" / "CloudStorage" / "OneDrive"

STATI = ("ipotesi", "prova", "demo", "attiva", "sospesa", "abbandonata")
VERDETTI_TEMA = ("regge", "non regge", "da approfondire")
VERDETTI_STRATEGIA = ("continuare", "correggere", "abbandonare")
SEZIONI_POSIZIONE = ("Fatti", "Cambiato da ieri", "Dubbi", "Proposta", "Non verificato")
ORDINE_SCHEDA = ("id", "gruppo", "titolo", "versione", "stato", "ipotesi", "regola", "taratura",
                 "prova", "previsioni", "decisione", "storico_decisioni", "versioni", "fonti",
                 "aggiornato")
MAX_VOCI = 5
CAMBIA = {"decisione": " (cambia una decisione)", "rischio": " (cambia un rischio)"}


# ---------------------------------------------------------------- percorsi e configurazione

def percorso(p) -> Path | None:
    """«MEM/...» (la memoria condivisa), «OD/...» e «~/...» diventano percorsi veri."""
    if not p:
        return None
    p = str(p)
    if p.startswith("MEM/"):
        try:
            import json as _j
            m = _j.loads((Path.home() / ".jarvis/percorsi.json").read_text(encoding="utf-8")).get("memoria")
        except (OSError, ValueError):
            m = None
        return Path(os.path.expanduser(m or "~/Jarvis-Memoria")) / p[4:]
    if p.startswith("OD/"):
        return OD / p[3:]
    return Path(os.path.expanduser(p))


def oggi() -> date:
    v = os.environ.get("RIUNIONE_OGGI")
    return date.fromisoformat(v) if v else date.today()


def adesso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def gruppi_da_spazi() -> dict:
    """Un gruppo per ogni progetto di spazi.json che ha il suo capogruppo (2026-10-10, Jarvis da zero)."""
    sys.path.insert(0, str(QUI.parent / "command-center"))
    try:
        import crea_progetto as cp
        import spazi as sp_mod
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for s in cp.carica_spazi().get("spazi", []):
        cart_mem = s.get("cartella_nome") or (Path(cp._esp(s["memoria"])).parent.name if s.get("memoria") else s["nome"])
        for pr in s.get("progetti", []):
            c = cp._esp(pr["cartella"])
            capo = pr.get("capogruppo")
            fcapo = c / ".claude" / "agents" / f"{capo}.md" if capo else None
            if not fcapo or not fcapo.is_file():
                continue
            membri = []
            for f in sorted((c / ".claude" / "agents").glob("*.md")):
                if f.stem == capo:
                    continue
                try:
                    campi, _ = sp_mod.frontmatter(f.read_text(encoding="utf-8"))
                except OSError:
                    continue
                if campi.get("description"):
                    membri.append({"agente": f.stem, "profilo": str(f),
                                   "temi": [campi["description"].split(". ")[0][:160]]})
            out[pr["id"]] = {"nome": pr["nome"], "spazio": cart_mem, "modo": "interno",
                             "capogruppo": {"agente": capo, "profilo": str(fcapo)}, "membri": membri,
                             "fonti": [{"nome": "Stato dello spazio", "percorso": f"MEM/{cart_mem}/Stato.md", "max_giorni": 14},
                                       {"nome": "Indice dei file", "percorso": str(c / "Indice-file.md"), "max_giorni": 365}],
                             "scadenze": [], "metriche": [],
                             "strategie": f"MEM/{cart_mem}/Strategie", "report": f"MEM/{cart_mem}/Report"}
    return out


def config() -> dict:
    f = Path(os.environ.get("RIUNIONE_CONFIG") or QUI / "riunione_gruppi.json")
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("grazia_giorni", 30)
    d["gruppi"] = d.get("gruppi") or {}
    if not os.environ.get("RIUNIONE_CONFIG"):            # le prove usano solo il loro file
        for gid, g in gruppi_da_spazi().items():
            d["gruppi"].setdefault(gid, g)
    return d


def chiave(nome: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nome.lower())


def gruppo(nome: str) -> tuple[str, dict]:
    gruppi = config()["gruppi"]
    for gid, g in gruppi.items():
        if chiave(nome) in (chiave(gid), chiave(g["nome"])):
            return gid, g
    raise SystemExit(f"❌ gruppo «{nome}» sconosciuto. Gruppi: {', '.join(gruppi)}")


def radice() -> Path:
    return Path(os.environ.get("RIUNIONE_RADICE") or Path.home() / "Jarvis" / "riunioni")


def cartella_giorno(gid: str, giorno: date) -> Path:
    return radice() / gid / giorno.isoformat()


def cartella_strategie(g: dict) -> Path:
    v = os.environ.get("RIUNIONE_STRATEGIE_DIR")
    return Path(v) if v else percorso(g["strategie"])


def cartella_report(g: dict) -> Path:
    v = os.environ.get("RIUNIONE_REPORT_DIR")
    return Path(v) if v else percorso(g["report"])


def file_report(gid: str, g: dict, giorno: date) -> Path:
    return cartella_report(g) / f"{giorno.isoformat()} riunione {gid}.md"


# ---------------------------------------------------------------- schede delle strategie
# Il frontespizio è YAML scritto in modo che si rilegga senza librerie: una chiave per riga,
# valori in JSON (che è YAML valido), liste di oggetti una voce per riga con «  - ».

def _valore(testo: str):
    testo = testo.strip()
    if testo == "":
        return []
    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        return testo.strip("'\"")


def leggi_scheda(f: Path) -> tuple[dict, str]:
    testo = f.read_text(encoding="utf-8")
    if not testo.startswith("---\n"):
        raise ValueError(f"{f.name}: manca il frontespizio")
    fm, _, corpo = testo[4:].partition("\n---\n")
    meta, ultima = {}, None
    for riga in fm.splitlines():
        if riga.startswith("  - ") and ultima is not None:
            if not isinstance(meta.get(ultima), list):
                meta[ultima] = []
            meta[ultima].append(_valore(riga[4:]))
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s?(.*)$", riga)
        if m:
            ultima = m.group(1)
            meta[ultima] = _valore(m.group(2))
    return meta, corpo


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def testo_scheda(meta: dict, corpo: str) -> str:
    righe = ["---"]
    chiavi = [k for k in ORDINE_SCHEDA if k in meta] + [k for k in meta if k not in ORDINE_SCHEDA]
    for k in chiavi:
        v = meta[k]
        if isinstance(v, list) and v:
            righe.append(f"{k}:")
            righe += [f"  - {_j(x)}" for x in v]
        else:
            righe.append(f"{k}: {_j(v)}")
    righe.append("---")
    return "\n".join(righe) + "\n" + corpo.lstrip("\n")


def scrivi_scheda(f: Path, meta: dict, corpo: str):
    """Scrive la scheda. Le previsioni si aggiungono e si chiudono, non si cancellano mai."""
    if f.exists():
        prima, _ = leggi_scheda(f)
        if len(meta.get("previsioni") or []) < len(prima.get("previsioni") or []):
            raise RuntimeError(f"{f.name}: la scheda perderebbe previsioni, non scrivo")
        for vecchia, nuova in zip(prima.get("previsioni") or [], meta.get("previsioni") or []):
            if vecchia.get("realizzato") is not None and nuova.get("realizzato") != vecchia.get("realizzato"):
                raise RuntimeError(f"{f.name}: una previsione chiusa cambierebbe esito, non scrivo")
    meta["aggiornato"] = adesso()
    f.write_text(testo_scheda(meta, corpo), encoding="utf-8")


def schede(g: dict) -> list[tuple[Path, dict, str]]:
    cart = cartella_strategie(g)
    if not cart or not cart.exists():
        return []
    out = []
    for f in sorted(cart.glob("*.md")):
        if f.name == "Strategie.md":
            continue
        meta, corpo = leggi_scheda(f)
        out.append((f, meta, corpo))
    return out


def data_valida(v) -> date | None:
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def piu_mesi(d: date, n: int) -> date:
    m = d.month - 1 + n
    anno, mese = d.year + m // 12, m % 12 + 1
    return date(anno, mese, min(d.day, calendar.monthrange(anno, mese)[1]))


def scadenza(p: dict) -> date | None:
    """Data + orizzonte («12 mesi», «3 settimane», «10 giorni»). Senza data o senza durata: None."""
    d = data_valida(p.get("data"))
    m = re.match(r"^\s*(\d+)\s*(mes[ei]|settiman[ae]|giorn[oi]|ann[oi])", str(p.get("orizzonte") or ""))
    if not d or not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    if u.startswith("mes"):
        return piu_mesi(d, n)
    if u.startswith("ann"):
        return piu_mesi(d, 12 * n)
    return d + timedelta(weeks=n) if u.startswith("settiman") else d + timedelta(days=n)


def aperta(p: dict) -> bool:
    return p.get("realizzato") is None and p.get("esito") in (None, "aperta", "senza data")


def conta_come_prova(p: dict) -> bool:
    return data_valida(p.get("data")) is not None


def previsioni_scadute(g: dict, giorno: date) -> list[dict]:
    out = []
    for f, meta, _ in schede(g):
        for i, p in enumerate(meta.get("previsioni") or [], 1):
            s = scadenza(p)
            if aperta(p) and s and s < giorno:
                out.append({"id": meta.get("id", f.stem), "n": i, "metrica": p.get("metrica"),
                            "scadenza": s.isoformat(), "giorni": (giorno - s).days})
    return out


def marca_scadute(g: dict, giorno: date, grazia: int) -> int:
    """Le previsioni scadute da più di `grazia` giorni senza esito diventano «scaduta senza dati»."""
    n = 0
    for f, meta, corpo in schede(g):
        cambiata = False
        for p in meta.get("previsioni") or []:
            s = scadenza(p)
            if aperta(p) and s and (giorno - s).days > grazia:
                p["esito"] = "scaduta senza dati"
                p["data_esito"] = giorno.isoformat()
                cambiata = True
                n += 1
        if cambiata:
            scrivi_scheda(f, meta, corpo)
    return n


def chiudi_previsione(g: dict, sid: str, n: int, realizzato: float, fonte: str | None, giorno: date) -> dict:
    for f, meta, corpo in schede(g):
        if meta.get("id") != sid:
            continue
        prev = meta.get("previsioni") or []
        if not 1 <= n <= len(prev):
            raise SystemExit(f"❌ {sid} ha {len(prev)} previsioni: la {n} non c'è")
        p = prev[n - 1]
        if p.get("realizzato") is not None:
            raise SystemExit(f"❌ la previsione {n} di {sid} è già chiusa ({p.get('esito')}): non si riscrive")
        atteso = p.get("atteso")
        p["realizzato"] = realizzato
        p["data_esito"] = giorno.isoformat()
        p["errore"] = None if atteso is None else round(realizzato - float(atteso), 6)
        itv = p.get("intervallo")
        if isinstance(itv, list) and len(itv) == 2 and None not in itv:
            p["dentro_intervallo"] = float(itv[0]) <= realizzato <= float(itv[1])
            p["esito"] = "riuscita" if p["dentro_intervallo"] else "fallita"
        else:
            p["dentro_intervallo"] = None
            p["esito"] = "chiusa senza intervallo"
        if fonte:
            p["fonte_esito"] = fonte
        if not conta_come_prova(p):
            p["nota_esito"] = "senza data: chiusa, ma non conta come prova"
        scrivi_scheda(f, meta, corpo)
        return p
    raise SystemExit(f"❌ nessuna scheda con id «{sid}» in {cartella_strategie(g)}")


def scrivi_indice(gid: str, g: dict, giorno: date) -> Path | None:
    cart = cartella_strategie(g)
    tutte = schede(g)
    if not tutte:
        return None
    righe, coperte, dentro = [], 0, 0
    for f, m, _ in tutte:
        prev = m.get("previsioni") or []
        aperte = sum(aperta(p) and conta_come_prova(p) for p in prev)
        chiuse = sum(p.get("realizzato") is not None for p in prev)
        senza = sum(not conta_come_prova(p) for p in prev)
        prossime = sorted(s for p in prev if aperta(p) and (s := scadenza(p)))
        for p in prev:
            if p.get("dentro_intervallo") is not None and conta_come_prova(p):
                coperte += 1
                dentro += bool(p["dentro_intervallo"])
        dec = m.get("decisione") or {}
        dec_txt = f"{dec.get('esito', '')} ({dec.get('data', '')})" if dec else "nessuna"
        righe.append(f"| [[{f.stem}]] | {m.get('versione', '')} | {m.get('stato', '')} | {aperte} | {chiuse} | "
                     f"{senza} | {prossime[0].isoformat() if prossime else '—'} | {dec_txt} |")
    scadute = previsioni_scadute(g, giorno)
    blocco_scadute = "\n".join(
        f"- {s['id']} n. {s['n']} ({s['metrica']}): scaduta il {s['scadenza']}, {s['giorni']} giorni fa. "
        f"Si chiude con `riunione.py {gid} chiudi-previsione {s['id']} {s['n']} <realizzato>`"
        for s in scadute) or "Nessuna."
    copertura = (f"{dentro} su {coperte} previsioni chiuse con intervallo sono cadute dentro ({dentro / coperte:.0%})."
                 if coperte else "Ancora nessuna previsione datata chiusa con un intervallo: la copertura non si misura.")
    testo = f"""---
titolo: Strategie {g['nome']}
tipo: indice
spazio: {g['spazio']}
aggiornato: {adesso()}
generato-da: strumenti/riunione.py (non si corregge a mano: si rilancia `riunione.py {gid} strategie`)
---

# Strategie {g['nome']}

Una scheda per strategia. Le previsioni si aggiungono e si chiudono, non si cancellano. Una
previsione «senza data» non conta come prova.

| Scheda | Versione | Stato | Aperte | Chiuse | Senza data | Prossima scadenza | Ultima decisione |
|---|---|---|---|---|---|---|---|
{chr(10).join(righe)}

## Previsioni scadute da chiudere

{blocco_scadute}

## Copertura

{copertura}
"""
    f = cart / "Strategie.md"
    f.write_text(testo, encoding="utf-8")
    return f


# ---------------------------------------------------------------- controlli meccanici

def numero_it(t: str) -> float:
    """«1.550» -> 1550, «3,5» -> 3.5, «-12.5» -> -12.5 (scrittura italiana e inglese)."""
    t = t.strip().rstrip(".")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    return float(t.replace(",", "."))


def controllo_fonti(g: dict, giorno: date) -> list[dict]:
    out = []
    for fo in g.get("fonti") or []:
        if fo.get("solo_agenti"):
            out.append({"fonte": fo["nome"], "stato": "solo agenti", "nota": fo.get("nota", "")})
            continue
        p = percorso(fo["percorso"])
        if not p.exists():
            out.append({"fonte": fo["nome"], "stato": "manca", "percorso": str(p)})
            continue
        ultimo = p.stat().st_mtime
        if p.is_dir():
            dentro = [x.stat().st_mtime for x in p.rglob("*") if x.is_file() and not x.name.startswith(".")]
            ultimo = max(dentro, default=ultimo)
        quando = datetime.fromtimestamp(ultimo)
        eta = (giorno - quando.date()).days
        vecchia = fo.get("max_giorni") is not None and eta > fo["max_giorni"]
        out.append({"fonte": fo["nome"], "stato": "vecchia" if vecchia else "ok", "percorso": str(p),
                    "aggiornata": quando.strftime("%Y-%m-%d %H:%M"), "giorni": eta,
                    "max_giorni": fo.get("max_giorni")})
    return out


def controllo_scadenze(g: dict, giorno: date) -> list[dict]:
    out = []
    for nome in g.get("scadenze") or []:
        f = percorso(nome)
        if not f.exists():
            out.append({"tipo": "file mancante", "file": str(f)})
            continue
        for riga in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*- \[ \] (\d{4}-\d{2}-\d{2})\s*·\s*(.*)$", riga)
            d = data_valida(m.group(1)) if m else None
            if d and d < giorno:
                out.append({"tipo": "scaduta", "data": d.isoformat(), "testo": m.group(2)[:160], "file": f.name})
            elif d and (d - giorno).days <= 7:
                out.append({"tipo": "entro 7 giorni", "data": d.isoformat(), "testo": m.group(2)[:160], "file": f.name})
    return out


def controllo_metriche(g: dict) -> list[dict]:
    out = []
    for me in g.get("metriche") or []:
        valori = []
        for fo in me["fonti"]:
            f = percorso(fo["file"])
            testo = f.read_text(encoding="utf-8") if f.exists() else ""
            m = re.search(fo["cerca"], testo)
            valori.append({"file": str(f), "valore": numero_it(m.group(1)) if m else None,
                           "aggiornato": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d") if f.exists() else None})
        letti = [v["valore"] for v in valori if v["valore"] is not None]
        if len(letti) < 2:
            esito = "non confrontabile"
        else:
            scarto = (max(letti) - min(letti)) / max(abs(x) for x in letti)
            esito = "discordante" if scarto > me.get("tolleranza", 0) else "concorde"
        out.append({"metrica": me["nome"], "esito": esito, "valori": valori})
    return out


def controllo_strategie(g: dict, giorno: date) -> list[dict]:
    out = []
    for f, m, _ in schede(g):
        sid = m.get("id", f.stem)
        if m.get("stato") not in STATI:
            out.append({"id": sid, "tipo": "stato non valido", "valore": m.get("stato")})
        t, p = m.get("taratura") or {}, m.get("prova") or {}
        if isinstance(t, dict) and isinstance(p, dict) and t.get("a") and p.get("da"):
            try:
                errori = backtest_check.periodi_ok(
                    (backtest_check.mese(t.get("da") or t["a"]), backtest_check.fine_periodo(t["a"])),
                    (backtest_check.mese(p["da"]), backtest_check.fine_periodo(p.get("a") or p["da"])))
            except ValueError as e:
                errori = [str(e)]
            out += [{"id": sid, "tipo": "periodi", "testo": e} for e in errori]
        else:
            out.append({"id": sid, "tipo": "periodi", "testo": "taratura o prova non dichiarate: nessuna prova fuori campione registrata"})
        for i, pr in enumerate(m.get("previsioni") or [], 1):
            s = scadenza(pr)
            if not conta_come_prova(pr):
                out.append({"id": sid, "n": i, "tipo": "senza data", "testo": "non conta come prova"})
            elif aperta(pr) and s and s < giorno:
                out.append({"id": sid, "n": i, "tipo": "scaduta senza esito", "scadenza": s.isoformat()})
            if aperta(pr) and not pr.get("intervallo"):
                out.append({"id": sid, "n": i, "tipo": "senza intervallo", "testo": "la copertura non si potrà misurare"})
    return out


def controllo_profili(g: dict) -> list[dict]:
    out = []
    for ruolo, a in [("capogruppo", g.get("capogruppo")), ("revisore", g.get("revisore"))] + \
                    [("specialista", m) for m in g.get("membri") or []]:
        if not a or not a.get("profilo"):
            continue
        p = percorso(a["profilo"])
        if not p.exists():
            out.append({"agente": a["agente"], "ruolo": ruolo, "profilo": str(p)})
    return out


def controllo_registro_esterno(g: dict, giorno: date) -> list[dict]:
    """Gruppi in modo «esterno»: decisioni del loro registro aperte e oltre la data «entro»."""
    f = percorso(g["esterna"]["registro"])
    if not f.exists():
        return [{"tipo": "registro mancante", "file": str(f)}]
    reg = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for d in reg.get("decisioni", []):
        entro = data_valida(str(d.get("entro", ""))[:10])
        if entro and entro < giorno and d.get("stato") in ("proposta", "approvata", "in_corso"):
            out.append({"id": d.get("id"), "titolo": d.get("titolo"), "entro": entro.isoformat(), "stato": d.get("stato")})
    return out


def controlli(gid: str, g: dict, giorno: date) -> dict:
    if g.get("modo") == "esterno":
        return {"gruppo": gid, "data": giorno.isoformat(), "profili_mancanti": controllo_profili(g),
                "decisioni_scadute": controllo_registro_esterno(g, giorno)}
    return {"gruppo": gid, "data": giorno.isoformat(),
            "fonti": controllo_fonti(g, giorno),
            "scadenze": controllo_scadenze(g, giorno),
            "metriche": controllo_metriche(g),
            "strategie": controllo_strategie(g, giorno),
            "profili_mancanti": controllo_profili(g)}


def controlli_md(c: dict) -> str:
    r = [f"# Controlli meccanici · {c['gruppo']} · {c['data']}", "",
         "Li fa lo script, sempre allo stesso modo. Sono fatti, non opinioni: chi li contesta porta la fonte.", ""]
    if "fonti" in c:
        r += ["## Fonti dei dati", ""]
        for f in c["fonti"]:
            if f["stato"] == "solo agenti":
                r.append(f"- {f['fonte']}: la leggono gli agenti ({f['nota']})")
            elif f["stato"] == "manca":
                r.append(f"- {f['fonte']}: MANCA ({f['percorso']})")
            else:
                lim = f", limite {f['max_giorni']} giorni" if f.get("max_giorni") is not None else ""
                r.append(f"- {f['fonte']}: {f['stato'].upper() if f['stato'] == 'vecchia' else 'ok'}, "
                         f"aggiornata {f['aggiornata']} ({f['giorni']} giorni{lim})")
        r.append("")
    if "scadenze" in c:
        r += ["## Date", ""] + ([f"- {s['tipo']}: {s.get('data', '')} · {s.get('testo', s.get('file', ''))}"
                                for s in c["scadenze"]] or ["Nessuna data scaduta o entro 7 giorni."]) + [""]
    if "metriche" in c:
        r += ["## Numeri con più fonti", ""]
        for m in c["metriche"]:
            vals = "; ".join(f"{v['valore']} in {Path(v['file']).name} (file del {v['aggiornato']})" for v in m["valori"])
            r.append(f"- {m['metrica']}: {m['esito'].upper()} · {vals}")
        r += ([] if c["metriche"] else ["Nessuna metrica configurata."]) + [""]
    if "strategie" in c:
        r += ["## Registro delle strategie", ""] + ([
            f"- {s['id']}{' n. ' + str(s['n']) if 'n' in s else ''}: {s['tipo']}"
            f"{' (' + s['scadenza'] + ')' if s.get('scadenza') else ''}{' · ' + s['testo'] if s.get('testo') else ''}"
            for s in c["strategie"]] or ["Niente da segnalare."]) + [""]
    if "decisioni_scadute" in c:
        r += ["## Decisioni del registro di direzione oltre la data", ""] + ([
            f"- {d.get('id')}: {d.get('titolo', d.get('tipo', ''))} · entro {d.get('entro', '')} · {d.get('stato', '')}"
            for d in c["decisioni_scadute"]] or ["Nessuna."]) + [""]
    r += ["## Profili degli agenti", ""] + ([
        f"- {p['agente']} ({p['ruolo']}): profilo non trovato in {p['profilo']}" for p in c["profili_mancanti"]]
        or ["Tutti i profili ci sono."]) + [""]
    return "\n".join(r)


# ---------------------------------------------------------------- compiti per gli agenti

REGOLE = """Regole che valgono per tutti:
- Ogni numero ha fonte (file o comando) e data. Senza, va in «Non verificato».
- Nessun consiglio finanziario dato come certezza: sono ipotesi con il loro margine d'errore.
- Nessun ordine reale, nessuna scrittura in database o sulla VPS, nessun messaggio mandato: si propone e decide l'utente.
- Pochi dati sono pochi dati: se il campione è piccolo lo scrivi, con il numero di casi.
- Italiano asciutto, frasi corte, niente aggettivi che non portano informazione."""

SCHEMA_POSIZIONE = """# Posizione di {agente} · {gruppo} · {data}

## Fatti
- <fatto> · fonte: <file o comando> · data: AAAA-MM-GG

## Cambiato da ieri
- <cosa è cambiato rispetto alla riunione precedente, o «niente»>

## Dubbi
- <cosa non torna e perché>

## Proposta
- <una proposta, con cosa cambierebbe e quanto costa verificarla>

## Non verificato
- <quello che hai letto ma non controllato>"""

SCHEMA_RIUNIONE = """{
  "gruppo": "<id>", "data": "AAAA-MM-GG",
  "temi": [{"tema": "...", "verdetto": "regge | non regge | da approfondire", "perche": "...", "fonti": ["..."]}],
  "strategie": [{"id": "<id della scheda>", "verdetto": "continuare | correggere | abbandonare", "perche": "...", "incarico": "se non è continuare: il compito già scritto"}],
  "importanti": [{"cosa": "...", "cambia": "decisione | rischio", "fonte": "file o comando, con data"}],
  "approfondire": [{"cosa": "...", "costo": "quanto costa il controllo (tempo, crediti, soldi)", "chi": "agente"}],
  "decisioni": [{"domanda": "cosa deve decidere l'utente", "incarico": "il compito già scritto, pronto da lanciare se dice sì"}],
  "non_verificato": ["..."],
  "revisore": {"esito": "ok | obiezioni", "note": ["..."]}
}"""


def profilo(a: dict) -> tuple[str, str]:
    """(modello, testo intero) del profilo; se manca lo dice nel testo."""
    p = percorso(a.get("profilo"))
    if not p or not p.exists():
        return "sonnet", f"(profilo di {a['agente']} non trovato: {p}. La chat master decide se lanciarlo lo stesso.)"
    testo = p.read_text(encoding="utf-8")
    m = re.search(r"^model:\s*(\S+)", testo, re.M)
    return (m.group(1) if m else "sonnet"), testo


def riunione_precedente(gid: str, giorno: date) -> Path | None:
    cart = radice() / gid
    if not cart.exists():
        return None
    prima = sorted(d for d in cart.iterdir() if d.is_dir() and d.name < giorno.isoformat()
                   and (d / "riunione.json").exists())
    return prima[-1] if prima else None


def scrivi_compiti(gid: str, g: dict, giorno: date, cart: Path) -> list[tuple[str, str, Path]]:
    comp = cart / "compiti"
    comp.mkdir(exist_ok=True)
    (cart / "posizioni").mkdir(exist_ok=True)
    prec = riunione_precedente(gid, giorno)
    ieri = (f"La riunione precedente è in {prec}: leggi riunione.json e le posizioni per dire cosa è cambiato."
            if prec else "Non c'è una riunione precedente: in «Cambiato da ieri» scrivi «prima riunione».")
    strat = cartella_strategie(g)
    indice = strat / "Strategie.md" if strat else None
    comuni = (f"Cartella della riunione: {cart}\n"
              f"Dati e stato delle fonti: {cart / 'dati.md'}\n"
              f"Controlli meccanici: {cart / 'controlli.md'}\n"
              f"Registro delle strategie: {indice if indice and indice.exists() else 'nessuna scheda ancora'}\n{ieri}")
    out = []
    for m in g.get("membri") or []:
        modello, testo = profilo(m)
        f = comp / f"{m['agente']}.md"
        f.write_text(f"""Modello: {modello}

{testo}

---

Riunione giornaliera {g['nome']} del {giorno.isoformat()}. Sei {m['agente']}, specialista.
{comuni}

Temi tuoi: {'; '.join(m.get('temi') or ['quelli del tuo profilo'])}.

Scrivi la tua posizione in {cart / 'posizioni' / (m['agente'] + '.md')}, con questo schema e nient'altro:

{SCHEMA_POSIZIONE.format(agente=m['agente'], gruppo=g['nome'], data=giorno.isoformat())}

{REGOLE}
Non parli con l'utente e non lanci agenti. Rispondi con il percorso del file scritto.
""", encoding="utf-8")
        out.append((m["agente"], modello, f))
    rev = g.get("revisore")
    if rev:
        modello, testo = profilo(rev)
        f = comp / "revisore.md"
        f.write_text(f"""Modello: {modello}

{testo}

---

Riunione giornaliera {g['nome']} del {giorno.isoformat()}. Sei {rev['agente']}, il revisore.
{comuni}

Leggi tutte le posizioni in {cart / 'posizioni'} e i controlli meccanici. Per ogni posizione
segna: fatti senza fonte o senza data, numeri che non tornano con i controlli o con un'altra
posizione, conclusioni che i dati non reggono, campioni troppo piccoli presentati come prove.
Verifica almeno un numero per posizione aprendo la fonte.

Scrivi in {cart / 'posizioni' / 'revisione.md'}: una sezione per posizione, poi una riga finale
«Esito: ok» oppure «Esito: obiezioni» con il numero delle obiezioni.

{REGOLE}
Rispondi con il percorso del file scritto.
""", encoding="utf-8")
        out.append((rev["agente"], modello, f))
    capo = g.get("capogruppo") or {}
    modello, testo = profilo(capo) if capo.get("profilo") else ("(chat master)", capo.get("nota", ""))
    f = comp / "capogruppo.md"
    f.write_text(f"""Modello: {modello}

{testo}

---

Riunione giornaliera {g['nome']} del {giorno.isoformat()}. Sei {capo.get('agente')}, il capogruppo: chiudi la riunione.
{comuni}

Leggi le posizioni, la revisione ({cart / 'posizioni' / 'revisione.md'}) e i controlli meccanici.
Dai un verdetto per ogni tema (regge, non regge, da approfondire) e per ogni strategia del
registro toccata oggi (continuare, correggere, abbandonare). Un «abbandonare» o un «correggere»
è una proposta: diventa decisione solo con il sì dell'utente, quindi mettilo anche in «decisioni»
con l'incarico già scritto.

Per l'utente scegli al massimo {MAX_VOCI} cose importanti, e solo se cambiano una decisione o un
rischio. Se non c'è niente così, lascia «importanti» e «decisioni» vuote: il report dirà
«niente di nuovo». Per ogni cosa da approfondire scrivi quanto costa il controllo.

Scrivi {cart / 'riunione.json'} con questo schema, JSON valido:

{SCHEMA_RIUNIONE}

{REGOLE}
Poi rispondi con il percorso del file. La chiusura (`riunione.py {gid} chiudi`) la lancia la chat master.
""", encoding="utf-8")
    out.append((capo.get("agente", "capogruppo"), modello, f))
    return out


def leggimi(gid: str, g: dict, giorno: date, cart: Path, compiti: list) -> str:
    specialisti = [c for c in compiti if c[2].stem not in ("revisore", "capogruppo")]
    rev = [c for c in compiti if c[2].stem == "revisore"]
    capo = [c for c in compiti if c[2].stem == "capogruppo"]
    r = [f"# Riunione {g['nome']} · {giorno.isoformat()}", "",
         "Preparata da `strumenti/riunione.py`. Gli agenti li lancia solo la chat master, in quest'ordine,",
         "come `general-purpose` con il modello scritto nella prima riga del compito e il testo intero del compito.", "",
         "1. Specialisti, tutti nello stesso messaggio:"]
    r += [f"   - {a} ({mod}): {f}" for a, mod, f in specialisti]
    if rev:
        r += ["2. Revisore, dopo che tutte le posizioni ci sono:"] + [f"   - {a} ({mod}): {f}" for a, mod, f in rev]
    r += [f"{3 if rev else 2}. Capogruppo, che scrive riunione.json:"] + [f"   - {a} ({mod}): {f}" for a, mod, f in capo]
    r += [f"{4 if rev else 3}. Chiusura: `python3 ~/Jarvis/strumenti/riunione.py {gid} chiudi --data {giorno.isoformat()}`",
          "", "Ogni sottoagente usa `--agente <nome>` nelle chiamate a lavori.py.", ""]
    return "\n".join(r)


# ---------------------------------------------------------------- comandi

def cmd_prepara(gid: str, g: dict, giorno: date) -> int:
    cart = cartella_giorno(gid, giorno)
    if (cart / "riunione.json").exists():
        print(f"✅ la riunione {gid} del {giorno} è già fatta ({cart / 'riunione.json'}): non la rifaccio.")
        print(f"   Se manca il report: riunione.py {gid} chiudi --data {giorno}")
        return 0
    cart.mkdir(parents=True, exist_ok=True)
    c = controlli(gid, g, giorno)
    (cart / "controlli.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    (cart / "controlli.md").write_text(controlli_md(c), encoding="utf-8")

    if g.get("modo") == "esterno":
        est = percorso(g["esterna"]["cartella"]) / giorno.isoformat()
        fatto = (est / "riunione.json").exists()
        (cart / "LEGGIMI.md").write_text(
            f"# Riunione {g['nome']} · {giorno}\n\nLa riunione la fa già la routine {g['esterna']['routine']}.\n"
            f"Qui non si lanciano agenti. Cartella della routine: {est}\n"
            f"Quando c'è riunione.json lì dentro: `python3 ~/Jarvis/strumenti/riunione.py {gid} chiudi --data {giorno}`\n",
            encoding="utf-8")
        print(f"ℹ️  {g['nome']}: la riunione la fa la routine ({g['esterna']['routine']}).")
        print(f"   riunione.json di oggi: {'c’è' if fatto else 'non ancora'} ({est})")
        print(f"   decisioni oltre la data nel registro di direzione: {len(c['decisioni_scadute'])}")
        print(f"   controlli: {cart / 'controlli.md'}")
        return 0

    dati = [f"# Dati · {g['nome']} · {giorno}", "", "Stato delle fonti letto dallo script (data dell'ultimo file).", ""]
    for f in c["fonti"]:
        dati.append(f"- {f['fonte']}: {f['stato']}" + (f", {f['aggiornata']}" if f.get("aggiornata") else "")
                    + (f" · {f['percorso']}" if f.get("percorso") else f" · {f.get('nota', '')}"))
    (cart / "dati.md").write_text("\n".join(dati) + "\n", encoding="utf-8")
    compiti = scrivi_compiti(gid, g, giorno, cart)
    (cart / "LEGGIMI.md").write_text(leggimi(gid, g, giorno, cart, compiti), encoding="utf-8")

    avvisi = (sum(f["stato"] in ("manca", "vecchia") for f in c["fonti"]) + len(c["scadenze"])
              + sum(m["esito"] == "discordante" for m in c["metriche"]) + len(c["strategie"])
              + len(c["profili_mancanti"]))
    print(f"✅ riunione {gid} del {giorno} preparata in {cart}")
    print(f"   compiti per gli agenti: {len(compiti)} (ordine in LEGGIMI.md) · segnalazioni meccaniche: {avvisi}")
    for m in c["metriche"]:
        if m["esito"] == "discordante":
            print(f"   ⚠️  numeri discordanti: {m['metrica']}: " + ", ".join(str(v['valore']) for v in m["valori"]))
    for p in c["profili_mancanti"]:
        print(f"   ⚠️  profilo mancante: {p['agente']} ({p['profilo']})")
    return 0


def valida_riunione(r: dict, ids: set[str]) -> list[str]:
    errori = []
    tipi = {"gruppo": str, "data": str, "temi": list, "strategie": list, "importanti": list,
            "approfondire": list, "decisioni": list, "non_verificato": list, "revisore": dict}
    errori += [f"manca «{k}» o non è {t.__name__}" for k, t in tipi.items() if not isinstance(r.get(k), t)]
    if errori:
        return errori
    for i, t in enumerate(r["temi"]):
        if t.get("verdetto") not in VERDETTI_TEMA or not t.get("tema") or not t.get("perche"):
            errori.append(f"tema {i + 1}: servono tema, perche e verdetto fra {', '.join(VERDETTI_TEMA)}")
    for s in r["strategie"]:
        if s.get("verdetto") not in VERDETTI_STRATEGIA or not s.get("perche"):
            errori.append(f"strategia {s.get('id')}: servono perche e verdetto fra {', '.join(VERDETTI_STRATEGIA)}")
        if s.get("id") not in ids:
            errori.append(f"strategia «{s.get('id')}» non c'è nel registro")
    if len(r["importanti"]) > MAX_VOCI:
        errori.append(f"importanti: {len(r['importanti'])} voci, il massimo è {MAX_VOCI}")
    for i, x in enumerate(r["importanti"]):
        if x.get("cambia") not in ("decisione", "rischio") or not x.get("cosa") or not x.get("fonte"):
            errori.append(f"importante {i + 1}: servono cosa, fonte e cambia (decisione o rischio)")
    for i, x in enumerate(r["approfondire"]):
        if not x.get("cosa") or not x.get("costo"):
            errori.append(f"approfondire {i + 1}: servono cosa e costo del controllo")
    for i, x in enumerate(r["decisioni"]):
        if not x.get("domanda") or not x.get("incarico"):
            errori.append(f"decisione {i + 1}: servono domanda e incarico già scritto")
    if r["revisore"].get("esito") not in ("ok", "obiezioni"):
        errori.append("revisore.esito deve essere ok oppure obiezioni")
    return errori


def _lista(voci: list, fmt, vuoto: str) -> list[str]:
    righe = [fmt(i, x) for i, x in enumerate(voci[:MAX_VOCI], 1)]
    if len(voci) > MAX_VOCI:
        righe.append(f"- e altre {len(voci) - MAX_VOCI} nella cartella della riunione")
    return righe or [vuoto]


def testo_report(g: dict, gid: str, giorno: date, r: dict, cart: Path, extra: list[str]) -> str:
    decisioni = list(r["decisioni"])
    nulla = not r["importanti"] and not decisioni
    corpo = [f"# Riunione {g['nome']} · {giorno.isoformat()}", ""]
    if nulla:
        corpo += ["Niente di nuovo.", ""]
    else:
        corpo += ["## Cosa cambia", ""] + _lista(
            r["importanti"], lambda i, x: f"{i}. {x['cosa']}{CAMBIA.get(x.get('cambia'), '')} · fonte: {x['fonte']}",
            "Niente che cambi una decisione o un rischio.") + [""]
        corpo += ["## Decisioni che servono", ""] + _lista(
            decisioni, lambda i, x: f"{i}. {x['domanda']}\n   Incarico se dici sì: {x['incarico']}", "Nessuna.") + [""]
    if r["approfondire"]:
        corpo += ["## Dove approfondire", ""] + _lista(
            r["approfondire"], lambda i, x: f"- {x['cosa']} · costo del controllo: {x['costo']}"
            + (f" · {x['chi']}" if x.get("chi") else ""), "") + [""]
    corpo += ["## Non verificato", ""] + _lista(r["non_verificato"], lambda i, x: f"- {x}", "Niente.") + [""]
    temi = {v: sum(t["verdetto"] == v for t in r["temi"]) for v in VERDETTI_TEMA}
    strat = ", ".join(f"{s['id']} {s['verdetto']}" for s in r["strategie"]) or "nessuna toccata"
    corpo += [f"Temi: {temi['regge']} reggono, {temi['non regge']} non reggono, {temi['da approfondire']} da approfondire. "
              f"Strategie: {strat}. Revisore: {r['revisore']['esito']}"
              + (f" ({len(r['revisore'].get('note') or [])} note)" if r["revisore"].get("note") else "") + "."]
    corpo += extra + [f"Cartella della riunione: {cart}", ""]
    return (f"---\ntitolo: Riunione {g['nome']} del {giorno.isoformat()}\ntipo: report\nspazio: {g['spazio']}\n"
            f"gruppo: {gid}\naggiornato: {adesso()}\ngenerato-da: strumenti/riunione.py\n---\n\n" + "\n".join(corpo))


def riunione_da_esterna(g: dict, giorno: date) -> tuple[dict, Path, list[str]]:
    """Il riunione.json scritto dalla routine di un gruppo in modo «esterno», ridotto allo schema comune."""
    est = percorso(g["esterna"]["cartella"]) / giorno.isoformat()
    f = est / "riunione.json"
    if not f.exists():
        raise SystemExit(f"❌ la routine non ha ancora scritto {f}: niente da chiudere")
    x = json.loads(f.read_text(encoding="utf-8"))
    r = {
        "gruppo": g["nome"], "data": giorno.isoformat(), "temi": [], "strategie": [],
        "importanti": [{"cosa": s, "cambia": None, "fonte": f"sintesi della riunione di direzione {x.get('data')}"}
                       for s in (x.get("sintesi") or [])],
        "approfondire": [{"cosa": f"{d.get('id')}: {d.get('domanda')}", "costo": f"una risposta del CEO ({d.get('formato', '')})",
                          "chi": f"capogruppo di {g['nome']}"} for d in (x.get("domande_ceo") or [])],
        "decisioni": [{"domanda": f"{d.get('id')} {d.get('titolo')}",
                       "incarico": d.get("come_fare") or d.get("azione") or ""} for d in (x.get("decisioni_proposte") or [])],
        "non_verificato": [str(v) for v in (x.get("non_verificato") or [])],
        "revisore": {"esito": "ok" if (x.get("garante") or {}).get("verdetto") == "TUTTO CARICATO" else "obiezioni",
                     "note": (x.get("garante") or {}).get("note") or []},
    }
    for d in r["decisioni"]:
        if isinstance(d["incarico"], list):
            d["incarico"] = "; ".join(map(str, d["incarico"]))
    pdf = next(est.glob("*.pdf"), None)
    extra = [f"Garante dei dati: {(x.get('garante') or {}).get('verdetto')}. "
             f"Report completo (PDF): {pdf if pdf else 'non ancora generato'}. La sintesi è riportata così com'è, senza filtro."]
    return r, est, extra


def cmd_chiudi(gid: str, g: dict, giorno: date) -> int:
    rep = file_report(gid, g, giorno)
    if g.get("modo") == "esterno":
        r, cart, extra = riunione_da_esterna(g, giorno)
        sorgente = cart / "riunione.json"
    else:
        cart = cartella_giorno(gid, giorno)
        sorgente = cart / "riunione.json"
        if not sorgente.exists():
            print(f"❌ manca {sorgente}: il capogruppo non ha chiuso la riunione")
            return 2
        r = json.loads(sorgente.read_text(encoding="utf-8"))
        extra = []
        c = cart / "controlli.json"
        if c.exists():
            cj = json.loads(c.read_text(encoding="utf-8"))
            disc = [m["metrica"] for m in cj.get("metriche", []) if m["esito"] == "discordante"]
            if disc:
                extra.append("Numeri con fonti discordanti (controllo meccanico): " + "; ".join(disc) + ".")
        ids = {m.get("id") for _, m, _ in schede(g)}
        errori = valida_riunione(r, ids)
        if errori:
            print("❌ riunione.json non valido, non tocco niente:")
            print("\n".join(f"   - {e}" for e in errori))
            return 2
    if rep.exists() and rep.stat().st_mtime >= sorgente.stat().st_mtime:
        print(f"✅ già chiusa: {rep} è più recente di riunione.json. Non riscrivo.")
        return 0

    # registro: verdetti del capogruppo nelle schede, scadute oltre la grazia, indice
    for f, meta, corpo in schede(g):
        v = next((s for s in r["strategie"] if s.get("id") == meta.get("id")), None)
        if not v:
            continue
        nuova = {"data": giorno.isoformat(), "esito": v["verdetto"], "motivo": v["perche"],
                 "fonte": f"riunione {gid} {giorno.isoformat()}",
                 "nota": "verdetto del capogruppo" + ("" if v["verdetto"] == "continuare" else ": proposta, serve il sì dell'utente")}
        vecchia = meta.get("decisione")
        if vecchia and (vecchia.get("data"), vecchia.get("esito")) == (nuova["data"], nuova["esito"]):
            continue
        if vecchia:
            meta["storico_decisioni"] = (meta.get("storico_decisioni") or []) + [vecchia]
        meta["decisione"] = nuova
        scrivi_scheda(f, meta, corpo)
    for s in r["strategie"]:
        if s["verdetto"] != "continuare" and not any(s["id"] in d["domanda"] for d in r["decisioni"]):
            r["decisioni"].append({"domanda": f"Strategia {s['id']}: il capogruppo propone di {s['verdetto']} ({s['perche']})",
                                   "incarico": s.get("incarico") or "scriverlo prima di lanciare: il capogruppo non l'ha dato"})
    scadute = marca_scadute(g, giorno, config().get("grazia_giorni", 30))
    indice = scrivi_indice(gid, g, giorno)

    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(testo_report(g, gid, giorno, r, cart, extra), encoding="utf-8")
    print(f"✅ report: {rep}")
    print(f"   registro: {'indice ' + str(indice) if indice else 'nessuna scheda'} · previsioni diventate «scaduta senza dati»: {scadute}")
    return 0


def valida_posizione(f: Path) -> list[str]:
    testo = f.read_text(encoding="utf-8")
    return [s for s in SEZIONI_POSIZIONE if not re.search(rf"^## {re.escape(s)}\s*$", testo, re.M)]


def cmd_stato(gid: str, g: dict, giorno: date) -> int:
    rep = file_report(gid, g, giorno)
    print(f"Riunione {g['nome']} ({gid}) del {giorno}")
    if g.get("modo") == "esterno":
        est = percorso(g["esterna"]["cartella"]) / giorno.isoformat()
        print(f"  modo: esterno, la fa la routine {g['esterna']['routine']}")
        for nome in ("dati.json", "posizioni", "riunione.json", "inviato.txt"):
            print(f"  {nome}: {'sì' if (est / nome).exists() else 'no'}")
        print(f"  PDF: {next(est.glob('*.pdf'), 'no')}")
    else:
        cart = cartella_giorno(gid, giorno)
        print(f"  cartella: {cart} ({'c’è' if cart.exists() else 'non ancora preparata'})")
        attesi = [m["agente"] for m in g.get("membri") or []]
        for a in attesi:
            f = cart / "posizioni" / f"{a}.md"
            if not f.exists():
                print(f"  posizione {a}: manca")
            else:
                buchi = valida_posizione(f)
                print(f"  posizione {a}: {'ok' if not buchi else 'mancano le sezioni ' + ', '.join(buchi)}")
        if g.get("revisore"):
            print(f"  revisione: {'sì' if (cart / 'posizioni' / 'revisione.md').exists() else 'manca'}")
        print(f"  riunione.json: {'sì' if (cart / 'riunione.json').exists() else 'manca'}")
    print(f"  report per l'utente: {rep if rep.exists() else 'non ancora'}")
    sc = schede(g)
    scadute = previsioni_scadute(g, giorno)
    print(f"  strategie nel registro: {len(sc)} · previsioni scadute da chiudere: {len(scadute)}")
    return 0


def cmd_strategie(gid: str, g: dict, giorno: date) -> int:
    sc = schede(g)
    if not sc:
        print(f"Nessuna scheda in {cartella_strategie(g)}")
        return 0
    indice = scrivi_indice(gid, g, giorno)
    grazia = config().get("grazia_giorni", 30)
    for f, m, _ in sc:
        print(f"■ {m.get('id')} · {m.get('versione')} · {m.get('stato')}")
        for i, p in enumerate(m.get("previsioni") or [], 1):
            s = scadenza(p)
            stato = p.get("esito") or "aperta"
            if not conta_come_prova(p):
                stato = ("senza data" if stato == "senza data" else stato + ", senza data") + ": non conta come prova"
            elif aperta(p) and s and s < giorno:
                stato = f"SCADUTA il {s}" + (" oltre la grazia: al prossimo chiudi «scaduta senza dati»"
                                               if (giorno - s).days > grazia else "")
            itv = p.get("intervallo")
            print(f"   {i}. {p.get('metrica')}: atteso {p.get('atteso')}"
                  f"{' [' + str(itv[0]) + ' – ' + str(itv[1]) + ']' if isinstance(itv, list) else ' (intervallo non dichiarato)'}"
                  f" · dichiarata {p.get('data')} · {p.get('orizzonte')} · {stato}")
    print(f"Indice: {indice}")
    return 0


def cmd_elenco() -> int:
    if not config()["gruppi"]:
        print("nessun gruppo ancora: ogni progetto creato con crea_progetto.py diventa un gruppo da solo")
    for gid, g in config()["gruppi"].items():
        capo = (g.get("capogruppo") or {}).get("agente")
        print(f"{gid:18} {g['nome']:18} modo {g.get('modo', 'interno'):8} capogruppo {capo} · "
              f"{len(g.get('membri') or [])} specialisti · report in {cartella_report(g)}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "elenco":
        return cmd_elenco()
    ap = argparse.ArgumentParser(prog="riunione.py")
    ap.add_argument("gruppo")
    ap.add_argument("comando", choices=("prepara", "chiudi", "stato", "strategie", "chiudi-previsione"))
    ap.add_argument("resto", nargs="*")
    ap.add_argument("--data", help="AAAA-MM-GG, predefinita oggi")
    ap.add_argument("--fonte", help="per chiudi-previsione: da dove viene il realizzato")
    a = ap.parse_args(argv)
    gid, g = gruppo(a.gruppo)
    giorno = date.fromisoformat(a.data) if a.data else oggi()
    if a.comando == "prepara":
        return cmd_prepara(gid, g, giorno)
    if a.comando == "chiudi":
        return cmd_chiudi(gid, g, giorno)
    if a.comando == "stato":
        return cmd_stato(gid, g, giorno)
    if a.comando == "strategie":
        return cmd_strategie(gid, g, giorno)
    if len(a.resto) != 3:
        print("uso: riunione.py <gruppo> chiudi-previsione <id> <n> <realizzato> [--fonte ...]")
        return 2
    try:
        realizzato = numero_it(a.resto[2])
    except ValueError:
        print(f"❌ realizzato non è un numero: «{a.resto[2]}»")
        return 2
    p = chiudi_previsione(g, a.resto[0], int(a.resto[1]), realizzato, a.fonte, giorno)
    scrivi_indice(gid, g, giorno)
    print(f"✅ {a.resto[0]} n. {a.resto[1]}: realizzato {p['realizzato']}, errore {p['errore']}, "
          f"dentro l'intervallo: {p['dentro_intervallo']}, esito {p['esito']}"
          + (f" · {p['nota_esito']}" if p.get("nota_esito") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
