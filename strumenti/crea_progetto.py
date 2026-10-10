#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Crea (o completa) un progetto: una sola fonte, spazi.json + cartelle + schede degli agenti.

Jarvis parte senza progetti. Quando il proprietario ne nomina uno nuovo, l'assistente lancia questo script.

    python3 strumenti/crea_progetto.py "<nome>" [--spazio "<spazio>"] [--cartella <percorso>]
                                       [--descrizione "<a cosa serve>"] [--modello sonnet] [--prova] [--json]
    python3 strumenti/crea_progetto.py --elenco
    python3 strumenti/crea_progetto.py --indice <progetto>         rifà Indice-file.md della cartella
    python3 strumenti/crea_progetto.py --rinomina <progetto> "<nome nuovo>"
    python3 strumenti/crea_progetto.py --sposta <progetto> <cartella nuova>
    python3 strumenti/crea_progetto.py --archivia <progetto>       esce da spazi.json, i file restano
    python3 strumenti/crea_progetto.py --ripristina <progetto>

Cosa crea (solo quello che manca; rilanciarlo non rifà niente):
  - la voce in command-center/spazi.json (spazio nuovo se --spazio non esiste; senza --spazio lo spazio ha il nome
    del progetto);
  - la memoria dello spazio <memoria>/<spazio>/: <spazio>.md (porta), Stato.md (FATTO / DA FARE / ERRORI, data-ora),
    Decisioni.md, Report/;
  - la cartella del progetto (predefinita <progetti>/<nome>, oppure --cartella già esistente) con File/,
    Indice-file.md, .claude/memoria/MEMORIA.md, .claude/memoria/agenti/ e .claude/agents/<id>-ceo.md (il capogruppo);
  - se la cartella è un repo git, i ganci post-commit e pre-push che salvano lo stato (strumenti/ganci_git.py).
Ogni file che esiste e va cambiato prima si copia in <file>.bak-AAAAMMGG-HHMMSS. --prova non scrive niente.
<memoria> e <progetti> vengono da ~/.jarvis/percorsi.json (chiavi «memoria» e «progetti»), predefiniti
~/Jarvis-Memoria e ~/Progetti. Variabile JARVIS_SPAZI per usare un altro spazi.json (prove).
"""
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

QUI = Path(__file__).resolve().parent
REPO = QUI.parent
CC = REPO / "command-center"
MODELLI = ("haiku", "sonnet", "opus")
ESCLUSI_INDICE = {"Indice-file.md", ".DS_Store", "Thumbs.db", "desktop.ini"}


# ---------------------------------------------------------------- percorsi
def casa():
    return Path(os.environ.get("HOME") or Path.home())


def _percorsi():
    try:
        return json.loads((casa() / ".jarvis" / "percorsi.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _esp(v):
    v = str(v)
    if v == "~" or v.startswith("~/") or v.startswith("~\\"):
        return casa() / v[2:] if len(v) > 1 else casa()
    return Path(v)


def memoria():
    for v in (os.environ.get("JARVIS_MEMORIA"), os.environ.get("JARVIS_VAULT"), _percorsi().get("memoria")):
        if v and str(v).strip():
            return _esp(str(v).strip())
    return casa() / "Jarvis-Memoria"


def radice_progetti():
    v = os.environ.get("JARVIS_PROGETTI") or _percorsi().get("progetti")
    return _esp(v) if v else casa() / "Progetti"


def file_spazi():
    """command-center/spazi.json. Dentro il Command Center vale il suo spazi.FILE (così le prove che lo spostano
    restano coerenti); fuori, JARVIS_SPAZI per le prove."""
    v = os.environ.get("JARVIS_SPAZI")
    if v:
        return Path(v)
    m = sys.modules.get("spazi")
    if m is not None and getattr(m, "FILE", None) and Path(getattr(m, "__file__", "")).parent == CC:
        return Path(m.FILE)
    return CC / "spazi.json"


def corto(p):
    """Percorso con ~ se sta nella casa: spazi.json resta valido anche se cambia il nome utente."""
    p = Path(p)
    try:
        return "~/" + p.resolve().relative_to(casa().resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def adesso():
    return time.strftime("%Y-%m-%d %H:%M")


def slug(testo):
    t = unicodedata.normalize("NFKD", str(testo).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "progetto"


# ---------------------------------------------------------------- spazi.json
def carica_spazi():
    f = file_spazi()
    if not f.is_file():
        return {"spazi": []}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        raise SystemExit(f"{f} non è un JSON valido: correggilo prima (c'è una copia .bak accanto?)")
    if isinstance(d, list):
        d = {"spazi": d}
    d.setdefault("spazi", [])
    return d


class Lavoro:
    """Le operazioni da fare: in --prova si elencano e basta."""

    def __init__(self, prova):
        self.prova, self.fatte, self.saltate = prova, [], []

    def _bak(self, f):
        if f.is_file():
            dst = f.with_name(f"{f.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(f, dst)
            return dst
        return None

    def cartella(self, d):
        if d.is_dir():
            self.saltate.append(f"c'è già: {d}")
            return
        self.fatte.append(f"crea cartella {d}")
        if not self.prova:
            d.mkdir(parents=True, exist_ok=True)

    def scrivi(self, f, testo, sovrascrivi=False):
        f = Path(f)
        if f.is_file():
            if not sovrascrivi or f.read_text(encoding="utf-8") == testo:
                self.saltate.append(f"c'è già: {f}")
                return False
            self.fatte.append(f"aggiorna {f} (copia .bak accanto)")
            if not self.prova:
                self._bak(f)
        else:
            self.fatte.append(f"scrive {f}")
        if not self.prova:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f".{f.name}.tmp")
            tmp.write_text(testo, encoding="utf-8")
            os.replace(tmp, f)
        return True

    def salva_spazi(self, d, motivo):
        testo = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
        f = file_spazi()
        if f.is_file() and f.read_text(encoding="utf-8") == testo:
            return
        self.fatte.append(f"spazi.json: {motivo}")
        if not self.prova:
            f.parent.mkdir(parents=True, exist_ok=True)
            self._bak(f)
            tmp = f.with_name(f".{f.name}.tmp")
            tmp.write_text(testo, encoding="utf-8")
            os.replace(tmp, f)


def trova_progetto(d, chi):
    """(spazio, progetto) per id o nome (senza badare a maiuscole), o (None, None)."""
    k = slug(chi)
    for s in d["spazi"]:
        for p in s.get("progetti", []):
            if p.get("id") == chi or p.get("id") == k or slug(p.get("nome", "")) == k:
                return s, p
    return None, None


def trova_spazio(d, nome):
    k = slug(nome)
    return next((s for s in d["spazi"] if s.get("id") == k or slug(s.get("nome", "")) == k), None)


# ---------------------------------------------------------------- testi di partenza
def testo_stato(spazio):
    return (f"---\ntitolo: Stato · {spazio}\ntipo: stato\naggiornato: {adesso()}\n---\n\n"
            f"# Stato · {spazio}\n\nPorta: [[{spazio}]] · Decisioni: [[Decisioni]]\n\n"
            "<!-- stato-auto:inizio -->\n"
            "_Ancora nessuna sessione di lavoro: la parte tra questi segni la scrivono da soli i ganci di Claude Code "
            "(fine risposta, compattazione, fine sessione)._\n\n"
            "**FATTO**\n- progetto creato\n\n**DA FARE**\n- (niente ancora)\n\n**ERRORI DA NON RIPETERE**\n- (nessuno)\n"
            "<!-- stato-auto:fine -->\n\n## Note\n")


def testo_porta(spazio, progetti):
    righe = [f"---\ntitolo: {spazio}\ntipo: spazio\naggiornato: {adesso()}\n---\n", f"# {spazio}\n",
             "Lo stato vivo è in [[Stato]]; le scelte prese in [[Decisioni]]; i report in `Report/`.\n", "## Progetti\n"]
    righe += [f"- **{p['nome']}**: `{p['cartella']}` · capogruppo `{p.get('capogruppo') or '-'}`" for p in progetti]
    return "\n".join(righe) + "\n"


def testo_decisioni(spazio):
    return (f"---\ntitolo: Decisioni · {spazio}\ntipo: decisioni\naggiornato: {adesso()}\n---\n\n# Decisioni · {spazio}\n\n"
            f"Una riga per scelta presa: data-ora, cosa, perché. Collegato a [[Stato]] e [[{spazio}]].\n")


def testo_memoria_progetto(nome):
    return (f"# Memoria — {nome}\n\nUn file per fatto. Questo è l'indice: si legge da solo, i file si aprono solo\n"
            f"quando servono.\n\n## A che punto siamo\n\n### Fatto\n- {adesso()} progetto creato con crea_progetto.py\n\n"
            "### Da fare\n- il capogruppo legge la cartella e crea gli specialisti che servono\n\n"
            "### Errori da non ripetere\n\n## Cosa sappiamo già\n\n## Diario\n")


# ---------------------------------------------------------------- registro delle azioni (Stato.md e diario del giorno)
def _gancio_stato():
    import importlib.util
    f = REPO / "claude-config" / "hooks" / "stato_avanzamento.py"
    spec = importlib.util.spec_from_file_location("stato_avanzamento", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def registra_azione(chi, testo, aggiorna_stato=True):
    """Una riga per ogni azione su un progetto (creato, agente creato o cambiato, file caricato, descrizione…):
    in <cartella>/.claude/memoria/azioni.jsonl (le ultime finiscono nello Stato.md dello spazio) e nel diario del
    giorno <memoria>/Diario/AAAA-MM-GG.md. chi = id o nome del progetto, o la sua voce di spazi.json."""
    d = carica_spazi()
    if isinstance(chi, dict):
        p = chi
        s = next((x for x in d["spazi"] if any(q.get("id") == p.get("id") for q in x.get("progetti", []))), None)
    else:
        s, p = trova_progetto(d, chi)
    if not p:
        return False
    s_nome = (s or {}).get("nome") or p.get("spazio") or p["nome"]
    ora = adesso()
    cart = _esp(p["cartella"])
    try:
        f = cart / ".claude" / "memoria" / "azioni.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps({"ora": ora, "testo": testo}, ensure_ascii=False) + "\n")
        dg = memoria() / "Diario" / f"{ora[:10]}.md"
        dg.parent.mkdir(parents=True, exist_ok=True)
        testa = "" if dg.is_file() else f"# Diario · {ora[:10]}\n\nLo scrivono da soli i ganci e il Command Center.\n\n"
        with open(dg, "a", encoding="utf-8") as h:
            h.write(testa + f"- {ora[11:]} · azione · {s_nome} / {p['nome']} · {testo}\n")
    except OSError:
        return False
    if aggiorna_stato and s:
        try:
            g = _gancio_stato()
            percorsi = {"memoria": str(memoria()), "repo": str(REPO)}
            for sp in g.spazi_json(percorsi):
                if sp["nome"] == s["nome"]:
                    g.aggiorna_spazio(percorsi, sp, "azione")
        except Exception:  # noqa: BLE001  — lo Stato.md si riallinea comunque al giro dopo
            pass
    return True


# ---------------------------------------------------------------- indice dei file caricati
def _cos_e(f):
    est = f.suffix.lower()
    tipi = {".pdf": "PDF", ".doc": "Word", ".docx": "Word", ".xls": "Excel", ".xlsx": "Excel", ".csv": "tabella CSV",
            ".ppt": "presentazione", ".pptx": "presentazione", ".png": "immagine", ".jpg": "immagine",
            ".jpeg": "immagine", ".gif": "immagine", ".webp": "immagine", ".heic": "immagine", ".mp3": "audio",
            ".m4a": "audio", ".wav": "audio", ".mp4": "video", ".mov": "video", ".zip": "archivio",
            ".json": "dati JSON", ".md": "nota", ".txt": "testo", ".html": "pagina web", ".py": "codice Python",
            ".js": "codice JavaScript", ".eml": "mail"}
    tipo = tipi.get(est, f"file {est[1:]}" if est else "file")
    if est in (".md", ".txt", ".csv", ".json", ".py", ".js", ".html"):
        try:
            with open(f, encoding="utf-8", errors="ignore") as h:
                prima = next((r.strip() for r in h if r.strip()), "")
            if prima:
                tipo += ": " + " ".join(prima.lstrip("#").split())[:70]
        except OSError:
            pass
    return tipo


def _misura(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} TB"


def aggiorna_indice(cartella, prova=False):
    """Riscrive <cartella>/Indice-file.md dai file in <cartella>/File/ (nome, data, cosa è, peso).
    Torna l'elenco dei cambi («arrivato: x», «cambiato: x», «tolto: x»), vuoto se niente è cambiato.
    La data di arrivo di ogni file resta in .claude/memoria/indice-file.json."""
    cartella = Path(cartella)
    dentro = cartella / "File"
    cache_f = cartella / ".claude" / "memoria" / "indice-file.json"
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    voci, cambi = [], []
    if dentro.is_dir():
        for f in sorted(dentro.rglob("*")):
            if not f.is_file() or f.name in ESCLUSI_INDICE or any(x.startswith(".") for x in f.relative_to(dentro).parts):
                continue
            rel = f.relative_to(dentro).as_posix()
            st = f.stat()
            c = cache.get(rel) or {}
            if c.get("mtime") != st.st_mtime or c.get("byte") != st.st_size:
                cambi.append(("cambiato: " if c else "arrivato: ") + rel)
                c = {"arrivato": c.get("arrivato") or time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                     "mtime": st.st_mtime, "byte": st.st_size, "cos_e": _cos_e(f)}
            cache[rel] = c
            voci.append((rel, c))
    cambi += [f"tolto: {k}" for k in cache if k not in {r for r, _ in voci}]
    cache = {k: v for k, v in cache.items() if k in {r for r, _ in voci}}
    righe = ["# Indice dei file", "",
             f"Cartella: `{corto(dentro)}`. Lo aggiorna da solo il sistema quando arrivano, cambiano o spariscono file:",
             "non modificarlo a mano. Il capogruppo lo legge all'inizio di ogni lavoro.", "",
             f"File: {len(voci)}", ""]
    if voci:
        righe += ["| File | Arrivato | Cosa è | Peso |", "|---|---|---|---|"]
        righe += [f"| `{r}` | {c['arrivato']} | {c['cos_e'].replace('|', '/')} | {_misura(c['byte'])} |" for r, c in voci]
    else:
        righe.append("_Nessun file ancora. Caricali dalla pagina del progetto nel Command Center o copiali in `File/`._")
    testo = "\n".join(righe) + "\n"
    f = cartella / "Indice-file.md"
    vecchio = f.read_text(encoding="utf-8") if f.is_file() else None
    if vecchio == testo:
        return []
    if not prova:
        cartella.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(".Indice-file.md.tmp")
        tmp.write_text(testo, encoding="utf-8")
        os.replace(tmp, f)
        cache_f.parent.mkdir(parents=True, exist_ok=True)
        cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cambi or ["indice riscritto"]


# ---------------------------------------------------------------- crea
def crea(nome, spazio=None, cartella=None, descrizione="", modello="sonnet", prova=False):
    nome = " ".join(str(nome or "").split())[:60]
    if not nome or nome.startswith(".") or "/" in nome or "\\" in nome:
        raise SystemExit("nome del progetto non valido")
    if modello not in MODELLI:
        raise SystemExit("modello del capogruppo: haiku, sonnet o opus")
    L = Lavoro(prova)
    d = carica_spazi()
    s_es, p_es = trova_progetto(d, nome)
    pid = p_es["id"] if p_es else slug(nome)
    if not p_es and any(p.get("id") == pid for s in d["spazi"] for p in s.get("progetti", [])):
        raise SystemExit(f"l'id «{pid}» è già usato da un altro progetto: scegli un nome diverso")
    nome_spazio = (s_es["nome"] if s_es else None) or " ".join(str(spazio or nome).split())[:60]
    sp = s_es or trova_spazio(d, nome_spazio)
    if p_es:
        cart = _esp(p_es["cartella"])
        if cartella and _esp(cartella).expanduser().resolve() != cart.resolve():
            raise SystemExit(f"«{nome}» esiste già con la cartella {cart}: per cambiarla usa --sposta")
    else:
        cart = _esp(cartella).expanduser() if cartella else radice_progetti() / nome
        if cartella and not cart.is_absolute():
            cart = Path.cwd() / cart
        if cart.exists() and not cart.is_dir():
            raise SystemExit(f"{cart} esiste ed è un file")
        for s in d["spazi"]:
            for p in s.get("progetti", []):
                try:
                    if _esp(p["cartella"]).resolve() == cart.resolve():
                        raise SystemExit(f"la cartella {cart} è già del progetto «{p['nome']}»")
                except OSError:
                    pass
    capo = (p_es or {}).get("capogruppo") or f"{pid}-ceo"
    mem = memoria()
    cart_spazio = (sp or {}).get("cartella_nome") or nome_spazio
    m_spazio = mem / cart_spazio

    # 1. spazi.json
    voce = p_es or {"id": pid, "nome": nome, "cartella": corto(cart), "capogruppo": capo,
                    "descrizione": descrizione or "", "creato": adesso(), "sezioni_memoria": [cart_spazio]}
    if not sp:
        sid = slug(nome_spazio)
        if any(s.get("id") == sid for s in d["spazi"]):
            sid = f"{sid}-{len(d['spazi']) + 1}"
        sp = {"id": sid, "nome": nome_spazio, "memoria": corto(m_spazio / f"{cart_spazio}.md"),
              "report": corto(m_spazio / "Report"), "progetti": []}
        d["spazi"].append(sp)
    if not p_es:
        sp.setdefault("progetti", []).append(voce)
        L.salva_spazi(d, f"progetto «{nome}» nello spazio «{nome_spazio}»")
    else:
        L.saltate.append(f"c'è già in spazi.json: {nome} (spazio {nome_spazio})")

    # 2. memoria dello spazio
    L.cartella(m_spazio)
    L.cartella(m_spazio / "Report")
    L.scrivi(m_spazio / "Stato.md", testo_stato(cart_spazio))
    L.scrivi(m_spazio / "Decisioni.md", testo_decisioni(cart_spazio))
    porta = m_spazio / f"{cart_spazio}.md"
    if porta.is_file():                         # la porta elenca i progetti: si aggiunge solo la riga che manca
        t = porta.read_text(encoding="utf-8")
        if f"**{voce['nome']}**" not in t:
            L.scrivi(porta, t.rstrip("\n") + f"\n- **{voce['nome']}**: `{voce['cartella']}` · capogruppo `{capo}`\n",
                     sovrascrivi=True)
        else:
            L.saltate.append(f"c'è già: {porta}")
    else:
        L.scrivi(porta, testo_porta(cart_spazio, sp.get("progetti") or [voce]))

    # 3. cartella del progetto
    L.cartella(cart)
    L.cartella(cart / "File")
    L.cartella(cart / ".claude" / "agents")
    L.cartella(cart / ".claude" / "memoria" / "agenti")
    L.scrivi(cart / ".claude" / "memoria" / "MEMORIA.md", testo_memoria_progetto(voce["nome"]))
    if not (cart / "Indice-file.md").is_file():
        L.fatte.append(f"scrive {cart / 'Indice-file.md'}")
        aggiorna_indice(cart, prova=prova)
    else:
        L.saltate.append(f"c'è già: {cart / 'Indice-file.md'}")

    # 3b. se la cartella è un repo git: a ogni commit e push lo stato si salva da solo (ganci senza sovrascrivere)
    if (cart / ".git").exists():
        sys.path.insert(0, str(QUI))
        import ganci_git
        for nome, cosa in ganci_git.installa(cart, prova=prova):
            (L.saltate if cosa == "già a posto" else L.fatte).append(f"gancio git {nome}: {cosa}")

    # 4. capogruppo
    sys.path.insert(0, str(QUI))
    import crea_agente
    missione = (f"Capogruppo di «{voce['nome']}»: conosce la cartella del progetto e i file caricati, divide il lavoro, "
                "crea gli specialisti che servono, verifica i risultati e riferisce all'assistente.")
    if descrizione:
        missione += f" Il progetto serve a: {' '.join(descrizione.split())[:300]}"
    crea_agente.scrivi_agente(L, progetto=voce, spazio=sp, nome=capo, missione=missione, modello=modello,
                              capogruppo="", ceo=True)
    if L.fatte and not prova:
        registra_azione(pid, ("progetto creato" if not p_es else "progetto completato") + f" con il capogruppo {capo}"
                        + (f" ({len(L.fatte)} operazioni)" if p_es else ""))
    return {"progetto": voce["nome"], "id": pid, "spazio": nome_spazio, "cartella": str(cart), "capogruppo": capo,
            "memoria": str(m_spazio), "fatte": L.fatte, "saltate": L.saltate, "prova": prova}


# ---------------------------------------------------------------- altre operazioni
def rinomina(chi, nuovo, prova=False):
    L = Lavoro(prova)
    d = carica_spazi()
    s, p = trova_progetto(d, chi)
    if not p:
        raise SystemExit(f"progetto «{chi}» non trovato")
    nuovo = " ".join(str(nuovo).split())[:60]
    if not nuovo or "/" in nuovo:
        raise SystemExit("nome non valido")
    vecchio = p["nome"]
    p["nome"] = nuovo
    L.salva_spazi(d, f"progetto «{chi}» rinominato in «{nuovo}» (id, cartella e agenti restano)")
    if not prova and L.fatte:
        registra_azione(p["id"], f"progetto rinominato: «{vecchio}» → «{nuovo}»")
    return L


def sposta(chi, cartella, prova=False):
    L = Lavoro(prova)
    d = carica_spazi()
    s, p = trova_progetto(d, chi)
    if not p:
        raise SystemExit(f"progetto «{chi}» non trovato")
    vecchia, nuova = _esp(p["cartella"]), _esp(cartella).expanduser()
    if nuova.exists():
        raise SystemExit(f"{nuova} esiste già: scegline una nuova")
    L.fatte.append(f"sposta {vecchia} → {nuova}")
    if not prova:
        nuova.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(vecchia), str(nuova))
    p["cartella"] = corto(nuova)
    L.salva_spazi(d, f"cartella di «{p['nome']}» → {p['cartella']}")
    if not prova:
        registra_azione(p["id"], f"cartella spostata in {p['cartella']}")
    return L


def archivia(chi, prova=False):
    """Toglie il progetto da spazi.json e lo mette in «archiviati» (cartella, agenti e memoria restano)."""
    L = Lavoro(prova)
    d = carica_spazi()
    s, p = trova_progetto(d, chi)
    if not p:
        raise SystemExit(f"progetto «{chi}» non trovato")
    if not prova:                                 # prima di uscire da spazi.json: riga nello Stato.md e nel diario
        registra_azione(p["id"], "progetto archiviato (cartella, agenti e memoria restano)")
    s["progetti"] = [x for x in s["progetti"] if x is not p]
    d.setdefault("archiviati", []).append({**p, "spazio": s["id"], "archiviato": adesso()})
    if not s["progetti"]:
        d["spazi"] = [x for x in d["spazi"] if x is not s]
        d["archiviati"][-1]["spazio_intero"] = {k: v for k, v in s.items() if k != "progetti"}
    L.salva_spazi(d, f"progetto «{p['nome']}» archiviato (i file restano in {p['cartella']})")
    return L


def ripristina(chi, prova=False):
    L = Lavoro(prova)
    d = carica_spazi()
    k = slug(chi)
    a = next((x for x in d.get("archiviati", []) if x.get("id") in (chi, k)), None)
    if not a:
        raise SystemExit(f"nessun progetto archiviato «{chi}»")
    d["archiviati"].remove(a)
    sid, intero = a.pop("spazio"), a.pop("spazio_intero", None)
    a.pop("archiviato", None)
    s = next((x for x in d["spazi"] if x["id"] == sid), None)
    if not s:
        s = {**(intero or {"id": sid, "nome": a["nome"]}), "progetti": []}
        d["spazi"].append(s)
    s["progetti"].append(a)
    L.salva_spazi(d, f"progetto «{a['nome']}» ripristinato")
    if not prova:
        registra_azione(a["id"], "progetto ripristinato dall'archivio")
    return L


def elenco():
    d = carica_spazi()
    if not d["spazi"]:
        print("Nessun progetto ancora. Per crearne uno: python3 strumenti/crea_progetto.py \"<nome>\"")
        return
    for s in d["spazi"]:
        print(f"spazio «{s['nome']}»")
        for p in s.get("progetti", []):
            ag = _esp(p["cartella"]) / ".claude" / "agents"
            n = len([f for f in ag.glob("*.md")]) if ag.is_dir() else 0
            print(f"  - {p['nome']} [{p['id']}] · {p['cartella']} · capogruppo {p.get('capogruppo') or '-'} · {n} agenti")
    for a in d.get("archiviati", []):
        print(f"  (archiviato) {a['nome']} [{a['id']}] · {a['cartella']}")


def _opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        raise SystemExit(f"{nome} vuole un valore")
    return predefinito


def _stampa(L, titolo):
    print(titolo + (" · PROVA: non scrivo niente" if L.prova else ""))
    for x in L.fatte:
        print(("  farei: " if L.prova else "  fatto: ") + x)
    if not L.fatte:
        print("  niente da fare: è già tutto a posto")


def main():
    a = sys.argv[1:]
    prova = "--prova" in a
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return
    if "--elenco" in a:
        return elenco()
    for op, fn in (("--rinomina", rinomina), ("--sposta", sposta)):
        if op in a:
            i = a.index(op)
            if len(a) < i + 3:
                raise SystemExit(f"uso: {op} <progetto> <valore>")
            return _stampa(fn(a[i + 1], a[i + 2], prova), f"{op[2:]} {a[i + 1]}")
    for op, fn in (("--archivia", archivia), ("--ripristina", ripristina)):
        if op in a:
            return _stampa(fn(_opzione(op), prova), f"{op[2:]} {_opzione(op)}")
    if "--indice" in a:
        _, p = trova_progetto(carica_spazi(), _opzione("--indice"))
        if not p:
            raise SystemExit("progetto non trovato")
        cambiato = aggiorna_indice(_esp(p["cartella"]), prova=prova)
        if cambiato and not prova:
            registra_azione(p["id"], "file: " + "; ".join(cambiato[:10]))
        print(f"Indice-file.md di «{p['nome']}»: " + ("aggiornato" if cambiato else "già aggiornato"))
        return
    valori = {"--spazio", "--cartella", "--descrizione", "--modello"}
    nome = next((x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] not in valori)), None)
    r = crea(nome, spazio=_opzione("--spazio"), cartella=_opzione("--cartella"),
             descrizione=_opzione("--descrizione", ""), modello=_opzione("--modello", "sonnet"), prova=prova)
    if "--json" in a:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"Progetto «{r['progetto']}» [{r['id']}] · spazio «{r['spazio']}» · {adesso()}"
          + (" · PROVA: non scrivo niente" if prova else ""))
    for x in r["fatte"]:
        print(("  farei: " if prova else "  fatto: ") + x)
    print(f"  già a posto: {len(r['saltate'])} cose" if r["saltate"] else "")
    if not r["fatte"]:
        print("  niente da fare: è già tutto a posto")
    print(f"  cartella: {r['cartella']}\n  capogruppo: {r['capogruppo']}\n  memoria: {r['memoria']}/Stato.md")


if __name__ == "__main__":
    main()
