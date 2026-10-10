#!/usr/bin/env python3
"""Prove dell'importazione «Da Chrome (CSV)». Uso:  python3 command-center/prova_vault_chrome.py

Casa finta COMPLETA (HOME, USERPROFILE, APPDATA, XDG_*, cartella del Vault, portachiavi usa-e-getta), CSV FINTO di circa
1000 righe:
UTF-8 con BOM, virgole e virgolette nei campi, righe vuote, note su più righe, doppioni, password diverse per la
stessa coppia, domini con www, IP, localhost, un IP di documentazione, app Android, password vuote e «passkey». Ogni valore
finto contiene «FINTOCHROME»: alla fine si cerca dappertutto (piano, risposte, log, file del Vault) e non deve esserci.
L'uscita stampa solo nomi delle prove ed esiti.
"""
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CASA_VERA = Path(os.path.expanduser("~")).resolve()
QUI = Path(__file__).resolve().parent
RADICE = Path(tempfile.mkdtemp(prefix="vault-chrome-prova-"))
CASA = RADICE / "casa"
(CASA / "Downloads").mkdir(parents=True)
assert CASA.resolve() != CASA_VERA and CASA_VERA not in CASA.resolve().parents
os.environ.update({"HOME": str(CASA), "USERPROFILE": str(CASA), "APPDATA": str(CASA / "AppData" / "Roaming"),
                   "LOCALAPPDATA": str(CASA / "AppData" / "Local"), "XDG_CONFIG_HOME": str(CASA / ".config"),
                   "XDG_DATA_HOME": str(CASA / ".local" / "share"), "XDG_CACHE_HOME": str(CASA / ".cache"),
                   "XDG_STATE_HOME": str(CASA / ".local" / "state"),
                   "JARVIS_VAULT_DIR": str(CASA / "dati" / "vault"), "JARVIS_VAULT_ENV_VERO": str(CASA / ".env.jarvis"),
                   "JARVIS_VAULT_PROVA": "1", "JARVIS_VAULT_GIRI": "2000"})
assert Path.home().resolve() == CASA.resolve(), "Path.home() non è la casa finta: mi fermo"
if sys.platform == "darwin":
    kc = RADICE / "prova.keychain-db"
    for comando in (["create-keychain", "-p", "p", str(kc)], ["set-keychain-settings", str(kc)], ["unlock-keychain", "-p", "p", str(kc)]):
        subprocess.run(["security", *comando], check=True, capture_output=True)
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = str(kc)
else:
    os.environ["JARVIS_VAULT_PORTACHIAVI"] = "file"
sys.path.insert(0, str(QUI))
import vault_cc as V  # noqa: E402
import vault_chrome as VC  # noqa: E402
import vault_gruppi as VG  # noqa: E402

SEGNO = "FINTOCHROME"
esiti = []


def prova(nome):
    def deco(fn):
        try:
            fn()
            esiti.append((nome, "ok", ""))
        except AssertionError as e:
            esiti.append((nome, "FALLITA", str(e)[:200]))
        except Exception as e:  # noqa: BLE001
            esiti.append((nome, "ERRORE", type(e).__name__ + ": " + str(e)[:120].replace(SEGNO, "***")))
        return fn
    return deco


def http(metodo, percorso, corpo=None, sessione=None):
    from urllib.parse import parse_qs, urlsplit
    return V.gestisci(metodo, percorso.split("?")[0], parse_qs(urlsplit(percorso).query), corpo or {},
                      {"X-Vault-Sessione": sessione or "", "Host": "127.0.0.1:7777"})


def senza_segno(testo, dove):
    assert SEGNO not in testo, f"valore finto in {dove}"


def csv_finto():
    """~1000 righe. Restituisce (testo con BOM, attesi)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name", "url", "username", "password", "note"])
    domini = ["google.com", "www.amazon.it", "online.banca-esempio.it", "portale.lavoro-esempio.com", "enel.it", "instagram.com",
              "booking.com", "aruba.it", "sito-sconosciuto-{i}.it", "negozio-{i}.com", "inps.it", "revolut.com"]
    for i in range(960):
        dom = domini[i % len(domini)].format(i=i)
        pw = f"{SEGNO}-pw-{i:04d}" if i % 10 else f"{SEGNO}-riusata-comune"       # una password riusata su molti siti
        nota = f"{SEGNO} nota {i}, con virgola e \"virgolette\"\nseconda riga" if i % 37 == 0 else ""
        w.writerow([f"Sito {i}, con virgola", f"https://{dom}/login", f"utente{i}@{SEGNO.lower()}.it", pw, nota])
        if i % 100 == 0:
            buf.write("\n")                                                           # riga vuota
    # doppioni: stessa coppia con www e senza, stessa password (unione) e con password diversa (conflitto)
    w.writerow(["Doppione A", "https://www.doppio.it/", f"io@{SEGNO.lower()}.it", f"{SEGNO}-doppio", ""])
    w.writerow(["Doppione A bis", "https://doppio.it/accesso", f"IO@{SEGNO.lower()}.it", f"{SEGNO}-doppio", ""])
    w.writerow(["Conflitto", "https://conflitto.it/", f"c@{SEGNO.lower()}.it", f"{SEGNO}-vecchia", ""])
    w.writerow(["Conflitto nuovo", "https://conflitto.it/", f"c@{SEGNO.lower()}.it", f"{SEGNO}-nuova", ""])
    # spazzatura e casi speciali
    w.writerow(["Router", "http://192.168.1.1/", "admin", f"{SEGNO}-router", ""])
    w.writerow(["Locale", "http://localhost:8080/", "dev", f"{SEGNO}-locale", ""])
    w.writerow(["Loop", "http://127.0.0.1:7777/", "x", f"{SEGNO}-loop", ""])
    w.writerow(["Server mio", "https://203.0.113.10:9443/", "root", f"{SEGNO}-server", ""])
    w.writerow(["App", "android://abc@app.esempio.invalid/", "app@x.invalid", f"{SEGNO}-app", ""])
    w.writerow(["Senza password", "https://vuota.it/", "v@x.invalid", "", ""])
    w.writerow(["Passkey", "https://chiave.it/", "k@x.invalid", "passkey", ""])
    w.writerow(["", "", "", "", ""])
    return "﻿" + buf.getvalue()


CSV = CASA / "Downloads" / "Password Chrome prova.csv"
CSV.write_text(csv_finto(), encoding="utf-8")
S = {}


@prova("lettura: BOM, virgole e virgolette, note su più righe, righe vuote saltate")
def _():
    righe = VC.leggi_csv(CSV)
    assert len(righe) == 960 + 11, len(righe)
    r37 = next(r for r in righe if r["name"] == "Sito 37, con virgola")
    assert "\nseconda riga" in r37["note"] and '"virgolette"' in r37["note"]
    assert VC.dominio("https://www.amazon.it/login") == "amazon.it" and VC.dominio("android://x@app.invalid/") == "app:app.invalid"


@prova("classificazione: regole dell'esempio generico, spazzatura in «Da riordinare», IP ammessi, sconosciuti con suggerimento")
def _():
    c = VC.classifica_dominio
    assert c("enel.it")["sezione"] == "Casa / Utenze", c("enel.it")
    assert c("inps.it")["sezione"] == "Soldi / Pubblica amministrazione", c("inps.it")
    assert c("online.banca-esempio.it")["sezione"] == "Soldi / Banche e pagamenti"
    assert c("revolut.com")["spazio"] == "Soldi" and c("revolut.com")["categoria"] == "Banche e pagamenti"
    assert c("aruba.it")["sezione"] == "Personale / Hosting e domini", c("aruba.it")
    assert c("instagram.com")["categoria"] == "Social" and c("booking.com")["categoria"] == "Viaggi"
    for d in ("192.168.1.1", "localhost", "127.0.0.1"):
        assert c(d)["sezione"] == "Da riordinare" and c(d)["problema"] in ("IP privato", "localhost"), d
    assert c("203.0.113.10")["sezione"] == "Da riordinare"                       # IP non ammesso (indirizzo di documentazione)
    assert c("203.0.113.10", {**VC.regole(), "ip_ammessi": ["203.0.113.10"]})["problema"] not in ("IP", "IP privato", "localhost")
    x = c("sito-sconosciuto-8.it")
    assert x["sezione"] == "Da riordinare" and "vault-sezioni.json" in x["suggerimento"]


@prova("piano: solo conteggi, nessun valore né utente; doppioni, conflitto, vuote, spazzatura, riuso")
def _():
    p = VC.piano(CSV)
    j = json.dumps(p)
    senza_segno(j, "piano")
    senza_segno(VC.piano_markdown(p), "piano Markdown")
    senza_segno(VC.piano_markdown(VC.piano(CSV, con_domini=True), con_domini=True), "piano locale")
    assert "utente" not in j.lower()
    assert p["righe"] == 971 and p["voci"] == 969, (p["righe"], p["voci"])
    pr = p["problemi"]
    assert pr["doppioni uniti"] == 2 and pr["conflitti di password"] == 1 and pr["senza password o passkey"] == 2
    assert pr["di prova o interne"] == 4 and p["gruppi_password_riusata"] >= 1 and p["siti_max_stessa_password"] >= 20


@prova("importazione: backup cifrato prima, conteggi, valori giusti (anche note su più righe), conflitto nello storico")
def _():
    c, d = http("POST", "/api/vault/crea", {"email": "prova@esempio.invalid", "password": "password-finta-lunga"})
    s = S["s"] = d["sessione"]
    ch = V.VAULT.sessione(s)
    r = VC.importa(V.VAULT, ch, CSV)
    senza_segno(json.dumps(r), "risposta dell'importazione")
    assert r["importate"] == 969 and r["unite"] == 2 and r["conflitti"] == 1 and r["senza_password"] == 2, r
    assert r["da_riordinare"] >= 3 and r["password_riusate"] >= 90
    assert list((V.cartella() / "backup").glob("vault-prima-chrome-*.json"))
    el = http("GET", "/api/vault/voci", sessione=s)[1]["voci"]
    assert len(el) == 969
    per_titolo = {v["titolo"]: v for v in el}
    v37 = per_titolo["Sito 37, con virgola"]
    m = http("POST", "/api/vault/mostra", {"id": v37["id"], "campo": "note"}, s)[1]
    assert m["valore"].endswith("seconda riga") and '"virgolette"' in m["valore"]
    conf = per_titolo["Conflitto nuovo"]
    assert "conflitto di password" in conf["tag"] and conf["versioni"] == 2
    assert http("POST", "/api/vault/mostra", {"id": conf["id"], "campo": "password"}, s)[1]["valore"].endswith("-nuova")
    st = http("GET", f"/api/vault/storico?id={conf['id']}", sessione=s)[1]
    vecchia = V.VAULT._apri(ch, V.VAULT._leggi()["voci"][conf["id"]], V.VAULT._leggi()["storico"][conf["id"]][0]["dati"], 1)
    assert vecchia["campi"]["password"].endswith("-vecchia") and len(st["versioni"]) == 2
    vuota = per_titolo["Senza password"]
    assert vuota["campi"]["password"]["presente"] is False and "senza password" in vuota["tag"]
    assert per_titolo["Passkey"]["campi"]["metodo"] == "passkey"
    assert per_titolo["Router"]["sezione"] == "Da riordinare" and per_titolo["Server mio"]["sezione"] == "Da riordinare"
    riusata = next(v for v in el if any(t.startswith("password riusata su") for t in v["tag"]))
    assert riusata["campi"]["metodo"] == "" and not riusata["campi"].get("alias"), "niente alias per password uguali fra siti"
    S["el"] = el


@prova("idempotente: seconda importazione senza doppioni; voce modificata a mano non sovrascritta; riga cambiata aggiornata")
def _():
    s = S["s"]
    ch = V.VAULT.sessione(s)
    r = VC.importa(V.VAULT, ch, CSV)
    assert r["importate"] == 0 and r["gia_presenti"] == 969 and r["aggiornate"] == 0, r
    # il proprietario modifica a mano una voce: la reimportazione non la tocca
    v = next(x for x in S["el"] if x["titolo"] == "Sito 1, con virgola")
    c, d = http("POST", "/api/vault/salva", {"id": v["id"], "versione_base": v["versione"], "tipo": "accesso", "titolo": v["titolo"],
                                             "campi": {"password": "password-cambiata-a-mano"}}, s)
    assert c == 200
    testo = CSV.read_text(encoding="utf-8").replace(f"{SEGNO}-pw-0001", f"{SEGNO}-pw-0001-NUOVA").replace(f"{SEGNO}-pw-0002", f"{SEGNO}-pw-0002-NUOVA")
    CSV2 = CASA / "Downloads" / "Password Chrome prova 2.csv"
    CSV2.write_text(testo, encoding="utf-8")
    r = VC.importa(V.VAULT, ch, CSV2)
    assert r["modificate_a_mano"] == 1 and r["aggiornate"] == 1 and r["importate"] == 0, r
    v1 = http("POST", "/api/vault/mostra", {"id": v["id"], "campo": "password"}, s)[1]["valore"]
    assert v1 == "password-cambiata-a-mano"
    assert len(http("GET", "/api/vault/voci", sessione=s)[1]["voci"]) == 969


@prova("HTTP: elenco dei CSV (solo nomi), piano, importazione; percorsi fuori da Download/Scrivania/Documenti rifiutati")
def _():
    s = S["s"]
    ch = V.VAULT.sessione(s)
    c, f = VC.gestisci("GET", "/api/vault/chrome/file", {}, {}, V.VAULT, ch)
    assert c == 200 and any(x["nome"] == CSV.name for x in f["file"])
    senza_segno(json.dumps(f), "elenco dei file")
    c, p = VC.gestisci("GET", "/api/vault/chrome/piano", {"cartella": ["Downloads"], "nome": [CSV.name]}, {}, V.VAULT, ch)
    assert c == 200 and p["voci"] == 969
    for cart, nome in (("..", CSV.name), ("Downloads", "../.env.jarvis"), ("Library", "x.csv"), ("Downloads", "x.txt")):
        try:
            VC.gestisci("POST", "/api/vault/chrome/importa", {}, {"cartella": cart, "nome": nome}, V.VAULT, ch)
            raise AssertionError(f"accettato {cart}/{nome}")
        except V.ErroreVault:
            pass


@prova("cancellazione del CSV: senza le due conferme non cancella; con le due conferme sovrascrive e toglie")
def _():
    s = S["s"]
    ch = V.VAULT.sessione(s)
    copia = CASA / "Downloads" / "da-eliminare.csv"
    copia.write_text(CSV.read_text(encoding="utf-8"), encoding="utf-8")
    for corpo in ({}, {"conferma_1": True}, {"conferma_1": True, "conferma_2": "si"}):
        try:
            VC.gestisci("POST", "/api/vault/chrome/elimina", {}, {"cartella": "Downloads", "nome": copia.name, **corpo}, V.VAULT, ch)
            raise AssertionError("cancellato senza le due conferme")
        except V.ErroreVault as e:
            assert e.codice == 428
    assert copia.exists()
    c, d = VC.gestisci("POST", "/api/vault/chrome/elimina", {}, {"cartella": "Downloads", "nome": copia.name,
                                                                  "conferma_1": True, "conferma_2": "ELIMINA"}, V.VAULT, ch)
    assert c == 200 and not copia.exists()


@prova("eliminazione in blocco: sezione e categoria intere, conferma col numero, backup prima, annulla del lotto")
def _():
    s = S["s"]
    ch = V.VAULT.sessione(s)
    g = lambda m, p, c=None, q=None: VG.gestisci(m, p, q or {}, c or {}, V.VAULT, ch)  # noqa: E731
    tot = len(http("GET", "/api/vault/voci", sessione=s)[1]["voci"])
    c, n = g("GET", "/api/vault/gruppo/conta", q={"sezione": ["Da riordinare"]})
    assert c == 200 and n["voci"] >= 3
    for sbagliata in (None, n["voci"] - 1, str(n["voci"])):
        try:
            g("POST", "/api/vault/gruppo/elimina", {"sezione": "Da riordinare", "conferma": sbagliata})
            raise AssertionError("eliminato senza la conferma giusta")
        except V.ErroreVault as e:
            assert e.codice == 409
    try:
        g("POST", "/api/vault/gruppo/elimina", {"sezione": "Da riordinare", "tipo": "accesso", "conferma": 1})
        raise AssertionError("due filtri accettati")
    except V.ErroreVault:
        pass
    c, r = g("POST", "/api/vault/gruppo/elimina", {"sezione": "Da riordinare", "conferma": n["voci"], "togli_sezione": True})
    assert c == 200 and r["eliminate"] == n["voci"] and r["backup_prima"]
    assert list((V.cartella() / "backup").glob("vault-prima-eliminazione-*.json"))
    el = http("GET", "/api/vault/voci", sessione=s)[1]
    assert len(el["voci"]) == tot - n["voci"] and "Da riordinare" not in el["sezioni"]
    # tutta la categoria «Accessi web»
    c, m = g("GET", "/api/vault/gruppo/conta", q={"tipo": ["accesso"]})
    c, r2 = g("POST", "/api/vault/gruppo/elimina", {"tipo": "accesso", "conferma": m["voci"]})
    assert r2["eliminate"] == m["voci"] and len(http("GET", "/api/vault/voci", sessione=s)[1]["voci"]) == 0
    c, l = g("GET", "/api/vault/gruppo/lotti")
    assert [x["lotto"] for x in l["lotti"]] == [r2["lotto"], r["lotto"]]
    senza_segno(json.dumps(l), "elenco dei lotti")
    c, a = g("POST", "/api/vault/gruppo/ripristina", {"lotto": r2["lotto"]})
    assert a["ripristinate"] == m["voci"]
    c, a = g("POST", "/api/vault/gruppo/ripristina", {"lotto": r["lotto"]})
    assert a["ripristinate"] == n["voci"]
    el = http("GET", "/api/vault/voci", sessione=s)[1]
    assert len(el["voci"]) == tot and "Da riordinare" in el["sezioni"]
    v = el["voci"][0]
    st = http("GET", f"/api/vault/storico?id={v['id']}", sessione=s)[1]
    assert any(x["eliminata"] for x in st["versioni"]), "l'eliminazione resta nello storico"


@prova("scansione: nessun valore finto in log, backup, piano, risposte; solo cifrato nel file del Vault")
def _():
    for f in V.cartella().rglob("*"):
        if f.is_file():
            senza_segno(f.read_text(errors="ignore"), f.name)
    r = subprocess.run([sys.executable, str(QUI / "vault_chrome.py"), "--piano", str(CSV), "--uscita", str(CASA / "p.md")],
                       capture_output=True, text=True, env=dict(os.environ), timeout=60)
    assert r.returncode == 0
    senza_segno(r.stdout + r.stderr, "uscita del comando")
    senza_segno((CASA / "p.md").read_text(), "p.md")


try:
    for n, e, m in esiti:
        print(f"{'✓' if e == 'ok' else '✗'} {n}" + (f"  [{e}: {m}]" if e != "ok" else ""))
    print(f"\n{sum(1 for _n, e, _m in esiti if e == 'ok')}/{len(esiti)} prove passate · casa finta {RADICE}")
finally:
    shutil.rmtree(RADICE, ignore_errors=True)
sys.exit(0 if all(e == "ok" for _n, e, _m in esiti) else 1)
