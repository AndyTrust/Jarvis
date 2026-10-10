#!/usr/bin/env python3
"""Sincronia fra progetti e memoria: una riga per progetto.

Dal 23/09/2026 la memoria sta in un posto solo, «Jarvis Brain/Memoria/» su
OneDrive: una sezione per progetto, con «Errori da non ripetere/», «Decisioni/»,
«Fatti/» e «Da fare.md». Le vecchie `<progetto>/.claude/memoria/MEMORIA.md` e le
pagine «A che punto siamo» non si guardano più.

L'elenco dei progetti e la loro sezione di memoria vengono da
command-center/spazi.json (l'unica fonte: la usano anche il Command Center e
le missioni). Per ogni progetto:
  memoria   data e ora dell'ultima nota modificata nella sua sezione di Memoria/
  da fare   caselle aperte (`- [ ]`) nel suo «Da fare.md»
  errori    note in «Errori da non ripetere/»
  lavoro    l'ultimo file toccato nella cartella del progetto
  agenti    quanti profili in .claude/agents/ e se c'è un caposquadra (ceo-*.md)
Per il CRM Azienda Uno conta anche domande e decisioni aperte nel registro di direzione.

Semaforo: 🔴 memoria o cartella mancante · 🟡 c'è lavoro più recente
dell'ultima nota di memoria (oltre TOLLERANZA_MIN minuti) · 🟢 in ordine.

Solo lettura, tranne con --scrivi: allora scrive la pagina di controllo
«Memoria/00 Comune/Report/Stato aggiornamenti.md» (unita con Postino-Report il 02/10/2026),
con data E ORA dell'ultima nota di
memoria e dell'ultimo lavoro di ogni progetto. Non scrive in nessuna memoria.

Uso:
  python3 sincro/controlla.py                          tabella leggibile
  python3 sincro/controlla.py --json                   per il Command Center, ogni30.py e il Vice CEO AI
  python3 sincro/controlla.py --scrivi                 scrive la pagina di controllo
                                                       (parte da sola a fine di ogni risposta)
  python3 sincro/controlla.py --registro AAAA-MM-GG    registro di direzione di Azienda Uno:
      decisioni e domande aperte già scadute o in scadenza entro quella data
Esce 1 se almeno un progetto è 🔴 (cartella o memoria mancante).
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "command-center")); import senza_finestre  # noqa: E402,F401  (Windows: niente finestre di terminale)
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
ONEDRIVE = HOME / "OneDrive" if sys.platform == "win32" else HOME / "Library/CloudStorage/OneDrive"
if hasattr(sys.stdout, "reconfigure"):  # Windows: la console e i pipe sono cp1252, i semafori 🟢🟡🔴 no
    sys.stdout.reconfigure(encoding="utf-8")
AGENTE = Path(__file__).resolve().parent.parent
SPAZI = AGENTE / "command-center/spazi.json"
# 2026-09-26: nel template spazi.json non c'è; si legge l'esempio, come fa command-center/spazi.py
if not SPAZI.exists():
    SPAZI = AGENTE / "command-center/spazi.esempio.json"
def _memoria_utente():
    """La memoria di chi usa questo PC: `memoria_dir` di utente.json (mai quella del capo)."""
    try:
        u = json.loads((AGENTE / "utente.json").read_text(encoding="utf-8"))
        return AGENTE / u["memoria_dir"]
    except (OSError, ValueError, KeyError):
        return AGENTE / ".claude/memoria"


MEMORIA = _memoria_utente() if sys.platform == "win32" else ONEDRIVE / "Jarvis Brain/Memoria"   # su Windows Jarvis Brain è del capo
REGISTRO_CEO_140 = ONEDRIVE / "CRM Azienda Uno/Reports/Direzione/registro.json"
# dove ogni caposquadra di progetto scrive i suoi report (dentro la cartella del
# progetto). I nomi `ceo-*` restano quelli di prima: dal 19/09/2026 il CEO AI è
# Jarvis, che parla con l'utente, e questi profili sono capisquadra sotto il Vice CEO AI.
REPORT_CEO = {"ceo-ai": "Reports/Direzione/CEO",
              "ceo-Azienda Due": "AZD-AZD/Rapporti/direzione"}
VAULT_CRM = ONEDRIVE / "CRM Azienda Uno/AZIENDA UNO OBSIDIAN/Azienda Uno CRM"
if sys.platform != "win32":
    PAGINA_CONTROLLO = ONEDRIVE / "Jarvis Brain/Memoria/00 Comune/Report/Stato aggiornamenti.md"
elif VAULT_CRM.is_dir():        # CRM condiviso presente: la pagina sta nel vault
    PAGINA_CONTROLLO = VAULT_CRM / "99 Meta/Stato aggiornamenti.md"
else:                           # installazione senza CRM: pagina locale accanto al battito
    PAGINA_CONTROLLO = AGENTE / "sincro/Stato aggiornamenti.md"
# Cartelle che non sono lavoro: rumore, uscite di programmi, copie del vault.
RUMORE = {".git", "node_modules", ".obsidian", "_to_delete", ".venv", "venv", "__pycache__",
          "worktrees", ".codegraph", "graphify-out", "memoria", "AZIENDA UNO OBSIDIAN",
          "lavori", "missioni", "chiamate", "asterisk", "state", "registri",
          # file che cambiano da soli, a orologio o perché un programma è aperto: non sono lavoro
          "ServizioLive",             # log del servizio in sala, launchd com.Azienda Uno.servizio-live, ogni minuto
          "archivio-notte",           # archivio della posta Azienda Due, launchd com.azd.archivio-notte, alle 03:15
          "chrome-profile-passbolt"}  # profilo di Chrome per Passbolt: cambia finché Chrome è aperto
# copie degli strumenti della memoria che la skill mette in ogni progetto: non sono lavoro
STRUMENTI_BRAIN = {"mappa.py", "stato_obsidian.py", "salva_brain.py", "handoff.py", "brain.py",
                   "impianta.py", "costo.py", "stato.py", "pdf_testo.py", "scompatta_sorgenti.py",
                   "stato_voce.json"}  # 29/09/2026: lo scrive la voce a ogni turno, non è lavoro
TOLLERANZA_MIN = 15  # minuti fra l'ultimo lavoro e l'ultima nota prima di dire «indietro»
CASELLA_APERTA = re.compile(r"^\s*[-*+] \[ \]", re.M)


def percorso(valore):
    """Come spazi.py: OD = la cartella di OneDrive, ~ = la casa."""
    v = str(valore or "")
    if v == "OD" or v.startswith("OD/"):
        return ONEDRIVE / v[3:] if len(v) > 2 else ONEDRIVE
    if v.startswith("~"):
        return HOME / v[2:] if len(v) > 1 else HOME
    return Path(v)


def leggi_spazi():
    """(spazio, id, nome, cartella, [sezioni di Memoria/]) per ogni progetto di spazi.json."""
    dati = json.loads(SPAZI.read_text(encoding="utf-8"))
    progetti = []
    for s in dati.get("spazi", []):
        for p in s.get("progetti", []):
            sezioni = [MEMORIA / m for m in p.get("sezioni_memoria", [])]
            # «memoria_propria»: cartelle di memoria fuori da Jarvis Brain. Serve al CRM Azienda Uno,
            # che per decisione ha il suo vault e salva nella memoria del progetto (27/09/2026).
            propria = [percorso(m) for m in p.get("memoria_propria", [])]
            progetti.append((s.get("nome", ""), p["id"], p["nome"],
                             percorso(p["cartella"]), sezioni, p.get("capogruppo"), propria))
    return progetti


def ultimo_lavoro(cartella):
    """L'ultimo file toccato dentro il progetto, saltando rumore, uscite dei
    programmi e file nascosti (i «.voice_*» e simili cambiano a ogni turno)."""
    ultimo, dove = None, None
    # 29/09/2026: «Agenti di casa» ha per cartella la home: girarla tutta (Library, OneDrive) durava
    # minuti e mandava in timeout la sincronia. Per la home contano solo gli agenti.
    radice_giro = cartella / ".claude" / "agents" if cartella == HOME else cartella
    for radice, dirs, files in os.walk(radice_giro):
        dirs[:] = [d for d in dirs if d not in RUMORE]
        for nome in files:
            if nome.startswith(".") or (nome in STRUMENTI_BRAIN and radice.endswith("strumenti")):
                continue
            try:
                t = dt.datetime.fromtimestamp(os.stat(os.path.join(radice, nome)).st_mtime)
            except OSError:
                continue
            if ultimo is None or t > ultimo:
                ultimo, dove = t, os.path.relpath(os.path.join(radice, nome), cartella)
    return (ultimo.replace(second=0, microsecond=0), dove) if ultimo else (None, None)



def modello(profilo):
    """Il `model:` scritto nel frontmatter di un profilo di agente."""
    try:
        m = re.search(r"^model:\s*(\S+)", profilo.read_text(encoding="utf-8")[:1500], re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def modelli_skill(profilo_ceo):
    """Il modello delle skill-specialista, dalla tabella del caposquadra che le guida
    (riga con `.claude/skills/<nome>` e il modello nell'ultima colonna)."""
    try:
        testo = profilo_ceo.read_text(encoding="utf-8")
    except OSError:
        return {}
    return dict(re.findall(r"`\.claude/skills/([\w-]+)`.*\|\s*(haiku|sonnet|opus)\s*\|", testo))


def registro_140():
    try:
        r = json.loads(REGISTRO_CEO_140.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    domande = sum(1 for d in r.get("domande", []) if d.get("stato") == "aperta")
    decisioni = sum(1 for d in r.get("decisioni", [])
                    if d.get("stato") in ("proposta", "in_corso"))
    return {"domande_aperte": domande, "decisioni_aperte": decisioni}

def stato_memoria(sezioni):
    """Quello che dice la memoria di un progetto, sommando le sue sezioni:
    ultima nota modificata (ora e file), caselle aperte nei «Da fare.md»,
    note in «Errori da non ripetere/», e cosa manca."""
    ultima, dove, aperte, errori, manca = None, None, 0, 0, []
    if not sezioni:
        return {"ora": None, "file": None, "aperte": None, "errori": None,
                "manca": ["nessuna sezione di Memoria/ in spazi.json"]}
    for sez in sezioni:
        if not sez.is_dir():
            manca.append(f"manca la sezione {sez.relative_to(MEMORIA)}")
            continue
        for radice, dirs, files in os.walk(sez):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for nome in files:
                if nome.startswith(".") or not nome.endswith(".md"):
                    continue
                f = os.path.join(radice, nome)
                try:
                    t = dt.datetime.fromtimestamp(os.stat(f).st_mtime)
                except OSError:
                    continue
                if ultima is None or t > ultima:
                    ultima, dove = t, os.path.relpath(f, MEMORIA)
        errori += sum(1 for _ in (sez / "Errori da non ripetere").rglob("*.md"))
        da_fare = sez / "Da fare.md"
        try:
            aperte += len(CASELLA_APERTA.findall(da_fare.read_text(encoding="utf-8")))
        except OSError:
            manca.append(f"manca {da_fare.relative_to(MEMORIA)}")
    return {"ora": ultima.replace(second=0, microsecond=0) if ultima else None,
            "file": dove, "aperte": aperte, "errori": errori, "manca": manca}


def ultima_nota(cartella):
    """(ora, file) dell'ultima nota .md scritta in una cartella di memoria fuori dal vault."""
    ultima, dove = None, None
    for radice, dirs, files in os.walk(cartella):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for nome in files:
            if nome.startswith(".") or not nome.endswith(".md"):
                continue
            try:
                t = dt.datetime.fromtimestamp(os.stat(os.path.join(radice, nome)).st_mtime)
            except OSError:
                continue
            if ultima is None or t > ultima:
                ultima, dove = t, os.path.join(radice, nome)
    return (ultima.replace(second=0, microsecond=0), dove) if ultima else (None, None)


def esamina(spazio, id_, nome, cartella, sezioni, capogruppo=None, propria=()):
    # I campi di prima restano (vault, vault_ora, scarto_giorni, dati) perché il
    # Command Center e ogni30.py li leggono: senza pagine «A che punto siamo»
    # valgono None.
    r = {"progetto": nome, "id": id_, "spazio": spazio, "cartella": str(cartella),
         "esiste": cartella.is_dir(),
         "sezioni_memoria": [str(s) for s in sezioni],
         "memoria": None, "memoria_ora": None, "memoria_file": None,
         "da_fare_aperte": None, "errori": None,
         "vault": None, "vault_ora": None, "scarto_giorni": None,
         "agenti": 0, "ceo": None, "specialisti": [], "modelli": {}, "dati": None,
         "lavoro_ora": None, "lavoro_file": None, "avvisi": []}
    mem = stato_memoria(sezioni)
    r["memoria_ora"], r["memoria_file"] = mem["ora"], mem["file"]
    for cart in propria:
        t, dove = ultima_nota(cart)
        if t and (r["memoria_ora"] is None or t > r["memoria_ora"]):
            r["memoria_ora"] = t
            r["memoria_file"] = str(dove).replace(str(ONEDRIVE) + "/", "")
    r["memoria"] = r["memoria_ora"].date() if r["memoria_ora"] else None
    r["da_fare_aperte"], r["errori"] = mem["aperte"], mem["errori"]
    r["avvisi"] += [m for m in mem["manca"] if not (propria and m.startswith("nessuna sezione"))]   # 29/09/2026: la memoria propria basta
    if not r["esiste"]:
        r["avvisi"].append("la cartella non esiste più: correggere spazi.json")
        r["semaforo"], r["esito"] = "🔴", "la cartella del progetto non esiste"
        return r
    # LEGGIMI e simili non sono agenti. Il capogruppo è quello di spazi.json
    # (per Patrimonio è «utente», che non comincia per ceo-); i ceo-* restano il ripiego.
    agenti = [a for a in sorted((cartella / ".claude/agents").glob("*.md")) if a.stem.upper() != "LEGGIMI"]
    r["agenti"] = len(agenti)
    ceo = [a.stem for a in agenti if a.stem == capogruppo] or \
        [a.stem for a in agenti if a.stem.startswith(("ceo", "vice-ceo-"))]
    r["ceo"] = ceo[0] if ceo else None
    # specialisti: gli altri agenti; dove non ce ne sono, le skill del progetto
    r["specialisti"] = [a.stem for a in agenti if a.stem != r["ceo"] and not a.stem.startswith("ceo")] or \
        sorted(s.parent.name for s in (cartella / ".claude/skills").glob("*/SKILL.md"))
    r["modelli"] = {a.stem: modello(a) for a in agenti}
    if r["ceo"]:
        r["modelli"].update(modelli_skill(cartella / ".claude/agents" / f"{r['ceo']}.md"))
    if r["ceo"] in REPORT_CEO:
        rep = sorted((cartella / REPORT_CEO[r["ceo"]]).glob("*.md"))
        r["ultimo_report"] = rep[-1].name if rep else None
    if id_ == "crm":
        r["registro_ceo"] = registro_140()
    r["lavoro_ora"], r["lavoro_file"] = ultimo_lavoro(cartella)
    r["semaforo"], r["esito"] = esito(r)
    return r


def esito(r):
    """(semaforo, frase) per una riga: la cosa che l'utente vuole poter controllare."""
    m, w = r["memoria_ora"], r["lavoro_ora"]
    if m is None:
        return "🔴", "il progetto non ha memoria in Memoria/"
    if w is not None and w > m + dt.timedelta(minutes=TOLLERANZA_MIN):
        ritardo = w - m
        ore, minuti = divmod(int(ritardo.total_seconds() // 60), 60)
        durata = f"{ore} h {minuti} min" if ore else f"{minuti} min"
        return "🟡", f"memoria indietro di {durata}: c'è lavoro più recente"
    return "🟢", "in ordine"


def stampa_registro(entro):
    """Voci aperte del registro CEO con scadenza fino a `entro`, le scadute per prime."""
    try:
        r = json.loads(REGISTRO_CEO_140.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"registro non leggibile: {e}")
        sys.exit(2)
    oggi = dt.date.today().isoformat()
    voci = [("DEC", d["id"], d.get("entro") or "", d.get("titolo", ""),
             d.get("beneficio_eur"), d.get("responsabile", ""))
            for d in r.get("decisioni", []) if d.get("stato") in ("proposta", "in_corso")]
    voci += [("DOM", d["id"], d.get("entro") or "", d.get("domanda", ""), None,
              d.get("chi_chiede", ""))
             for d in r.get("domande", []) if d.get("stato") == "aperta"]
    voci = sorted((v for v in voci if v[2] and v[2][:10] <= entro), key=lambda v: v[2])
    if "--json" in sys.argv:
        print(json.dumps([{"tipo": v[0], "id": v[1], "entro": v[2][:10], "testo": v[3],
                           "eur": v[4], "chi": v[5], "scaduta": v[2][:10] < oggi}
                          for v in voci], ensure_ascii=False))
        return
    for tipo, id_, scad, testo, eur, chi in voci:
        segno = "SCADUTA" if scad[:10] < oggi else "       "
        soldi = f" · {eur} €" if eur else ""
        print(f"{segno} {scad[:10]} {tipo} {id_} · {str(testo)[:90]}{soldi} · {str(chi)[:30]}")
    senza = sum(1 for d in r.get("decisioni", []) + r.get("domande", [])
                if not d.get("entro") and d.get("stato") in ("proposta", "in_corso", "aperta"))
    print(f"— {len(voci)} voci fino al {entro}; {senza} aperte senza scadenza")



def scrivi_pagina(righe):
    """La pagina di controllo nel vault: data e ora di ogni cosa, e l'esito."""
    adesso = dt.datetime.now()
    f = lambda d: d.strftime("%d/%m/%Y %H:%M") if d else "—"
    corto = lambda p: "/".join(pathlib.PurePath(p).parts[-3:])
    n = lambda v: "—" if v is None else str(v)
    out = [
        "---", "titolo: Stato aggiornamenti", "tipo: report",
        f"aggiornato: {adesso.strftime('%Y-%m-%d %H:%M')}", "---", "",
        "# Stato aggiornamenti", "",
        f"*Controllo fatto il **{adesso.strftime('%d/%m/%Y alle %H:%M')}**. Lo rifà da solo "
        "`sincro/controlla.py --scrivi` a fine di ogni risposta di Jarvis: se l'ora qui sopra è "
        "vecchia, Jarvis non sta salvando.*", "",
        "| Spazio | Progetto | Ultima nota in Memoria/ | Da fare aperte | Errori | Ultimo lavoro nella cartella | Esito |",
        "|---|---|---|---|---|---|---|"]
    for r in righe:
        nota = f(r.get("memoria_ora")) + (f" · `{corto(r['memoria_file'])}`" if r.get("memoria_file") else "")
        lavoro = f(r.get("lavoro_ora")) + (f" · `{corto(r['lavoro_file'])}`" if r.get("lavoro_file") else "")
        out.append(f"| {r.get('spazio', '')} | {r['progetto']} | {nota} | {n(r.get('da_fare_aperte'))} | "
                   f"{n(r.get('errori'))} | {lavoro} | {r.get('semaforo', '')} {r.get('esito', '')} |")
    out += ["", "## Come si legge", "",
            "- **Ultima nota in Memoria/**: l'ultima nota modificata nella sezione del progetto dentro "
            "`Jarvis Brain/Memoria/` (la mappa progetto → sezione sta in `command-center/spazi.json`).",
            "- **Da fare aperte**: le caselle `- [ ]` nel `Da fare.md` della sezione. **Errori**: le note in "
            "`Errori da non ripetere/`.",
            "- **Ultimo lavoro**: l'ultimo file toccato nella cartella del progetto, senza le uscite dei "
            "programmi e senza i file nascosti.",
            f"- 🟢 in ordine · 🟡 c'è lavoro più recente dell'ultima nota di memoria (oltre {TOLLERANZA_MIN} minuti) · "
            "🔴 memoria o cartella mancante.",
            "", "Una memoria vecchia non è per forza un errore: se in quella cartella non si è lavorato, "
            "non c'è niente da salvare. Il segnale è 🟡: c'è lavoro più recente della memoria.", ""]
    PAGINA_CONTROLLO.parent.mkdir(parents=True, exist_ok=True)
    PAGINA_CONTROLLO.write_text("\n".join(out), encoding="utf-8")


def main():
    if "--registro" in sys.argv:
        i = sys.argv.index("--registro")
        entro = sys.argv[i + 1] if len(sys.argv) > i + 1 else dt.date.today().isoformat()
        stampa_registro(entro)
        return
    righe = [esamina(*p) for p in leggi_spazi()]
    if "--scrivi" in sys.argv:
        scrivi_pagina(righe)
        # la pagina condivisa del CRM (Mac + PC amministrazione): 0,1 s, solo file locali
        team = ONEDRIVE / "CRM Azienda Uno/strumenti/team/stato_team.py"
        if team.exists():
            subprocess.run([sys.executable, str(team)], capture_output=True, timeout=60)
        return
    problemi = any(r.get("semaforo") == "🔴" for r in righe)

    if "--json" in sys.argv:
        print(json.dumps({"oggi": dt.date.today().isoformat(), "memoria": str(MEMORIA),
                          "progetti": righe},
                         default=str, ensure_ascii=False, indent=1))
        sys.exit(1 if problemi else 0)

    f = lambda d: d.strftime("%Y-%m-%d %H:%M") if d else "—"
    n = lambda v: "—" if v is None else str(v)
    print(f"{'Progetto':<24}{'Memoria':<18}{'Da fare':<9}{'Errori':<8}{'Lavoro':<18}"
          f"{'Agenti':<8}{'CEO':<18}Esito · Note")
    for r in righe:
        note = list(r["avvisi"])
        reg = r.get("registro_ceo")
        if reg:
            note.append(f"registro CEO: {reg['domande_aperte']} domande, "
                        f"{reg['decisioni_aperte']} decisioni aperte")
        print(f"{r['progetto'][:23]:<24}{f(r.get('memoria_ora')):<18}{n(r.get('da_fare_aperte')):<9}"
              f"{n(r.get('errori')):<8}{f(r.get('lavoro_ora')):<18}{r['agenti']:<8}{(r['ceo'] or '—'):<18}"
              f"{r.get('semaforo', '')} {r.get('esito', '')}" + (f" · {' · '.join(note)}" if note else ""))
    sys.exit(1 if problemi else 0)


if __name__ == "__main__":
    main()
