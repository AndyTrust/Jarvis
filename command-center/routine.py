#!/usr/bin/env python3
"""Le Routine del Command Center (l'utente, 2026-10-05): tutti i lavori automatici, dove girano, quando, come è
andata l'ultima volta, e i comandi per avviarli, leggerne il log, cambiarli o crearne di nuovi.

Fonti (lette dal server, mai a mano):
  vps   i timer systemd della VPS jarvis-*, cc-ponte-* (systemctl show + list-timers -o json)
  cron  il crontab di root della VPS (crontab -l), una routine per riga; «#ROUTINE-PAUSA » davanti = in pausa
  mac   ~/Library/LaunchAgents/com.jarvis.* (+ launchctl list)
La VPS sta su UTC: le ore si mostrano in Europe/Rome. Una sola chiamata ssh per tutta la VPS, in cache CACHE_S.

Azioni:
  avvia(id)               SENZA conferma (decisione dell'utente): systemctl start --no-block / launchctl kickstart /
                          la riga di cron lanciata una volta con systemd-run. Lo stato si segue in un thread.
  log(id)                 le ultime righe (journal e file di log della routine), passate da approvazioni.pulisci
  prepara(dati)           modifica o nuova: valida e scrive il COMANDO ESATTO, non tocca niente. Torna un codice.
  conferma(prep, codice)  esegue il comando preparato, solo con il codice giusto, dopo PREP_MIN_S e entro PREP_MAX_S.
Ogni passo va nel registro (DIR/registro.jsonl) e nel registro delle attività (attivita.registra).

Gruppi e tipi (controllo / dati) stanno in routine-gruppi.json, accanto a questo file (fuori dai segreti).

Per le prove: CC_ROUTINE_DIR (cartella del registro), CC_ROUTINE_GRUPPI (file dei gruppi),
CC_ROUTINE_LAUNCHAGENTS (cartella dei plist), CC_ROUTINE_VPS (nome ssh). ESEGUI si può sostituire con un finto.
Solo libreria standard.
"""
import fnmatch
import json
import os
import plistlib
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ROMA = ZoneInfo("Europe/Rome")
except Exception:  # noqa: BLE001  (Windows senza tzdata)
    ROMA = None

QUI = Path(__file__).resolve().parent
FILE_GRUPPI = Path(os.environ.get("CC_ROUTINE_GRUPPI") or QUI / "routine-gruppi.json")
DIR = Path(os.environ.get("CC_ROUTINE_DIR") or Path.home() / ".locale-onedrive" / "jarvis-cc" / "routine")
AGENTI_MAC = Path(os.environ.get("CC_ROUTINE_LAUNCHAGENTS") or Path.home() / "Library" / "LaunchAgents")
VPS = os.environ.get("CC_ROUTINE_VPS") or "vps-tuo"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=5"]
MAC = sys.platform == "darwin"

CACHE_S = 45
PREP_MIN_S = 1.0          # il «Conferma» non può arrivare insieme al «Prepara» (doppio clic)
PREP_MAX_S = 600          # un comando preparato vale 10 minuti
SEGUI_MAX_S = 30 * 60     # oltre, l'esecuzione resta «in corso da molto»
SEP = "@@CC-ROUTINE@@"
TIMER_VPS = ("jarvis-*", "cc-ponte-*")
PREFISSI_MAC = ("com.jarvis.",)
NOME = re.compile(r"[a-z0-9-]{1,40}")
ID = re.compile(r"(vps|cron|mac):[A-Za-z0-9._-]{1,80}")
PERCORSO_LOG = re.compile(r"/[A-Za-z0-9._/-]{1,200}")
CALENDARIO = re.compile(r"[A-Za-z0-9*:,./~ _+-]{1,80}")
FINE = "CC_ROUTINE_FINE"
PAUSA_CRON = "#ROUTINE-PAUSA "
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

# Il comando di lettura della VPS: fisso, nessun pezzo viene dalla richiesta.
LETTURA_VPS = f"""T=$(systemctl list-unit-files --type=timer --no-legend --plain {' '.join(repr(x) for x in TIMER_VPS)} 2>/dev/null | awk '{{print $1}}')
if [ -n "$T" ]; then systemctl show --timestamp=unix -p Id,Description,TimersCalendar,TimersMonotonic,Unit,UnitFileState,ActiveState $T; fi
echo {SEP}
if [ -n "$T" ]; then S=$(systemctl show -p Unit --value $T); systemctl show --timestamp=unix -p Id,Description,ExecStart,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,ActiveState,SubState,FragmentPath,DropInPaths $S; fi
echo {SEP}
systemctl list-timers --all -o json --no-pager 2>/dev/null
echo {SEP}
crontab -l 2>/dev/null
echo {SEP}
crontab -l 2>/dev/null | sha256sum | cut -c1-64
echo {SEP}
crontab -l 2>/dev/null | grep -oE '>>?[[:space:]]*/[^[:space:];|&]+' | sed -E 's/^>>?[[:space:]]*//' | sort -u | while read -r f; do stat -c '%Y %n' "$f" 2>/dev/null; done
echo {SEP}
timedatectl show -p Timezone --value 2>/dev/null; date +%s
echo {SEP}
cd /root/jarvis/routine/compiti 2>/dev/null && sha256sum -- * 2>/dev/null
echo {SEP}
grep -H "^# REGOLA" /root/jarvis/routine/compiti/* 2>/dev/null
true
"""


class RoutineNonValida(ValueError):
    pass


class NonTrovata(KeyError):
    pass


# ---------------------------------------------------------------- esecuzione dei comandi

SU_SE_STESSA = None       # il server ci mette _ssh_su_se_stessa: Command Center acceso sulla VPS = niente ssh


def _esegui_vero(cmd, timeout=30, ingresso=None):
    if SU_SE_STESSA is not None:
        locale = SU_SE_STESSA(cmd)
        if locale is not None:
            cmd = ["bash", "-c", locale]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           input=ingresso, stdin=None if ingresso is not None else subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (("\n" + r.stderr) if r.stderr and r.returncode else "")
    except subprocess.TimeoutExpired:
        return 124, "tempo scaduto"
    except OSError as e:
        return 1, str(e)


ESEGUI = _esegui_vero


def ssh(remoto, timeout=30, ingresso=None):
    return ESEGUI(SSH + [VPS, remoto], timeout=timeout, ingresso=ingresso)


def _pulisci(testo, n=20000):
    try:
        import approvazioni
        return approvazioni.pulisci(testo, n)
    except Exception:  # noqa: BLE001
        return str(testo)[:n]


# ---------------------------------------------------------------- ore

def _ts(v):
    """«@1791195665» o un numero in microsecondi/secondi → secondi epoch (float) o None."""
    if v in (None, "", "0", 0, "n/a"):
        return None
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("@"):
            v = v[1:]
        try:
            v = float(v)
        except ValueError:
            return None
    if v > 1e14:
        v = v / 1e6
    return float(v) if v > 0 else None


def _roma(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, ROMA) if ROMA else datetime.fromtimestamp(ts)


def testo_ora(ts, adesso=None):
    """«09:07» oggi, «dom 07:00» entro una settimana, «12/10 07:00» oltre. Ora di Roma."""
    if ts is None:
        return ""
    d = _roma(ts)
    oggi = _roma(adesso or time.time()).date()
    if d.date() == oggi:
        return d.strftime("%H:%M")
    if abs((d.date() - oggi).days) < 7:
        return f"{GIORNI[d.weekday()]} {d.strftime('%H:%M')}"
    return d.strftime("%d/%m %H:%M")


# ---------------------------------------------------------------- systemd

def blocchi_show(testo):
    """L'uscita di «systemctl show» per più unità: una lista di dizionari. Le chiavi ripetute (TimersCalendar)
    diventano liste nella chiave «<nome>*»."""
    out, cur = [], {}
    for riga in (testo or "").splitlines():
        if not riga.strip():
            if cur:
                out.append(cur)
                cur = {}
            continue
        k, _, v = riga.partition("=")
        if not _:
            continue
        cur.setdefault(k + "*", []).append(v)
        cur[k] = v
    if cur:
        out.append(cur)
    return out


def calendari_di(blocco):
    """[«*-*-* 07:00:00 Europe/Rome», …] e [(«OnUnitActiveSec», «30min»), …] da un blocco di systemctl show."""
    cal = []
    for v in blocco.get("TimersCalendar*", []):
        m = re.search(r"OnCalendar=(.+?)\s*;", v)
        if m:
            cal.append(m.group(1).strip())
    mono = []
    for v in blocco.get("TimersMonotonic*", []):
        m = re.search(r"(On\w+)USec=(.+?)\s*;", v)
        if m:
            mono.append((m.group(1) + "Sec", m.group(2).strip()))
    return cal, mono


def _valori_cal(t, massimo):
    """«19..23», «00,30», «5», «*» → lista di interi (None se la forma non è semplice)."""
    if t == "*":
        return list(range(massimo + 1))
    out = []
    for parte in t.split(","):
        m = re.fullmatch(r"(\d{1,2})(?:\.\.(\d{1,2}))?(?:/(\d{1,2}))?", parte)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else (massimo if m.group(3) else a)
        out += list(range(a, b + 1, int(m.group(3) or 1)))
    return out if all(0 <= x <= massimo for x in out) else None


def orari_del_giorno(c):
    """«*-*-* 19..23:00,30:00 Europe/Rome» → [(19,0),(19,30)…]; None se non è un calendario «tutti i giorni»."""
    m = re.fullmatch(r"(?:\*-\*-\*\s+)?([\d.,*/]+):([\d.,*/]+)(?::(?:0?0))?(?:\s+Europe/Rome)?", c.strip())
    if not m:
        return None
    ore, minuti = _valori_cal(m.group(1), 23), _valori_cal(m.group(2), 59)
    if ore is None or minuti is None:
        return None
    return [(h, mi) for h in ore for mi in minuti]


def testo_orari(orari):
    """Orari di un giorno in italiano: «ogni giorno 07:00», «ogni 30 min 12:00–16:00, 19:00–01:00»."""
    orari = sorted(set(orari))
    if len(orari) == 1:
        return "ogni giorno %02d:%02d" % orari[0]
    t = [h * 60 + m for h, m in orari]
    corse, cur = [], [t[0]]
    for x in t[1:]:
        if len(cur) == 1 or x - cur[-1] == cur[1] - cur[0]:
            if len(cur) == 1 and x - cur[0] > 60:
                corse.append(cur)
                cur = [x]
            else:
                cur.append(x)
        else:
            corse.append(cur)
            cur = [x]
    corse.append(cur)
    passi = {c[1] - c[0] for c in corse if len(c) > 1}
    # a cavallo della mezzanotte: l'ultima corsa (…23:30) e la prima (00:00…) con lo stesso passo diventano una
    if len(corse) > 1 and len(passi) == 1:
        p = passi.pop()
        passi.add(p)
        if corse[0][0] == 0 and corse[-1][-1] + p == 24 * 60 and len(corse[0]) > 1 and len(corse[-1]) > 1:
            corse = corse[1:-1] + [corse[-1] + [x + 24 * 60 for x in corse[0]]]
    hm = lambda x: "%02d:%02d" % ((x // 60) % 24, x % 60)  # noqa: E731
    if len(passi) == 1 and all(len(c) > 1 for c in corse):
        passo = passi.pop()
        return ("ogni ora " if passo == 60 else f"ogni {passo} min ") + ", ".join(f"{hm(c[0])}–{hm(c[-1])}" for c in corse)
    if len(t) <= 6:
        return "ogni giorno " + ", ".join(hm(x) for x in t)
    return f"{len(t)} volte al giorno: " + ", ".join(f"{hm(c[0])}–{hm(c[-1])}" if len(c) > 1 else hm(c[0]) for c in corse)


def testo_calendario(cal, mono):
    if cal:
        tutti = [orari_del_giorno(c) for c in cal]
        if all(x is not None for x in tutti):
            return testo_orari([o for x in tutti for o in x])
        return "; ".join(re.sub(r"\s+Europe/Rome$", "", c) for c in cal)
    attivo = [v for k, v in mono if k == "OnUnitActiveSec"]
    if attivo:
        return "ogni " + attivo[0].replace("min", " min").replace("h", " h")
    dopo = [v for k, v in mono if k == "OnUnitInactiveSec"]
    if dopo:
        return dopo[0].replace("min", " min").replace("h", " h") + " dopo la fine della precedente"
    if mono:
        return "all'avvio (" + mono[0][1] + ")"
    return "a mano"


def comando_di(execstart):
    """«{ path=/bin/bash ; argv[]=/bin/bash -c python3 … ; ignore_errors=no ; … }» → «/bin/bash -c python3 …»."""
    m = re.search(r"argv\[\]=(.*?)\s;\s(?:ignore_errors|start_time)=", execstart or "")
    return m.group(1).strip() if m else (execstart or "").strip(" {}")


def file_log_di(comando):
    """Il file dove la routine scrive l'uscita («>> /var/log/x.log»), se c'è e ha un percorso pulito."""
    for m in re.finditer(r">>?\s*(/[^\s;|&\"']+)", comando or ""):
        p = m.group(1)
        if PERCORSO_LOG.fullmatch(p) and not p.startswith("/dev/"):
            return p
    return None


def routine_systemd(timers_txt, servizi_txt, elenco_json, adesso=None):
    """Le routine dei timer systemd. timers_txt e servizi_txt: uscite di systemctl show; elenco_json: list-timers -o json."""
    try:
        tempi = {x.get("unit"): x for x in json.loads(elenco_json or "[]") if isinstance(x, dict)}
    except ValueError:
        tempi = {}
    servizi = {b.get("Id"): b for b in blocchi_show(servizi_txt)}
    out = []
    for t in blocchi_show(timers_txt):
        tid = t.get("Id") or ""
        if not tid.endswith(".timer") or not any(fnmatch.fnmatch(tid, p + ".timer") or fnmatch.fnmatch(tid, p) for p in TIMER_VPS):
            continue
        nome = tid[:-len(".timer")]
        svc_id = t.get("Unit") or nome + ".service"
        s = servizi.get(svc_id, {})
        cal, mono = calendari_di(t)
        tt = tempi.get(tid, {})
        attivo = t.get("UnitFileState") in ("enabled", "static", "linked") and t.get("ActiveState") == "active"
        in_corso = s.get("ActiveState") in ("activating", "active", "reloading") and s.get("SubState") not in ("exited", "dead")
        inizio, fine = _ts(s.get("ExecMainStartTimestamp")), _ts(s.get("ExecMainExitTimestamp"))
        ultimo = _ts(tt.get("last")) or inizio
        prossimo = _ts(tt.get("next")) if attivo else None
        esito = None
        if inizio:
            esito = "ok" if s.get("Result") == "success" and str(s.get("ExecMainStatus") or "0") == "0" else "errore"
        if in_corso:
            esito = "in_corso"
        comando = comando_di(s.get("ExecStart", ""))
        out.append({
            "id": "vps:" + nome, "fonte": "vps", "dove": "VPS", "nome": nome, "unita": svc_id, "timer": tid,
            "descrizione": t.get("Description") or s.get("Description") or nome,
            "orario": testo_calendario(cal, mono), "calendario": cal, "intervallo": dict(mono),
            "orario_grezzo": "; ".join(cal) or "; ".join(f"{k}={v}" for k, v in mono),
            "attivo": attivo, "in_corso": in_corso, "esito": esito,
            "codice": None if not inizio else (int(s["ExecMainStatus"]) if str(s.get("ExecMainStatus", "")).lstrip("-").isdigit() else None),
            "risultato": s.get("Result") or "",
            "ultimo": ultimo, "fine": fine, "prossimo": prossimo,
            "comando": _pulisci(comando, 600), "log_file": file_log_di(comando), "_comando": comando,
            # per «Modifica»: il comando nuovo va già dentro «/bin/bash -c "…"», quindi si propone solo quello che c'è dentro
            "comando_modifica": _pulisci(re.sub(r"^/bin/bash -c ", "", comando), 600),
            "file": s.get("FragmentPath") or "", "dropin": s.get("DropInPaths") or "",
            "avviabile": True, "perche_no": "",
            "modifica": {"orario": True, "comando": True, "descrizione": True, "attivo": True},
        })
    return out


# ---------------------------------------------------------------- cron

CAMPI_CRON = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
SPECIALI_CRON = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
                 "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}


def campo_cron(testo, minimo, massimo):
    """L'insieme dei valori di un campo cron («*/10», «3,13», «1-5», «0-30/15»). RoutineNonValida se non va."""
    valori = set()
    for parte in testo.split(","):
        m = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", parte)
        if not m:
            raise RoutineNonValida(f"campo cron non valido: «{testo}»")
        base, passo = m.group(1), int(m.group(2) or 1)
        if passo < 1:
            raise RoutineNonValida(f"passo cron non valido: «{testo}»")
        if base == "*":
            a, b = minimo, massimo
        elif "-" in base:
            a, b = (int(x) for x in base.split("-"))
        else:
            a = b = int(base)
            if m.group(2):
                b = massimo
        if a < minimo or b > massimo or a > b:
            raise RoutineNonValida(f"valore cron fuori dall'intervallo {minimo}-{massimo}: «{testo}»")
        valori.update(range(a, b + 1, passo))
    return valori


def orario_cron(espr):
    """«*/10 * * * *» → (minuti, ore, giorni, mesi, giorni_settimana, giorno_libero, settimana_libera). Valida."""
    espr = SPECIALI_CRON.get(espr.strip(), espr.strip())
    campi = espr.split()
    if len(campi) != 5:
        raise RoutineNonValida("l'orario di cron vuole 5 campi: minuto ora giorno mese giorno-della-settimana")
    insiemi = [campo_cron(c, a, b) for c, (a, b) in zip(campi, CAMPI_CRON)]
    if 7 in insiemi[4]:
        insiemi[4].add(0)
    return (*insiemi, campi[2] == "*", campi[4] == "*")


def _combacia(o, d):
    mi, ore, gg, mesi, sett, gg_libero, sett_libera = o
    if d.minute not in mi or d.hour not in ore or d.month not in mesi:
        return False
    g_ok, s_ok = d.day in gg, ((d.weekday() + 1) % 7) in sett
    if gg_libero or sett_libera:
        return g_ok and s_ok
    return g_ok or s_ok


def cron_vicino(espr, dopo, zona, verso=1, limite_min=8 * 24 * 60):
    """La prossima (verso=1) o l'ultima (verso=-1) esecuzione, in secondi epoch. None se oltre 8 giorni."""
    try:
        o = orario_cron(espr)
    except RoutineNonValida:
        return None
    d = datetime.fromtimestamp(dopo, zona).replace(second=0, microsecond=0)
    if verso > 0:
        d += timedelta(minutes=1)
    for _ in range(limite_min):
        if _combacia(o, d):
            return d.timestamp()
        d += timedelta(minutes=verso)
    return None


def testo_cron(espr, zona):
    """Una frase: «ogni 10 min», «ogni giorno 05:40», «ogni ora ai minuti 3, 13…»; le ore in ora di Roma."""
    e = SPECIALI_CRON.get(espr.strip(), espr.strip())
    c = e.split()
    if len(c) != 5:
        return espr
    m = re.fullmatch(r"\*/(\d+)", c[0])
    if m and c[1:] == ["*"] * 4:
        return f"ogni {m.group(1)} min"
    if c[1:] == ["*"] * 4 and re.fullmatch(r"[\d,]+", c[0]):
        return f"ogni ora ai minuti {c[0].replace(',', ', ')}"
    if re.fullmatch(r"\d+", c[0]) and re.fullmatch(r"\d+", c[1]) and c[2:] == ["*"] * 3:
        oggi = datetime.now(zona).replace(hour=int(c[1]), minute=int(c[0]), second=0, microsecond=0)
        r = oggi.astimezone(ROMA) if ROMA else oggi
        return f"ogni giorno {r.strftime('%H:%M')}"
    return e + " (ora della VPS)"


def _slug(t):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")[:40]


GENERICHE = {"scripts", "script", "bin", "strumenti", "root", "opt", "desktop", "usr", "local", "home", "sbin"}


def nome_cron(comando, etichetta=None):
    if etichetta and NOME.fullmatch(etichetta):
        return etichetta
    for p in re.findall(r"(/[A-Za-z0-9._/-]+)", comando):
        parti = [x for x in p.split("/") if x]
        if not parti or p.startswith(("/usr/bin/", "/bin/", "/usr/local/bin/", "/dev/")) and not p.endswith((".sh", ".py")):
            continue
        if ">" in comando.split(p)[0][-3:]:
            continue        # è il file di log, non lo script
        stem = parti[-1].rsplit(".", 1)[0]
        padre = next((x for x in reversed(parti[:-1]) if x.lower() not in GENERICHE), "")
        return _slug(f"{padre}-{stem}" if padre else stem) or "cron"
    return _slug(comando.split()[0] if comando.split() else "cron") or "cron"


def righe_cron(testo):
    """Il crontab riga per riga: [{n, orario, comando, descrizione, etichetta, pausa}] (n = indice della riga)."""
    out, commento = [], []
    for n, riga in enumerate((testo or "").splitlines()):
        s = riga.strip()
        if not s:
            commento = []
            continue
        pausa = s.startswith(PAUSA_CRON.strip())
        if pausa:
            s = s[len(PAUSA_CRON.strip()):].strip()
        elif s.startswith("#"):
            commento.append(s.lstrip("#").strip())
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", s):
            continue
        if s.startswith("@"):
            orario, _, comando = s.partition(" ")
        else:
            campi = s.split(None, 5)
            if len(campi) < 6:
                continue
            orario, comando = " ".join(campi[:5]), campi[5]
        try:
            orario_cron(orario)
        except RoutineNonValida:
            continue
        descr, etichetta = "", None
        for c in commento:
            m = re.match(r"routine(?:\s+([a-z0-9-]{1,40}))?\s*:\s*(.*)", c)
            if m:
                etichetta, descr = m.group(1), m.group(2)
        if not descr:
            fine = re.search(r"\s#\s*(.+)$", comando)
            descr = fine.group(1).strip() if fine else (commento[0] if commento else "")
        out.append({"n": n, "orario": orario, "comando": comando.strip(), "descrizione": descr[:160],
                    "etichetta": etichetta, "pausa": pausa})
        commento = []
    return out


def routine_cron(testo, mtimes_txt="", zona=timezone.utc, adesso=None):
    adesso = adesso or time.time()
    mtimes = {}
    for riga in (mtimes_txt or "").splitlines():
        t, _, p = riga.partition(" ")
        if t.isdigit():
            mtimes[p.strip()] = int(t)
    out, visti = [], {}
    for r in righe_cron(testo):
        nome = nome_cron(r["comando"], r["etichetta"])
        visti[nome] = visti.get(nome, 0) + 1
        if visti[nome] > 1:
            nome = f"{nome}-{visti[nome]}"
        log = file_log_di(r["comando"])
        out.append({
            "id": "cron:" + nome, "fonte": "cron", "dove": "VPS", "nome": nome, "riga": r["n"],
            "descrizione": r["descrizione"] or nome, "orario": testo_cron(r["orario"], zona), "cron": r["orario"],
            "attivo": not r["pausa"], "in_corso": False, "esito": None, "codice": None,
            "ultimo": None if r["pausa"] else cron_vicino(r["orario"], adesso, zona, -1),
            "prossimo": None if r["pausa"] else cron_vicino(r["orario"], adesso, zona, 1),
            "log_aggiornato": mtimes.get(log) if log else None,
            "comando": _pulisci(r["comando"], 600), "log_file": log, "_comando": r["comando"],
            "avviabile": True, "perche_no": "",
            "modifica": {"orario": True, "comando": True, "descrizione": True, "attivo": True},
        })
    return out


# ---------------------------------------------------------------- launchd (Mac)

def stato_launchctl(testo):
    """«launchctl list» → {label: (pid|None, ultimo_codice|None)}."""
    out = {}
    for riga in (testo or "").splitlines()[1:]:
        p = riga.split("\t")
        if len(p) != 3:
            p = riga.split()
        if len(p) != 3:
            continue
        pid = int(p[0]) if p[0].isdigit() else None
        cod = int(p[1]) if p[1].lstrip("-").isdigit() else None
        out[p[2].strip()] = (pid, cod)
    return out


def _intervalli_cal(sci):
    return [x for x in (sci if isinstance(sci, list) else [sci]) if isinstance(x, dict)]


def testo_launchd(d):
    sci = d.get("StartCalendarInterval")
    if sci:
        parti, quotidiane = [], []
        for x in _intervalli_cal(sci):
            ora = f"{int(x.get('Hour', 0)):02d}:{int(x.get('Minute', 0)):02d}" if "Hour" in x else f"ogni ora al minuto {x.get('Minute', 0)}"
            if "Weekday" in x:
                parti.append(f"{GIORNI[(int(x['Weekday']) - 1) % 7]} {ora}")
            elif "Day" in x:
                parti.append(f"il {x['Day']}" + (f"/{x['Month']}" if "Month" in x else "") + f" {ora}")
            elif "Hour" in x:
                quotidiane.append((int(x.get("Hour", 0)), int(x.get("Minute", 0))))
            else:
                parti.append(ora)
        if quotidiane:
            parti.insert(0, testo_orari(quotidiane))
        return "; ".join(parti)
    if d.get("StartInterval"):
        s = int(d["StartInterval"])
        if s % 3600 == 0:
            return f"ogni {s // 3600} h"
        return f"ogni {s // 60} min" if s % 60 == 0 else f"ogni {s} s"
    if d.get("KeepAlive"):
        return "sempre acceso"
    if d.get("RunAtLoad"):
        return "all'accensione"
    return "a mano"


def prossimo_launchd(d, adesso):
    """Il prossimo StartCalendarInterval in ora del Mac (ora di Roma)."""
    cand = []
    for x in _intervalli_cal(d.get("StartCalendarInterval")):
        o = (str(x.get("Minute", "*")) + " " + str(x.get("Hour", "*")) + " " + str(x.get("Day", "*")) + " "
             + str(x.get("Month", "*")) + " " + str(x.get("Weekday", "*")))
        t = cron_vicino(o, adesso, ROMA or timezone.utc, 1, 32 * 24 * 60)
        if t:
            cand.append(t)
    return min(cand) if cand else None


def routine_mac(cartella=None, launchctl_txt="", adesso=None):
    adesso = adesso or time.time()
    cartella = Path(cartella or AGENTI_MAC)
    stati = stato_launchctl(launchctl_txt)
    out = []
    if not cartella.is_dir():
        return out
    for f in sorted(cartella.iterdir()):
        nome_f = f.name
        spento = nome_f.endswith(".plist.disabled")
        if not (nome_f.endswith(".plist") or spento) or not nome_f.startswith(PREFISSI_MAC):
            continue
        try:
            d = plistlib.loads(f.read_bytes())
        except Exception:  # noqa: BLE001
            continue
        label = str(d.get("Label") or nome_f.split(".plist")[0])
        pid, cod = stati.get(label, (None, None))
        caricato = label in stati
        sempre = bool(d.get("KeepAlive")) and not d.get("StartCalendarInterval") and not d.get("StartInterval")
        argomenti = d.get("ProgramArguments") or ([d["Program"]] if d.get("Program") else [])
        comando = " ".join(shlex.quote(str(a)) for a in argomenti)
        log = d.get("StandardOutPath") or d.get("StandardErrorPath") or None
        try:
            log_t = Path(log).stat().st_mtime if log else None
        except OSError:
            log_t = None
        in_corso = bool(pid) and not sempre
        esito = "in_corso" if in_corso else (None if cod is None else ("ok" if cod == 0 else "errore"))
        perche_no = ("sempre acceso: si riavvia da Computer, non da qui" if sempre else
                     "non caricato: riattivalo con «Modifica» → attiva" if not caricato else "")
        out.append({
            "id": "mac:" + label, "fonte": "mac", "dove": "Mac", "nome": label, "file": str(f),
            "descrizione": str(d.get("Comment") or label.split(".", 2)[-1].replace("-", " ")),
            "orario": testo_launchd(d), "attivo": caricato and not spento, "caricato": caricato, "sempre": sempre,
            "in_corso": in_corso, "pid": pid if sempre else None, "esito": esito if not sempre else ("ok" if pid else "errore"),
            "codice": cod, "ultimo": log_t, "prossimo": prossimo_launchd(d, adesso) if caricato else None,
            "comando": _pulisci(comando, 600), "log_file": log, "_comando": comando,
            "_plist": {k: d[k] for k in ("StartCalendarInterval", "StartInterval") if k in d}, "_argomenti": [str(a) for a in argomenti],
            "avviabile": caricato and not sempre, "perche_no": perche_no,
            "modifica": {"orario": not sempre, "comando": True, "descrizione": False, "attivo": label != "com.jarvis.command-center"},
        })
    return out


# ---------------------------------------------------------------- gruppi

def carica_gruppi():
    try:
        return json.loads(FILE_GRUPPI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"gruppi": [], "regole": [], "routine": {}}


EFFETTI = ("lettura", "scrive", "invia")


def classifica(r, conf=None):
    """(gruppo, tipo, effetto) di una routine: prima la voce esplicita in «routine», poi la prima regola che combacia.
    2026-10-05 sera (verificatore): «controllo» vale SOLO con effetto «lettura» deciso nella voce esplicita (letto
    nello script vero); «dati» solo con effetto «scrive». Una routine sconosciuta non è mai un controllo."""
    conf = conf or carica_gruppi()
    esplicita = (conf.get("routine") or {}).get(r["id"])
    if isinstance(esplicita, dict):
        effetto = esplicita.get("effetto") if esplicita.get("effetto") in EFFETTI else ""
        tipo = esplicita.get("tipo") or ""
        if (tipo == "controllo" and effetto != "lettura") or (tipo == "dati" and effetto != "scrive"):
            tipo = ""
        return esplicita.get("gruppo") or "sistema", tipo, effetto
    # 2026-10-05: la cartella di casa («/Users/tu») non conta, se no tutto il Mac finisce in un gruppo solo
    testo = f"{r['id']} {r.get('descrizione', '')} {r.get('comando', '')}".replace(str(Path.home()), "~")
    for regola in conf.get("regole") or []:
        try:
            if re.search(regola.get("se", "(?!)"), testo, re.I):
                return regola.get("gruppo") or "sistema", "", ""   # dalle regole: mai controllo né dati
        except re.error:
            continue
    return "sistema", "", ""


def gruppi_per_lavagna(routine, extra=(), conf=None):
    """I gruppi dei comandi rapidi: quelli di routine-gruppi.json più quelli della lavagna e delle riunioni che non
    combaciano con nessun alias (i gruppi futuri). Ognuno con le sue routine «controllo» e «dati» avviabili."""
    conf = conf or carica_gruppi()
    gruppi, alias = [], {}
    for g in conf.get("gruppi") or []:
        if not isinstance(g, dict) or not g.get("id"):
            continue
        gruppi.append({"id": g["id"], "nome": g.get("nome") or g["id"], "controllo": [], "dati": [], "lavagna": bool(g.get("lavagna", True))})
        for a in [g["id"], *(g.get("alias") or [])]:
            alias[str(a).lower()] = g["id"]
    for e in extra:
        gid, nome = str(e.get("id") or ""), str(e.get("nome") or "")
        chiavi = {gid.lower(), _slug(nome), gid.lower().removeprefix("spazio-")}
        if not gid or any(k in alias for k in chiavi):
            continue
        nuovo = _slug(nome) or gid
        alias.update({k: nuovo for k in chiavi})
        gruppi.append({"id": nuovo, "nome": nome or gid, "controllo": [], "dati": [], "lavagna": True})
    per_id = {g["id"]: g for g in gruppi}
    for r in routine:
        g = per_id.get(r.get("gruppo"))
        if g and r.get("avviabile") and ((r.get("tipo") == "controllo" and r.get("effetto") == "lettura")
                                         or (r.get("tipo") == "dati" and r.get("effetto") == "scrive")):
            g[r["tipo"]].append(r["id"])
    return [g for g in gruppi if g["lavagna"]]


# ---------------------------------------------------------------- l'elenco, con la cache

_CACHE = {"ts": 0.0, "dati": None, "vps": {}, "crontab": ""}
_CACHE_LOCK = threading.Lock()


def leggi_vps():
    """Una chiamata ssh. → dict con i pezzi grezzi e lo stato della lettura."""
    codice, out = ssh(LETTURA_VPS, timeout=40)
    pezzi = out.split(SEP + "\n") if SEP in out else []
    if codice != 0 or len(pezzi) < 7:
        return {"ok": False, "errore": f"VPS non raggiungibile ({codice}): {_pulisci(out, 160).strip()}"}
    fondo = pezzi[6].split()
    zona = timezone.utc
    if fondo and ROMA and fondo[0] not in ("UTC", "Etc/UTC"):
        try:
            zona = ZoneInfo(fondo[0])
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "timers": pezzi[0], "servizi": pezzi[1], "elenco": pezzi[2], "crontab": pezzi[3],
            "hash_cron": pezzi[4].strip(), "mtimes": pezzi[5], "zona": zona,
            "compiti_sha": pezzi[7] if len(pezzi) > 7 else "", "regole": pezzi[8] if len(pezzi) > 8 else "",
            "ora_vps": int(fondo[-1]) if fondo and fondo[-1].isdigit() else None}


def elenco(forza=False, extra_gruppi=()):
    with _CACHE_LOCK:
        if not forza and _CACHE["dati"] and time.time() - _CACHE["ts"] < CACHE_S:
            d = dict(_CACHE["dati"])
            d["esecuzioni"] = esecuzioni()
            return d
        avvisi, routine = [], []
        v = leggi_vps()
        if v["ok"]:
            routine += routine_systemd(v["timers"], v["servizi"], v["elenco"])
            routine += routine_cron(v["crontab"], v["mtimes"], v["zona"])
            _CACHE["vps"] = v
        else:
            avvisi.append(v["errore"])
        if MAC:
            _, lc = ESEGUI(["launchctl", "list"], timeout=10)
            routine += routine_mac(AGENTI_MAC, lc)
        conf = carica_gruppi()
        for r in routine:
            r["gruppo"], r["tipo"], r["effetto"] = classifica(r, conf)
            voce = (conf.get("routine") or {}).get(r["id"]) or {}
            if voce.get("avvio") is False:           # «non avviare» (es. un ciclo che chiude un programma aperto)
                r["avviabile"], r["perche_no"] = False, voce.get("perche") or "segnata «non avviare» in routine-gruppi.json"
        try:
            import routine_salva
            avvisi += routine_salva.arricchisci(routine, v if v.get("ok") else {})
        except Exception as e:  # noqa: BLE001
            avvisi.append(f"orari e regole non letti: {type(e).__name__}: {str(e)[:120]}")
        _CACHE["grezzi"] = {r["id"]: {k: r.pop(k) for k in [k for k in r if k.startswith("_")]} for r in routine}
        for r in routine:
            r["ultimo_testo"] = testo_ora(r.get("ultimo"))
            r["prossimo_testo"] = testo_ora(r.get("prossimo"))
        conta = {}
        for r in routine:
            conta.setdefault(r["fonte"], 0)
            conta[r["fonte"]] += 1
        dati = {"routine": routine, "avvisi": avvisi, "letto": time.time(), "conta": conta,
                "gruppi": gruppi_per_lavagna(routine, extra_gruppi, conf),
                "nomi_gruppi": {g["id"]: g.get("nome", g["id"]) for g in conf.get("gruppi") or [] if isinstance(g, dict)},
                "tipi": ["controllo", "dati", ""]}
        _CACHE.update(ts=time.time(), dati=dati)
        d = dict(dati)
        d["esecuzioni"] = esecuzioni()
        return d


def invalida():
    with _CACHE_LOCK:
        _CACHE["ts"] = 0.0


def trova(rid):
    if not isinstance(rid, str) or not ID.fullmatch(rid):
        raise NonTrovata("routine non trovata")
    d = elenco()
    for r in d["routine"]:
        if r["id"] == rid:
            return r
    raise NonTrovata("routine non trovata")


# ---------------------------------------------------------------- registro

AVVISA = None             # il server ci mette una funzione(evento, dati) per il flusso e gli eventi


def registra(azione, rid, esito, **dettagli):
    riga = {"ts": round(time.time(), 3), "azione": azione, "id": rid, "esito": esito}
    riga.update({k: (_pulisci(v, 4000) if isinstance(v, str) else v) for k, v in dettagli.items() if v not in (None, "")})
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(DIR / "registro.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(riga, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass
    try:
        import attivita
        ev = {"partito": "partito", "ok": "risposta", "errore": "errore", "preparato": "richiesta", "rifiutato": "errore"}.get(esito, "richiesta")
        attivita.registra(ev, f"routine-{rid}-{int(riga['ts'])}", "utente", "jarvis",
                          f"Routine {azione}: {rid} ({esito})", fonte="routine", esito=str(dettagli.get("uscita") or "")[:300])
    except Exception:  # noqa: BLE001
        pass
    if AVVISA:
        try:
            AVVISA(azione, riga)
        except Exception:  # noqa: BLE001
            pass


def ultime_righe_registro(n=50):
    try:
        righe = (DIR / "registro.jsonl").read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for x in reversed(righe):
        try:
            out.append(json.loads(x))
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- avvia ora, e lo stato in tempo reale

_ESEC = {}
_ESEC_LOCK = threading.Lock()


def esecuzioni():
    with _ESEC_LOCK:
        return sorted((dict(e) for e in _ESEC.values()), key=lambda e: -e["partito"])[:30]


def _aggiorna_esec(eid, **campi):
    with _ESEC_LOCK:
        e = _ESEC.get(eid)
        if e:
            e.update(campi)
            copia = dict(e)
        else:
            copia = None
    if copia and AVVISA:
        try:
            AVVISA("esecuzione", copia)
        except Exception:  # noqa: BLE001
            pass
    return copia


def _stato_unita(unita):
    cod, out = ssh("systemctl show --timestamp=unix -p ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestamp,"
                   f"ExecMainExitTimestamp,LoadState {shlex.quote(unita)}", timeout=20)
    b = blocchi_show(out)
    return (b[0] if b else {}) if cod == 0 else None


def _segui_systemd(eid, unita, da, transitoria=False):
    inizio = time.time()
    while time.time() - inizio < SEGUI_MAX_S:
        time.sleep(2)
        s = _stato_unita(unita)
        if s is None:
            continue
        att = s.get("ActiveState")
        uscita = _ts(s.get("ExecMainExitTimestamp"))
        finita = (att in ("inactive", "failed") or (transitoria and s.get("SubState") == "exited")) and \
            (uscita is None or uscita >= da - 2)
        if s.get("LoadState") == "not-found" and transitoria:
            finita = True
        if finita:
            ok = s.get("Result") in ("success", "") and str(s.get("ExecMainStatus") or "0") == "0"
            cod = int(s["ExecMainStatus"]) if str(s.get("ExecMainStatus", "")).lstrip("-").isdigit() else None
            e = _aggiorna_esec(eid, stato="ok" if ok else "errore", codice=cod, finito=time.time(),
                               esito=("finita bene" if ok else f"finita con errore ({s.get('Result')}, codice {cod})"))
            if transitoria:
                ssh(f"systemctl stop {shlex.quote(unita)} 2>/dev/null; systemctl reset-failed {shlex.quote(unita)} 2>/dev/null; true", timeout=20)
            registra("avvia", e["id"] if e else eid, "ok" if ok else "errore", uscita=e.get("esito") if e else "")
            invalida()
            return
        _aggiorna_esec(eid, stato="in_corso", esito=f"{att}/{s.get('SubState')}")
    _aggiorna_esec(eid, stato="lunga", esito="in corso da più di 30 minuti: guarda il log")


def _stato_mac(label):
    cod, out = ESEGUI(["launchctl", "list", label], timeout=10)
    if cod != 0:
        return None
    pid = re.search(r'"PID"\s*=\s*(\d+)', out)
    st = re.search(r'"LastExitStatus"\s*=\s*(-?\d+)', out)
    return (int(pid.group(1)) if pid else None, int(st.group(1)) if st else None)


def _segui_mac(eid, label):
    inizio = time.time()
    visto = False
    while time.time() - inizio < SEGUI_MAX_S:
        time.sleep(1.5)
        s = _stato_mac(label)
        if s is None:
            continue
        pid, cod = s
        if pid:
            visto = True
            _aggiorna_esec(eid, stato="in_corso", esito=f"in corso (pid {pid})")
            continue
        if visto or time.time() - inizio > 4:
            ok = cod in (0, None)
            e = _aggiorna_esec(eid, stato="ok" if ok else "errore", codice=cod, finito=time.time(),
                               esito="finita bene" if ok else f"finita con errore (codice {cod})")
            registra("avvia", e["id"] if e else eid, "ok" if ok else "errore", uscita=e.get("esito") if e else "")
            invalida()
            return
    _aggiorna_esec(eid, stato="lunga", esito="in corso da più di 30 minuti: guarda il log")


def avvia(rid, chi="pagina"):
    """«Avvia ora»: consentito senza conferma (l'utente, 2026-10-05). Torna l'esecuzione, che poi si segue da sola."""
    r = trova(rid)
    if not r.get("avviabile"):
        raise RoutineNonValida(r.get("perche_no") or "questa routine non si avvia da qui")
    with _ESEC_LOCK:
        for e in _ESEC.values():
            if e["id"] == rid and e["stato"] in ("partenza", "in_corso"):
                return dict(e)
    eid = secrets.token_hex(6)
    e = {"eid": eid, "id": rid, "nome": r["nome"], "descrizione": r["descrizione"], "partito": time.time(),
         "stato": "partenza", "esito": "parte…", "codice": None, "finito": None, "chi": chi}
    with _ESEC_LOCK:
        _ESEC[eid] = e
        for k in sorted(_ESEC, key=lambda k: _ESEC[k]["partito"])[:-50]:
            del _ESEC[k]
    if r["fonte"] == "vps":
        cod, out = ssh(f"date +%s; systemctl start --no-block {shlex.quote(r['unita'])}", timeout=25)
        da = _ts(out.split()[0]) if cod == 0 and out.split() else None
        if cod != 0:
            _aggiorna_esec(eid, stato="errore", esito=f"non partita: {_pulisci(out, 200).strip()}", finito=time.time())
            registra("avvia", rid, "errore", uscita=out)
            return _aggiorna_esec(eid)
        threading.Thread(target=_segui_systemd, args=(eid, r["unita"], da or time.time()), daemon=True).start()
    elif r["fonte"] == "cron":
        riga = _riga_cron_vera(r)
        unita = f"cc-routine-{r['nome'][:40]}-{int(time.time())}"
        remoto = (f"date +%s; systemd-run --unit={shlex.quote(unita)} --no-block -p RemainAfterExit=yes "
                  f"-p WorkingDirectory=/root -E HOME=/root --description={shlex.quote('Routine (cron, a mano): ' + r['nome'])} "
                  f"/bin/bash -c {shlex.quote(riga['comando'].replace(chr(92) + '%', '%'))}")
        cod, out = ssh(remoto, timeout=25)
        if cod != 0:
            _aggiorna_esec(eid, stato="errore", esito=f"non partita: {_pulisci(out, 200).strip()}", finito=time.time())
            registra("avvia", rid, "errore", uscita=out)
            return _aggiorna_esec(eid)
        da = _ts(out.split()[0]) if out.split() else None
        threading.Thread(target=_segui_systemd, args=(eid, unita + ".service", da or time.time(), True), daemon=True).start()
    elif r["fonte"] == "mac":
        cod, out = ESEGUI(["launchctl", "kickstart", f"gui/{os.getuid()}/{r['nome']}"], timeout=15)
        if cod != 0:
            _aggiorna_esec(eid, stato="errore", esito=f"non partita: {_pulisci(out, 200).strip()}", finito=time.time())
            registra("avvia", rid, "errore", uscita=out)
            return _aggiorna_esec(eid)
        threading.Thread(target=_segui_mac, args=(eid, r["nome"]), daemon=True).start()
    registra("avvia", rid, "partito", chi=chi)
    invalida()          # 2026-10-05 (verificatore): «ultimo» si aggiorna alla prossima lettura
    return _aggiorna_esec(eid, stato="in_corso", esito="partita")


def _riga_cron_vera(r):
    """La riga di cron dal crontab letto (non dalla pagina): il comando senza maschere."""
    tutte = routine_cron(_CACHE.get("vps", {}).get("crontab", ""), "", timezone.utc)
    righe = {x["n"]: x for x in righe_cron(_CACHE.get("vps", {}).get("crontab", ""))}
    for t in tutte:
        if t["id"] == r["id"]:
            return righe[t["riga"]]
    raise NonTrovata("riga di cron non trovata: ricarica l'elenco")


_SEQ = {}


def avvia_molte(ids, chi="lavagna"):
    """«Tutti» dei comandi rapidi: in sequenza, la successiva parte quando la precedente è finita."""
    if not isinstance(ids, list) or not ids or len(ids) > 40 or not all(isinstance(x, str) and ID.fullmatch(x) for x in ids):
        raise RoutineNonValida("ids: da 1 a 40 routine")
    for x in ids:
        trova(x)
    sid = secrets.token_hex(5)
    _SEQ[sid] = {"sid": sid, "ids": ids, "fatte": 0, "stato": "in_corso", "partito": time.time()}

    def giro():
        for i, x in enumerate(ids):
            try:
                e = avvia(x, chi=chi)
            except Exception as err:  # noqa: BLE001
                registra("avvia", x, "errore", uscita=str(err))
                continue
            inizio = time.time()
            while time.time() - inizio < 20 * 60:
                with _ESEC_LOCK:
                    st = (_ESEC.get(e["eid"]) or {}).get("stato")
                if st not in ("partenza", "in_corso"):
                    break
                time.sleep(2)
            _SEQ[sid]["fatte"] = i + 1
        _SEQ[sid]["stato"] = "finita"
    threading.Thread(target=giro, daemon=True).start()
    return _SEQ[sid]


# ---------------------------------------------------------------- log

def log(rid, righe=80):
    r = trova(rid)
    pezzi = []
    if r["fonte"] in ("vps", "cron"):
        comandi = []
        if r["fonte"] == "vps":
            comandi.append(f"echo '--- journal {r['unita']}'; journalctl -u {shlex.quote(r['unita'])} -n {righe} --no-pager -o short-iso 2>&1")
        else:
            comandi.append(f"echo '--- lanci a mano (cc-routine-{r['nome']})'; journalctl -u 'cc-routine-{r['nome']}-*' -n 30 --no-pager -o short-iso 2>&1")
        if r.get("log_file") and PERCORSO_LOG.fullmatch(r["log_file"]):
            comandi.append(f"echo '--- {r['log_file']}'; tail -n {righe} {shlex.quote(r['log_file'])} 2>&1")
        cod, out = ssh("; ".join(comandi), timeout=25)
        pezzi.append(out if cod == 0 or out else f"VPS non raggiungibile ({cod})")
    else:
        visti = set()
        for k in ("log_file",):
            p = r.get(k)
            if p and p not in visti:
                visti.add(p)
                try:
                    testo = Path(p).read_text(encoding="utf-8", errors="replace").splitlines()[-righe:]
                    pezzi.append(f"--- {p}\n" + "\n".join(testo))
                except OSError as e:
                    pezzi.append(f"--- {p}: {e}")
        if not pezzi:
            pezzi.append("Questa routine non scrive un file di log (StandardOutPath assente nel plist).")
    return {"id": rid, "testo": _pulisci("\n".join(pezzi), 60000), "letto": time.time()}


# ---------------------------------------------------------------- modifica e nuova: prepara → conferma

_PREP = {}
_PREP_LOCK = threading.Lock()


def _testo_breve(v, nome, massimo, vuoto_ok=False):
    if v is None:
        return None
    if not isinstance(v, str):
        raise RoutineNonValida(f"{nome}: un testo")
    v = v.strip()
    if not v and not vuoto_ok:
        raise RoutineNonValida(f"{nome}: non può essere vuoto")
    if len(v) > massimo:
        raise RoutineNonValida(f"{nome}: al massimo {massimo} caratteri")
    if re.search(r"[\x00-\x1f\x7f]", v):
        raise RoutineNonValida(f"{nome}: niente a capo né caratteri di controllo")
    if FINE in v:
        raise RoutineNonValida(f"{nome}: contiene una parola riservata")
    return v


def _intervallo(v):
    """«ogni 15 min», «15min», «2h» → minuti. None se non è un intervallo."""
    m = re.fullmatch(r"(?:ogni\s+)?(\d{1,6})\s*(min|m|minuti|h|ore|ora)?", v.strip().lower())
    if not m:
        return None
    n = int(m.group(1)) * (60 if (m.group(2) or "min").startswith(("h", "or")) else 1)
    if not 1 <= n <= 7 * 24 * 60:
        raise RoutineNonValida("intervallo: da 1 minuto a 7 giorni")
    return n


def calendario_systemd(v):
    """Un OnCalendar valido sulla VPS (systemd-analyze calendar), con Europe/Rome se non ha un fuso.
    → (espressione, prossima in testo)."""
    if not CALENDARIO.fullmatch(v):
        raise RoutineNonValida("orario: solo lettere, cifre e * : , . / ~ - + _ spazio (es. «*-*-* 07:00:00» o «Mon..Fri 08:30»)")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v.strip())
    if m:
        v = f"*-*-* {int(m.group(1)):02d}:{m.group(2)}:00"
    if not re.search(r"\b[A-Z][A-Za-z]+/[A-Za-z_]+$|\bUTC$", v):
        v = v.strip() + " Europe/Rome"
    cod, out = ssh(f"systemd-analyze calendar {shlex.quote(v)}", timeout=20)
    if cod != 0:
        raise RoutineNonValida(f"orario non valido per systemd: {_pulisci(out, 200).strip()}")
    prossima = re.search(r"Next elapse:\s*(.+)", out)
    return v, (prossima.group(1).strip() if prossima else "")


def _quota_systemd(cmd):
    """Un comando dentro ExecStart=/bin/bash -c "…": \\ e " protetti, % → %%, $ → $$ (systemd li espande)."""
    return '"' + cmd.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def _scrivi_file(percorso, contenuto):
    if any(riga.strip() == FINE for riga in contenuto.splitlines()):
        raise RoutineNonValida("contenuto non valido")
    return f"cat > {shlex.quote(percorso)} <<'{FINE}'\n{contenuto.rstrip()}\n{FINE}\n"


def _ora_file():
    return datetime.now(ROMA).strftime("%Y%m%d-%H%M%S") if ROMA else time.strftime("%Y%m%d-%H%M%S")


def _piano_vps(r, nuovo, orario, comando, descrizione, attivo, nome=None):
    righe = ["set -euo pipefail", f"TS={_ora_file()}"]
    riepilogo = []
    if nuovo:
        base = nome if nome.startswith("jarvis-") else f"jarvis-{nome}"
        svc, tim = f"/etc/systemd/system/{base}.service", f"/etc/systemd/system/{base}.timer"
        cal, _ = orario
        log = f"/var/log/{base}.log"
        righe += [f"test ! -e {svc} && test ! -e {tim} || {{ echo 'esiste già {base}: scegli un altro nome'; exit 3; }}"]
        righe.append(_scrivi_file(svc, "\n".join([
            "[Unit]", f"Description={descrizione}", "After=network-online.target", "OnFailure=jarvis-errore@%n.service", "",
            "[Service]", "Type=oneshot", "User=root", "WorkingDirectory=/root/jarvis",
            "Environment=HOME=/root TZ=Europe/Rome PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
            f"ExecStart=/bin/bash -c {_quota_systemd(comando + ' >> ' + log + ' 2>&1')}", "TimeoutStartSec=3h"])))
        sched = [f"OnCalendar={cal}", "Persistent=true"] if cal else [f"OnBootSec=3min", f"OnUnitActiveSec={orario[1]}min"]
        righe.append(_scrivi_file(tim, "\n".join(["[Unit]", f"Description={descrizione}", "", "[Timer]", *sched, "",
                                                  "[Install]", "WantedBy=timers.target"])))
        righe += ["systemctl daemon-reload", f"systemctl enable --now {base}.timer" if attivo is not False else "true",
                  f"systemctl list-timers --all --no-pager {base}.timer"]
        riepilogo.append(f"crea {base}.service e {base}.timer ({'attivo' if attivo is not False else 'in pausa'}), log in {log}")
        return righe, riepilogo, "vps:" + base
    tim, svc = r["timer"], r["unita"]
    if orario is not None or descrizione is not None:
        d = f"/etc/systemd/system/{tim}.d"
        f = f"{d}/50-routine.conf"
        if orario is not None:
            cal, minuti = orario
            sched = ["OnCalendar=", f"OnCalendar={cal}", "Persistent=true"] if cal else \
                ["OnCalendar=", "OnBootSec=3min", f"OnUnitActiveSec={minuti}min"]
            riepilogo.append(f"orario: {cal or f'ogni {minuti} min'}")
        else:
            sched = ["OnCalendar="] + [f"OnCalendar={c}" for c in r.get("calendario") or []] + \
                [f"{k}={v}" for k, v in (r.get("intervallo") or {}).items()]
        descr = descrizione if descrizione is not None else r["descrizione"]
        if descrizione is not None:
            riepilogo.append(f"descrizione: {descrizione}")
        righe += [f"mkdir -p {d}", f"[ -f {f} ] && cp -a {f} {f}.bak-$TS || true",
                  _scrivi_file(f, "\n".join(["# Command Center, pagina Routine: questo file lo riscrive «Modifica»",
                                             "[Unit]", f"Description={descr}", "", "[Timer]", *sched]))]
    if comando is not None:
        d = f"/etc/systemd/system/{svc}.d"
        f = f"{d}/50-routine.conf"
        righe += [f"mkdir -p {d}", f"[ -f {f} ] && cp -a {f} {f}.bak-$TS || true",
                  _scrivi_file(f, "\n".join(["# Command Center, pagina Routine: il comando nuovo", "[Service]",
                                             "ExecStart=", f"ExecStart=/bin/bash -c {_quota_systemd(comando)}"]))]
        riepilogo.append(f"comando: {comando}")
    righe.append("systemctl daemon-reload")
    if attivo is True:
        righe.append(f"systemctl enable --now {tim}")
        riepilogo.append("riattiva il timer")
    elif attivo is False:
        righe.append(f"systemctl disable --now {tim}")
        riepilogo.append("mette in pausa il timer (disable --now)")
    elif orario is not None and r.get("attivo"):
        righe.append(f"systemctl restart {tim}")
    righe.append(f"systemctl list-timers --all --no-pager {tim}")
    return righe, riepilogo, r["id"]


def _piano_cron(r, nuovo, orario, comando, descrizione, attivo, nome=None):
    v = _CACHE.get("vps") or {}
    testo, hash_cron = v.get("crontab", ""), v.get("hash_cron", "")
    if not hash_cron:
        raise RoutineNonValida("il crontab non è stato letto: ricarica l'elenco")
    righe_testo = testo.splitlines()
    riepilogo = []
    if nuovo:
        if any(x["id"] == "cron:" + nome for x in routine_cron(testo, "", timezone.utc)):
            raise RoutineNonValida(f"esiste già una routine cron «{nome}»")
        if orario is None or comando is None:
            raise RoutineNonValida("una routine cron nuova vuole orario e comando")
        riga = f"{orario} {comando}"
        aggiunta = ["", f"# routine {nome}: {descrizione or nome}", (PAUSA_CRON if attivo is False else "") + riga]
        nuove = righe_testo + aggiunta
        riepilogo.append(f"aggiunge in fondo: {riga}" + (" (in pausa)" if attivo is False else ""))
        rid = "cron:" + nome
    else:
        vera = _riga_cron_vera(r)
        n = vera["n"]
        o = orario if orario is not None else vera["orario"]
        c = comando if comando is not None else vera["comando"]
        pausa = (not attivo) if attivo is not None else vera["pausa"]
        nuove = list(righe_testo)
        nuove[n] = (PAUSA_CRON if pausa else "") + f"{o} {c}"
        if descrizione is not None:
            etichetta = f"# routine {r['nome']}: {descrizione}"
            if n > 0 and re.match(r"#\s*routine\b", nuove[n - 1].strip()):
                nuove[n - 1] = etichetta
            else:
                nuove.insert(n, etichetta)
            riepilogo.append(f"descrizione: {descrizione}")
        if orario is not None:
            riepilogo.append(f"orario: {orario}")
        if comando is not None:
            riepilogo.append(f"comando: {comando}")
        if attivo is not None:
            riepilogo.append("riattiva la riga" if attivo else "mette in pausa la riga (commentata con #ROUTINE-PAUSA)")
        rid = r["id"]
    nuovo_testo = "\n".join(nuove).rstrip("\n") + "\n"
    if any(x.strip() == FINE for x in nuovo_testo.splitlines()):
        raise RoutineNonValida("contenuto non valido")
    righe = ["set -euo pipefail", f"TS={_ora_file()}",
             f"ATTUALE=$(crontab -l 2>/dev/null | sha256sum | cut -c1-64)",
             f"[ \"$ATTUALE\" = \"{hash_cron}\" ] || {{ echo 'il crontab è cambiato dopo «Prepara»: rifai la modifica'; exit 3; }}",
             "crontab -l > /root/crontab-$TS.bak",
             f"crontab - <<'{FINE}'\n{nuovo_testo.rstrip()}\n{FINE}",
             "echo \"backup: /root/crontab-$TS.bak\"; crontab -l | tail -n 5"]
    return righe, riepilogo, rid


def _plist_xml(d):
    return plistlib.dumps(d, sort_keys=False).decode("utf-8")


def _piano_mac(r, nuovo, orario, comando, descrizione, attivo, nome=None):
    uid = os.getuid() if hasattr(os, "getuid") else 501
    righe = ["set -euo pipefail", f"TS={_ora_file()}"]
    riepilogo = []
    if nuovo:
        label = f"com.jarvis.{nome}"
        p = str(AGENTI_MAC / f"{label}.plist")
        logf = str(Path.home() / ".locale-onedrive" / "log" / f"{nome}.log")
        d = {"Label": label, "Comment": descrizione or nome, "ProgramArguments": ["/bin/bash", "-lc", comando],
             "StandardOutPath": logf, "StandardErrorPath": logf}
        d.update(orario)
        righe += [f"test ! -e {shlex.quote(p)} || {{ echo 'esiste già {label}'; exit 3; }}",
                  f"mkdir -p {shlex.quote(str(Path(logf).parent))}", _scrivi_file(p, _plist_xml(d)),
                  f"plutil -lint {shlex.quote(p)}"]
        if attivo is not False:
            righe.append(f"launchctl bootstrap gui/{uid} {shlex.quote(p)}")
        riepilogo.append(f"crea {label}.plist ({'caricato' if attivo is not False else 'non caricato'}), log in {logf}")
        return righe, riepilogo, "mac:" + label
    p, label = r["file"], r["nome"]
    q = shlex.quote(p)
    disabilitato = p.endswith(".disabled")
    vero = p[:-len(".disabled")] if disabilitato else p
    righe.append(f"cp -p {q} {q}.bak-$TS")
    if orario is not None:
        for k in ("StartCalendarInterval", "StartInterval"):
            righe.append(f"plutil -remove {k} {q} 2>/dev/null || true")
        for k, v in orario.items():
            righe.append(f"plutil -replace {k} -json {shlex.quote(json.dumps(v))} {q}")
        riepilogo.append("orario: " + testo_launchd(orario))
    if comando is not None:
        righe.append(f"plutil -remove Program {q} 2>/dev/null || true")
        righe.append(f"plutil -replace ProgramArguments -json {shlex.quote(json.dumps(['/bin/bash', '-lc', comando]))} {q}")
        riepilogo.append(f"comando: {comando}")
    righe.append(f"plutil -lint {q}")
    ricarica = orario is not None or comando is not None
    if attivo is False:
        righe += [f"launchctl bootout gui/{uid}/{label} 2>/dev/null || true"]
        if not disabilitato:
            righe.append(f"mv {q} {q}.disabled")
        riepilogo.append("mette in pausa (bootout e plist rinominato .disabled)")
    elif attivo is True or (ricarica and r.get("caricato")):
        if disabilitato:
            righe.append(f"mv {q} {shlex.quote(vero)}")
        righe += [f"launchctl bootout gui/{uid}/{label} 2>/dev/null || true",
                  f"launchctl bootstrap gui/{uid} {shlex.quote(vero)}"]
        if attivo is True:
            riepilogo.append("riattiva (bootstrap)")
    righe.append(f"launchctl list | grep -F {shlex.quote(label)} || echo 'non caricato'")
    return righe, riepilogo, r["id"]


def _orario_per(fonte, v):
    """Il campo «orario» della pagina, nel formato della fonte. RoutineNonValida se non va."""
    v = _testo_breve(v, "orario", 80)
    if fonte == "vps":
        minuti = _intervallo(v)
        if minuti:
            return (None, minuti)
        return (calendario_systemd(v)[0], None)
    if fonte == "cron":
        orario_cron(v)
        return v.strip()
    minuti = _intervallo(v)
    if minuti:
        return {"StartInterval": minuti * 60}
    orari = []
    for parte in v.split(","):
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", parte)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise RoutineNonValida("orario sul Mac: «07:30», più orari separati da virgole, oppure «ogni 15 min»")
        orari.append({"Hour": int(m.group(1)), "Minute": int(m.group(2))})
    return {"StartCalendarInterval": orari[0] if len(orari) == 1 else orari}


def prepara(dati, chi="pagina"):
    """Valida la modifica (o la routine nuova) e prepara il comando esatto. Non esegue niente."""
    if not isinstance(dati, dict):
        raise RoutineNonValida("serve un oggetto JSON")
    nuovo = dati.get("nuova") is True
    if nuovo:
        fonte = dati.get("fonte")
        if fonte not in ("vps", "cron", "mac"):
            raise RoutineNonValida("fonte: vps, cron o mac")
        if fonte == "mac" and not MAC:
            raise RoutineNonValida("le routine del Mac si creano solo dal Command Center del Mac")
        nome = dati.get("nome")
        if not isinstance(nome, str) or not NOME.fullmatch(nome):
            raise RoutineNonValida("nome: minuscole, cifre e trattini, da 1 a 40 caratteri")
        r = {"id": f"{fonte}:{nome}", "fonte": fonte, "nome": nome}
        if dati.get("orario") in (None, "") or dati.get("comando") in (None, ""):
            raise RoutineNonValida("una routine nuova vuole orario e comando")
        if fonte == "vps" and any(x["id"] in (f"vps:{nome}", f"vps:jarvis-{nome}") for x in elenco()["routine"]):
            raise RoutineNonValida(f"esiste già una routine «{nome}» sulla VPS")
    else:
        r = trova(dati.get("id"))
        fonte, nome = r["fonte"], None
    mod = r.get("modifica") or {"orario": True, "comando": True, "descrizione": True, "attivo": True}
    orario = comando = descrizione = attivo = None
    if dati.get("orario") not in (None, ""):
        if not nuovo and not mod.get("orario"):
            raise RoutineNonValida("l'orario di questa routine non si cambia da qui")
        orario = _orario_per(fonte, dati["orario"])
    if dati.get("comando") not in (None, ""):
        if not nuovo and not mod.get("comando"):
            raise RoutineNonValida("il comando di questa routine non si cambia da qui")
        comando = _testo_breve(dati["comando"], "comando", 600)
        if fonte == "cron" and re.search(r"(?<!\\)%", comando):
            raise RoutineNonValida("comando: in cron il simbolo % va scritto \\%")
    if dati.get("descrizione") not in (None, ""):
        if not nuovo and not mod.get("descrizione"):
            raise RoutineNonValida("la descrizione di questa routine non si cambia da qui")
        descrizione = _testo_breve(dati["descrizione"], "descrizione", 120)
        if fonte == "cron" and "%" in descrizione:
            raise RoutineNonValida("descrizione: in cron niente %")
    if "attivo" in dati and dati["attivo"] is not None:
        if not isinstance(dati["attivo"], bool):
            raise RoutineNonValida("attivo: vero o falso")
        if nuovo or dati["attivo"] != r.get("attivo"):
            if not nuovo and not mod.get("attivo"):
                raise RoutineNonValida("questa routine non si mette in pausa da qui")
            attivo = dati["attivo"]
    gruppo, tipo = dati.get("gruppo"), dati.get("tipo")
    if gruppo is not None and (not isinstance(gruppo, str) or not NOME.fullmatch(gruppo)):
        raise RoutineNonValida("gruppo: minuscole, cifre e trattini")
    if tipo not in (None, "", "controllo", "dati"):
        raise RoutineNonValida("tipo: controllo, dati o vuoto")
    if not nuovo and all(x is None for x in (orario, comando, descrizione, attivo)):
        raise RoutineNonValida("niente da cambiare")
    if nuovo and fonte == "vps" and descrizione is None:
        descrizione = nome
    piano = {"vps": _piano_vps, "cron": _piano_cron, "mac": _piano_mac}[fonte]
    righe, riepilogo, rid = piano(r, nuovo, orario, comando, descrizione, attivo, nome)
    script = "\n".join(righe).rstrip() + "\n"
    dove = "Mac (questo computer)" if fonte == "mac" else f"VPS (ssh {VPS}, come root)"
    pid = secrets.token_hex(8)
    codice = secrets.token_hex(16)
    prep = {"prep": pid, "id": rid, "fonte": fonte, "nuova": nuovo, "dove": dove, "riepilogo": riepilogo,
            "comando": (f"ssh {VPS} 'bash -s' <<'SCRIPT'\n{script}SCRIPT" if fonte != "mac" else f"bash -s <<'SCRIPT'\n{script}SCRIPT"),
            "preparato": time.time(), "scade": time.time() + PREP_MAX_S,
            "gruppo": gruppo if nuovo or gruppo else None, "tipo": tipo}
    with _PREP_LOCK:
        for k in [k for k, v in _PREP.items() if time.time() > v["scade"]]:
            del _PREP[k]
        _PREP[pid] = {**prep, "script": script, "codice": codice}
    registra("prepara", rid, "preparato", chi=chi, riepilogo="; ".join(riepilogo))
    return {**prep, "codice": codice, "valido_s": PREP_MAX_S}


def conferma(pid, codice, chi="pagina"):
    """Esegue il comando preparato. Senza il codice giusto, troppo presto o troppo tardi: rifiutato (e registrato)."""
    with _PREP_LOCK:
        p = _PREP.get(pid) if isinstance(pid, str) else None
        if not p:
            registra("conferma", str(pid)[:40], "rifiutato", motivo="nessun comando preparato con questo id")
            raise RoutineNonValida("serve la conferma: prima «Prepara», poi «Conferma ed esegui» (nessun comando preparato con questo id)")
        if not isinstance(codice, str) or not secrets.compare_digest(codice.encode(), p["codice"].encode()):
            registra("conferma", p["id"], "rifiutato", motivo="codice di conferma mancante o sbagliato")
            raise RoutineNonValida("serve la conferma esplicita dalla pagina: codice mancante o sbagliato")
        trascorso = time.time() - p["preparato"]
        if trascorso < PREP_MIN_S:
            raise RoutineNonValida("conferma troppo veloce: leggi il comando, poi conferma")
        del _PREP[pid]
    if time.time() > p["scade"]:
        registra("conferma", p["id"], "rifiutato", motivo="scaduto")
        raise RoutineNonValida("il comando preparato è scaduto (10 minuti): rifai «Prepara»")
    registra("conferma", p["id"], "partito", chi=chi, comando=p["script"])
    if p["fonte"] == "mac":
        cod, out = ESEGUI(["bash", "-s"], timeout=60, ingresso=p["script"])
    else:
        cod, out = ssh("bash -s", timeout=90, ingresso=p["script"])
    ok = cod == 0
    if ok and (p.get("gruppo") or p.get("tipo")):
        _salva_gruppo(p["id"], p.get("gruppo"), p.get("tipo"))
    registra("conferma", p["id"], "ok" if ok else "errore", uscita=out, codice=cod)
    invalida()
    return {"ok": ok, "id": p["id"], "codice": cod, "uscita": _pulisci(out, 6000)}


def annulla(pid):
    with _PREP_LOCK:
        p = _PREP.pop(pid, None) if isinstance(pid, str) else None
    if p:
        registra("annulla", p["id"], "annullato")
    return {"ok": True}


def _salva_gruppo(rid, gruppo, tipo, effetto=None):
    """Dopo una routine nuova confermata: il suo gruppo e tipo in routine-gruppi.json («routine»)."""
    conf = carica_gruppi()
    voce = conf.setdefault("routine", {}).get(rid) or {}
    if gruppo:
        voce["gruppo"] = gruppo
    if tipo is not None:
        voce["tipo"] = tipo
    if effetto:
        voce["effetto"] = effetto
        voce.setdefault("nota", "effetto calcolato dallo script al «Salva» della pagina Routine")
    conf["routine"][rid] = voce
    tmp = FILE_GRUPPI.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, FILE_GRUPPI)

