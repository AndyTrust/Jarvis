#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Prova completa di «Jarvis da zero» su una casa finta (agente mac-zero, 2026-10-10).

    python3 strumenti/prova_da_zero.py <cartella del prodotto> <cartella di lavoro della prova> [--porta 7797]

Ogni passo stampa «OK»/«NO» e il dato che lo dimostra. Nessuna scrittura fuori dalla cartella di lavoro:
HOME, JARVIS_* e CLAUDE_HOME puntano tutti lì. Alla fine controlla che ~/.claude e ~/.jarvis veri non abbiano
file nuovi o cambiati da questa prova.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if len([a for a in sys.argv[1:] if not a.startswith("--")]) < 2:
    print(__doc__)                       # senza cartelle non prova niente (e non è un errore: lo lancia anche il giro delle prove)
    sys.exit(0)
PRODOTTO = Path(sys.argv[1]).resolve()
LAVORO = Path(sys.argv[2]).resolve()
PORTA = int(sys.argv[sys.argv.index("--porta") + 1]) if "--porta" in sys.argv else 7797
import socket
with socket.socket() as _s:
    if _s.connect_ex(("127.0.0.1", PORTA)) == 0:
        sys.exit(f"la porta {PORTA} è occupata da un altro processo: scegline un'altra con --porta")
VERA = Path("/Users") / os.environ.get("USER", "") if sys.platform == "darwin" else Path.home()
esiti = []


def ok(nome, cond, dato=""):
    esiti.append(bool(cond))
    print(("OK  " if cond else "NO  ") + nome + (f"  ·  {str(dato)[:300]}" if dato != "" else ""), flush=True)


def sh(cmd, env=None, cwd=None, timeout=300, inp=None):
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout, input=inp)
    return r.returncode, (r.stdout + r.stderr)


# ---------------------------------------------------------------- 0. impronta dei veri ~/.claude e ~/.jarvis
segno = LAVORO / ".inizio"
if LAVORO.exists():
    shutil.rmtree(LAVORO)
LAVORO.mkdir(parents=True)
segno.write_text("x")
time.sleep(1.1)
VERI = [VERA / ".jarvis", VERA / ".claude" / "hooks", VERA / ".claude" / "skills", VERA / ".claude" / "agents",
        VERA / ".claude" / "commands", VERA / ".claude" / "settings.json"]


def impronta():
    out = {}
    for v in VERI:
        for f in ([v] if v.is_file() else v.rglob("*") if v.is_dir() else []):
            try:
                if f.is_file():
                    out[str(f)] = (f.stat().st_size, f.stat().st_mtime)
            except OSError:
                pass
    return out


prima = impronta()

# ---------------------------------------------------------------- 1. casa finta e installazione da zero
CASA = LAVORO / "casa"
REPO = CASA / "Jarvis"
shutil.copytree(PRODOTTO, REPO, ignore=shutil.ignore_patterns(".git", "__pycache__", "spazi.json", "pannello.json*",
                                                              "profilo-jarvis.md", "configurazione.json"))
subprocess.run(["git", "init", "-q", str(REPO)])
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("JARVIS_", "CLAUDE_", "CC_"))}
ENV.update({"HOME": str(CASA), "JARVIS_ATTIVITA_DIR": str(CASA / "attivita"), "PYTHONDONTWRITEBYTECODE": "1"})
(CASA / ".jarvis").mkdir(parents=True)
risposte = json.loads((REPO / "docs" / "risposte-avvio.esempio.json").read_text())
risposte.update({"come_chiamarti": "Marta", "nome_assistente": "Ada", "avvio": "zero", "primo_progetto": None,
                 "creazione": "piano", "harness": ["claude"]})
risposte.pop("_nota", None)
(CASA / ".jarvis" / "risposte-avvio.json").write_text(json.dumps(risposte, ensure_ascii=False, indent=1))
c, out = sh([sys.executable, str(REPO / "strumenti" / "installa_guidata.py"), "--prova", "--senza-brew", "--senza-venv"], ENV)
ok("1a installa_guidata --prova finisce", c == 0, out.strip().splitlines()[-1] if out.strip() else "")
ok("1b --prova non crea spazi.json né la memoria", not (REPO / "command-center" / "spazi.json").exists()
   and not (CASA / "Jarvis-Memoria").exists())
c, out = sh([sys.executable, str(REPO / "strumenti" / "installa_guidata.py"), "--senza-brew", "--senza-venv", "--si"], ENV, timeout=600)
(LAVORO / "uscita-installazione.txt").write_text(out)
ok("1c installazione reale finisce", c == 0 and (CASA / ".jarvis" / "installato.json").is_file(), out.strip().splitlines()[-1])
sp = json.loads((REPO / "command-center" / "spazi.json").read_text())
ok("1d si parte da zero: spazi.json vuoto", sp.get("spazi") == [], sp)
ok("1e «si parte da zero» detto nel passo 7b", "si parte da zero" in out)
mem = CASA / "Jarvis-Memoria"
ok("1f memoria condivisa creata (Comune/Memoria.md, Diario/, Sessioni/, Claude/projects/)",
   all((mem / x).exists() for x in ("Comune/Memoria.md", "Diario", "Sessioni", "Claude/projects")), sorted(p.name for p in mem.iterdir()))
pj = json.loads((CASA / ".jarvis" / "percorsi.json").read_text())
ok("1g percorsi.json senza spazi, con memoria e progetti", "spazi" not in pj and pj.get("memoria") and pj.get("progetti"), pj.get("memoria"))
ok("1h ganci e skill installati nella casa finta (conferma_salva, stato_avanzamento, nuovo-progetto, /nuovo-agente)",
   all((CASA / ".claude" / x).exists() for x in ("hooks/conferma_salva.py", "hooks/stato_avanzamento.py",
                                                 "skills/nuovo-progetto/SKILL.md", "skills/aggiorna-memoria/SKILL.md",
                                                 "commands/nuovo-progetto.md", "commands/nuovo-agente.md")))
st = json.loads((CASA / ".claude" / "settings.json").read_text())
cmds = json.dumps(st.get("hooks", {}))
ok("1i settings.json finto: UserPromptSubmit conferma_salva, Stop/PreCompact/SessionEnd stato_avanzamento",
   "conferma_salva.py" in cmds and cmds.count("stato_avanzamento.py") >= 3)
ok("1j ganci git nel repo di Jarvis (post-commit, pre-push)",
   all("jarvis-stato:inizio" in (REPO / ".git" / "hooks" / g).read_text() for g in ("post-commit", "pre-push")))
c, out = sh([sys.executable, str(REPO / "strumenti" / "installa_guidata.py"), "--senza-brew", "--senza-venv", "--si"], ENV, timeout=600)
ok("1k secondo giro dell'installazione: spazi.json resta vuoto (idempotente)", c == 0 and
   json.loads((REPO / "command-center" / "spazi.json").read_text()).get("spazi") == [])

# ---------------------------------------------------------------- 2. Command Center con zero progetti
srv = subprocess.Popen([sys.executable, str(REPO / "command-center" / "server.py")], cwd=str(REPO / "command-center"),
                       env={**ENV, "CC_PORTA": str(PORTA), "CC_PROVA": "1"}, stdout=open(LAVORO / "server.log", "w"),
                       stderr=subprocess.STDOUT)
BASE = f"http://127.0.0.1:{PORTA}"
TOKEN = ""


def get(p, tetto=20):
    req = urllib.request.Request(BASE + p, headers={"X-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=tetto) as r:
        return r.status, r.read().decode("utf-8", "replace")


def post(p, corpo, tetto=60):
    req = urllib.request.Request(BASE + p, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": TOKEN, "Origin": BASE})
    try:
        with urllib.request.urlopen(req, timeout=tetto) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


for _ in range(60):
    try:
        s_, html = get("/")
        TOKEN = re.search(r"[\"']([A-Za-z0-9_-]{30,})[\"']", html.split("CC_TOKEN", 1)[1]).group(1) if "CC_TOKEN" in html else ""
        break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
try:
    ok("2a pagina / risponde 200 con il token", s_ == 200 and TOKEN, len(html))
    s_, t = get("/api/spazi")
    d = json.loads(t)
    ok("2b /api/spazi con zero progetti: elenco vuoto, nessun errore", s_ == 200 and d["spazi"] == [], {k: d[k] for k in ("spazi", "memoria_radice", "assistente")})
    for p in ("/api/stato", "/api/catalogo", "/api/pannello", "/api/missioni", "/api/routine", "/api/scadenze", "/api/riallineo"):
        try:
            s_, t = get(p, 40)
            ok(f"2c {p} con zero progetti risponde {s_}", s_ == 200, t[:120])
        except urllib.error.HTTPError as e:
            ok(f"2c {p} con zero progetti", e.code in (404,) and p in ("/api/missioni", "/api/routine"), f"{e.code}")
    s_, t = get("/static/app.js")
    ok("2d app.js servito: stato vuoto «Nessun progetto ancora» presente", "Nessun progetto ancora" in t)
    ok("P1 «Crea il tuo primo progetto» e modulo apribile con zero agenti (profiliNuovi sempre vero)",
       "Crea il tuo primo progetto" in t and "const profiliNuovi = () => true;" in t)
    ok("P2 colonna agenti: stato vuoto dopo la lettura, non «lettura degli agenti…» per sempre",
       "SPAZI_LETTI ? statoVuotoProgetti(true)" in t)
    ok("P8 il terminale non si accende da solo: conferma esplicita, nessun avvio in termApri/termScegli",
       "TERM_CONFERMATO" in t and "if (s && s.installato && !(modi[termModo]" not in t and "termAccendi($(\"term-accendi\"), m)" not in t)
    ok("P7 primo caricamento: caricaSpazi all'avvio e riprova", "caricaSpazi();       // 2026-10-10" in t and "SPAZI_API_OK" in t)
    _, t = get("/api/spazi")
    d = json.loads(t)
    ok("P3/P4 nomi dal profilo: assistente Ada, utente Marta", d.get("assistente") == "Ada" and d.get("utente") == "Marta",
       {k: d.get(k) for k in ("assistente", "utente")})
    for rotta in ("/_ponte/stato", "/api/incarichi", "/api/assistenza/tecnico/stato", "/api/agenti/allineamento?lavagna=generale"):
        try:
            s_, t = get(rotta)
            ok(f"P10 {rotta} con zero progetti: 200, «non attivo» (nessun errore in console)", s_ == 200, t[:100])
        except urllib.error.HTTPError as e:
            ok(f"P10 {rotta} con zero progetti", False, e.code)
    _, t = get("/api/stato")
    st0 = json.loads(t)
    ok("P9 Telegram non configurato: niente righe né segnalazioni", all((st0.get("telegram") or {}).get(x, {}).get("non_configurato") for x in ("mac", "vps")))
    conf = json.loads((REPO / "command-center" / "configurazione.json").read_text())
    ok("P9 configurazione di partenza senza siti, collegamenti e verifiche dell'autore",
       conf.get("siti") == {} and conf.get("collegamenti") == {} and conf.get("verifiche") == [])
    att = [s for s in (st0.get("sentinella") or {}).get("anomalie", []) if "battito" in str(s)]
    ok("P9 nessuna anomalia «battito mai passato» con il giro non acceso", not att, att[:1])
    rac = (st0.get("salute") or {}).get("raccoglitori") or []
    rac = rac.items() if isinstance(rac, dict) else [(x.get("nome") or x.get("id"), x) for x in rac if isinstance(x, dict)]
    sal = [f"{k}: {str(v.get('errore'))[:80]}" for k, v in rac if isinstance(v, dict) and v.get("errore")]
    ok("P10 salute del pannello: nessun raccoglitore in errore", not sal, sal)

    # ------------------------------------------------------------ 2e. zero progetti: gli strumenti dei gruppi non danno errore
    for nome, cmd in (("riunione elenco", ["strumenti/riunione.py", "elenco"]), ("giro notturno", ["strumenti/giro_apprendimento.py", "--secco"]),
                      ("stato_vault", ["strumenti/stato_vault.py"]), ("controlla sincronia", ["sincro/controlla.py"]),
                      ("quaderni", ["strumenti/quaderno.py", "elenco"]), ("crea_progetto --elenco", ["strumenti/crea_progetto.py", "--elenco"])):
        c, out = sh([sys.executable, str(REPO / cmd[0])] + cmd[1:], ENV)
        ok(f"2e zero progetti · {nome}: esce 0 senza errori", c == 0 and "Traceback" not in out, out.strip().splitlines()[-1] if out.strip() else "(niente da dire)")
    ev0 = {"hook_event_name": "SessionEnd", "cwd": str(CASA), "session_id": "prova-zero"}
    c, out = sh([sys.executable, str(CASA / ".claude/hooks/stato_avanzamento.py")], ENV, inp=json.dumps(ev0))
    ok("2f zero progetti · gancio di stato: esce 0, solo la riga in Sessioni/", c == 0 and any((mem / "Sessioni").glob("*.md")))

    # ------------------------------------------------------------ 3. crea_progetto due volte, due progetti
    CP = [sys.executable, str(REPO / "strumenti" / "crea_progetto.py")]
    c, out = sh(CP + ["Sito Vetrina", "--descrizione", "sito di presentazione", "--prova"], ENV)
    ok("3a crea_progetto --prova non scrive", c == 0 and json.loads((REPO / "command-center" / "spazi.json").read_text())["spazi"] == []
       and "farei:" in out)
    t0 = time.time()
    c, out = sh(CP + ["Sito Vetrina", "--descrizione", "sito di presentazione"], ENV)
    (LAVORO / "uscita-crea-progetto-1.txt").write_text(out)
    ok("3b crea_progetto «Sito Vetrina»", c == 0, out.splitlines()[0])
    c, out2 = sh(CP + ["Sito Vetrina"], ENV)
    ok("3c secondo lancio identico: niente da fare (idempotente)", c == 0 and "niente da fare" in out2, out2.splitlines()[1])
    # un repo git già esistente: i ganci si aggiungono senza toccare quello che c'è
    rep2 = CASA / "Lavori" / "Ricette"
    rep2.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(rep2)])
    (rep2 / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\necho gancio-mio\nexit 0\n")
    c, out = sh(CP + ["Ricettario", "--cartella", str(rep2), "--spazio", "Cucina"], ENV)
    ok("3d secondo progetto in una cartella git esistente, spazio «Cucina»", c == 0, out.splitlines()[0])
    pp = (rep2 / ".git" / "hooks" / "pre-push").read_text()
    ok("3e gancio pre-push esistente conservato, blocco di Jarvis in testa", "gancio-mio" in pp and pp.index("jarvis-stato") < pp.index("gancio-mio"))
    sp = json.loads((REPO / "command-center" / "spazi.json").read_text())
    nomi = sorted(p["nome"] for s in sp["spazi"] for p in s["progetti"])
    ok("3f spazi.json ha SOLO i due progetti creati", nomi == ["Ricettario", "Sito Vetrina"], nomi)
    vetrina = CASA / "Progetti" / "Sito Vetrina"
    ok("3g cartella, File/, Indice-file.md, MEMORIA.md, capogruppo, diario del capogruppo",
       all((vetrina / x).exists() for x in ("File", "Indice-file.md", ".claude/memoria/MEMORIA.md",
                                             ".claude/agents/sito-vetrina-ceo.md", ".claude/memoria/agenti/sito-vetrina-ceo.md")))
    ok("3h memoria dello spazio: Stato.md, porta, Decisioni.md, Report/",
       all((mem / "Sito Vetrina" / x).exists() for x in ("Stato.md", "Sito Vetrina.md", "Decisioni.md", "Report"))
       and (mem / "Cucina" / "Stato.md").exists())
    diario = (vetrina / ".claude/memoria/agenti/sito-vetrina-ceo.md").read_text()
    ok("3i il diario nasce con FATTO / DA FARE / ERRORI COMMESSI DA NON RIPETERE",
       all(x in diario for x in ("## Fatto", "## Da fare", "## Errori commessi da non ripetere")))

    # ------------------------------------------------------------ 4. la lavagna e il menu si allineano da soli
    def attendi(cond, tetto=15):
        t0 = time.time()
        while time.time() - t0 < tetto:
            try:
                if cond():
                    return round(time.time() - t0, 2)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.25)
        return None

    def sulla_lavagna(chiave):
        _, t = get("/api/pannello")
        p = json.loads(t)
        return any(n.get("agente") == chiave for L in (p.get("lavagne") or {}).values() for n in L.get("nodi") or [])

    rit = attendi(lambda: sulla_lavagna("sito-vetrina:sito-vetrina-ceo") and sulla_lavagna("ricettario:ricettario-ceo"))
    ok("4a capogruppo dei due progetti sulla lavagna senza ricaricare (ritardo in s)", rit is not None, rit)
    _, t = get("/api/pannello")
    orch = [n.get("testo") for L in (json.loads(t).get("lavagne") or {}).values() for n in L.get("nodi") or []
            if "orchestratore" in str(n.get("testo"))]
    ok("P4 un solo orchestratore sulla lavagna, col nome del profilo", orch == ["Ada — orchestratore"], orch)
    _, t = get("/api/spazi")
    ok("4b menu agenti (/api/spazi) elenca i due progetti", sorted(p["nome"] for s in json.loads(t)["spazi"] for p in s["progetti"]) == nomi)
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_agente.py"), "Sito Vetrina", "copywriter",
                 "--missione", "scrive i testi delle pagine partendo dai file in File/", "--limiti", "non pubblica niente"], ENV)
    ok("4c crea_agente copywriter", c == 0, out.splitlines()[0])
    t0 = time.time()
    rit = attendi(lambda: sulla_lavagna("sito-vetrina:copywriter"))
    ok("4d lo specialista compare sulla lavagna da solo (ritardo in s)", rit is not None, rit)
    _, t = get("/api/spazi")
    ag = [a["nome"] for s in json.loads(t)["spazi"] for p in s["progetti"] if p["id"] == "sito-vetrina" for a in p["agenti"]]
    ok("4e e nel menu agenti", "copywriter" in ag, ag)
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_agente.py"), "Sito Vetrina", "copy", "--missione", "corta"], ENV)
    ok("4f nessun agente senza missione chiara (rifiutato)", c != 0, out.strip()[:100])
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_agente.py"), "Sito Vetrina", "grafico", "--missione",
                 "prepara le immagini delle pagine del sito", "--modello", "opus"], ENV)
    ok("4g opus solo per programmare (rifiutato)", c != 0, out.strip()[:100])

    # ------------------------------------------------------------ 5. modifica missione dalla pagina e dalla riga di comando
    f_copy = vetrina / ".claude/agents/copywriter.md"
    s_, r = post("/api/agente-profilo", {"file": str(f_copy), "description": "scrive e corregge i testi delle pagine del sito",
                                        "limiti": "non pubblica e non manda mail"})
    testo = f_copy.read_text()
    ok("5a modifica missione e limiti dalla pagina: scheda vera riscritta con copia .bak",
       s_ == 200 and "scrive e corregge i testi" in testo and "non pubblica e non manda mail" in testo
       and list(f_copy.parent.glob("copywriter.md.bak-*")), r)
    _, t = get("/api/spazi")
    d_ag = next(a for s in json.loads(t)["spazi"] for p in s["progetti"] for a in p["agenti"] if a["nome"] == "copywriter")
    ok("5b il menu mostra la missione nuova", d_ag["descrizione"].startswith("scrive e corregge"), d_ag["descrizione"])

    # ------------------------------------------------------------ 6. file caricati e Indice-file.md
    import base64
    s_, r = post("/api/progetto/carica", {"progetto": "sito-vetrina", "nome": "listino.csv",
                                          "base64": base64.b64encode(b"prodotto,prezzo\nmela,1\n").decode()})
    ind = (vetrina / "Indice-file.md").read_text()
    ok("6a file caricato dalla pagina: in File/ e nell'indice subito", s_ == 200 and (vetrina / "File" / "listino.csv").exists()
       and "listino.csv" in ind, r)
    (vetrina / "File" / "note-cliente.md").write_text("# Note del cliente\ncolori caldi\n")
    t0 = time.time()
    rit = attendi(lambda: "note-cliente.md" in (vetrina / "Indice-file.md").read_text())
    ok("6b file copiato a mano in File/: Indice-file.md si aggiorna da solo (ritardo in s)", rit is not None, rit)
    ok("6c l'indice dice cosa è (prima riga della nota)", "Note del cliente" in (vetrina / "Indice-file.md").read_text())
    s_, t = get("/api/progetto/file?progetto=sito-vetrina")
    ok("6d /api/progetto/file elenca i due file", sorted(x["nome"] for x in json.loads(t)["file"]) == ["listino.csv", "note-cliente.md"])
    s_, r = post("/api/progetto/modifica", {"cosa": "descrizione", "progetto": "sito-vetrina", "valore": "vetrina del negozio di via Roma"})
    statot = lambda: (mem / "Sito Vetrina" / "Stato.md").read_text()
    oggi_d = mem / "Diario" / f"{time.strftime('%Y-%m-%d')}.md"
    rit = attendi(lambda: all(x in statot() for x in ("agente creato: copywriter", "file caricato dalla pagina: listino.csv",
                                                       "note-cliente.md", "descrizione cambiata", "scheda di copywriter modificata")))
    ok("P6 Stato.md registra agente creato, scheda cambiata, file caricato e copiato, descrizione (ritardo in s)", rit is not None,
       [l for l in statot().splitlines() if l.startswith("- 20")][-6:])
    dd_ = oggi_d.read_text() if oggi_d.is_file() else ""
    ok("P6 il diario del giorno ha le stesse azioni", all(x in dd_ for x in ("agente creato: copywriter", "listino.csv", "descrizione cambiata")),
       [l for l in dd_.splitlines() if "azione" in l][-4:])

    # ------------------------------------------------------------ 7. diario dell'agente, Stato.md e lavagna
    Q = [sys.executable, str(REPO / "strumenti" / "quaderno.py")]
    c, out = sh(Q + ["scrivi", "copywriter", "--fatto", "testi della home", "--da_fare", "pagina contatti",
                     "--errore", "ho letto un listino vecchio"], ENV)
    ok("7a lavoro simulato: l'agente scrive le tre sezioni del diario", c == 0, out.strip())
    stato = mem / "Sito Vetrina" / "Stato.md"
    rit = attendi(lambda: "testi della home" in stato.read_text())
    ok("7b Stato.md mostra il diario senza altre azioni (ritardo in s)", rit is not None, rit)
    s_, t = get("/api/diario?progetto=sito-vetrina&agente=copywriter")
    dd = json.loads(t)
    ok("7c la pagina dell'agente legge FATTO / DA FARE / ERRORI", [x[1] for x in dd["fatto"]] == ["testi della home"]
       and dd["da_fare"] and dd["errori"], {k: dd[k] for k in ("fatto", "da_fare", "errori")})
    nuovo = dd["testo"].replace("## Da fare\n", "## Da fare\n- 2026-10-09 18:00 · foto della vetrina\n")
    s_, r = post("/api/diario", {"progetto": "sito-vetrina", "agente": "copywriter", "testo": nuovo})
    rit = attendi(lambda: "foto della vetrina" in stato.read_text())
    ok("7d diario modificato dalla pagina: file vero (con .bak) e Stato.md aggiornati (ritardo in s)",
       s_ == 200 and rit is not None and list((vetrina / ".claude/memoria/agenti").glob("copywriter.md.bak-*")), rit)
    # errore ripetuto in due giorni diversi
    fq = vetrina / ".claude/memoria/agenti/copywriter.md"
    fq.write_text(fq.read_text().replace("## Errori commessi da non ripetere\n",
                                         "## Errori commessi da non ripetere\n- 2026-10-08 10:00 · ho letto un listino vecchio\n"))
    rit = attendi(lambda: "ERRORI RIPETUTI" in stato.read_text())
    ok("7e errore ripetuto due giorni: segnalato in Stato.md (ritardo in s)", rit is not None, rit)

    # ------------------------------------------------------------ 8. ganci: stato, diario del giorno, conferme, git
    HK = CASA / ".claude" / "hooks"
    ev = {"hook_event_name": "SessionEnd", "cwd": str(vetrina), "session_id": "prova-fine", "reason": "exit"}
    c, out = sh([sys.executable, str(HK / "stato_avanzamento.py")], ENV, inp=json.dumps(ev))
    oggi = time.strftime("%Y-%m-%d")
    dg = mem / "Diario" / f"{oggi}.md"
    ok("8a SessionEnd simulato: esce 0, Stato.md e diario del giorno", c == 0 and "SessionEnd" in stato.read_text() and dg.is_file()
       and "copywriter: testi della home" in dg.read_text())
    n_prima = dg.read_text()
    sh([sys.executable, str(HK / "stato_avanzamento.py")], ENV, inp=json.dumps({**ev, "hook_event_name": "PreCompact", "trigger": "auto"}))
    ok("8b PreCompact subito dopo: Stato.md aggiornato, diario muto (niente di nuovo)", "PreCompact" in stato.read_text() and dg.read_text() == n_prima)
    c, out = sh([sys.executable, str(HK / "conferma_salva.py")], ENV, inp=json.dumps({"prompt": "perfetto", "cwd": str(vetrina)}))
    ok("8c «perfetto»: il gancio inietta il salvataggio nello stesso turno", c == 0 and "aggiorna-memoria" in out and "additionalContext" in out)
    c, out = sh([sys.executable, str(HK / "conferma_salva.py")], ENV, inp=json.dumps({"prompt": "perfetto, ma perché il sito è lento?", "cwd": str(vetrina)}))
    ok("8d una domanda non è una conferma: niente", c == 0 and out.strip() == "")
    sh(["git", "-C", str(rep2), "add", "-A"], ENV)
    (CASA / "Lavori" / "Ricette" / ".claude" / "memoria" / "MEMORIA.md").write_text(
        (rep2 / ".claude/memoria/MEMORIA.md").read_text().replace("### Fatto\n", "### Fatto\n- prima ricetta caricata\n"))
    sh(["git", "-C", str(rep2), "add", "-A"], ENV)
    c, out = sh(["git", "-C", str(rep2), "-c", "user.email=prova@esempio.it", "-c", "user.name=Prova", "commit", "-qm", "prima"], ENV)
    rit = attendi(lambda: "post-commit" in (mem / "Cucina" / "Stato.md").read_text() and "prima ricetta caricata" in dg.read_text())
    ok("8e commit in un progetto: post-commit aggiorna Stato.md e diario del giorno (ritardo in s)", c == 0 and rit is not None, rit)

    # ------------------------------------------------------------ 9. riunione e giro notturno sui gruppi creati
    c, out = sh([sys.executable, str(REPO / "strumenti" / "riunione.py"), "elenco"], ENV)
    ok("9a riunione: i gruppi sono i progetti creati", c == 0 and "sito-vetrina" in out and "ricettario" in out, out.strip()[:200])
    c, out = sh([sys.executable, str(REPO / "strumenti" / "giro_apprendimento.py"), "--secco"], ENV)
    ok("9b giro notturno dei quaderni sui gruppi creati (esce 3 perché c'è l'errore ripetuto di 7e)",
       c == 3 and "Sito Vetrina" in out and "errori ripetuti 1" in out, out.strip()[:200])

    # ------------------------------------------------------------ 10. modifica e archivio del progetto
    s_, r = post("/api/progetto/modifica", {"cosa": "rinomina", "progetto": "ricettario", "valore": "Ricettario di casa"})
    _, t = get("/api/spazi")
    ok("10a rinomina dalla pagina: spazi.json e menu", s_ == 200 and any(p["nome"] == "Ricettario di casa" for s in json.loads(t)["spazi"] for p in s["progetti"]), r.get("messaggio"))
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_agente.py"), "Sito Vetrina", "copywriter", "--togli"], ENV)
    rit = attendi(lambda: not sulla_lavagna("sito-vetrina:copywriter"))
    ok("10b agente tolto: esce dalla lavagna da solo (ritardo in s)", c == 0 and rit is not None, rit)
    s_, r = post("/api/progetto/modifica", {"cosa": "archivia", "progetto": "ricettario"})
    _, t = get("/api/spazi")
    ok("10c archivia: il progetto esce dal menu, i file restano", s_ == 200 and not any(p["id"] == "ricettario" for s in json.loads(t)["spazi"] for p in s["progetti"])
       and (rep2 / ".claude/agents/ricettario-ceo.md").exists())
    def nota_cartella(parola):
        _, t = get("/api/pannello")
        return any(str(n.get("testo", "")).startswith("📁 ") and parola in str(n.get("testo")) for L in (json.loads(t).get("lavagne") or {}).values()
                   for n in L.get("nodi") or [])
    rit = attendi(lambda: not nota_cartella("Ricettario") and not sulla_lavagna("ricettario:ricettario-ceo"))
    ok("P5 archiviato: la scheda «📁» e il capogruppo escono dalla lavagna e da pannello.json (ritardo in s)", rit is not None, rit)
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_progetto.py"), "--ripristina", "ricettario"], ENV)
    rit = attendi(lambda: nota_cartella("Ricettario") and sulla_lavagna("ricettario:ricettario-ceo"))
    ok("P5 ripristinato: tornano da soli (ritardo in s)", c == 0 and rit is not None, rit)
    # terza passata: «Togli gruppo» e «Ripristina» dalla pagina scrivono Stato.md e diario come gli script
    s1, r1 = post("/api/azione", {"tipo": "agente", "cosa": "togli_gruppo", "progetto": "ricettario"})
    s2, r2 = post("/api/azione", {"tipo": "agente", "cosa": "ripristina_gruppo", "progetto": "ricettario"})
    st_c = (mem / "Cucina" / "Stato.md").read_text()
    dg_ = (mem / "Diario" / f"{time.strftime('%Y-%m-%d')}.md").read_text()
    ok("Q1 togli e ripristina gruppo dalla pagina: righe in Stato.md e nel diario", s1 == 200 and s2 == 200
       and "gruppo tolto dalla pagina" in st_c and "gruppo ripristinato dalla pagina" in st_c and "gruppo ripristinato dalla pagina" in dg_,
       (r1.get("messaggio"), r2.get("messaggio")))
    # spazi.json cambiato da riga di comando: l'evento «spazi» del flusso arriva da solo (prima poteva essere scambiato per nostro)
    import threading
    eventi_sse = []
    def ascolta():
        try:
            rq = urllib.request.Request(f"{BASE}/api/flusso?token={TOKEN}", headers={"X-Token": TOKEN})
            with urllib.request.urlopen(rq, timeout=12) as fl:
                t0 = time.time()
                while time.time() - t0 < 10:
                    riga = fl.readline().decode()
                    if riga.startswith("data") and '"spazi"' in riga:
                        eventi_sse.append(time.time())
        except Exception:  # noqa: BLE001
            pass
    th = threading.Thread(target=ascolta, daemon=True)
    th.start()
    time.sleep(1.5)
    eventi_sse.clear()
    c, out = sh([sys.executable, str(REPO / "strumenti" / "crea_progetto.py"), "--archivia", "ricettario"], ENV)
    fine_cli = time.time()
    rit = attendi(lambda: eventi_sse and eventi_sse[-1] >= fine_cli - 1, tetto=8)
    ok("Q2 archivio da riga di comando: evento «spazi» alle pagine senza ricaricare (ritardo in s, < 2)",
       c == 0 and rit is not None and rit < 2, rit)
    _, t = get("/api/spazi")
    arch = json.loads(t).get("progetti_archiviati") or []
    ok("Q3 /api/spazi elenca i progetti archiviati (pulsante «Ripristina» nella pagina)", any(a.get("id") == "ricettario" for a in arch), arch)
    s_, r = post("/api/progetto/modifica", {"cosa": "ripristina", "progetto": "ricettario"})
    _, t = get("/api/spazi")
    ok("Q3 «Ripristina» dalla pagina rimette il progetto", s_ == 200 and any(p["id"] == "ricettario" for s in json.loads(t)["spazi"] for p in s["progetti"]))
    _, js = get("/static/app.js")
    ok("Q3 la lavagna si centra da sola se nessuna scheda è in vista (375 px)", "centraSeFuoriVista" in js and "progetti-archiviati" in js)
    _, t = get("/api/stato")
    sess = ((json.loads(t).get("locale") or {}).get("agenti_sessioni") or {}).get("sessioni") or []
    fuori = [x for x in sess if not str(x.get("dove") or "").startswith("~")]
    ok("Q4 sessioni Claude: solo quelle nella casa di questo Jarvis (nessuna dell'host)", not fuori, fuori[:2])
    s_, r = post("/api/azione", {"tipo": "agente", "cosa": "crea_gruppo", "nome": "Dal Pannello", "description": "progetto creato dal modulo"})
    _, t = get("/api/spazi")
    ok("P1 il modulo «＋ Nuovo gruppo» crea un progetto dal pannello (stesso codice di crea_progetto.py)",
       s_ == 200 and any(p["nome"] == "Dal Pannello" and p["capogruppo"] == "dal-pannello-ceo" for s in json.loads(t)["spazi"] for p in s["progetti"]),
       r.get("messaggio") or r.get("errore"))
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except subprocess.TimeoutExpired:
        srv.kill()

# ---------------------------------------------------------------- 11. pulisci_claude su un ~/.claude finto
cl = CASA / ".claude"
vecchio = time.time() - 40 * 86400
pr = cl / "projects" / "-Users-prova-Progetti-x"
(pr / "memory").mkdir(parents=True)
(pr / "memory" / "nota.md").write_text("una cosa da ricordare")
chat = pr / "11111111-2222-3333-4444-555555555555.jsonl"
chat.write_text(json.dumps({"type": "user", "timestamp": "2026-08-31T09:00:00Z", "cwd": "/Users/prova/Progetti/x",
                            "message": {"content": "sistema il menu"}}) + "\n" +
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "menu sistemato"}]}}) + "\n")
os.utime(chat, (vecchio, vecchio))
recente = pr / "99999999-2222-3333-4444-555555555555.jsonl"
recente.write_text("{}\n")
(cl / "shell-snapshots").mkdir(exist_ok=True)
snap = cl / "shell-snapshots" / "snapshot-vecchio.sh"
snap.write_text("x")
os.utime(snap, (vecchio, vecchio))
(cl / "cache").mkdir(exist_ok=True)
(cl / "cache" / "model-catalog").write_text("{}")
os.utime(cl / "cache" / "model-catalog", (vecchio, vecchio))
PC = [sys.executable, str(REPO / "strumenti" / "pulisci_claude.py")]
c, out = sh(PC + ["--prova"], ENV)
(LAVORO / "uscita-pulizia-prova.txt").write_text(out)
ok("11a pulisci_claude --prova: elenca e non tocca niente", c == 0 and chat.exists() and snap.exists() and "Prova (niente scritto)" in out, out.strip().splitlines()[-1])
c, out = sh(PC + ["--applica"], ENV)
(LAVORO / "uscita-pulizia.txt").write_text(out)
arch = list((CASA / ".jarvis" / "archivio-chat").glob("*.tar.gz"))
dsett = mem / "Diario" / "2026-08-31.md"
ok("11b chat di 40 giorni: archiviata, riassunta nel diario, tolta", not chat.exists() and arch and dsett.is_file()
   and "sistema il menu" in dsett.read_text(), [a.name for a in arch])
ok("11c chat recente e memory/ intatte; memory unita alla memoria condivisa", recente.exists()
   and (pr / "memory" / "nota.md").exists() and (pr / "memory").is_symlink(), os.readlink(pr / "memory") if (pr / "memory").is_symlink() else "non collegata")
ok("11d snapshot vecchio tolto, cache del catalogo intatta", not snap.exists() and (cl / "cache" / "model-catalog").exists())

# ---------------------------------------------------------------- 12. niente scritto fuori dalla casa finta
dopo = impronta()
cambiati = [f for f in dopo if f not in prima or dopo[f] != prima[f]]
miei = [f for f in cambiati if str(LAVORO) in Path(f).read_text(errors="ignore")] if cambiati else []
ok("12a nei veri ~/.claude e ~/.jarvis nessun file scritto da questa prova", not miei,
   f"{len(cambiati)} file cambiati da altri processi nel frattempo; con riferimenti a questa prova: {len(miei)}")
print(f"\n{sum(esiti)}/{len(esiti)} prove passate · {time.strftime('%Y-%m-%d %H:%M')} · cartella {LAVORO}")
sys.exit(0 if all(esiti) else 1)
