#!/usr/bin/env python3
"""Il piano approvato (l'utente, 2026-10-04): «decido una volta, poi procede, e una sola conferma finale dettagliata».

Come si usa (lo fa Jarvis; l'approvazione la dà l'utente dalla pagina «Piani» del Command Center):
    python3 ~/Jarvis/strumenti/piano.py nuovo --file piano.json     # scrive il piano, stato «da_approvare»
    python3 ~/Jarvis/strumenti/piano.py stato [<id>]
    python3 ~/Jarvis/strumenti/piano.py passo <id> <n> fatto|saltato
    python3 ~/Jarvis/strumenti/piano.py finale <id>                 # chiede all'utente la conferma finale dettagliata
    python3 ~/Jarvis/strumenti/piano.py attendi <id> [--secondi 900]  # aspetta il sì o lo stop (esito 0 = sì)
    python3 ~/Jarvis/strumenti/piano.py chiudi <id> "<esito verificato>"
    python3 ~/Jarvis/strumenti/piano.py prova

Forma di piano.json:
    {"titolo": "...", "scopo": "...", "spazio": "generale", "durata_min": 120,
     "servizi": ["vps", "telegram"], "cartelle": ["/root/jarvis"], "non_tocco": ["database dei CRM"],
     "passi": [{"testo": "leggere i log", "tipo": "lettura"},
               {"testo": "riavviare il servizio", "tipo": "irreversibile",
                "comando": "ssh vps-tuo systemctl restart jarvis-telegram"}]}
tipo: lettura | scrittura | irreversibile. Per ogni passo irreversibile scrivi il COMANDO ESATTO: è quello che
l'hook delle connessioni ferma finché l'utente non dà la conferma finale. Un irreversibile senza comando non si può
fermare da solo (resta la tua parola e la conferma finale).

Cosa fa l'approvazione (solo dall'utente): apre le finestre delle Connessioni per i servizi dichiarati, per la durata
del piano (massimo 240 minuti), con «origine» = il piano. A scadenza, o alla chiusura, si chiudono.
Cosa NON fa: non controlla le cartelle né i singoli passi; non ferma un irreversibile non dichiarato.

Dati: ~/.locale-onedrive/jarvis-cc/piani/<id>.json (0600). Solo libreria standard.
"""
import json
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import connessioni as C  # noqa: E402  (una sola fonte per servizi e finestre)

CARTELLA = Path(os.environ.get("CC_PIANI_DIR", C.CARTELLA / "piani"))
TIPI = ("lettura", "scrittura", "irreversibile")
ATTIVI = ("da_approvare", "approvato", "attesa_finale")
DURATA_DEFAULT = 120
DURATA_MAX = 240
MAX_PASSI = 30


class PianoNonValido(ValueError):
    pass


class NonTrovato(KeyError):
    pass


def _norma(cmd):
    return re.sub(r"\s+", " ", str(cmd or "")).strip()


def _scrivi(p, dati):
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(dati, h, ensure_ascii=False, indent=1)
            h.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _file(id_):
    if not re.fullmatch(r"pi_[0-9a-f]{8}", str(id_ or "")):
        raise NonTrovato("piano non trovato")
    return CARTELLA / f"{id_}.json"


def _testo(v, nome, n, vuoto_ok=False):
    if not isinstance(v, str):
        if vuoto_ok and v is None:
            return ""
        raise PianoNonValido(f"{nome}: serve un testo")
    v = v.strip()
    if not v and not vuoto_ok:
        raise PianoNonValido(f"{nome}: vuoto")
    if len(v) > n:
        raise PianoNonValido(f"{nome}: oltre {n} caratteri")
    return v


def _lista_testi(v, nome, n=300, tetto=30):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > tetto:
        raise PianoNonValido(f"{nome}: una lista di al massimo {tetto} voci")
    return [_testo(x, nome, n) for x in v]


def valida(dati, servizi_noti=None):
    if not isinstance(dati, dict):
        raise PianoNonValido("il piano deve essere un oggetto")
    noti = servizi_noti if servizi_noti is not None else {s["id"] for s in C.leggi()["servizi"]}
    servizi = _lista_testi(dati.get("servizi"), "servizi", 40, 20)
    for s in servizi:
        if s not in noti:
            raise PianoNonValido(f"servizio sconosciuto: {s}")
    durata = dati.get("durata_min", DURATA_DEFAULT)
    if isinstance(durata, bool) or not isinstance(durata, int) or not 1 <= durata <= DURATA_MAX:
        raise PianoNonValido(f"durata_min: un numero intero da 1 a {DURATA_MAX}")
    passi_in = dati.get("passi")
    if not isinstance(passi_in, list) or not 1 <= len(passi_in) <= MAX_PASSI:
        raise PianoNonValido(f"passi: da 1 a {MAX_PASSI}")
    passi = []
    for i, p in enumerate(passi_in, 1):
        if not isinstance(p, dict) or p.get("tipo") not in TIPI:
            raise PianoNonValido(f"passo {i}: «tipo» deve essere {', '.join(TIPI)}")
        passo = {"n": i, "testo": _testo(p.get("testo"), f"passo {i}", 300), "tipo": p["tipo"], "stato": "da_fare"}
        cmd = _testo(p.get("comando"), f"passo {i} comando", 2000, vuoto_ok=True)
        if cmd:
            passo["comando"] = _norma(cmd)
        passi.append(passo)
    spazio = _testo(dati.get("spazio", "generale"), "spazio", 60)
    return {"titolo": _testo(dati.get("titolo"), "titolo", 120), "scopo": _testo(dati.get("scopo"), "scopo", 500),
            "spazio": spazio, "servizi": servizi, "cartelle": _lista_testi(dati.get("cartelle"), "cartelle", 300),
            "non_tocco": _lista_testi(dati.get("non_tocco"), "non_tocco", 300), "durata_min": durata, "passi": passi}


def _aggiorna_scadenza(p, adesso=None):
    adesso = time.time() if adesso is None else adesso
    if p["stato"] in ("approvato", "attesa_finale") and p.get("scade") and adesso > p["scade"]:
        p["stato"] = "scaduto"
        p["esito"] = p.get("esito") or "scaduto: la finestra è finita prima della chiusura"
        return True
    return False


def leggi(id_, adesso=None):
    f = _file(id_)
    if not f.exists():
        raise NonTrovato("piano non trovato")
    with open(f, encoding="utf-8") as h:
        p = json.load(h)
    if _aggiorna_scadenza(p, adesso):
        _scrivi(f, p)
        _chiudi_finestre(p)
    return p


def elenco(adesso=None):
    out = []
    if CARTELLA.exists():
        for f in sorted(CARTELLA.glob("pi_*.json")):
            try:
                out.append(leggi(f.stem, adesso))
            except (OSError, ValueError, NonTrovato):
                continue
    out.sort(key=lambda p: p.get("creato", 0), reverse=True)
    return out


def _chiudi_finestre(p):
    """Chiude le finestre dei servizi del piano, salvo quelli che servono a un altro piano ancora approvato."""
    altri = {s for q in elenco() if q["id"] != p["id"] and q["stato"] in ("approvato", "attesa_finale") for s in q["servizi"]}
    for s in p["servizi"]:
        if s not in altri:
            try:
                C.chiudi(s, origine=f"piano {p['id']}")
            except (KeyError, C.FileNonValido):
                pass


def nuovo(dati, adesso=None):
    adesso = time.time() if adesso is None else adesso
    v = valida(dati)
    for q in elenco(adesso):
        if q["stato"] in ATTIVI and q["spazio"] == v["spazio"]:
            raise PianoNonValido(f"c'è già un piano aperto per lo spazio «{v['spazio']}»: {q['id']} ({q['stato']}). "
                                 "Chiudilo o fallo annullare prima.")
    p = dict(v, id="pi_" + secrets.token_hex(4), stato="da_approvare", creato=int(adesso), finale=None, esito="")
    _scrivi(_file(p["id"]), p)
    return p


def _salva(p):
    _scrivi(_file(p["id"]), p)
    return p


def approva(id_, origine="cli", adesso=None):
    """Solo dall'utente (pagina, o Jarvis dopo il suo sì in chat). Apre le finestre dei servizi dichiarati."""
    adesso = time.time() if adesso is None else adesso
    p = leggi(id_, adesso)
    if p["stato"] != "da_approvare":
        raise PianoNonValido(f"il piano è «{p['stato']}»: non si può approvare")
    p.update(stato="approvato", approvato=int(adesso), scade=int(adesso + p["durata_min"] * 60), approvato_da=origine)
    for s in p["servizi"]:
        C.via(s, p["durata_min"], origine=f"piano {p['id']}")
    return _salva(p)


def rifiuta(id_, origine="cli", adesso=None):
    p = leggi(id_, adesso)
    if p["stato"] not in ATTIVI:
        raise PianoNonValido(f"il piano è «{p['stato']}»: non si può rifiutare")
    p.update(stato="annullato", esito=f"fermato dall'utente ({origine})", chiuso=int(time.time() if adesso is None else adesso))
    _salva(p)
    _chiudi_finestre(p)
    return p


def passo(id_, n, stato):
    if stato not in ("fatto", "saltato"):
        raise PianoNonValido("stato del passo: fatto o saltato")
    p = leggi(id_)
    if p["stato"] not in ("approvato", "attesa_finale"):
        raise PianoNonValido(f"il piano è «{p['stato']}»")
    for x in p["passi"]:
        if x["n"] == n:
            if x["tipo"] == "irreversibile" and stato == "fatto" and not (p.get("finale") or {}).get("confermato"):
                raise PianoNonValido("un passo irreversibile si segna «fatto» solo dopo la conferma finale")
            x["stato"] = stato
            return _salva(p)
    raise PianoNonValido(f"passo {n} inesistente")


def irreversibili(p):
    return [x for x in p["passi"] if x["tipo"] == "irreversibile" and x["stato"] == "da_fare"]


def chiedi_finale(id_, adesso=None):
    adesso = time.time() if adesso is None else adesso
    p = leggi(id_, adesso)
    if p["stato"] != "approvato":
        raise PianoNonValido(f"il piano è «{p['stato']}»: la conferma finale si chiede su un piano approvato")
    if not irreversibili(p):
        raise PianoNonValido("nessun passo irreversibile da confermare")
    p["stato"] = "attesa_finale"
    p["finale"] = {"richiesto": int(adesso), "confermato": None, "fermato": None}
    return _salva(p)


def conferma_finale(id_, origine="cli", adesso=None):
    adesso = time.time() if adesso is None else adesso
    p = leggi(id_, adesso)
    if p["stato"] != "attesa_finale":
        raise PianoNonValido(f"il piano è «{p['stato']}»: non c'è una conferma finale da dare")
    p["stato"] = "approvato"
    p["finale"].update(confermato=int(adesso), da=origine)
    return _salva(p)


def ferma(id_, origine="cli", adesso=None):
    """«Fermati» alla conferma finale: il piano si annulla e le finestre si chiudono."""
    adesso = time.time() if adesso is None else adesso
    p = leggi(id_, adesso)
    if p["stato"] == "attesa_finale":
        p["finale"]["fermato"] = int(adesso)
    return rifiuta(id_, origine, adesso)


def chiudi(id_, esito, adesso=None):
    p = leggi(id_, adesso)
    if p["stato"] not in ("approvato", "attesa_finale"):
        raise PianoNonValido(f"il piano è «{p['stato']}»")
    p.update(stato="concluso", esito=_testo(esito, "esito", 500), chiuso=int(time.time() if adesso is None else adesso))
    _salva(p)
    _chiudi_finestre(p)
    return p


def blocca_irreversibile(strumento, ingresso, adesso=None):
    """Per l'hook delle connessioni: se il comando è un passo irreversibile dichiarato di un piano e la conferma
    finale non c'è, torna il motivo del blocco; altrimenti None. Mai un'eccezione."""
    try:
        if strumento != "Bash":
            return None
        cmd = _norma((ingresso or {}).get("command"))
        if not cmd:
            return None
        for p in elenco(adesso):
            if p["stato"] not in ("approvato", "attesa_finale"):
                continue
            for x in p["passi"]:
                if x["tipo"] == "irreversibile" and x["stato"] == "da_fare" and x.get("comando") == cmd:
                    if (p.get("finale") or {}).get("confermato"):
                        return None
                    return (f"Passo {x['n']} del piano «{p['titolo']}» ({p['id']}): è irreversibile e manca la conferma "
                            f"finale dell'utente. Esegui prima i passi che non lo sono, poi: python3 ~/Jarvis/strumenti/piano.py "
                            f"finale {p['id']} e python3 ~/Jarvis/strumenti/piano.py attendi {p['id']}.")
        return None
    except Exception:  # noqa: BLE001 — l'hook non deve mai rompersi per questo
        return None


def pubblico(p):
    """Per la pagina: il piano com'è, con il riepilogo della conferma finale (i comandi veri)."""
    q = json.loads(json.dumps(p))
    q["conferma_finale"] = [{"n": x["n"], "testo": x["testo"], "comando": x.get("comando", "")} for x in irreversibili(p)] \
        if p["stato"] == "attesa_finale" else []
    return q


# ------------------------------------------------------------------ prove e riga di comando

def prova():
    import shutil
    base = Path(tempfile.mkdtemp(prefix="prova-piano-"))
    global CARTELLA
    CARTELLA = base / "piani"
    C.CARTELLA, C.FILE, C.FILE_USO = base, base / "connessioni.json", base / "uso.json"
    ok = True

    def v(nome, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("  ok   " if cond else "  FAIL ") + nome)

    def solleva(nome, f, *a, **k):
        try:
            f(*a, **k)
        except (PianoNonValido, NonTrovato):
            return v(nome, True)
        v(nome, False)
    piano = {"titolo": "Telegram VPS", "scopo": "rimettere online il bot", "durata_min": 60, "servizi": ["vps", "telegram"],
             "passi": [{"testo": "leggere i log", "tipo": "lettura"},
                       {"testo": "riavviare", "tipo": "irreversibile", "comando": "ssh  vps-tuo systemctl restart jarvis-telegram"}]}
    solleva("servizio sconosciuto", nuovo, dict(piano, servizi=["boh"]))
    solleva("tipo di passo sbagliato", nuovo, dict(piano, passi=[{"testo": "x", "tipo": "boh"}]))
    solleva("durata troppo lunga", nuovo, dict(piano, durata_min=999))
    p = nuovo(piano)
    v("nuovo: da_approvare", p["stato"] == "da_approvare")
    v("comando normalizzato", p["passi"][1]["comando"] == "ssh vps-tuo systemctl restart jarvis-telegram")
    solleva("un solo piano aperto per spazio", nuovo, piano)
    d = C.leggi(crea=True)
    v("prima dell'approvazione nessuna finestra", not C.finestra_aperta(d, "vps"))
    solleva("non si segna fatto prima dell'approvazione", passo, p["id"], 1, "fatto")
    p = approva(p["id"], origine="prova")
    d = C.leggi()
    v("approvato: finestra aperta per vps e telegram", C.finestra_aperta(d, "vps") and C.finestra_aperta(d, "telegram"))
    v("non si approva due volte", _prova_solleva(approva, p["id"]))
    cmd = {"command": "ssh vps-tuo   systemctl restart jarvis-telegram"}
    v("irreversibile fermato senza conferma finale", blocca_irreversibile("Bash", cmd) is not None)
    v("un comando diverso non è fermato", blocca_irreversibile("Bash", {"command": "ssh vps-tuo uptime"}) is None)
    solleva("irreversibile non si segna fatto senza conferma", passo, p["id"], 2, "fatto")
    p = passo(p["id"], 1, "fatto")
    p = chiedi_finale(p["id"])
    v("attesa_finale con il riepilogo dei comandi veri", pubblico(p)["conferma_finale"][0]["comando"].endswith("jarvis-telegram"))
    v("ancora fermato in attesa_finale", blocca_irreversibile("Bash", cmd) is not None)
    p = conferma_finale(p["id"], origine="prova")
    v("dopo la conferma finale passa", blocca_irreversibile("Bash", cmd) is None)
    p = passo(p["id"], 2, "fatto")
    p = chiudi(p["id"], "bot online, messaggio di prova ricevuto")
    d = C.leggi()
    v("chiuso: finestre chiuse", p["stato"] == "concluso" and not C.finestra_aperta(d, "vps"))
    # scadenza
    p2 = nuovo(piano)
    p2 = approva(p2["id"], adesso=time.time() - 7200)
    p2 = leggi(p2["id"])
    v("scaduto da solo", p2["stato"] == "scaduto")
    # stop alla conferma finale
    p3 = approva(nuovo(piano)["id"])
    chiedi_finale(p3["id"])
    p3 = ferma(p3["id"], origine="prova")
    v("«Fermati» annulla e chiude le finestre", p3["stato"] == "annullato" and not C.finestra_aperta(C.leggi(), "vps"))
    v("file dei piani 0600", all((f.stat().st_mode & 0o777) == 0o600 for f in CARTELLA.glob("pi_*.json")))
    shutil.rmtree(base, ignore_errors=True)
    print("tutto ok" if ok else "CI SONO ERRORI")
    return 0 if ok else 1


def _prova_solleva(f, *a):
    try:
        f(*a)
    except (PianoNonValido, NonTrovato):
        return True
    return False


def _riga(p):
    fatti = sum(1 for x in p["passi"] if x["stato"] != "da_fare")
    return f"{p['id']}  {p['stato']:<13} {fatti}/{len(p['passi'])} passi  {p['titolo']}"


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "nuovo" and "--file" in argv:
            with open(argv[argv.index("--file") + 1], encoding="utf-8") as h:
                p = nuovo(json.load(h))
            print(f"{p['id']} scritto, in attesa dell'utente: lo approva dalla pagina «Piani» del Command Center.")
        elif cmd == "stato":
            if len(argv) > 1:
                print(json.dumps(pubblico(leggi(argv[1])), ensure_ascii=False, indent=1))
            else:
                for p in elenco():
                    print(_riga(p))
        elif cmd == "passo" and len(argv) == 4:
            print(_riga(passo(argv[1], int(argv[2]), argv[3])))
        elif cmd == "finale" and len(argv) == 2:
            p = chiedi_finale(argv[1])
            print(f"{p['id']}: conferma finale chiesta all'utente per {len(irreversibili(p))} passi. Aspetta con: piano.py attendi {p['id']}")
        elif cmd == "attendi" and len(argv) >= 2:
            fine = time.time() + (int(argv[argv.index("--secondi") + 1]) if "--secondi" in argv else 900)
            while time.time() < fine:
                p = leggi(argv[1])
                if (p.get("finale") or {}).get("confermato") and p["stato"] == "approvato":
                    print("confermato: procedi con i passi irreversibili")
                    return 0
                if p["stato"] in ("annullato", "scaduto", "concluso"):
                    print(f"fermato: il piano è {p['stato']}")
                    return 3
                time.sleep(2)
            print("nessuna risposta dell'utente nel tempo dato: non procedere")
            return 4
        elif cmd == "chiudi" and len(argv) == 3:
            print(_riga(chiudi(argv[1], argv[2])))
        elif cmd == "prova":
            return prova()
        else:
            print(__doc__)
            return 2
    except (PianoNonValido, NonTrovato, C.FileNonValido) as e:
        print(f"errore: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
