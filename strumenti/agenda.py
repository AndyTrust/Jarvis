#!/usr/bin/env python3
"""Agenda dell'utente: Google Calendar e Google Tasks, senza librerie da installare.

Gira uguale sul Mac e sulla VPS: solo urllib, così il report del mattino non
dipende da pacchetti Python di sistema.

  python3 strumenti/agenda.py login            consenso Google, salva il token
  python3 strumenti/agenda.py oggi             eventi e task in chiaro
  python3 strumenti/agenda.py oggi --giorni 7  la settimana
  python3 strumenti/agenda.py json             lo stesso in JSON (lo legge dati_mattino.py)
  python3 strumenti/agenda.py task             i task aperti, i più urgenti prima
  python3 strumenti/agenda.py aggiungi "testo" [--quando 2026-09-25] [--lista Lavoro]
  python3 strumenti/agenda.py evento "titolo" --da "2026-09-25 15:00" [--a "16:00"] [--dove "…"]
  python3 strumenti/agenda.py fatto "pezzo di testo del task"
  python3 strumenti/agenda.py scrivi [--cartella /opt/jarvis-vps/agenda]

Le credenziali del client OAuth stanno in ~/.env.jarvis
(GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET) o nelle variabili d'ambiente.
Il token dell'utente sta in ~/.jarvis-google.json, a 600: non si scrive nelle note.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AMBITI = ["https://www.googleapis.com/auth/calendar",
          "https://www.googleapis.com/auth/tasks"]
PORTA_LOGIN = 8765
TOKEN = Path(os.environ.get("JARVIS_GOOGLE_TOKEN", Path.home() / ".jarvis-google.json"))
ENV = Path(os.environ.get("JARVIS_ENV", Path.home() / ".env.jarvis"))
CAL = "https://www.googleapis.com/calendar/v3"
TASKS = "https://tasks.googleapis.com/tasks/v1"
# Calendari da saltare sempre: feste e ricorrenze di Google, rumore nel report.
SALTA = ("#holiday@group.v.calendar.google.com", "#contacts@group.v.calendar.google.com")
GIORNI_IT = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


class Fermo(Exception):
    """Errore da mostrare all'utente così com'è, senza traccia dello stack."""


# --- credenziali -------------------------------------------------------------

def dall_env(nome):
    if os.environ.get(nome):
        return os.environ[nome].strip()
    try:
        for riga in ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            g = re.match(r"^\s*" + nome + r"\s*=\s*(.*)$", riga)
            if g:
                v = g.group(1).strip().strip('"').strip("'")
                if v:
                    return v
    except OSError:
        pass
    return ""


def client():
    cid = dall_env("GOOGLE_OAUTH_CLIENT_ID")
    cs = dall_env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not cs:
        raise Fermo("manca il client OAuth di Google: metti GOOGLE_OAUTH_CLIENT_ID e "
                    f"GOOGLE_OAUTH_CLIENT_SECRET in {ENV}")
    return cid, cs


def posta(url, dati):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(dati).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="ignore")[:300]
        raise Fermo(f"Google ha risposto {e.code}: {corpo}") from None


def token_salvato():
    try:
        return json.loads(TOKEN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Fermo(f"nessun token in {TOKEN}: lancia prima «agenda.py login»") from None


def salva_token(d):
    TOKEN.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.chmod(TOKEN, 0o600)


def accesso():
    """Il token di accesso, rinfrescato se scaduto."""
    d = token_salvato()
    if d.get("scade_il", 0) - 120 > dt.datetime.now().timestamp() and d.get("access_token"):
        return d["access_token"]
    cid, cs = client()
    r = posta("https://oauth2.googleapis.com/token",
              {"client_id": cid, "client_secret": cs,
               "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
    d["access_token"] = r["access_token"]
    d["scade_il"] = dt.datetime.now().timestamp() + int(r.get("expires_in", 3600))
    salva_token(d)
    return d["access_token"]


def api(url, params=None, metodo="GET", corpo=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo,
                                 headers={"Authorization": "Bearer " + accesso(),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            testo = r.read().decode()
            return json.loads(testo) if testo.strip() else {}
    except urllib.error.HTTPError as e:
        corpo_err = e.read().decode(errors="ignore")
        msg = corpo_err[:300]
        try:
            msg = json.loads(corpo_err)["error"]["message"][:300]
        except (ValueError, KeyError, TypeError):
            pass
        raise Fermo(f"Google ha risposto {e.code}: {msg}") from None


def pagine(url, params, chiave="items"):
    """Tutte le pagine di una lista, fino a un tetto di sicurezza."""
    fuori, p = [], dict(params or {})
    for _ in range(10):
        d = api(url, p)
        fuori += d.get(chiave) or []
        t = d.get("nextPageToken")
        if not t:
            break
        p["pageToken"] = t
    return fuori


# --- login -------------------------------------------------------------------

def login():
    """Consenso nel browser dell'utente, con PKCE e ritorno su localhost."""
    import http.server
    import threading
    import webbrowser

    cid, cs = client()
    verifica = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    sfida = base64.urlsafe_b64encode(hashlib.sha256(verifica.encode()).digest()).decode().rstrip("=")
    stato = secrets.token_urlsafe(16)
    ritorno = f"http://localhost:{PORTA_LOGIN}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": ritorno, "response_type": "code",
        "scope": " ".join(AMBITI), "access_type": "offline", "prompt": "consent",
        "state": stato, "code_challenge": sfida, "code_challenge_method": "S256"})

    preso = {}

    class Ascolto(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            preso.update({k: v[0] for k, v in q.items()})
            ok = preso.get("code") and preso.get("state") == stato
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<h2>" + ("Fatto. Torna da Jarvis." if ok else
                                        "Non ha funzionato: " + preso.get("error", "risposta strana"))
                              + "</h2>").encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORTA_LOGIN), Ascolto)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Apro il consenso Google nel browser. Se non si apre, incolla questo indirizzo:\n" + url)
    webbrowser.open(url)
    srv.timeout = 300
    scade = dt.datetime.now().timestamp() + 300
    while "code" not in preso and "error" not in preso and dt.datetime.now().timestamp() < scade:
        srv.handle_request()
    srv.shutdown()
    if not preso.get("code"):
        raise Fermo("consenso non arrivato: " + preso.get("error", "tempo scaduto"))
    if preso.get("state") != stato:
        raise Fermo("lo stato non torna: rifai il login")
    r = posta("https://oauth2.googleapis.com/token",
              {"code": preso["code"], "client_id": cid, "client_secret": cs,
               "redirect_uri": ritorno, "grant_type": "authorization_code",
               "code_verifier": verifica})
    if not r.get("refresh_token"):
        raise Fermo("Google non ha dato il refresh token: togli l'accesso a questa app da "
                    "myaccount.google.com/permissions e rifai il login")
    salva_token({"refresh_token": r["refresh_token"], "access_token": r.get("access_token", ""),
                 "scade_il": dt.datetime.now().timestamp() + int(r.get("expires_in", 3600))})
    chi = api("https://www.googleapis.com/oauth2/v2/userinfo").get("email", "?") \
        if "userinfo" in " ".join(AMBITI) else ""
    print(f"token salvato in {TOKEN}" + (f" per {chi}" if chi else ""))


# --- lettura -----------------------------------------------------------------

def calendari(tutti=False):
    """I calendari che contano: quelli dell'utente, non le feste e i calendari pubblici."""
    fuori = []
    for c in pagine(f"{CAL}/users/me/calendarList", {"maxResults": 250}):
        cid = c.get("id", "")
        if any(cid.endswith(s) for s in SALTA):
            continue
        if not tutti and c.get("accessRole") not in ("owner", "writer"):
            continue
        if not tutti and c.get("selected") is False:
            continue
        fuori.append({"id": cid, "nome": c.get("summary", cid)})
    return fuori


def quando(e, campo):
    v = e.get(campo, {})
    return v.get("dateTime") or v.get("date") or ""


def eventi(giorni=1, tutti=False):
    """Gli eventi da adesso (o da stanotte) per N giorni, ordinati per inizio."""
    oggi = dt.datetime.now().astimezone()
    da = oggi.replace(hour=0, minute=0, second=0, microsecond=0)
    a = da + dt.timedelta(days=max(1, giorni))
    fuori = []
    for c in calendari(tutti):
        for e in pagine(f"{CAL}/calendars/{urllib.parse.quote(c['id'])}/events",
                        {"timeMin": da.isoformat(), "timeMax": a.isoformat(),
                         "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}):
            if e.get("status") == "cancelled":
                continue
            inizio = quando(e, "start")
            fuori.append({"titolo": e.get("summary", "(senza titolo)")[:120],
                          "inizio": inizio, "fine": quando(e, "end"),
                          "tutto_il_giorno": "date" in (e.get("start") or {}),
                          "dove": (e.get("location") or "")[:100],
                          "calendario": c["nome"],
                          "link": e.get("htmlLink", ""),
                          "id": e.get("id", "")})
    fuori.sort(key=lambda e: e["inizio"])
    return fuori


def task(solo_aperti=True, entro=None):
    """I task di tutte le liste. «entro» è una data: tiene solo quelli in scadenza o senza data."""
    fuori = []
    for lista in pagine(f"{TASKS}/users/@me/lists", {"maxResults": 100}):
        for t in pagine(f"{TASKS}/lists/{lista['id']}/tasks",
                        {"showCompleted": "false" if solo_aperti else "true",
                         "showHidden": "false", "maxResults": 100}):
            if solo_aperti and t.get("status") == "completed":
                continue
            scad = (t.get("due") or "")[:10]
            if entro and scad and scad > entro:
                continue
            fuori.append({"titolo": (t.get("title") or "(senza titolo)")[:120],
                          "scadenza": scad or None,
                          "lista": lista.get("title", ""),
                          "lista_id": lista["id"],
                          "note": (t.get("notes") or "")[:200],
                          "id": t.get("id", "")})
    fuori.sort(key=lambda t: (t["scadenza"] or "9999-99-99", t["titolo"]))
    return fuori


def raccolta(giorni=1, tutti=False):
    """Il pacchetto che legge il report del mattino. Se una parte manca, non si rompe il resto."""
    oggi = dt.date.today()
    limite = (oggi + dt.timedelta(days=max(1, giorni) - 1)).isoformat()
    d = {"data": oggi.isoformat(), "giorni": giorni, "eventi": [], "task": [],
         "scaduti": 0, "note": "", "errore": None}
    try:
        d["eventi"] = eventi(giorni, tutti)
        tutti_task = task(entro=limite)
        d["task"] = tutti_task
        d["scaduti"] = sum(1 for t in tutti_task if t["scadenza"] and t["scadenza"] < oggi.isoformat())
        d["note"] = (f"{len(d['eventi'])} eventi · {len(d['task'])} task"
                     + (f" · {d['scaduti']} scaduti" if d["scaduti"] else ""))
    except Fermo as e:
        d["errore"] = str(e)[:200]
        d["note"] = "agenda non letta: " + d["errore"]
    return d


# --- scrittura ---------------------------------------------------------------

def aggiungi_task(testo, quando_=None, lista=None):
    liste = pagine(f"{TASKS}/users/@me/lists", {"maxResults": 100})
    if not liste:
        raise Fermo("nessuna lista di task sull'account")
    scelta = liste[0]
    if lista:
        for l in liste:
            if lista.lower() in (l.get("title") or "").lower():
                scelta = l
                break
        else:
            raise Fermo("lista «%s» non trovata: ci sono %s" %
                        (lista, ", ".join(l.get("title", "?") for l in liste)))
    corpo = {"title": testo}
    if quando_:
        corpo["due"] = dt.datetime.strptime(quando_, "%Y-%m-%d").strftime("%Y-%m-%dT00:00:00.000Z")
    t = api(f"{TASKS}/lists/{scelta['id']}/tasks", metodo="POST", corpo=corpo)
    return {"titolo": t.get("title"), "lista": scelta.get("title"), "id": t.get("id"),
            "scadenza": (t.get("due") or "")[:10] or None}


def chiudi_task(pezzo):
    aperti = [t for t in task() if pezzo.lower() in t["titolo"].lower()]
    if not aperti:
        raise Fermo(f"nessun task aperto contiene «{pezzo}»")
    if len(aperti) > 1:
        raise Fermo("più di un task: " + " · ".join(t["titolo"] for t in aperti[:5]))
    t = aperti[0]
    api(f"{TASKS}/lists/{t['lista_id']}/tasks/{t['id']}", metodo="PATCH",
        corpo={"status": "completed"})
    return t


def data_ora(v, base=None):
    """«2026-09-25 15:00», «25/09 15:00» o «16:00» (stesso giorno di base)."""
    v = v.strip().replace("T", " ")
    oggi = dt.date.today()
    for f, ha_data in (("%Y-%m-%d %H:%M", True), ("%d/%m/%Y %H:%M", True),
                       ("%d/%m %H:%M", False), ("%H:%M", False)):
        try:
            d = dt.datetime.strptime(v, f)
        except ValueError:
            continue
        if not ha_data:
            giorno = (base.date() if base else oggi)
            if f == "%d/%m %H:%M":
                giorno = dt.date(oggi.year, d.month, d.day)
            d = dt.datetime.combine(giorno, d.time())
        return d.astimezone()
    raise Fermo(f"non capisco la data «{v}»: scrivila come 2026-09-25 15:00")


def crea_evento(titolo, da, a=None, dove=None, calendario=None):
    inizio = data_ora(da)
    fine = data_ora(a, inizio) if a else inizio + dt.timedelta(hours=1)
    if fine <= inizio:
        raise Fermo("la fine viene prima dell'inizio")
    cid = "primary"
    if calendario:
        for c in calendari(tutti=True):
            if calendario.lower() in c["nome"].lower():
                cid = c["id"]
                break
        else:
            raise Fermo(f"calendario «{calendario}» non trovato")
    corpo = {"summary": titolo,
             "start": {"dateTime": inizio.isoformat()},
             "end": {"dateTime": fine.isoformat()}}
    if dove:
        corpo["location"] = dove
    e = api(f"{CAL}/calendars/{urllib.parse.quote(cid)}/events", metodo="POST", corpo=corpo)
    return {"titolo": e.get("summary"), "inizio": quando(e, "start"), "fine": quando(e, "end"),
            "link": e.get("htmlLink", ""), "id": e.get("id", "")}


# --- stampa ------------------------------------------------------------------

def ora_corta(iso, tutto_il_giorno=False):
    if tutto_il_giorno:
        return "tutto il giorno"
    try:
        return dt.datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return iso[:16]


def etichetta_giorno(iso):
    try:
        g = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso[:10]
    scarto = (g - dt.date.today()).days
    if scarto == 0:
        return "oggi"
    if scarto == 1:
        return "domani"
    return f"{GIORNI_IT[g.weekday()]} {g.strftime('%d/%m')}"


def stampa(d):
    if d.get("errore"):
        print("Agenda non letta:", d["errore"])
        return 1
    giorno = None
    if not d["eventi"]:
        print("Calendario: niente in programma.")
    for e in d["eventi"]:
        g = etichetta_giorno(e["inizio"])
        if g != giorno:
            print(("\n" if giorno else "") + g.capitalize())
            giorno = g
        dove = f" — {e['dove']}" if e["dove"] else ""
        cal = f" [{e['calendario']}]" if e["calendario"] else ""
        print(f"  {ora_corta(e['inizio'], e['tutto_il_giorno']):>14}  {e['titolo']}{dove}{cal}")
    if d["task"]:
        print("\nDa fare")
        oggi = dt.date.today().isoformat()
        for t in d["task"]:
            s = t["scadenza"]
            marca = "⚠️ " if s and s < oggi else "   "
            data = f" ({etichetta_giorno(s)})" if s else ""
            print(f"{marca}{t['titolo']}{data}" + (f" [{t['lista']}]" if t["lista"] else ""))
    else:
        print("\nDa fare: niente in scadenza.")
    return 0


def scrivi_file(d, cartella):
    c = Path(cartella)
    c.mkdir(parents=True, exist_ok=True)
    fuori = c / "oggi.json"
    tmp = c / "oggi.json.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(fuori)
    print(fuori, "·", d["note"])


def main():
    p = argparse.ArgumentParser(description="Google Calendar e Google Tasks per Jarvis")
    s = p.add_subparsers(dest="cmd")
    s.add_parser("login")
    for nome in ("oggi", "json", "scrivi"):
        q = s.add_parser(nome)
        q.add_argument("--giorni", type=int, default=1)
        q.add_argument("--tutti", action="store_true", help="anche i calendari pubblici e in sola lettura")
        if nome == "scrivi":
            q.add_argument("--cartella", default="/opt/jarvis-vps/agenda")
    s.add_parser("task")
    q = s.add_parser("aggiungi")
    q.add_argument("testo")
    q.add_argument("--quando", help="AAAA-MM-GG")
    q.add_argument("--lista")
    q = s.add_parser("fatto")
    q.add_argument("pezzo")
    q = s.add_parser("evento")
    q.add_argument("titolo")
    q.add_argument("--da", required=True)
    q.add_argument("--a")
    q.add_argument("--dove")
    q.add_argument("--calendario")
    a = p.parse_args()
    if not a.cmd:
        p.print_help()
        return 2
    try:
        if a.cmd == "login":
            login()
        elif a.cmd == "oggi":
            return stampa(raccolta(a.giorni, a.tutti))
        elif a.cmd == "json":
            print(json.dumps(raccolta(a.giorni, a.tutti), ensure_ascii=False, indent=1))
        elif a.cmd == "scrivi":
            scrivi_file(raccolta(a.giorni, a.tutti), a.cartella)
        elif a.cmd == "task":
            for t in task():
                print(("⚠️ " if t["scadenza"] and t["scadenza"] < dt.date.today().isoformat() else "   ")
                      + t["titolo"] + (f" ({t['scadenza']})" if t["scadenza"] else "")
                      + (f" [{t['lista']}]" if t["lista"] else ""))
        elif a.cmd == "aggiungi":
            t = aggiungi_task(a.testo, a.quando, a.lista)
            print("task creato:", t["titolo"], "·", t["lista"], *( [f"scade {t['scadenza']}"] if t["scadenza"] else []))
        elif a.cmd == "fatto":
            t = chiudi_task(a.pezzo)
            print("segnato fatto:", t["titolo"])
        elif a.cmd == "evento":
            e = crea_evento(a.titolo, a.da, a.a, a.dove, a.calendario)
            print("evento creato:", e["titolo"], e["inizio"], "→", e["fine"])
            if e["link"]:
                print(e["link"])
    except Fermo as e:
        print("Errore:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
