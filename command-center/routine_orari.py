#!/usr/bin/env python3
"""Gli orari delle Routine come nelle attività pianificate di Claude Code (l'utente, 2026-10-05 14:08: «le classiche
opzioni… giorno, quale giorno o tutti i giorni… identico; devo modificare sia le date che il compito»).

Un «piano» è un dizionario che la pagina compila con i campi:
    {"frequenza": "minuti" | "ora" | "giorno" | "settimana" | "una_volta",
     "ogni": 30,                                   # minuti, solo per «minuti»
     "fasce": [["12:00", "16:00"], ["19:00", "01:00"]],   # facoltative, per «minuti»/«ora»; la fine è compresa
     "orari": ["07:00", "19:00"],                  # per «giorno»/«settimana»
     "giorni": ["lun", "mar", …],                  # vuoto = tutti i giorni (per «settimana» almeno uno)
     "data": "2026-10-08", "ora": "10:45",         # per «una_volta»
     "dal": "2026-10-05", "al": "2026-10-20",      # facoltativi: periodo in cui gira
     "monotono": true}                             # letto da un timer «ogni N min» dall'ultimo giro (OnUnitActiveSec)
Tutte le ore sono di Roma. Conversioni (andata e ritorno):
    systemd  righe OnCalendar con « Europe/Rome» (systemd ≥ 235: la VPS ha 255 ed è in UTC), oppure OnUnitActiveSec
    cron     5 campi in UTC (il cron della VPS non conosce i fusi): si converte con lo scarto di oggi e si avvisa
    launchd  StartCalendarInterval (lista di dizionari, ora del Mac = Roma) oppure StartInterval
Il periodo dal/al non esiste in nessuno dei tre: diventa una guardia in testa al compito (`[ "$(date +%Y%m%d)" -lt …`).
Errori: PianoNonValido con il messaggio che comincia dal nome del campo (la pagina lo mette sotto quel campo).
Solo libreria standard.
"""
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ROMA = ZoneInfo("Europe/Rome")
except Exception:  # noqa: BLE001
    ROMA = timezone(timedelta(hours=1))

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
SD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FREQUENZE = ("minuti", "ora", "giorno", "settimana", "una_volta")
GIORNO = 1440
MAX_LAUNCHD = 400


class PianoNonValido(ValueError):
    pass


# ---------------------------------------------------------------- campi

def _hm(v, campo):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise PianoNonValido(f"{campo}: un'ora come «07:30»")
    return int(m.group(1)) * 60 + int(m.group(2))


def _fmt(t):
    return "%02d:%02d" % ((t // 60) % 24, t % 60)


def _data(v, campo):
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        raise PianoNonValido(f"{campo}: una data come «2026-10-08»") from None


def valida(p):
    """Il piano pulito (solo le chiavi note, valori controllati). PianoNonValido se non va."""
    if not isinstance(p, dict):
        raise PianoNonValido("frequenza: manca il piano degli orari")
    f = p.get("frequenza")
    if f not in FREQUENZE:
        raise PianoNonValido("frequenza: ogni N minuti, ogni ora, ogni giorno, ogni settimana o una volta")
    out = {"frequenza": f}
    giorni = p.get("giorni") or []
    if not isinstance(giorni, list) or any(g not in GIORNI for g in giorni):
        raise PianoNonValido("giorni: lun, mar, mer, gio, ven, sab, dom")
    giorni = [g for g in GIORNI if g in giorni]
    if len(giorni) == 7:
        giorni = []
    if f in ("minuti", "ora"):
        ogni = 60 if f == "ora" else p.get("ogni")
        if isinstance(ogni, str) and ogni.isdigit():
            ogni = int(ogni)
        if not isinstance(ogni, int) or isinstance(ogni, bool) or not 1 <= ogni <= 60 or 60 % ogni:
            raise PianoNonValido("ogni: minuti che dividono l'ora (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30)")
        out["ogni"] = ogni
        fasce = p.get("fasce") or []
        if not isinstance(fasce, list) or len(fasce) > 6:
            raise PianoNonValido("fasce: al massimo 6")
        pulite = []
        for x in fasce:
            if not isinstance(x, (list, tuple)) or len(x) != 2:
                raise PianoNonValido("fasce: «dalle» e «alle»")
            a, b = _hm(x[0], "fasce"), _hm(x[1], "fasce")
            if a == b:
                raise PianoNonValido("fasce: inizio e fine uguali")
            pulite.append([_fmt(a), _fmt(b)])
        out["fasce"] = pulite
        if p.get("monotono") and not pulite and not giorni:
            out["monotono"] = True
    elif f in ("giorno", "settimana"):
        orari = p.get("orari") or []
        if not isinstance(orari, list) or not orari or len(orari) > 24:
            raise PianoNonValido("orari: da 1 a 24 orari")
        out["orari"] = [_fmt(t) for t in sorted({_hm(x, "orari") for x in orari})]
        if f == "settimana" and not giorni:
            raise PianoNonValido("giorni: scegli almeno un giorno della settimana")
    else:
        d = _data(p.get("data"), "data")
        out["data"] = d.isoformat()
        out["ora"] = _fmt(_hm(p.get("ora"), "ora"))
    if f != "una_volta":
        out["giorni"] = giorni
        for k in ("dal", "al"):
            if p.get(k):
                out[k] = _data(p[k], k).isoformat()
        if out.get("dal") and out.get("al") and out["dal"] > out["al"]:
            raise PianoNonValido("al: la fine del periodo viene prima dell'inizio")
    return out


def tempi(p):
    """(giorni 0..6, minuti del giorno 0..1439) di un piano valido. Per «una_volta» None."""
    f = p["frequenza"]
    if f == "una_volta":
        return None
    giorni = {GIORNI.index(g) for g in p.get("giorni") or []} or set(range(7))
    if f in ("minuti", "ora"):
        n = p["ogni"]
        if not p.get("fasce"):
            return giorni, set(range(0, GIORNO, n))
        minuti = set()
        for a, b in p["fasce"]:
            a, b = _hm(a, "fasce"), _hm(b, "fasce")
            if b < a:
                b += GIORNO
            minuti.update(t % GIORNO for t in range(a, b + 1, n))
        return giorni, minuti
    return giorni, {_hm(x, "orari") for x in p["orari"]}


# ---------------------------------------------------------------- in italiano

def _ora_it(t):
    h, m = (t // 60) % 24, t % 60
    testo = str(h) if not m else f"{h}:{m:02d}"
    return ("all'" if h in (1, 8, 11) and not m or h in (1, 8, 11) else "alle ") + testo


def _dalle(t):
    h, m = (t // 60) % 24, t % 60
    testo = str(h) if not m else f"{h}:{m:02d}"
    return ("dall'" if h in (1, 8, 11) else "dalle ") + testo


def testo_giorni(giorni):
    idx = sorted(GIORNI.index(g) for g in giorni or [])
    if not idx or len(idx) == 7:
        return "tutti i giorni"
    if len(idx) > 2 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{GIORNI[idx[0]]}–{GIORNI[idx[-1]]}"
    return ", ".join(GIORNI[i] for i in idx)


def testo(p):
    """«ogni 30 min dalle 12 alle 16 e dalle 19 all'1, lun–ven»."""
    f = p["frequenza"]
    if f == "una_volta":
        d = date.fromisoformat(p["data"])
        return f"una volta, il {d.day}/{d.month}/{d.year} alle {p['ora']}"
    if f in ("minuti", "ora"):
        base = "ogni ora" if p["ogni"] == 60 else f"ogni {p['ogni']} min"
        if p.get("monotono"):
            base += " (dalla fine del giro prima)"
        if p.get("fasce"):
            base += " " + " e ".join(f"{_dalle(_hm(a, ''))} {_ora_it(_hm(b, ''))}" for a, b in p["fasce"])
    elif f == "giorno":
        base = "ogni giorno alle " + ", ".join(p["orari"])
    else:
        base = "ogni settimana alle " + ", ".join(p["orari"])
    g = testo_giorni(p.get("giorni"))
    out = base if g == "tutti i giorni" and f != "settimana" else f"{base}, {g}"
    if p.get("dal") or p.get("al"):
        out += f" (dal {p['dal']})" if p.get("dal") and not p.get("al") else \
            f" (fino al {p['al']})" if not p.get("dal") else f" (dal {p['dal']} al {p['al']})"
    return out


# ---------------------------------------------------------------- dai tempi al piano

def piano_da_tempi(giorni, minuti):
    """Il piano più semplice che dà esattamente questi tempi, o None."""
    if not minuti:
        return None
    gg = [GIORNI[i] for i in sorted(giorni)] if len(giorni) < 7 else []
    ts = sorted(minuti)
    candidati = []
    if len(ts) > 1:
        passi = sorted({b - a for a, b in zip(ts, ts[1:])})
        n = passi[0]
        if n <= 60 and 60 % n == 0:
            if len(ts) == GIORNO // n and ts[0] == 0:
                candidati.append({"frequenza": "ora" if n == 60 else "minuti", "ogni": n, "fasce": [], "giorni": gg})
            corse, cur = [], [ts[0]]
            for x in ts[1:]:
                if x - cur[-1] == n:
                    cur.append(x)
                else:
                    corse.append(cur)
                    cur = [x]
            corse.append(cur)
            if len(corse) > 1 and corse[0][0] == 0 and corse[-1][-1] + n == GIORNO:   # a cavallo della mezzanotte
                corse = corse[1:-1] + [corse[-1] + [x + GIORNO for x in corse[0]]]
            if len(corse) <= 6 and all(len(c) > 2 for c in corse):     # una «fascia» ha almeno 3 giri
                candidati.append({"frequenza": "ora" if n == 60 else "minuti", "ogni": n,
                                  "fasce": [[_fmt(c[0]), _fmt(c[-1])] for c in corse], "giorni": gg})
    if len(ts) <= 24:
        candidati.append({"frequenza": "giorno" if not gg else "settimana", "orari": [_fmt(t) for t in ts], "giorni": gg})
    for c in candidati:
        c = valida(c)
        if tempi(c) == (set(giorni), set(minuti)):
            return c
    return None


# ---------------------------------------------------------------- systemd

def _gruppi_ore(minuti):
    """{(minuti dell'ora): [ore]} → [(ore, minuti)] con le ore unite in intervalli dove possibile."""
    per_ora = {}
    for t in minuti:
        per_ora.setdefault(t // 60, set()).add(t % 60)
    per_insieme = {}
    for h, ms in per_ora.items():
        per_insieme.setdefault(tuple(sorted(ms)), []).append(h)
    return sorted(((sorted(hh), ms) for ms, hh in per_insieme.items()), key=lambda x: x[0][0])


def _lista(valori, sep="..", larghezza=2):
    """[12,13,14,15,17] → «12..15,17» (systemd) o «12-15,17» (cron)."""
    valori = sorted(valori)
    pezzi, i = [], 0
    while i < len(valori):
        j = i
        while j + 1 < len(valori) and valori[j + 1] == valori[j] + 1:
            j += 1
        if j - i >= 2:
            pezzi.append(f"{valori[i]:0{larghezza}d}{sep}{valori[j]:0{larghezza}d}")
        else:
            pezzi += [f"{v:0{larghezza}d}" for v in valori[i:j + 1]]
        i = j + 1
    return ",".join(pezzi)


def _giorni_systemd(giorni):
    if len(giorni) == 7:
        return ""
    idx = sorted(giorni)
    if len(idx) > 2 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{SD[idx[0]]}..{SD[idx[-1]]} "
    return ",".join(SD[i] for i in idx) + " "


def a_systemd(p):
    """→ {"calendari": [OnCalendar…]} oppure {"intervallo_min": N} (timer dall'ultimo giro)."""
    if p.get("monotono"):
        return {"intervallo_min": p["ogni"]}
    if p["frequenza"] == "una_volta":
        return {"calendari": [f"{p['data']} {p['ora']}:00 Europe/Rome"]}
    giorni, minuti = tempi(p)
    pre = _giorni_systemd(giorni)
    return {"calendari": [f"{pre}*-*-* {_lista(ore)}:{_lista(ms)}:00 Europe/Rome" for ore, ms in _gruppi_ore(minuti)]}


def _valori_sd(t, massimo):
    if t == "*":
        return set(range(massimo + 1))
    out = set()
    for parte in t.split(","):
        m = re.fullmatch(r"(\d{1,2})(?:\.\.(\d{1,2}))?(?:/(\d{1,2}))?", parte)
        if not m:
            return None
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else (massimo if m.group(3) else a)
        out.update(range(a, b + 1, int(m.group(3) or 1)))
    return out if all(0 <= x <= massimo for x in out) else None


def _giorni_da_sd(t):
    if not t:
        return set(range(7))
    out = set()
    for parte in t.split(","):
        a, _, b = parte.partition("..")
        try:
            i, j = SD.index(a[:3].title()), SD.index((b or a)[:3].title())
        except ValueError:
            return None
        out.update(range(i, j + 1) if j >= i else list(range(i, 7)) + list(range(0, j + 1)))
    return out


RIGA_SD = re.compile(r"(?:(?P<g>[A-Za-z][A-Za-z.,]*)\s+)?(?P<d>\*-\*-\*|\d{4}-\d{2}-\d{2})\s+"
                     r"(?P<h>[\d.,*/]+):(?P<m>[\d.,*/]+)(?::(?P<s>[\d.,*/]+))?(?:\s+(?P<tz>\S+))?")


def da_systemd(calendari, intervallo=None):
    """Il piano da righe OnCalendar (o da OnUnitActiveSec). None se non si rappresenta nei campi."""
    if not calendari:
        if intervallo:
            n = minuti_da_durata(intervallo)
            if n and n <= 60 and 60 % n == 0:
                return valida({"frequenza": "ora" if n == 60 else "minuti", "ogni": n, "monotono": True})
        return None
    insiemi = []
    for c in calendari:
        m = RIGA_SD.fullmatch(c.strip())
        if not m or (m.group("tz") or "") != "Europe/Rome" or (m.group("s") or "0").lstrip("0") not in ("",):
            return None
        if m.group("d") != "*-*-*":
            if len(calendari) != 1 or m.group("g"):
                return None
            h, mi = _valori_sd(m.group("h"), 23), _valori_sd(m.group("m"), 59)
            if not h or not mi or len(h) != 1 or len(mi) != 1:
                return None
            return valida({"frequenza": "una_volta", "data": m.group("d"), "ora": _fmt(h.pop() * 60 + mi.pop())})
        g, h, mi = _giorni_da_sd(m.group("g")), _valori_sd(m.group("h"), 23), _valori_sd(m.group("m"), 59)
        if g is None or h is None or mi is None:
            return None
        insiemi.append((frozenset(g), {a * 60 + b for a in h for b in mi}))
    if len({g for g, _ in insiemi}) != 1:
        return None
    return piano_da_tempi(set(insiemi[0][0]), set().union(*(t for _, t in insiemi)))


def minuti_da_durata(v):
    """«30min», «1h», «2h 30min», «15m» → minuti; «30» (secondi) o «45s» → None."""
    v = str(v or "").strip()
    tot = 0
    parti = re.findall(r"(\d+)\s*(h|min|m|s)?", v)
    if not parti or re.sub(r"[\d\s]+(h|min|m|s)?", "", v):
        return None
    for n, u in parti:
        if u in ("", "s"):
            return None
        tot += int(n) * (60 if u == "h" else 1)
    return tot or None


# ---------------------------------------------------------------- cron (in UTC sulla VPS)

def scarto_roma(quando=None):
    """Minuti da aggiungere all'UTC per avere l'ora di Roma, in quel momento (120 d'estate, 60 d'inverno)."""
    d = datetime.fromtimestamp(quando or time.time(), ROMA)
    return int(d.utcoffset().total_seconds() // 60)


def _campo_cron(valori, minimo, massimo):
    valori = sorted(valori)
    if valori == list(range(minimo, massimo + 1)):
        return "*"
    if len(valori) > 2 and valori[0] == minimo:
        n = valori[1] - valori[0]
        if valori == list(range(minimo, massimo + 1, n)):
            return f"*/{n}"
    return _lista(valori, "-", 1)


def a_cron(p, scarto=None):
    """Il piano (ore di Roma) → 5 campi cron in UTC. PianoNonValido se serve più di una riga."""
    if p["frequenza"] == "una_volta":
        raise PianoNonValido("frequenza: «una volta» non esiste in cron (si ripeterebbe ogni anno): usa un timer systemd")
    scarto = scarto_roma() if scarto is None else scarto
    giorni, minuti = tempi(p)
    utc = set()
    for g in giorni:
        for t in minuti:
            u = (g * GIORNO + t - scarto) % (7 * GIORNO)
            utc.add((u // GIORNO, (u % GIORNO) // 60, u % 60))
    D, H, M = {x[0] for x in utc}, {x[1] for x in utc}, {x[2] for x in utc}
    if len(D) * len(H) * len(M) != len(utc):
        raise PianoNonValido("fasce: in cron questi orari non stanno in una riga sola (ore e minuti devono combinarsi "
                             "tutti): cambia le fasce (es. fine alle 15:30) oppure usa un timer systemd")
    dow = "*" if len(D) == 7 else _lista([(d + 1) % 7 for d in D], "-", 1)
    return f"{_campo_cron(M, 0, 59)} {_campo_cron(H, 0, 23)} * * {dow}"


def da_cron(espr, scarto=None):
    """5 campi cron in UTC → piano in ore di Roma, o None."""
    import routine as _R   # il lettore dei campi sta là (orario_cron), una sola fonte
    try:
        mi, ore, gg, mesi, sett, gg_libero, sett_libera = _R.orario_cron(espr)
    except ValueError:
        return None
    if not gg_libero or len(mesi) != 12:
        return None
    scarto = scarto_roma() if scarto is None else scarto
    giorni_utc = {(d - 1) % 7 for d in sett} if not sett_libera else set(range(7))   # cron: 0 = domenica
    roma = set()
    for g in giorni_utc:
        for h in ore:
            for m in mi:
                r = (g * GIORNO + h * 60 + m + scarto) % (7 * GIORNO)
                roma.add((r // GIORNO, r % GIORNO))
    D, T = {x[0] for x in roma}, {x[1] for x in roma}
    if len(D) * len(T) != len(roma):
        return None
    return piano_da_tempi(D, T)


# ---------------------------------------------------------------- launchd (Mac, ora di Roma)

def a_launchd(p):
    if p["frequenza"] == "una_volta":
        d = date.fromisoformat(p["data"])
        t = _hm(p["ora"], "ora")
        return {"StartCalendarInterval": {"Month": d.month, "Day": d.day, "Hour": t // 60, "Minute": t % 60}}
    giorni, minuti = tempi(p)
    if p["frequenza"] in ("minuti", "ora") and not p.get("fasce") and len(giorni) == 7:
        return {"StartInterval": p["ogni"] * 60}
    voci = []
    for t in sorted(minuti):
        if len(giorni) == 7:
            voci.append({"Hour": t // 60, "Minute": t % 60})
        else:
            voci += [{"Weekday": (g + 1) % 7, "Hour": t // 60, "Minute": t % 60} for g in sorted(giorni)]
    if len(voci) > MAX_LAUNCHD:
        raise PianoNonValido(f"ogni: sul Mac al massimo {MAX_LAUNCHD} orari (questo ne fa {len(voci)})")
    return {"StartCalendarInterval": voci[0] if len(voci) == 1 else voci}


def da_launchd(d):
    if d.get("StartInterval") and not d.get("StartCalendarInterval"):
        s = int(d["StartInterval"])
        if s % 60 == 0 and s // 60 <= 60 and 60 % (s // 60) == 0:
            return valida({"frequenza": "ora" if s == 3600 else "minuti", "ogni": s // 60, "fasce": [], "giorni": []})
        return None
    sci = d.get("StartCalendarInterval")
    voci = [x for x in (sci if isinstance(sci, list) else [sci]) if isinstance(x, dict)]
    if not voci:
        return None
    if len(voci) == 1 and "Day" in voci[0] and "Month" in voci[0] and "Hour" in voci[0]:
        x = voci[0]
        oggi = date.today()
        anno = oggi.year if (x["Month"], x["Day"]) >= (oggi.month, oggi.day) else oggi.year + 1
        try:
            return valida({"frequenza": "una_volta", "data": date(anno, int(x["Month"]), int(x["Day"])).isoformat(),
                           "ora": _fmt(int(x["Hour"]) * 60 + int(x.get("Minute", 0)))})
        except ValueError:
            return None
    coppie = set()
    for x in voci:
        if "Day" in x or "Month" in x or "Hour" not in x:
            return None
        gg = [(int(x["Weekday"]) - 1) % 7] if "Weekday" in x else list(range(7))
        coppie.update((g, int(x["Hour"]) * 60 + int(x.get("Minute", 0))) for g in gg)
    D, T = {c[0] for c in coppie}, {c[1] for c in coppie}
    if len(D) * len(T) != len(coppie):
        return None
    return piano_da_tempi(D, T)


# ---------------------------------------------------------------- periodo dal/al come guardia nel compito

GUARDIA = re.compile(r'\[ "\$+\(date \+\\?%+Y\\?%+m\\?%+d\)" -(lt|gt) (\d{8}) \] && exit 0; ')


def con_periodo(compito, p, fonte):
    """Mette (o toglie) la guardia del periodo in testa al compito."""
    nudo, _, _ = senza_periodo(compito)
    pc = "\\%" if fonte == "cron" else "%"
    pezzi = []
    if p.get("dal"):
        pezzi.append(f'[ "$(date +{pc}Y{pc}m{pc}d)" -lt {p["dal"].replace("-", "")} ] && exit 0; ')
    if p.get("al"):
        pezzi.append(f'[ "$(date +{pc}Y{pc}m{pc}d)" -gt {p["al"].replace("-", "")} ] && exit 0; ')
    return "".join(pezzi) + nudo


def senza_periodo(compito):
    """(compito senza guardia, dal, al)."""
    dal = al = None
    s = compito or ""
    while True:
        m = GUARDIA.match(s)
        if not m:
            break
        d = f"{m.group(2)[:4]}-{m.group(2)[4:6]}-{m.group(2)[6:]}"
        if m.group(1) == "lt":
            dal = d
        else:
            al = d
        s = s[m.end():]
    return s, dal, al


# ---------------------------------------------------------------- le prossime esecuzioni

def prossime(p, n=3, adesso=None):
    """Le prossime n esecuzioni (secondi epoch) di un piano, in ora di Roma, rispettando dal/al."""
    adesso = adesso or time.time()
    inizio = datetime.fromtimestamp(adesso, ROMA)
    if p["frequenza"] == "una_volta":
        t = _hm(p["ora"], "ora")
        d = date.fromisoformat(p["data"])
        x = datetime(d.year, d.month, d.day, t // 60, t % 60, tzinfo=ROMA).timestamp()
        return [x] if x > adesso else []
    giorni, minuti = tempi(p)
    out = []
    dal = date.fromisoformat(p["dal"]) if p.get("dal") else None
    al = date.fromisoformat(p["al"]) if p.get("al") else None
    for k in range(0, 400):
        d = (inizio + timedelta(days=k)).date()
        if al and d > al:
            break
        if (dal and d < dal) or d.weekday() not in giorni:
            continue
        for t in sorted(minuti):
            x = datetime(d.year, d.month, d.day, t // 60, t % 60, tzinfo=ROMA).timestamp()
            if x > adesso:
                out.append(x)
                if len(out) == n:
                    return out
    return out


def grezzo_launchd(d):
    if d.get("StartInterval"):
        return f"ogni {int(d['StartInterval']) // 60} min" if int(d["StartInterval"]) % 60 == 0 else f"StartInterval={d['StartInterval']}"
    return json.dumps(d.get("StartCalendarInterval"), ensure_ascii=False)
