#!/usr/bin/env python3
"""La sentinella di Jarvis: guarda, ripulisce e scrive il rapporto. Solo Python, nessun modello.

Decisione dell'utente del 2026-09-26 17:07: «la sentinella deve attivarsi ogni 15 minuti
e se ci sono problemi deve dirlo a Jarvis, che si attiva con tutti gli agenti per
risolvere e ripulire lo stato. Telegram e la VPS restano in ascolto: si controllano
e si riavviano se cadono, non si chiudono. Le sessioni ferme anomale si chiudono.»

Due metà, in ordine:

  1. LA PULIZIA (`pulisci`), uno script senza modello. Fa quello che è già deciso:
       - ritira le prese fantasma (processo morto) del registro dei lavori;
       - cancella i recapiti orfani in /tmp/cc-socks;
       - chiude le sessioni di Claude ferme da più di 4 ore che NON sono in ascolto
         (Telegram, il telefono, la voce e la Cloud Chat sono ascoltatori: mai chiusi);
       - controlla Telegram sul Mac e sulla VPS col guardiano, che riavvia se cade.
  2. IL RAPPORTO (`rapporto`), per quello che resta dopo la pulizia: al massimo 5 righe
     da una tabella fissa (cosa vuol dire, gravità, a chi tocca). Dal 2026-09-26 17:35
     (l'utente: «solo Python, per non usare crediti e liberare Jarvis e gli LLM») non lancia
     più `claude -p`; prima le anomalie andavano a Jarvis in modo lavoro su Sonnet.

Chi la lancia:
  - il Command Center (server.py, ciclo «sentinella»): guarda ogni minuto, agisce al
    massimo ogni 15 minuti (pulizia + rapporto, sotto «Ultimo rapporto» nel box Sentinella);
  - launchd (com.jarvis.sentinella15, ogni 15 minuti): `--giro` fa tutto da solo
    SOLO se il Command Center è spento, se no lascia fare a lui.

    python3 strumenti/sentinella.py --pulisci [--json]   solo la pulizia
    python3 strumenti/sentinella.py --quadro             le anomalie che vede da solo
    python3 strumenti/sentinella.py --giro [--zitto]     pulizia + rapporto nel registro (launchd)
"""
import argparse
import datetime
import json
import os
import re
import pathlib
import socket
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:            # Windows: niente fcntl, lucchetto con msvcrt
    fcntl = None
    import msvcrt

QUI = pathlib.Path(__file__).resolve().parent
AGENTE = QUI.parent
HOME = pathlib.Path.home()
sys.path.insert(0, str(QUI))
import agenti  # noqa: E402
import lavori  # noqa: E402
import portiere  # noqa: E402

VPS = "vps-tuo"
GUARDIA = QUI / "telegram_guardia.py"
GUARDIA_VPS = "/opt/jarvis-vps/strumenti/telegram_guardia.py"
# Il bot della VPS gira come utente jarvis (tmux -L jarvis-telegram): root non vede quel tmux,
# leggeva «sessione: false» e a ogni giro riavviava una sessione sua (2026-10-04).
GUARDIA_VPS_CMD = f"sudo -n -u jarvis env HOME=/home/jarvis python3 {GUARDIA_VPS}"
# Dal 2026-10-03 il giro ogni30 gira sulla VPS. ultimo.json lì è in git e jarvis-repo-sync
# (reset --hard ogni 10 min) lo riporta alla versione del commit: per questo si legge anche
# l'ultima riga di ogni30.log, che è in .gitignore e il reset non tocca.
SINCRO_VPS = "/root/jarvis/sincro"
# Su Windows non ci sono né il Telegram del Mac né la VPS: niente da controllare, niente falsi allarmi.
DOVE_TELEGRAM = () if sys.platform == "win32" else ("mac", "vps")
PORTA_PANNELLO = 7777
OGNI_MIN = 15
# MODELLO tolto il 2026-09-26 17:35 (decisione dell'utente): la sentinella non chiama più modelli.
LUCCHETTO = HOME / ".locale-onedrive" / "sentinella.lock"
LOG_DIR = AGENTE / "command-center" / "lavori"
PATH_ENV = f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"  # lsof sta in /usr/sbin
ENV = {**os.environ, "PATH": PATH_ENV}


def ora():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=ENV,
                           stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except OSError as e:
        return 1, str(e)


# ---------------------------------------------------------------- Telegram

def telegram_stato(dove):
    if dove == "mac":
        c, out = _sh(["python3", str(GUARDIA), "stato"], 25)
    else:
        c, out = _sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS,
                      f"{GUARDIA_VPS_CMD} stato"], 30)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"errore": out.strip()[:200] or "nessuna risposta"}


def telegram_controlla(dove):
    """Il guardiano riavvia solo se sessione o lettore mancano; se è tutto vivo non fa niente."""
    if dove == "mac":
        return _sh(["python3", str(GUARDIA), "controlla"], 40)
    return _sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS,
                f"{GUARDIA_VPS_CMD} controlla"], 45)


def telegram_vivo(st):
    return bool(st) and not st.get("errore") and bool(st.get("sessione")) and bool(st.get("lettore"))


def telegram_giovane(st, minuti=3):
    """Appena riavviato il lettore ci mette fino a 90 s: non è un'anomalia."""
    try:
        avv = datetime.datetime.strptime(st.get("avviato") or "", "%Y-%m-%d %H:%M")
        return (datetime.datetime.now() - avv).total_seconds() < minuti * 60
    except ValueError:
        return False


# ---------------------------------------------------------------- la pulizia

def pulisci(secondi=3):
    """Torna {fatto: [righe], chiuse, orfane, fantasmi, telegram: {mac, vps}, ascolto: [...]}."""
    fatto, esito = [], {"quando": ora()}

    # 1. prese fantasma (il portiere stampa; qui si vuole solo il numero)
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            esito["fantasmi"] = portiere.ritira_fantasmi()
        except Exception as e:  # noqa: BLE001
            esito["fantasmi"] = 0
            fatto.append(f"prese fantasma: errore {e}")
    if esito["fantasmi"]:
        fatto.append(f"ritirate {esito['fantasmi']} prese fantasma")
    # 1a. dal 2026-10-05 il registro sta sulla VPS, che non vede i processi del Mac:
    # le prese del Mac col processo vivo ricevono un battito, se no dopo 45 minuti
    # sembrerebbero morte e la loro chiave tornerebbe libera mentre lavorano.
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            portiere.lavori.battito_vivi()
    except Exception as e:  # noqa: BLE001
        fatto.append(f"battito delle prese vive: errore {e}")

    # 1b. badge di lavoro (command-center/badge.py): rinnova quelli con un lavoro aperto, revoca gli altri
    try:
        sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "command-center")))
        import badge as _badge
        rev, rin = _badge.giro(_badge._sessioni_con_presa())
        esito["badge"] = {"revocati": rev, "rinnovati": rin}
        if rev:
            fatto.append(f"revocati {rev} badge di lavoro senza più un lavoro aperto")
    except Exception as e:  # noqa: BLE001
        esito["badge"] = {"errore": type(e).__name__}

    # 2. sessioni: orfane via, ferme vecchie chiuse, ascoltatori lasciati stare
    righe, orfani = agenti.guarda(secondi)
    esito["orfane"] = agenti.pulisci_orfane(orfani)
    if esito["orfane"]:
        fatto.append(f"tolti {esito['orfane']} recapiti orfani")
    esito["ascolto"] = [{"pid": r["pid"], "nome": r["ascolto"]} for r in righe if r["ascolto"]]
    chiuse, non_chiuse = [], []
    for r in agenti.da_chiudere(righe):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = agenti.chiudi(r["pid"], chiedi=False)
        (chiuse if ok else non_chiuse).append(r["pid"])
        dove = (r["dove"] or r["cosa"]).replace(str(HOME), "~")
        fatto.append(f"{'chiusa' if ok else 'NON chiusa'} la sessione {r['pid']} ferma da {r['ore']:.1f} h in {dove}")
    esito["chiuse"], esito["non_chiuse"] = chiuse, non_chiuse

    # 3. Telegram Mac e VPS: controlla (riavvia se serve), poi lo stato
    esito["telegram"] = {}
    for dove in DOVE_TELEGRAM:
        st = telegram_stato(dove)
        if st.get("spento"):
            esito["telegram"][dove] = st
            fatto.append(f"Telegram {dove.upper()}: spento dall'utente, lasciato spento")
            continue
        if dove == "vps" and st.get("errore") and "ssh" in st["errore"].lower():
            # la VPS non risponde in ssh: non è Telegram a essere giù, e il guardiano da qui non ci arriva
            esito["telegram"][dove] = st
            fatto.append(f"VPS non raggiungibile in ssh, Telegram VPS non controllato ({st['errore'][-90:]})")
            continue
        if not telegram_vivo(st):
            c, out = telegram_controlla(dove)
            time.sleep(2)
            st = telegram_stato(dove)
            fatto.append(f"Telegram {dove.upper()}: era giù, riavviato col guardiano"
                         + ("" if telegram_vivo(st) or telegram_giovane(st) else f" ma non risponde ({out.strip()[-120:]})"))
        esito["telegram"][dove] = st
    esito["fatto"] = fatto
    return esito


def righe_pulizia(esito):
    """Una riga per l'evento del pannello e per il registro."""
    tg = esito.get("telegram") or {}
    vivi = [d.upper() for d in DOVE_TELEGRAM if telegram_vivo(tg.get(d)) or telegram_giovane(tg.get(d) or {})]
    testo = "; ".join(esito.get("fatto") or []) or "niente da ripulire"
    if vivi:
        testo += f" · Telegram in ascolto: {' e '.join(vivi)}"
    return testo


# ---------------------------------------------------------------- il battito della memoria

BATTITO_MAX_MIN = 30


def _quando(testo):
    try:
        return datetime.datetime.strptime(testo.strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def battito_vps():
    """L'ultimo giro ogni30 sulla VPS, in ora italiana (il servizio ha TZ=Europe/Rome).
    Una sola chiamata ssh: legge «quando» di ultimo.json e l'inizio dell'ultima riga di ogni30.log,
    e tiene il più recente. Torna (datetime, None), oppure (None, errore) se la VPS non risponde."""
    c, out = _sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS,
                  f"python3 -c 'import json;print(json.load(open(\"{SINCRO_VPS}/ultimo.json\"))[\"quando\"])'; "
                  f"tail -n 1 {SINCRO_VPS}/ogni30.log"], 15)
    date = [d for d in (_quando(r) for r in out.splitlines()) if d]
    if date:
        return max(date), None
    if c == 255 or out.strip() == "timeout":
        return None, f"ssh: {out.strip()[-120:] or 'nessuna risposta'}"
    return None, f"illeggibile: {out.strip()[-120:] or 'nessuna risposta'}"


def battito(metti, ultimo_mac):
    """Fermo solo se è vecchio il giro del Mac E quello della VPS. VPS non raggiungibile:
    nessun allarme qui, c'è già «vps:ssh»."""
    passato = (datetime.datetime.now() - _quando(ultimo_mac)).total_seconds()
    if passato <= BATTITO_MAX_MIN * 60:
        return
    if sys.platform == "win32":
        metti("sincronia", "sincronia:battito", f"battito della memoria fermo: ultimo giro {int(passato // 60)} min fa")
        return
    vps, errore = battito_vps()
    if errore and errore.startswith("ssh"):
        return
    if vps is None:
        metti("sincronia", "sincronia:battito",
              f"battito della memoria fermo: copia del Mac vecchia di {int(passato // 60)} min, "
              f"quella della VPS {errore}")
        return
    passato_vps = (datetime.datetime.now() - vps).total_seconds()
    if passato_vps > BATTITO_MAX_MIN * 60:
        metti("sincronia", "sincronia:battito",
              f"battito della memoria fermo: vecchie tutte e due le copie, Mac {int(passato // 60)} min, "
              f"VPS {int(passato_vps // 60)} min (ultimo giro VPS {vps:%Y-%m-%d %H:%M})")


# ---------------------------------------------------------------- il quadro (da soli, senza pannello)

def quadro():
    """Le anomalie che la sentinella vede da sola: portiere, battito, Telegram. Il Command
    Center ne vede di più (raccoglitori, lavori, missioni): questo serve quando è spento."""
    fuori = {}

    def metti(tipo, chiave, testo):
        fuori[chiave] = {"tipo": tipo, "chiave": chiave, "testo": testo[:300]}

    try:
        g = portiere.giro()
    except Exception as e:  # noqa: BLE001
        g = {"note": []}
        metti("portiere", "portiere:errore", f"il portiere non risponde: {e}")
    for n in g.get("note") or []:
        chi = ",".join(n.get("chiavi") or []) or (n.get("presa") or {}).get("agente") or ""
        import re
        m = re.search(r"\bpid (\d+)", n.get("perche") or "")
        chi = chi or (m.group(1) if m else "?")
        metti("portiere", f"portiere:{n['tipo']}:{chi}", f"{n['tipo']}: {n.get('perche')}")
    try:
        b = json.loads((AGENTE / "sincro" / "ultimo.json").read_text())
        datetime.datetime.strptime(b["quando"], "%Y-%m-%d %H:%M")   # se è rotto, va nell'except
        battito(metti, b["quando"])
        for p in b.get("progetti") or []:
            if p.get("semaforo") in ("🟡", "🔴"):
                metti("sincronia", f"sincronia:{p.get('progetto')}:{p['semaforo']}",
                      f"{p['semaforo']} {p.get('progetto')}: {p.get('esito')}")
    except Exception as e:  # noqa: BLE001
        metti("sincronia", "sincronia:battito", f"ultimo.json non leggibile: {e}")
    # 2026-10-04: il Mac sovraccarico fa cracchiare l'audio (OneDrive al 97% di CPU per giorni + coreaudiod al 14%): si avvisa
    # prima, con il colpevole. Solo macOS. Media di carico a 5 minuti sopra 10 e un processo che da solo vale più dell'80% di un core.
    if sys.platform == "darwin":
        try:
            carico5 = os.getloadavg()[1]
            if carico5 > 10:
                r = subprocess.run(["ps", "-Ao", "pcpu,comm", "-r"], capture_output=True, text=True, timeout=8).stdout.splitlines()[1:4]
                pesanti = [(float(x.split(None, 1)[0]), os.path.basename(x.split(None, 1)[1].strip())) for x in r if x.strip()]
                if pesanti and pesanti[0][0] > 80:
                    metti("carico", "carico:mac", f"Mac sovraccarico (carico {carico5:.0f}): {pesanti[0][1]} al {pesanti[0][0]:.0f}% di CPU. "
                          "Riavvia quell'app (non il Mac); se l'audio cracchia: sudo killall coreaudiod")
        except Exception:  # noqa: BLE001 — un controllo in più non deve rompere la sentinella
            pass
    for dove in DOVE_TELEGRAM:
        st = telegram_stato(dove)
        if dove == "vps" and st.get("errore") and "ssh" in st["errore"].lower():
            metti("vps", "vps:ssh", f"VPS non raggiungibile in ssh (Telegram VPS non controllato): {st['errore'][-120:]}")
        elif st.get("errore"):
            metti("telegram", f"telegram:{dove}", f"Telegram {dove.upper()}: {st['errore']}")
        elif not st.get("spento") and not telegram_vivo(st) and not telegram_giovane(st):
            metti("telegram", f"telegram:{dove}", f"Telegram {dove.upper()}: bot non agganciato")
    return fuori


# ---------------------------------------------------------------- il rapporto (solo Python)
# Decisione dell'utente del 2026-09-26 17:35: «la sentinella deve lavorare solo in Python per non
# usare crediti e liberare Jarvis e gli LLM». Fino a quell'ora, dopo la pulizia, le anomalie
# rimaste andavano a `claude -p` in modo lavoro su Sonnet (incarico/comando_jarvis/lancia_jarvis,
# tolti). Adesso il rapporto lo scrive `rapporto()` con una tabella fissa: cosa vuol dire,
# gravità e a chi tocca. Nessun modello, nessun lavoro lanciato.

# (tipo della nota, gravità, a chi, cosa fare). «a chi»: jarvis = la chat master; capogruppo = il
# capogruppo dello spazio del progetto; nessuno = si sistema da sé o con un clic dell'utente.
TABELLA = {
    "FANTASMA": ("giallo", "nessuno", "presa di un processo morto: si ritira con «Ritira i fantasmi»"),
    "SCADUTA": ("giallo", "nessuno", "presa scaduta: si ritira con «Ritira i fantasmi»"),
    "VPS": ("giallo", "jarvis", "terminale VPS senza chiave: si spegne o prende la chiave"),
    "ABUSIVO": ("giallo", "jarvis", "risorsa accesa senza chiave: si spegne o prende la chiave"),
    "MUTO": ("giallo", "nessuno", "sessione non registrata: se legge soltanto va bene"),
    "LUNGA": ("giallo", "jarvis", "sottoagente oltre il tempo: controllare in Squadra"),
    "🟡": ("giallo", "capogruppo", "progetto con lavoro più recente della memoria: salva in memoria"),
    "🔴": ("rosso", "jarvis", "cartella o memoria mancante: correggere spazi.json"),
    "battito": ("rosso", "jarvis", "battito della memoria fermo: rilanciare sincro/controlla.py"),
    "carico": ("giallo", "jarvis", "Mac sovraccarico: l'audio può cracchiare; chiudere o riavviare il processo più pesante, non il Mac"),
    "salute": ("rosso", "jarvis", None),         # None: il testo è l'errore del raccoglitore
    "lavoro": ("giallo", "jarvis", None),        # «guardare il lavoro X»
    "missione": ("giallo", "nessuno", "rispondere in Missioni"),
    "telegram": ("rosso", "jarvis", "Telegram giù: il guardiano lo riavvia, se resta giù controllare"),
}
MASSIMO_RIGHE = 5


def voce_tabella(a):
    """(chiave della TABELLA, testo corto) per un'anomalia {tipo, chiave, testo}."""
    tipo, chiave, testo = a.get("tipo"), a.get("chiave") or "", a.get("testo") or ""
    if tipo == "portiere":
        sotto = chiave.split(":")[1] if chiave.count(":") >= 1 else ""
        if sotto == "ABUSIVO" and "vps-shell" in chiave:
            sotto = "VPS"
        return (sotto if sotto in TABELLA else "ABUSIVO"), testo
    if tipo == "carico":
        return "carico", testo
    if tipo == "sincronia":
        if chiave == "sincronia:battito":
            return "battito", testo
        return ("🔴" if chiave.endswith("🔴") else "🟡"), testo
    return (tipo if tipo in TABELLA else "salute"), testo


def rapporto(anomalie_nuove, rientrate=(), capogruppo_di=None, quando=None):
    """Il rapporto della sentinella in al massimo 5 righe, senza modello.

    anomalie_nuove: le anomalie da riferire ({tipo, chiave, testo}); rientrate: quelle
    sparite dal giro prima; capogruppo_di: nome progetto -> capogruppo (per le 🟡)."""
    capogruppo_di = capogruppo_di or {}
    quando = quando or ora()
    righe = []
    for a in anomalie_nuove:
        voce, testo = voce_tabella(a)
        gravita, a_chi, cosa = TABELLA[voce]
        if voce == "salute":
            cosa = testo[:140]
        elif voce == "lavoro":
            cosa = "guardare il " + testo.replace("lavoro in errore: ", "lavoro «", 1)[:120] + "»"
        if a_chi == "capogruppo":
            m = re.match(r"\S+ (.+?): ", testo)
            progetto = m.group(1) if m else ""
            a_chi = capogruppo_di.get(progetto) or "jarvis"
            cosa = f"{progetto}: {cosa}" if progetto else cosa
        elif voce in ("FANTASMA", "MUTO", "LUNGA", "VPS", "ABUSIVO", "SCADUTA"):
            m = re.search(r"\(([^)]{1,60})\)|pid (\d+)", testo)
            dove = (m.group(1) or f"pid {m.group(2)}") if m else ""
            cosa = f"{cosa} ({dove})" if dove else cosa
        segno = "🔴" if gravita == "rosso" else "🟡"
        chi = {"jarvis": "Jarvis (chat master)", "nessuno": "nessuno"}.get(a_chi, a_chi)
        etichetta = {"🟡": "memoria", "🔴": "progetto"}.get(voce, voce)
        righe.append((gravita != "rosso", f"{segno} {etichetta}: {cosa} → a chi: {chi}"))
    righe.sort(key=lambda r: r[0])                 # prima i rossi
    testi = [r[1] for r in righe]
    coda = []
    if rientrate:
        coda.append(f"rientrate da sole: {len(rientrate)}")
    if not testi:
        return f"{quando} · nessuna anomalia da riferire" + (f" · {coda[0]}" if coda else "")
    posto = MASSIMO_RIGHE - 1                       # la prima riga è la testa
    if len(testi) > posto:
        altre = len(testi) - (posto - 1)
        testi = testi[:posto - 1] + [f"… e altre {altre} (lista nel box Sentinella)"]
    rossi = sum(1 for r in righe if not r[0])
    testa = f"{quando} · {len(righe)} anomali{'a' if len(righe) == 1 else 'e'} ({rossi} ross{'a' if rossi == 1 else 'e'})" + (f" · {coda[0]}" if coda else "")
    return "\n".join([testa] + testi)


# ---------------------------------------------------------------- giro da launchd

def pannello_acceso():
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", PORTA_PANNELLO)) == 0


def registro(testo):
    d = HOME / ".locale-onedrive" / "log"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "sentinella.log", "a", encoding="utf-8") as f:
        f.write(f"{ora()}  {testo}\n")


def giro(zitto=False):
    if pannello_acceso():
        if not zitto:
            print("Command Center acceso: la sentinella la fa lui.")
        return 0
    LUCCHETTO.parent.mkdir(parents=True, exist_ok=True)
    with open(LUCCHETTO, "w") as lk:
        try:
            if fcntl:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            registro("giro saltato: un altro giro è ancora in corso")
            return 0
        pul = pulisci()
        registro("pulizia: " + righe_pulizia(pul))
        an = list(quadro().values())
        if not an:
            registro("quadro pulito")
            if not zitto:
                print("Pulizia: " + righe_pulizia(pul) + "\nNessuna anomalia.")
            return 0
        testo = rapporto(an)                        # dal 2026-09-26 17:35 solo Python, niente claude -p
        registro("rapporto: " + testo.replace("\n", " | "))
        if not zitto:
            print(f"Pulizia: {righe_pulizia(pul)}\n{testo}")
        return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pulisci", action="store_true")
    p.add_argument("--quadro", action="store_true")
    p.add_argument("--giro", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--zitto", action="store_true")
    a = p.parse_args()
    if a.giro:
        return giro(a.zitto)
    if a.quadro:
        q = quadro()
        print(json.dumps(q, ensure_ascii=False, indent=1) if a.json else
              ("\n".join(f"[{x['tipo']}] {x['testo']}" for x in q.values()) or "nessuna anomalia"))
        return 3 if q else 0
    if a.pulisci:
        e = pulisci()
        print(json.dumps(e, ensure_ascii=False, indent=1, default=str) if a.json else
              f"Pulizia delle {e['quando']}: {righe_pulizia(e)}")
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
