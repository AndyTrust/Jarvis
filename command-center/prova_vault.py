#!/usr/bin/env python3
"""Prove del Vault. Uso:  python3 command-center/prova_vault.py

Tutto in una CASA FINTA COMPLETA (cartella temporanea): HOME, USERPROFILE, APPDATA, LOCALAPPDATA, XDG_*, cartella del
Vault, file .env vero e copia di prova sono finti; prima di tutto si controlla che Path.home() sia la casa finta. Su macOS la chiave del dispositivo va in un portachiavi usa-e-getta (non nel Portachiavi di login).
Dati solo finti (PROVA_VAULT_*, carta 4242 4242 4242 4242). L'uscita stampa solo nomi delle prove ed esiti, mai valori.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CASA_VERA = Path(os.path.expanduser("~")).resolve()
QUI = Path(__file__).resolve().parent
RADICE = Path(tempfile.mkdtemp(prefix="vault-prova-"))
CASA = RADICE / "casa"
CASA.mkdir()
assert CASA.resolve() != CASA_VERA and CASA_VERA not in CASA.resolve().parents, "la casa finta non può stare nella casa vera"
os.environ.update({"HOME": str(CASA), "USERPROFILE": str(CASA), "APPDATA": str(CASA / "AppData" / "Roaming"),
                   "LOCALAPPDATA": str(CASA / "AppData" / "Local"), "XDG_CONFIG_HOME": str(CASA / ".config"),
                   "XDG_DATA_HOME": str(CASA / ".local" / "share"), "XDG_CACHE_HOME": str(CASA / ".cache"),
                   "XDG_STATE_HOME": str(CASA / ".local" / "state"),
                   "JARVIS_VAULT_DIR": str(CASA / "dati" / "vault"), "JARVIS_VAULT_ENV_VERO": str(CASA / ".env.jarvis"),
                   "JARVIS_VAULT_ENV_PROVA": str(CASA / "prova" / "env.jarvis.prova"), "JARVIS_VAULT_PROVA": "1",
                   "JARVIS_VAULT_GIRI": "2000", "ENV_CENTRALE": str(CASA / "centrale.env"),
                   "ENV_MAPPA": str(CASA / ".env.mappa.json"), "ENV_BACKUP": str(CASA / "backup-env"),
                   "JARVIS_VAULT_PROFILO": str(CASA / "profilo-finto.md")})
assert Path.home().resolve() == CASA.resolve(), "Path.home() non è la casa finta: mi fermo"
(CASA / "profilo-finto.md").write_text("---\nname: jarvis\nnome_assistente: Aiutante\nchiamami: Capo Finto\n---\n")
PORTACHIAVI = None
if sys.platform == "darwin":
    PORTACHIAVI = RADICE / "prova.keychain-db"
    subprocess.run(["security", "create-keychain", "-p", "prova-vault", str(PORTACHIAVI)], check=True, capture_output=True)
    subprocess.run(["security", "set-keychain-settings", str(PORTACHIAVI)], check=True, capture_output=True)
    subprocess.run(["security", "unlock-keychain", "-p", "prova-vault", str(PORTACHIAVI)], check=True, capture_output=True)
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = str(PORTACHIAVI)
else:
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = "file"

sys.path.insert(0, str(QUI))
import vault_cc as V  # noqa: E402

FRASE = "password-finta-PROVA-VAULT"
EMAIL = "proprietario@esempio.invalid"
SEGRETI = {"PROVA_VAULT_PASSWORD": "finto-PROVA-VAULT-pw-7f3a91", "PROVA_VAULT_TOKEN": "finto-PROVA-VAULT-tok-55e0c2",
           "CARTA": "4242 4242 4242 4242", "CVV": "987", "PIN_CARTA": "13579", "PIN": "246802",
           "NOTA": "finto-PROVA-VAULT-nota-a1b2c3", "EXTRA": "finto-PROVA-VAULT-extra-d4e5f6"}
VERO_TESTO = "# file vero finto\nPROVA_VAULT_VERO_UNO=finto-PROVA-VAULT-vero-uno\nexport PROVA_VAULT_VERO_DUE='finto PROVA VAULT due'\n"
PROVA_TESTO = "# copia di prova\nPROVA_VAULT_TOKEN=finto-PROVA-VAULT-tok-55e0c2\nPROVA_VAULT_ALTRA=finto-PROVA-VAULT-altra-0001\n"

esiti = []


def prova(nome):
    def deco(fn):
        try:
            fn()
            esiti.append((nome, "ok", ""))
        except AssertionError as e:
            esiti.append((nome, "FALLITA", str(e)[:200]))
        except Exception as e:  # noqa: BLE001
            esiti.append((nome, "ERRORE", f"{type(e).__name__}"))
        return fn
    return deco


def nessun_segreto(testo, dove):
    for k, v in SEGRETI.items():      # i valori corti (CVV, PIN) compaiono per caso nel base64: si controllano campo per campo
        if len(v) >= 8:
            assert v not in testo, f"valore finto {k} trovato in {dove}"
    assert "4242424242424242" not in testo.replace(" ", ""), f"numero carta in {dove}"


def http(metodo, percorso, corpo=None, sessione=None, sfondo=False):
    from urllib.parse import parse_qs, urlsplit
    h = {"X-Vault-Sessione": sessione or "", "Host": "127.0.0.1:7777"}
    if sfondo:
        h["X-Vault-Sfondo"] = "1"
    return V.gestisci(metodo, percorso.split("?")[0], parse_qs(urlsplit(percorso).query), corpo or {}, h)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


Path(os.environ["JARVIS_VAULT_ENV_VERO"]).write_text(VERO_TESTO)
os.chmod(os.environ["JARVIS_VAULT_ENV_VERO"], 0o400)
SHA_VERO = sha(os.environ["JARVIS_VAULT_ENV_VERO"])
Path(os.environ["JARVIS_VAULT_ENV_PROVA"]).parent.mkdir(parents=True)
Path(os.environ["JARVIS_VAULT_ENV_PROVA"]).write_text(PROVA_TESTO)
S = {}


# ------------------------------------------------------------------------------------------------ cifratura
@prova("cifra/decifra: andata e ritorno, AAD e manomissione")
def _():
    k = os.urandom(32)
    b = V.cifra(k, b"dato finto", b"aad-1")
    assert V.decifra(k, b, b"aad-1") == b"dato finto"
    for sbagliato in (lambda: V.decifra(k, b, b"aad-2"), lambda: V.decifra(os.urandom(32), b, b"aad-1")):
        try:
            sbagliato()
            raise AssertionError("decifrato con AAD o chiave sbagliata")
        except AssertionError:
            raise
        except Exception:  # noqa: BLE001
            pass
    raw = bytearray(V._unb64(b))
    raw[-1] ^= 1
    try:
        V.decifra(k, V._b64(bytes(raw)), b"aad-1")
        raise AssertionError("blob manomesso accettato")
    except AssertionError:
        raise
    except Exception:  # noqa: BLE001
        pass
    assert V._unb64(b)[0] == 1 and len(V._unb64(b)) == 1 + 12 + len(b"dato finto") + 16


@prova("giri PBKDF2: 600 000 fuori dalle prove")
def _():
    vecchio = os.environ.pop("JARVIS_VAULT_PROVA")
    try:
        assert V._giri() == 600_000
    finally:
        os.environ["JARVIS_VAULT_PROVA"] = vecchio


@prova("cartella: rifiuta repo git e cartelle sincronizzate")
def _():
    g = RADICE / "repo" / "sotto"
    (RADICE / "repo" / ".git").mkdir(parents=True)
    g.mkdir()
    for p in (g, RADICE / "Library" / "CloudStorage" / "OneDrive-Esempio" / "x", RADICE / "Documenti" / "Obsidian" / "x",
              RADICE / "Dropbox" / "x"):
        try:
            V.controlla_cartella(p)
            raise AssertionError(f"accettata {p.name}")
        except V.ErroreVault:
            pass
    V.controlla_cartella(CASA / "dati" / "vault")


# ------------------------------------------------------------------------------------------------ creazione e sblocco
@prova("crea: email e password (12+), mail non valida e password corta rifiutate, 24 parole di recupero")
def _():
    c, d = http("POST", "/api/vault/crea", {"email": EMAIL, "password": "corta"})
    assert c == 400
    c, d = http("POST", "/api/vault/crea", {"email": "non-una-mail", "password": FRASE})
    assert c == 400
    c, d = http("POST", "/api/vault/crea", {"email": EMAIL, "password": FRASE})
    assert c == 200 and d["sessione"] and len(d["codice_recupero"].split()) == 24
    S["sessione"], S["codice"] = d["sessione"], d["codice_recupero"]
    st = os.stat(V.file_vault())
    assert oct(st.st_mode & 0o777) == "0o600" and oct(os.stat(V.cartella()).st_mode & 0o777) == "0o700"


@prova("portachiavi: chiave del dispositivo nel portachiavi, non nei file del Vault")
def _():
    d = json.loads(V.file_vault().read_text())
    k = V.VAULT.portachiavi.leggi("dispositivo-" + d["id"])
    assert k and len(k) == 32
    for f in V.cartella().rglob("*"):
        if f.is_file():
            b = f.read_bytes()
            assert k.hex().encode() not in b and V._b64(k).encode() not in b, f"chiave del dispositivo in {f.name}"


@prova("sblocco: frase giusta sì, sbagliata 401, stato senza segreti")
def _():
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": "password-sbagliata-di-prova"})
    assert c == 401 and "password" in d["errore"]
    c, d = http("POST", "/api/vault/sblocca", {"email": "altra@esempio.invalid", "password": FRASE})
    assert c == 401, "email sbagliata accettata"
    V.VAULT._giusto()
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL.upper(), "password": FRASE})
    assert c == 200
    c, st = http("GET", "/api/vault/stato", sessione=d["sessione"])
    assert st["creato"] and st["sbloccato"] and st["assistente"]
    c, _ = http("GET", "/api/vault/voci")
    assert c == 401


# ------------------------------------------------------------------------------------------------ voci
@prova("voci: accesso, carta, PIN, nota, variabile salvate; elenco senza valori")
def _():
    s = S["sessione"]
    voci = [
        {"tipo": "accesso", "titolo": "Sito finto", "sezione": "Casa / Spesa", "tag": ["prova"], "preferito": True,
         "campi": {"link": "https://esempio.invalid", "utente": "utente-finto", "mail": "finto@esempio.invalid",
                   "password": SEGRETI["PROVA_VAULT_PASSWORD"], "metodo": "password", "due_fa": "sms",
                   "codici_recupero": "codici-finti", "note": SEGRETI["NOTA"]},
         "extra": [{"nome": "Domanda", "valore": SEGRETI["EXTRA"], "segreto": True}]},
        {"tipo": "accesso", "titolo": "Con Google finto", "campi": {"link": "esempio2.invalid", "metodo": "google",
                                                                   "password": "non-deve-restare"}},
        {"tipo": "carta", "titolo": "Carta di prova", "campi": {"intestatario": "PROVA", "circuito": "visa",
         "numero": SEGRETI["CARTA"], "scadenza_mese": "09", "scadenza_anno": "29", "cvv": SEGRETI["CVV"],
         "pin_carta": SEGRETI["PIN_CARTA"]}},
        {"tipo": "pin", "titolo": "PIN finto", "campi": {"uso": "porta", "codice": SEGRETI["PIN"]}},
        {"tipo": "nota", "titolo": "Nota finta", "campi": {"testo": SEGRETI["NOTA"]}},
    ]
    for v in voci:
        c, d = http("POST", "/api/vault/salva", v, s)
        assert c == 200, d
        S.setdefault("id", {})[v["titolo"]] = d["id"]
    c, el = http("GET", "/api/vault/voci", sessione=s)
    assert c == 200 and len(el["voci"]) == 5 and el["voci"][0]["preferito"]
    nessun_segreto(json.dumps(el), "elenco")
    carta = next(x for x in el["voci"] if x["tipo"] == "carta")
    assert carta["campi"]["ultime4"] == "4242" and carta["campi"]["cvv"] == {"segreto": True, "presente": True, "a_parte": True}
    g = next(x for x in el["voci"] if x["titolo"] == "Con Google finto")
    assert g["campi"]["password"]["presente"] is False, "metodo google: la password non si salva"
    assert "Casa / Spesa" in el["sezioni"]


@prova("a riposo: nel file del Vault nessun valore, nessun titolo")
def _():
    t = V.file_vault().read_text()
    nessun_segreto(t, "vault.json")
    assert "Sito finto" not in t and "Carta di prova" not in t and "Spesa" not in t


@prova("mostra: valore solo su richiesta; CVV e PIN carta con sblocco a parte")
def _():
    s, ids = S["sessione"], S["id"]
    c, d = http("POST", "/api/vault/mostra", {"id": ids["Sito finto"], "campo": "password"}, s)
    assert c == 200 and d["valore"] == SEGRETI["PROVA_VAULT_PASSWORD"] and d["svuota_dopo_s"] == 30
    c, d = http("POST", "/api/vault/mostra", {"id": ids["Sito finto"], "campo": "extra:Domanda"}, s)
    assert c == 200 and d["valore"] == SEGRETI["EXTRA"]
    c, d = http("POST", "/api/vault/mostra", {"id": ids["Carta di prova"], "campo": "cvv"}, s)
    assert c == 403 and d.get("serve_conferma") and "valore" not in d
    c, d = http("POST", "/api/vault/mostra", {"id": ids["Carta di prova"], "campo": "cvv", "password": "sbagliata-sbagliata"}, s)
    assert c == 403
    c, d = http("POST", "/api/vault/mostra", {"id": ids["Carta di prova"], "campo": "cvv", "password": FRASE}, s)
    assert c == 200 and d["valore"] == SEGRETI["CVV"]


@prova("modifica: campi segreti «invariato» restano, versione vecchia = 409")
def _():
    s, i = S["sessione"], S["id"]["Sito finto"]
    c, v = http("GET", f"/api/vault/voce?id={i}", sessione=s)
    nessun_segreto(json.dumps(v), "dettaglio")
    corpo = {"id": i, "versione_base": v["versione"], "tipo": "accesso", "titolo": "Sito finto", "sezione": v["sezione"],
             "tag": ["prova", "due"], "campi": {"password": {"invariato": True}, "utente": "utente-nuovo"},
             "extra": [{"nome": "Domanda", "segreto": True, "valore": {"invariato": True}}]}
    c, d = http("POST", "/api/vault/salva", corpo, s)
    assert c == 200 and d["versione"] == v["versione"] + 1
    c, d = http("POST", "/api/vault/mostra", {"id": i, "campo": "password"}, s)
    assert d["valore"] == SEGRETI["PROVA_VAULT_PASSWORD"]
    c, d = http("POST", "/api/vault/mostra", {"id": i, "campo": "extra:Domanda"}, s)
    assert d["valore"] == SEGRETI["EXTRA"]
    c, d = http("POST", "/api/vault/salva", corpo, s)
    assert c == 409 and d.get("conflitto")


@prova("storico: al massimo 20 versioni; annulla rimette la precedente")
def _():
    s, i = S["sessione"], S["id"]["PIN finto"]
    for n in range(25):
        c, v = http("GET", f"/api/vault/voce?id={i}", sessione=s)
        c, d = http("POST", "/api/vault/salva", {"id": i, "versione_base": v["versione"], "tipo": "pin", "titolo": "PIN finto",
                                                 "campi": {"uso": f"porta {n}", "codice": {"invariato": True}}}, s)
        assert c == 200
    c, st = http("GET", f"/api/vault/storico?id={i}", sessione=s)
    assert len(st["versioni"]) == 21 and st["versioni"][0]["attuale"]
    nessun_segreto(json.dumps(st), "storico")
    c, d = http("POST", "/api/vault/annulla", {"id": i}, s)
    assert c == 200
    c, v = http("GET", f"/api/vault/voce?id={i}", sessione=s)
    assert v["campi"]["uso"] == "porta 23" and v["origine"] == "annulla"


@prova("elimina e annulla: la voce sparisce e torna")
def _():
    s, i = S["sessione"], S["id"]["Nota finta"]
    c, _ = http("POST", "/api/vault/elimina", {"id": i}, s)
    c, el = http("GET", "/api/vault/voci", sessione=s)
    assert all(x["id"] != i for x in el["voci"])
    c, _ = http("POST", "/api/vault/annulla", {"id": i}, s)
    c, el = http("GET", "/api/vault/voci", sessione=s)
    assert any(x["id"] == i for x in el["voci"])


@prova("sezioni e categorie: aggiungi, rinomina (sposta le voci), togli solo se vuota, rinomina categoria")
def _():
    s = S["sessione"]
    c, d = http("POST", "/api/vault/sezione", {"nome": "Viaggi finti"}, s)
    assert "Viaggi finti" in d["sezioni"]
    c, d = http("POST", "/api/vault/sezione", {"azione": "rinomina", "nome": "Casa / Spesa", "nuovo": "Spesa finta"}, s)
    c, v = http("GET", f"/api/vault/voce?id={S['id']['Sito finto']}", sessione=s)
    assert v["sezione"] == "Spesa finta"
    c, d = http("POST", "/api/vault/sezione", {"azione": "togli", "nome": "Spesa finta"}, s)
    assert c == 400
    c, d = http("POST", "/api/vault/sezione", {"azione": "togli", "nome": "Viaggi finti"}, s)
    assert c == 200 and "Viaggi finti" not in d["sezioni"]
    c, d = http("POST", "/api/vault/categoria", {"tipo": "accesso", "nome": "Siti"}, s)
    assert d["categorie"]["accesso"] == "Siti"


# ------------------------------------------------------------------------------------------------ PIN, recupero, blocco
@prova("PIN: sblocca col PIN, 5 errori lo spengono")
def _():
    s = S["sessione"]
    c, d = http("POST", "/api/vault/pin", {"password": FRASE, "nuovo_pin": "4821"}, s)
    assert c == 200
    c, d = http("POST", "/api/vault/sblocca", {"pin": "4821"})
    assert c == 200
    for _n in range(5):
        c, d = http("POST", "/api/vault/sblocca", {"pin": "0000"})
        assert c in (401, 400)
    c, d = http("POST", "/api/vault/sblocca", {"pin": "4821"})
    assert c == 400 and "PIN" in d["errore"]
    assert json.loads(V.file_vault().read_text())["avvolte"]["pin"] is None
    V.VAULT._giusto()


@prova("blocco automatico: la sessione scade; le richieste di sfondo non la allungano")
def _():
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": FRASE})
    t = d["sessione"]
    V.VAULT.sessioni[t]["ultimo"] -= 4 * 60
    prima = V.VAULT.sessioni[t]["ultimo"]
    c, _ = http("GET", "/api/vault/voci", sessione=t, sfondo=True)
    assert c == 200 and V.VAULT.sessioni[t]["ultimo"] == prima
    V.VAULT.sessioni[t]["ultimo"] -= 2 * 60
    c, d = http("GET", "/api/vault/voci", sessione=t)
    assert c == 401 and d.get("bloccato")
    c, d = http("POST", "/api/vault/blocca", {}, S["sessione"])
    c, d = http("GET", "/api/vault/voci", sessione=S["sessione"])
    assert c == 401


@prova("recupero: senza chiave nel portachiavi la frase non basta; il codice apre e rimette la frase")
def _():
    d = json.loads(V.file_vault().read_text())
    V.VAULT.portachiavi.togli("dispositivo-" + d["id"])
    c, r = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": FRASE})
    assert c == 409 and r.get("serve_recupero")
    c, r = http("POST", "/api/vault/recupera", {"codice": "acqua " * 24, "nuova_password": FRASE})
    assert c == 401
    c, r = http("POST", "/api/vault/recupera", {"codice": S["codice"].upper().replace(" ", "-"), "nuova_password": FRASE})
    assert c == 200
    S["sessione"] = r["sessione"]
    c, r = http("POST", "/api/vault/mostra", {"id": S["id"]["PIN finto"], "campo": "codice"}, S["sessione"])
    assert r["valore"] == SEGRETI["PIN"]


# ------------------------------------------------------------------------------------------------ ambiente
@prova("ambiente: file vero letto solo per nomi e impronte; mostra a richiesta; mai scritto")
def _():
    s = S["sessione"]
    c, a = http("GET", "/api/vault/ambiente", sessione=s)
    assert c == 200 and a["vero"]["quante"] == 2 and not a["vero"]["scrivibile"] and not a["scrittura_file_vero"]
    nessun_segreto(json.dumps(a), "ambiente")
    assert "finto-PROVA-VAULT-vero-uno" not in json.dumps(a)
    c, d = http("POST", "/api/vault/mostra", {"file": "vero", "nome": "PROVA_VAULT_VERO_DUE"}, s)
    assert d["valore"] == "finto PROVA VAULT due"
    c, d = http("POST", "/api/vault/salva", {"tipo": "variabile", "titolo": "PROVA_VAULT_VERO_UNO", "campi": {
        "nome": "PROVA_VAULT_VERO_UNO", "valore": "finto-PROVA-VAULT-cambiato", "destinazione": "vero"}}, s)
    assert c == 200 and d["sincronia"]["scrivibile"] is False
    S["id_vero"] = d["id"]
    c, a = http("GET", "/api/vault/ambiente", sessione=s)
    assert sha(os.environ["JARVIS_VAULT_ENV_VERO"]) == SHA_VERO, "il file vero è cambiato"
    c, d = http("POST", "/api/vault/ambiente/risolvi", {"id": S["id_vero"], "tieni": "app"}, s)
    assert sha(os.environ["JARVIS_VAULT_ENV_VERO"]) == SHA_VERO, "il file vero è cambiato con «tieni app»"
    assert not list(Path(os.environ["JARVIS_VAULT_ENV_VERO"]).parent.glob(".env.jarvis.lock"))


@prova("ambiente: importa dalla copia di prova; app → file con backup e 0600")
def _():
    s = S["sessione"]
    c, d = http("POST", "/api/vault/ambiente/importa", {"nome": "PROVA_VAULT_TOKEN"}, s)
    assert c == 200 and d["sincronia"]["stato"] == "allineata"
    S["id_tok"] = d["id"]
    c, v = http("GET", f"/api/vault/voce?id={d['id']}", sessione=s)
    c, d = http("POST", "/api/vault/salva", {"id": v["id"], "versione_base": v["versione"], "tipo": "variabile", "titolo": v["titolo"],
                                             "campi": {"valore": "finto-PROVA-VAULT-tok-NUOVO", "nome": "PROVA_VAULT_TOKEN",
                                                       "destinazione": "prova"}}, s)
    assert c == 200 and d["sincronia"]["stato"] == "allineata"
    f = Path(os.environ["JARVIS_VAULT_ENV_PROVA"])
    righe = V.analizza_env(f.read_text())
    assert righe["PROVA_VAULT_TOKEN"][1] == "finto-PROVA-VAULT-tok-NUOVO" and righe["PROVA_VAULT_ALTRA"]
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert list(f.parent.glob("backup-env-*/env.jarvis.prova.*")), "manca il backup"
    c, d = http("POST", "/api/vault/salva", {"tipo": "variabile", "titolo": "PROVA_VAULT_NUOVA", "campi": {
        "nome": "PROVA_VAULT_NUOVA", "valore": "valore con spazi e 'apici'", "destinazione": "prova"}}, s)
    assert d["sincronia"]["stato"] == "allineata"
    assert V.analizza_env(f.read_text())["PROVA_VAULT_NUOVA"][1] == "valore con spazi e 'apici'"


@prova("ambiente: file → app (cambio a mano diventa versione «file»)")
def _():
    s = S["sessione"]
    f = Path(os.environ["JARVIS_VAULT_ENV_PROVA"])
    f.write_text(V.imposta_in_env(f.read_text(), "PROVA_VAULT_TOKEN", "finto-PROVA-VAULT-dal-file"))
    c, a = http("GET", "/api/vault/ambiente", sessione=s, sfondo=True)
    c, v = http("GET", f"/api/vault/voce?id={S['id_tok']}", sessione=s)
    assert v["origine"] == "file"
    c, d = http("POST", "/api/vault/mostra", {"id": S["id_tok"], "campo": "valore"}, s)
    assert d["valore"] == "finto-PROVA-VAULT-dal-file"


@prova("ambiente: conflitto (cambiano file e app) → nessuno vince, poi «tieni il file» / «tieni il Vault»")
def _():
    s = S["sessione"]
    f = Path(os.environ["JARVIS_VAULT_ENV_PROVA"])
    sinc_prima = None
    # l'app cambia ma il file è occupato: simulo cambiando il file subito dopo l'ultimo allineamento
    d = V.VAULT._leggi()
    ch = V.VAULT.sessione(s)
    rec = d["voci"][S["id_tok"]]
    vv = V.VAULT._apri(ch, rec)
    vv["campi"]["valore"] = "finto-PROVA-VAULT-app-conflitto"
    V.VAULT._nuova_versione(d, ch, rec, vv, "app")
    V.VAULT._salva(d)
    f.write_text(V.imposta_in_env(f.read_text(), "PROVA_VAULT_TOKEN", "finto-PROVA-VAULT-file-conflitto"))
    c, a = http("GET", "/api/vault/ambiente", sessione=s)
    assert a["variabili"][S["id_tok"]]["stato"] == "conflitto", a["variabili"][S["id_tok"]]["stato"]
    assert V.analizza_env(f.read_text())["PROVA_VAULT_TOKEN"][1] == "finto-PROVA-VAULT-file-conflitto"
    c, r = http("POST", "/api/vault/ambiente/risolvi", {"id": S["id_tok"], "tieni": "app"}, s)
    assert r["stato"] == "allineata" and V.analizza_env(f.read_text())["PROVA_VAULT_TOKEN"][1] == "finto-PROVA-VAULT-app-conflitto"
    f.write_text(V.imposta_in_env(f.read_text(), "PROVA_VAULT_TOKEN", "finto-PROVA-VAULT-file-due"))
    d = V.VAULT._leggi()
    rec = d["voci"][S["id_tok"]]
    vv = V.VAULT._apri(ch, rec)
    vv["campi"]["valore"] = "finto-PROVA-VAULT-app-due"
    V.VAULT._nuova_versione(d, ch, rec, vv, "app")
    V.VAULT._salva(d)
    c, r = http("POST", "/api/vault/ambiente/risolvi", {"id": S["id_tok"], "tieni": "file"}, s)
    c, m = http("POST", "/api/vault/mostra", {"id": S["id_tok"], "campo": "valore"}, s)
    assert r["stato"] == "allineata" and m["valore"] == "finto-PROVA-VAULT-file-due"
    assert sinc_prima is None


@prova("ambiente: annulla su una variabile riscrive la copia di prova")
def _():
    s = S["sessione"]
    f = Path(os.environ["JARVIS_VAULT_ENV_PROVA"])
    c, v = http("GET", f"/api/vault/voce?id={S['id_tok']}", sessione=s)
    c, d = http("POST", "/api/vault/salva", {"id": v["id"], "versione_base": v["versione"], "tipo": "variabile", "titolo": v["titolo"],
                                             "campi": {"valore": "finto-PROVA-VAULT-da-annullare"}}, s)
    assert V.analizza_env(f.read_text())["PROVA_VAULT_TOKEN"][1] == "finto-PROVA-VAULT-da-annullare"
    c, d = http("POST", "/api/vault/annulla", {"id": S["id_tok"]}, s)
    assert c == 200 and V.analizza_env(f.read_text())["PROVA_VAULT_TOKEN"][1] == "finto-PROVA-VAULT-file-due"


# ------------------------------------------------------------------------------------------------ esportazione e backup
@prova("esporta/importa: file cifrato, frase sbagliata 401, importazione in un Vault nuovo")
def _():
    s = S["sessione"]
    c, e = http("POST", "/api/vault/esporta", {"frase": "esportazione-finta-lunga"}, s)
    assert c == 200
    nessun_segreto(e["contenuto"], "esportazione")
    c, d = http("POST", "/api/vault/importa", {"contenuto": e["contenuto"], "frase": "esportazione-finta-lunga"}, s)
    assert d["nuove"] == 0 and d["saltate"] >= 5
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-due")
    try:
        c, n = http("POST", "/api/vault/crea", {"email": EMAIL, "password": FRASE + "-due"})
        c, d = http("POST", "/api/vault/importa", {"contenuto": e["contenuto"], "frase": "sbagliata-sbagliata"}, n["sessione"])
        assert c == 401
        c, d = http("POST", "/api/vault/importa", {"contenuto": e["contenuto"], "frase": "esportazione-finta-lunga"}, n["sessione"])
        assert c == 200 and d["nuove"] >= 7
        c, el = http("GET", "/api/vault/voci", sessione=n["sessione"])
        carta = next(x for x in el["voci"] if x["tipo"] == "carta")
        c, m = http("POST", "/api/vault/mostra", {"id": carta["id"], "campo": "numero"}, n["sessione"])
        assert m["valore"] == SEGRETI["CARTA"]
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("backup: copia cifrata del file, nessun valore")
def _():
    c, d = http("POST", "/api/vault/backup", {}, S["sessione"])
    assert c == 200 and d["cifrato"]
    b = sorted((V.cartella() / "backup").glob("vault-*.json"))
    assert b
    for f in b:
        nessun_segreto(f.read_text(), f.name)


@prova("registro degli usi: azioni registrate, nessun valore")
def _():
    t = (V.cartella() / "usi.jsonl").read_text()
    nessun_segreto(t, "usi.jsonl")
    for parola in ("finto-PROVA-VAULT", "frase-finta"):
        assert parola not in t
    azioni = {json.loads(r)["azione"] for r in t.splitlines()}
    assert {"creato", "sblocco", "mostra", "modifica", "annulla", "elimina", "esporta", "backup", "sul-file", "dal-file"} <= azioni, azioni


@prova("errori HTTP: nessun valore nei messaggi")
def _():
    s = S["sessione"]
    risposte = [http("POST", "/api/vault/salva", {"tipo": "carta", "titolo": "x", "campi": {"numero": "finto-PROVA-VAULT-non-cifre"}}, s),
                http("POST", "/api/vault/salva", {"tipo": "variabile", "titolo": "x", "campi": {"nome": "finto-PROVA-VAULT-nome sbagliato"}}, s),
                http("POST", "/api/vault/mostra", {"id": "v_inesistente", "campo": "password"}, s),
                http("GET", "/api/vault/inesistente", sessione=s)]
    for c, d in risposte:
        assert c >= 400 and "finto-PROVA-VAULT" not in json.dumps(d)


# ------------------------------------------------------------------------------------------------ lucchetto
@prova("lucchetto: lock abbandonato (più di 30 s) si toglie, lock vivo fa aspettare")
def _():
    f = CASA / "lucchetto.env"
    f.write_text("")
    lock = Path(str(f) + ".lock")
    lock.write_text("99999 altro 0 vecchio")
    os.utime(lock, (time.time() - 60, time.time() - 60))
    with V.Lucchetto(f, attesa=1):
        assert lock.exists()
    assert not lock.exists()
    lock.write_text("99999 altro 0 vivo")
    t0 = time.monotonic()
    try:
        with V.Lucchetto(f, attesa=0.3):
            raise AssertionError("preso un lucchetto vivo")
    except V.ErroreVault as e:
        assert e.codice == 423 and time.monotonic() - t0 >= 0.3
    lock.unlink()


@prova("lucchetto: tre processi del Vault scrivono lo stesso file insieme, 900 righe, nessuna persa")
def _():
    f = CASA / "comune.env"
    f.write_text("# inizio\n")
    py = lambda lettera: (f"import sys; sys.path.insert(0, {str(QUI)!r}); import vault_cc as V\n"  # noqa: E731
                          f"for i in range(300): V.scrivi_variabile_su_file(__import__('pathlib').Path({str(f)!r}), f'PROVA_VAULT_{lettera}{{i}}', f'v{{i}}')\n")
    proc = [subprocess.Popen([sys.executable, "-c", py(x)], env=dict(os.environ)) for x in "ABC"]
    codici = [p.wait(timeout=300) for p in proc]
    assert codici == [0, 0, 0], codici
    righe = V.analizza_env(f.read_text())
    attese = {f"PROVA_VAULT_{x}{i}" for x in "ABC" for i in range(300)}
    mancano = attese - set(righe)
    assert not mancano, f"righe perse: {len(mancano)}"
    assert not Path(str(f) + ".lock").exists()


# ------------------------------------------------------------------------------------------------ Google (finto)
import socket as _socket  # noqa: E402
import urllib.request as _ur  # noqa: E402
from urllib.parse import parse_qs as _pq, urlsplit as _us  # noqa: E402


def _porta_libera():
    with _socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


sys.path.insert(0, str(QUI))
import prova_vault_google as GF  # noqa: E402
PORTA_GF = _porta_libera()
EM, SRV_GF = GF.avvia(PORTA_GF)
os.environ["JARVIS_VAULT_OIDC_EMITTENTE"] = f"http://127.0.0.1:{PORTA_GF}"


class _NoRedirect(_ur.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def google(account, scenario="ok", tocca_flusso=None):
    """Il giro completo: inizio → /auth del Google finto → callback → esito. Restituisce l'esito."""
    c, d = http("GET", "/api/vault/google/inizio")
    if c != 200:
        return {"codice_inizio": c, **d}
    if tocca_flusso:
        tocca_flusso(V.GOOGLE_ACC.flussi[d["stato"]])
    try:
        _ur.build_opener(_NoRedirect).open(d["url"] + "&" + GF.urlencode({"account": account, "scenario": scenario}))
        raise AssertionError("niente redirect dal Google finto")
    except _ur.HTTPError as e:
        dest = e.headers["Location"]
    c, pagina, tipo = http("GET", "/api/vault/google/callback?" + _us(dest).query)
    assert c == 200 and tipo.startswith("text/html")
    c, esito = http("GET", "/api/vault/google/esito?stato=" + d["stato"])
    esito["_pagina"] = pagina.decode()
    esito["_query"] = _us(dest).query
    return esito


def _scrivi_vero(testo):
    f = Path(os.environ["JARVIS_VAULT_ENV_VERO"])
    os.chmod(f, 0o600)
    f.write_text(testo)
    os.chmod(f, 0o400)


@prova("Google: senza ID client il pulsante è spento con il motivo, e l'avvio risponde 503")
def _():
    c, st = http("GET", "/api/vault/stato")
    assert st["google_pronto"] is False and "client OAuth" in st["google_motivo"] and "docs/wiki/Vault.md" in st["google_motivo"]
    c, d = http("GET", "/api/vault/google/inizio")
    assert c == 503 and d.get("manca_client")
    _scrivi_vero(VERO_TESTO + f"VAULT__GOOGLE_CLIENT_ID={GF.CLIENT_ID}\nVAULT__GOOGLE_CLIENT_SECRET={GF.CLIENT_SECRET}\n")
    c, st = http("GET", "/api/vault/stato")
    assert st["google_pronto"] is True and GF.CLIENT_ID not in json.dumps(st) and GF.CLIENT_SECRET not in json.dumps(st)
    c, d = http("GET", "/api/vault/google/inizio")
    q = _pq(_us(d["url"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email"] and q["client_id"] == [GF.CLIENT_ID]
    assert GF.CLIENT_SECRET not in d["url"]
    V.GOOGLE_ACC.flussi.pop(d["stato"], None)


@prova("Google: token scaduto, aud sbagliato, email non verificata, firma, emittente e nonce sbagliati: rifiutati")
def _():
    attesi = {"scaduto": "scaduto", "aud": "aud", "nonverificata": "non è verificata", "firma": "firma",
              "iss": "emittente", "nonce": "nonce"}
    for scen, parola in attesi.items():
        V.VAULT._giusto()
        e = google("proprietario@esempio.invalid", scen)
        assert "biglietto" not in e and parola in e.get("errore", ""), f"{scen}: {e.get('errore')}"
    V.VAULT._giusto()


@prova("Google: state monouso, PKCE controllata (verifier sbagliato = niente biglietto)")
def _():
    e = google("proprietario@esempio.invalid")
    assert e.get("biglietto")
    c, pagina, _t = http("GET", "/api/vault/google/callback?" + e["_query"])
    assert "non valido" in pagina.decode()
    e = google("proprietario@esempio.invalid", tocca_flusso=lambda f: f.update(verifier="verifier-sbagliato-" + "x" * 40))
    assert "biglietto" not in e and "Google non risponde" in e.get("errore", "")
    V.VAULT._giusto()


@prova("Google: crea con il primo account (proprietario), sblocca; un altro account è rifiutato; lista consentita")
def _():
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-google")
    try:
        e = google("proprietario@esempio.invalid")
        c, d = http("POST", "/api/vault/crea", {"biglietto": e["biglietto"]})
        assert c == 200 and len(d["codice_recupero"].split()) == 24
        S["codice_g"] = d["codice_recupero"]
        st = http("GET", "/api/vault/stato")[1]
        assert st["email"] == "proprietario@esempio.invalid" and st["accesso"]["google"] and not st["accesso"]["password"]
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"]})
        assert c == 200
        S["sess_g"] = d["sessione"]
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("altro@esempio.invalid")["biglietto"]})
        assert c == 403
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": "biglietto-inventato"})
        assert c in (401, 429)
        V.VAULT._giusto()
        (V.cartella() / "config.json").write_text(json.dumps({"google_consentiti": ["altro@esempio.invalid"]}))
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"]})
        assert c == 403
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("altro@esempio.invalid")["biglietto"]})
        assert c == 200
        (V.cartella() / "config.json").unlink()
        V.VAULT._giusto()
        c, d = http("POST", "/api/vault/sblocca", {"email": "proprietario@esempio.invalid", "password": FRASE})
        assert c == 400 and "Google" in d["errore"]
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("Google: password come seconda protezione; conferma a parte con un nuovo accesso Google; recupero")
def _():
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-google")
    try:
        s = S["sess_g"]
        c, d = http("POST", "/api/vault/password", {"nuova": FRASE, "biglietto": google("proprietario@esempio.invalid")["biglietto"]}, s)
        assert c == 200
        c, d = http("POST", "/api/vault/google/con-password", {"acceso": True, "password": FRASE}, s)
        assert c == 200 and d["google_con_password"]
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"]})
        assert c == 401 and d.get("serve_password")
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"], "password": FRASE})
        assert c == 200
        c, d = http("POST", "/api/vault/sblocca", {"email": "proprietario@esempio.invalid", "password": FRASE})
        assert c == 200, "con Google irraggiungibile resta email e password"
        c, d = http("POST", "/api/vault/salva", {"tipo": "carta", "titolo": "Carta G", "campi": {"cvv": SEGRETI["CVV"]}}, s)
        c, m = http("POST", "/api/vault/mostra", {"id": d["id"], "campo": "cvv", "biglietto": google("proprietario@esempio.invalid")["biglietto"]}, s)
        assert c == 200 and m["valore"] == SEGRETI["CVV"]
        c, m = http("POST", "/api/vault/mostra", {"id": d["id"], "campo": "cvv", "biglietto": google("altro@esempio.invalid")["biglietto"]}, s)
        assert c == 403
        c, d = http("POST", "/api/vault/google/con-password", {"acceso": False, "password": FRASE}, s)
        dd = json.loads(V.file_vault().read_text())
        V.VAULT.portachiavi.togli("dispositivo-" + dd["id"])
        c, r = http("POST", "/api/vault/recupera", {"codice": S["codice_g"]})
        assert c == 200
        c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"]})
        assert c == 200, "dopo il recupero Google apre di nuovo"
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("Google: collegare l'account a un Vault con email e password (solo la stessa email o la lista)")
def _():
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": FRASE})
    s = d["sessione"]
    c, d = http("POST", "/api/vault/google/collega", {"biglietto_google": google("altro@esempio.invalid")["biglietto"]}, s)
    assert c == 403
    c, d = http("POST", "/api/vault/google/collega", {"biglietto_google": google("proprietario@esempio.invalid")["biglietto"]}, s)
    assert c == 200
    c, d = http("POST", "/api/vault/sblocca", {"biglietto": google("proprietario@esempio.invalid")["biglietto"]})
    assert c == 200


@prova("tentativi: ritardo crescente dal terzo errore (429 con l'attesa), poi si riparte dopo un accesso giusto")
def _():
    V.VAULT._giusto()
    codici = [http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": f"sbagliata-numero-{i}"})[0] for i in range(4)]
    assert codici[:3] == [401, 401, 401] and codici[3] == 429, codici
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": FRASE})
    assert c == 429 and d.get("attesa_s")
    primo = V.VAULT.fermo_fino
    V.VAULT.fermo_fino = 0
    http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": "ancora-sbagliata-xx"})
    assert V.VAULT.fermo_fino - time.time() > 8, "il ritardo non cresce"
    V.VAULT.fermo_fino = 0
    c, d = http("POST", "/api/vault/sblocca", {"email": EMAIL, "password": FRASE})
    assert c == 200 and V.VAULT.errori == 0 and primo > 0


@prova("Google: nessun ID/segreto client e nessun token nei log del Vault")
def _():
    for f in V.cartella().parent.rglob("usi.jsonl"):
        t = f.read_text()
        assert GF.CLIENT_SECRET not in t and GF.CLIENT_ID not in t and "eyJ" not in t, f.name


# ------------------------------------------------------------------------------------------------ importazione
def _env_finto():
    """200 righe circa: prefissi vari, righe vuote, commenti, export, virgolette, «=» nei valori, nomi doppi,
    una credenziale sotto due nomi (alias) e una password riusata in due servizi (riuso)."""
    r = ["# env finto per le prove dell'importazione", ""]
    pref = ["LAVORO__CRM", "LAVORO__POSTA", "CASA__WIFI", "BANCA_CONTO", "PERSONALE__SITO", "SERVER_", "MIO__NEGOZIO", "GOOGLE_CLOUD"]
    for i in range(180):
        p = pref[i % len(pref)]
        ruolo = ["PASSWORD", "USER", "API_KEY", "URL", "TOKEN", "PORT"][i % 6]
        r.append(f"{p}_{ruolo}_{i:03d}=finto-IMPORT-{i:03d}-valore")
        if i % 25 == 0:
            r += ["", "# blocco"]
    r += ["export PROVA_IMPORT__CON_EXPORT=finto-IMPORT-export-001",
          "PROVA_IMPORT__VIRGOLETTE=\"finto-IMPORT con spazi e = uguale\"",
          "PROVA_IMPORT__APICI='finto-IMPORT=apici=dentro'",
          "PROVA_IMPORT__VUOTA=",
          "BANCA__DB_PASSWORD=finto-IMPORT-stessa-credenziale-db",
          "BANCA_PORTFOLIO__DB_PASSWORD=finto-IMPORT-stessa-credenziale-db",
          "NEGOZIO_PASSWORD=finto-IMPORT-password-riusata-xyz",
          "POSTA_PEC_PASSWORD=finto-IMPORT-password-riusata-xyz",
          "ZZZ_SCONOSCIUTO_TOKEN=finto-IMPORT-sconosciuto-001",
          "LAVORO__CRM_PASSWORD_000=finto-IMPORT-DOPPIONE-NOME-seconda-riga",
          "BANCA__DEBUG=true", "BANCA_PORTFOLIO__DEBUG=true"]
    return "\n".join(r) + "\n"


def _nessun_import(testo, dove):
    assert "finto-IMPORT" not in testo, f"valore finto dell'importazione in {dove}"


@prova("importazione: piano solo nomi (env finto di ~200 righe), doppioni uniti alla lettera, riuso, da riordinare")
def _():
    f = CASA / "env-import.finto"
    f.write_text(_env_finto())
    os.chmod(f, 0o400)
    S["env_import"], S["sha_import"] = f, sha(f)
    os.environ.update({"JARVIS_VAULT_ENV_VERO": str(f)})
    p = V.piano_import()
    j = json.dumps(p)
    _nessun_import(j, "piano JSON")
    _nessun_import(V.piano_markdown(p), "piano Markdown")
    nomi = {x["nome"] for x in p["voci"]}
    assert p["righe_env"] == 180 + 12 - 1, p["righe_env"]            # il nome doppio vale una volta
    assert {"voce": "BANCA__DB_PASSWORD", "alias": ["BANCA_PORTFOLIO__DB_PASSWORD"]} in p["doppioni"]
    assert "BANCA_PORTFOLIO__DB_PASSWORD" not in nomi
    assert ["NEGOZIO_PASSWORD", "POSTA_PEC_PASSWORD"] in p["riusi"], "riuso segnalato"
    assert {"voce": "NEGOZIO_PASSWORD", "alias": ["POSTA_PEC_PASSWORD"]} in p["doppioni"] and "POSTA_PEC_PASSWORD" not in nomi
    assert next(v for v in p["voci"] if v["nome"] == "NEGOZIO_PASSWORD")["riuso"] == 2
    assert "BANCA_PORTFOLIO__DEBUG" in nomi, "«true» uguale in due servizi non è un doppione"
    assert any(d["nome"] == "ZZZ_SCONOSCIUTO_TOKEN" for d in p["da_riordinare"])
    x = next(v for v in p["voci"] if v["nome"] == "LAVORO__CRM_PASSWORD_000")
    assert x["sezione"].startswith("Lavoro / ") and x["descrizione"]
    assert next(v for v in p["voci"] if v["nome"] == "PROVA_IMPORT__VUOTA")["tag"][-1] == "vuota"
    assert "accessi_vps" not in p, "il piano pubblico legge solo ~/.env.jarvis"


@prova("importazione: dal pulsante (Vault aperto), valori giusti, nessun valore in risposta e log, ripetibile senza doppioni")
def _():
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-import")
    try:
        c, d = http("POST", "/api/vault/crea", {"email": EMAIL, "password": FRASE})
        s = d["sessione"]
        c, p = http("GET", "/api/vault/piano-import", sessione=s)
        assert c == 200 and p["stati"]["nuova nel file"] == len(p["voci"]) and p["stati"]["importata"] == 0
        _nessun_import(json.dumps(p), "piano dalla pagina")
        c, r = http("POST", "/api/vault/importa-attuali", {}, s)
        assert c == 200 and r["nuove"] == len(p["voci"]), r
        _nessun_import(json.dumps(r), "risposta dell'importazione")
        c, el = http("GET", "/api/vault/voci", sessione=s)
        _nessun_import(json.dumps(el), "elenco")
        per_nome = {v["campi"].get("nome") or v["titolo"]: v for v in el["voci"]}
        for nome, atteso in (("PROVA_IMPORT__VIRGOLETTE", "finto-IMPORT con spazi e = uguale"),
                             ("PROVA_IMPORT__APICI", "finto-IMPORT=apici=dentro"),
                             ("LAVORO__CRM_PASSWORD_000", "finto-IMPORT-000-valore"),
                             ("PROVA_IMPORT__CON_EXPORT", "finto-IMPORT-export-001")):
            c, m = http("POST", "/api/vault/mostra", {"id": per_nome[nome]["id"], "campo": "valore"}, s)
            assert m["valore"] == atteso, nome
        db = per_nome["BANCA__DB_PASSWORD"]
        assert db["campi"]["alias"] == "BANCA_PORTFOLIO__DB_PASSWORD" and db["classe"] == "servizio"
        c, a = http("GET", "/api/vault/ambiente", sessione=s)
        assert a["vero"]["conti"]["nuova nel file"] == 0 and a["vero"]["conti"]["diversa"] == 0, a["vero"]["conti"]
        _nessun_import(json.dumps(a), "ambiente")
        c, r2 = http("POST", "/api/vault/importa-attuali", {}, s)
        assert r2["nuove"] == 0 and r2["aggiornate"] == 0 and r2["gia_presenti"] == len(p["voci"]), r2
        c, el2 = http("GET", "/api/vault/voci", sessione=s)
        assert len(el2["voci"]) == len(el["voci"]), "doppioni dopo la seconda importazione"
        # una riga cambia nel file (copia: il file vero delle prove resta 400): la voce diventa «diversa», poi si aggiorna
        f2 = CASA / "env-import-2.finto"
        f2.write_text(S["env_import"].read_text().replace("CASA__WIFI_PASSWORD_018=finto-IMPORT-018-valore",
                                                         "CASA__WIFI_PASSWORD_018=finto-IMPORT-018-CAMBIATO"))
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(f2)
        c, p3 = http("GET", "/api/vault/piano-import", sessione=s)
        assert p3["stati"]["diversa"] == 1, p3["stati"]
        c, r3 = http("POST", "/api/vault/importa-attuali", {}, s)
        assert r3["aggiornate"] == 1 and r3["nuove"] == 0
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(S["env_import"])
        t = (V.cartella() / "usi.jsonl").read_text()
        _nessun_import(t, "usi.jsonl")
        _nessun_import(V.file_vault().read_text(), "vault.json")
        assert sha(S["env_import"]) == S["sha_import"], "il file sorgente è cambiato"
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("unione: migrazione di voci già importate (backup cifrato prima, voce unita, annulla), separa, conferma, divergenza")
def _():
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-unione")
    try:
        c, d = http("POST", "/api/vault/crea", {"email": EMAIL, "password": FRASE})
        s = d["sessione"]
        c, r = http("POST", "/api/vault/importa-attuali", {}, s)
        n_prima = len(http("GET", "/api/vault/voci", sessione=s)[1]["voci"])
        # nel file due nomi arrivano allo stesso valore: la seconda importazione li unisce
        f2 = CASA / "env-unione.finto"
        f2.write_text(S["env_import"].read_text().replace("GOOGLE_CLOUD_USER_007=finto-IMPORT-007-valore",
                                                         "GOOGLE_CLOUD_USER_007=finto-IMPORT-000-valore"))
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(f2)
        c, p = http("GET", "/api/vault/piano-import", sessione=s)
        assert p["stati"]["da unire"] == 1, p["stati"]
        c, r = http("POST", "/api/vault/importa-attuali", {}, s)
        assert r["unite"] == 1 and r["backup_prima"] is True, r
        _nessun_import(json.dumps(r), "risposta dell'unione")
        assert list((V.cartella() / "backup").glob("vault-prima-unione-*.json")), "manca il backup prima dell'unione"
        el = http("GET", "/api/vault/voci", sessione=s)[1]["voci"]
        assert len(el) == n_prima - 1
        coppia = {"LAVORO__CRM_PASSWORD_000", "GOOGLE_CLOUD_USER_007"}
        unita = next(v for v in el if v["campi"].get("nome") in coppia)
        alias_unito = (coppia - {unita["campi"]["nome"]}).pop()
        assert unita["campi"]["alias"] == alias_unito and unita["campi"]["riuso"] == "2"
        # la voce assorbita è «eliminata» con lo storico: «annulla» la rimette
        d_ = V.VAULT._leggi()
        ch = V.VAULT.sessione(s)
        assorbita = next(rec["id"] for rec in d_["voci"].values()
                         if V.VAULT._apri(ch, rec).get("unita_in") == unita["id"])
        c, st = http("GET", f"/api/vault/storico?id={assorbita}", sessione=s)
        assert st["versioni"][0]["eliminata"] is True and st["versioni"][0]["origine"] == "unione"
        c, a = http("POST", "/api/vault/annulla", {"id": assorbita}, s)
        assert c == 200 and len(http("GET", "/api/vault/voci", sessione=s)[1]["voci"]) == n_prima
        c, _ = http("POST", "/api/vault/elimina", {"id": assorbita}, s)
        # conferma: cambiare il valore di una voce con alias vuole il sì, e dice quali nomi cambierebbero
        c, v = http("GET", f"/api/vault/voce?id={unita['id']}", sessione=s)
        corpo = {"id": v["id"], "versione_base": v["versione"], "tipo": "variabile", "titolo": v["titolo"],
                 "campi": {"valore": "finto-IMPORT-nuovo-per-tutti"}}
        c, d = http("POST", "/api/vault/salva", corpo, s)
        assert c == 409 and d.get("serve_conferma_alias") and set(d["cambiera_in"]) == {"LAVORO__CRM_PASSWORD_000", "GOOGLE_CLOUD_USER_007"}
        assert d["file_vero_scrivibile"] is False
        _nessun_import(json.dumps(d), "risposta della conferma")
        c, d = http("POST", "/api/vault/salva", {**corpo, "conferma_alias": True}, s)
        assert c == 200
        c, _ = http("POST", "/api/vault/annulla", {"id": unita["id"]}, s)
        # separa: l'alias diventa una voce sua; la prossima importazione non lo riunisce
        c, r = http("POST", "/api/vault/separa", {"id": unita["id"], "alias": alias_unito}, s)
        assert c == 200
        c, v = http("GET", f"/api/vault/voce?id={unita['id']}", sessione=s)
        assert v["campi"]["alias"] == "" and v["campi"]["riuso"] == ""
        c, nv = http("GET", f"/api/vault/voce?id={r['nuova']}", sessione=s)
        assert nv["campi"]["nome"] == alias_unito and nv["sezione"].split(" / ")[0] in ("Lavoro", "Da riordinare")
        c, m = http("POST", "/api/vault/mostra", {"id": r["nuova"], "campo": "valore"}, s)
        assert m["valore"] == "finto-IMPORT-000-valore"
        c, r2 = http("POST", "/api/vault/importa-attuali", {}, s)
        assert r2["unite"] == 0 and r2["nuove"] == 0, r2
        # divergenza: nel file un alias cambia valore -> esce dagli alias e diventa voce sua
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(S["env_import"])
        c, r3 = http("POST", "/api/vault/importa-attuali", {}, s)
        c, db = http("GET", "/api/vault/voci", sessione=s)
        f3 = CASA / "env-diverge.finto"
        f3.write_text(S["env_import"].read_text().replace("POSTA_PEC_PASSWORD=finto-IMPORT-password-riusata-xyz",
                                                         "POSTA_PEC_PASSWORD=finto-IMPORT-pec-cambiata"))
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(f3)
        c, r4 = http("POST", "/api/vault/importa-attuali", {}, s)
        assert r4["separate"] == 1 and r4["nuove"] == 1, r4
        el = http("GET", "/api/vault/voci", sessione=s)[1]["voci"]
        neg = next(v for v in el if v["campi"].get("nome") == "NEGOZIO_PASSWORD")
        assert neg["campi"]["alias"] == "" and any(v["campi"].get("nome") == "POSTA_PEC_PASSWORD" for v in el)
        os.environ["JARVIS_VAULT_ENV_VERO"] = str(S["env_import"])
        _nessun_import((V.cartella() / "usi.jsonl").read_text(), "usi.jsonl")
        assert sha(S["env_import"]) == S["sha_import"]
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("importazione: «vault_cc.py --piano-import» da riga di comando scrive il piano senza valori")
def _():
    uscita = CASA / "piano.md"
    r = subprocess.run([sys.executable, str(QUI / "vault_cc.py"), "--piano-import", "--uscita", str(uscita)],
                       capture_output=True, text=True, env=dict(os.environ), timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    _nessun_import(r.stdout + r.stderr, "uscita del comando")
    _nessun_import(uscita.read_text(), "piano.md")
    assert "Da riordinare" in uscita.read_text() and "BANCA_PORTFOLIO__DB_PASSWORD" in uscita.read_text()


# ------------------------------------------------------------------------------------------------ barriere
@prova("barriere: il pre-commit ferma i file del Vault, lascia passare il resto")
def _():
    r = RADICE / "repo-prova"
    (r / "command-center").mkdir(parents=True)
    shutil.copy(QUI / "vault_cc.py", r / "command-center" / "vault_cc.py")
    g = lambda *a: subprocess.run(["git", "-C", str(r), *a], capture_output=True, text=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.email", "prova@esempio.invalid")
    g("config", "user.name", "prova")
    g("config", "core.hooksPath", str(r / ".git" / "hooks"))      # niente hooksPath globali della macchina
    inst = subprocess.run([sys.executable, str(QUI.parent / "strumenti" / "ganci_git.py"), str(r)], capture_output=True,
                          text=True, env=dict(os.environ), timeout=30)
    assert inst.returncode == 0 and "pre-commit" in inst.stdout, inst.stdout + inst.stderr
    (r / "pulito.txt").write_text("niente di segreto")
    g("add", "-A")
    assert g("commit", "-qm", "pulito").returncode == 0, "commit pulito fermato"
    (r / "copia.json").write_text(V.file_vault().read_text())
    (r / "vault-esportazione-20261010-1200.json").write_text("{}")
    (r / "vault-sezioni.json").write_text("{}")
    (r / "Chrome Passwords.csv").write_text("name,url,username,password,note\n")
    g("add", "-f", "copia.json", "vault-esportazione-20261010-1200.json", "vault-sezioni.json", "Chrome Passwords.csv")
    c = g("commit", "-qm", "fuga")
    assert c.returncode != 0 and "copia.json" in c.stderr and "vault-esportazione" in c.stderr, c.stderr
    assert "vault-sezioni.json" in c.stderr and "Chrome Passwords.csv" in c.stderr, c.stderr
    nessun_segreto(c.stdout + c.stderr, "uscita del pre-commit")


@prova("carte: si salvano e si mostrano al proprietario, ma l'uso dagli agenti le rifiuta sempre")
def _():
    s = S["sessione"]
    ch = V.VAULT.sessione(s)
    rec = V.VAULT._leggi()["voci"][S["id"]["Carta di prova"]]
    voce = V.VAULT._apri(ch, rec)
    for campo in ("password", "numero", "cvv", "codice"):
        r = {"campo": campo, "browser": "prova", "porta": 9, "selettore": "", "invio": False, "chi": "prova"}
        V.USO._esegui(r, rec, voce)
        assert r["stato"] == "rifiutata" and "servizio di pagamento" in r["motivo"], r
    c, m = http("POST", "/api/vault/mostra", {"id": S["id"]["Carta di prova"], "campo": "numero"}, s)
    assert c == 200 and m["valore"] == SEGRETI["CARTA"], "il proprietario la vede"
    t = (V.cartella() / "usi.jsonl").read_text()
    nessun_segreto(t, "usi.jsonl dopo il rifiuto della carta")


@prova("uso dagli agenti: spento di default (403 con il motivo), Windows mai; vault.py rifiuta su Windows")
def _():
    c, d = http("POST", "/api/vault/uso/richiedi", {"nome": "Sito finto", "campo": "password"})
    assert c == 403 and "Windows" in d["errore"], d
    vero = sys.platform
    try:
        V.sys.platform = "win32"
        assert V.uso_agenti_attivo() is False
    finally:
        V.sys.platform = vero
    assert V.porte_browser() == {}, "nessun browser predefinito"
    f = QUI.parent / "strumenti" / "vault.py"          # nel prodotto Windows non c'è (lì gli agenti non usano il Vault)
    if f.exists():
        src = f.read_text(encoding="utf-8")
        assert 'sys.platform == "win32"' in src and "carta" in src.lower()


@prova("portachiavi su Windows: DPAPI se c'è, altrimenti ripiego con file protetto (qui si prova il ripiego)")
def _():
    vecchio = os.environ.get("JARVIS_VAULT_PORTACHIAVI")
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = "dpapi"
    try:
        p = V.Portachiavi()
        assert p.modo == "dpapi"
        if sys.platform != "win32":
            assert V.dpapi_disponibile() is False and p.debole is True and "ripiego" in p.nome
        k = os.urandom(32)
        p.scrivi("prova-dpapi", k)
        assert p.leggi("prova-dpapi") == k
        f = V.cartella_chiavi() / "dispositivo-prova-dpapi.chiave"
        assert f.exists() and oct(f.stat().st_mode & 0o777) == "0o400"
        k2 = os.urandom(32)
        p.scrivi("prova-dpapi", k2)                       # riscrittura sopra un file 0400 (su Windows: sola lettura)
        assert p.leggi("prova-dpapi") == k2
        p.togli("prova-dpapi")
        assert p.leggi("prova-dpapi") is None and not f.exists()
    finally:
        if vecchio is None:
            os.environ.pop("JARVIS_VAULT_PORTACHIAVI", None)
        else:
            os.environ["JARVIS_VAULT_PORTACHIAVI"] = vecchio


@prova("vuoto e neutro: un Vault nuovo parte senza voci, con le sezioni generiche; nomi dal profilo")
def _():
    vecchia = os.environ["JARVIS_VAULT_DIR"]
    os.environ["JARVIS_VAULT_DIR"] = str(CASA / "dati" / "vault-vuoto")
    try:
        c, st = http("GET", "/api/vault/stato")
        assert c == 200 and st["creato"] is False and st["sbloccato"] is False
        assert st["assistente"] == "Aiutante" and st["proprietario"] == "Capo Finto"
        assert V.sezioni_partenza() == ["Lavoro", "Personale", "Famiglia", "Casa", "Soldi", "Altro"]
        assert V.file_sezioni().name == "vault-sezioni.esempio.json"
        c, d = http("POST", "/api/vault/crea", {"email": EMAIL, "password": FRASE})
        c, el = http("GET", "/api/vault/voci", sessione=d["sessione"])
        assert el["voci"] == [] and el["sezioni"] == ["Lavoro", "Personale", "Famiglia", "Casa", "Soldi", "Altro"]
    finally:
        os.environ["JARVIS_VAULT_DIR"] = vecchia


@prova("nomi: vault_cc è unico nelle cartelle del sys.path del server e server.py non fa «import vault»")
def _():
    doppi = [str(d) for d in (QUI.parent / "strumenti", QUI.parent, QUI.parent / "vps") if (d / "vault_cc.py").exists()]
    assert not doppi, f"vault_cc.py doppio in {doppi}"
    import re as _re
    src = (QUI / "server.py").read_text(encoding="utf-8")
    assert not _re.search(r"^\s*(import vault\b|from vault import)", src, _re.M), "server.py importa «vault»: collide con strumenti/vault.py"
    assert 'spec_from_file_location("vault_cc", QUI / "vault_cc.py")' in src


# ------------------------------------------------------------------------------------------------ fine
try:
    for n, e, m in esiti:
        print(f"{'✓' if e == 'ok' else '✗'} {n}" + (f"  [{e}: {m}]" if e != "ok" else ""))
    ok = sum(1 for _n, e, _m in esiti if e == "ok")
    print(f"\n{ok}/{len(esiti)} prove passate · casa finta {RADICE}")
finally:
    # il portachiavi usa-e-getta non è mai nella lista di ricerca del sistema: basta togliere la cartella temporanea
    shutil.rmtree(RADICE, ignore_errors=True)
sys.exit(0 if all(e == "ok" for _n, e, _m in esiti) else 1)
