#!/usr/bin/env python3
"""Importazione «Da Chrome (CSV)» nel Vault (funzione generica: qualsiasi file esportato da Chrome).

Il file esportato da Chrome (colonne name,url,username,password,note) è IN CHIARO: lo legge solo il server, in locale,
e i valori vanno dritti alla cifratura del Vault. Mai nella pagina, nella rete (solo il nome del file scelto), nei log,
nel piano, nelle note, nella memoria o in cartelle sincronizzate.

    python3 command-center/vault_chrome.py --piano FILE.csv [--uscita F.md] [--conteggi F.md]

stampa e scrive un piano di soli conteggi (per sezione, per categoria, per tipo di problema). --uscita (solo in locale)
aggiunge i domini da riordinare, senza utenti; --conteggi scrive solo i conteggi aggregati.

Regole (vault-sezioni.json, o l'esempio vault-sezioni.esempio.json, chiave «chrome»): sezione e categoria dal dominio
(suffisso o parola). Ogni riga = un
Accesso web. Doppioni: stessa coppia (dominio senza www, utente) = una voce; se le password sono diverse vince
l'ultima riga e quelle di prima restano nello storico. Password uguali su siti diversi NON si uniscono: avviso e tag.
Idempotente: ogni voce porta l'impronta (HMAC) della coppia; una voce modificata a mano non si sovrascrive.
Usa vault_cc (VAULT, cifratura, storico) e un backup cifrato del Vault prima di ogni importazione.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

QUI = Path(__file__).resolve().parent
COLONNE = ("name", "url", "username", "password", "note")
CARTELLE_CSV = ("Downloads", "Desktop", "Documents")       # stessi nomi su disco in macOS e Windows


def _vault():
    """vault_cc dal suo percorso (stesso modulo già caricato dal server, se c'è)."""
    m = sys.modules.get("vault_cc")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("vault_cc", QUI / "vault_cc.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["vault_cc"] = m
        spec.loader.exec_module(m)
    return m


REGOLE_PREDEFINITE = {
    "spazio_predefinito": "Altro",
    "spazi": [],
    "categorie": [
        {"categoria": "Google", "domini": ["google.", "gmail.", "youtube.", "android.com"]},
        {"categoria": "Posta e PEC", "domini": ["mail", "pec.", "legalmail", "aruba.it", "outlook", "libero.it", "yahoo."]},
        {"categoria": "Banche e pagamenti", "domini": ["bank", "banca", "paypal", "revolut", "satispay", "stripe", "nexi", "poste"]},
        {"categoria": "Social", "domini": ["facebook", "instagram", "linkedin", "twitter", "x.com", "tiktok", "meta.", "whatsapp", "telegram"]},
        {"categoria": "Shopping", "domini": ["amazon", "ebay", "zalando", "aliexpress", "shop", "store"]},
        {"categoria": "Hosting e domini", "domini": ["aruba", "godaddy", "cloudflare", "register.it", "vercel", "github", "netlify", "ovh"]},
        {"categoria": "Gestionali e fatture", "domini": ["fattur", "erp", "gestional"]},
        {"categoria": "Viaggi", "domini": ["booking", "airbnb", "ryanair", "easyjet", "trenitalia", "italo", "expedia", "skyscanner"]},
    ],
}


def regole():
    """Le regole «chrome» del file delle sezioni (il tuo vault-sezioni.json, altrimenti l'esempio generico)."""
    d = _vault()._leggi_sezioni()
    c = d.get("chrome") if isinstance(d, dict) else None
    return {**REGOLE_PREDEFINITE, **(c or {})}


# ------------------------------------------------------------------------------------------------ lettura del CSV
def leggi_csv(percorso, testo=None) -> list[dict]:
    """Righe del CSV di Chrome (UTF-8 con o senza BOM, campi con virgole, virgolette e a capo). Righe vuote saltate.
    testo: il contenuto già in memoria (sito della VPS: caricato dal browser, mai scritto su disco)."""
    if testo is None:
        testo = Path(percorso).expanduser().read_text(encoding="utf-8-sig", errors="replace")
    testo = testo.lstrip("\ufeff")
    lettore = csv.DictReader(io.StringIO(testo, newline=""))
    righe = []
    for n, r in enumerate(lettore, 2):
        r = {k.strip().lower(): (v or "") for k, v in r.items() if k}
        if not any((r.get(c) or "").strip() for c in COLONNE):
            continue
        righe.append({c: r.get(c, "") for c in COLONNE} | {"riga": n})
    return righe


def dominio(url: str) -> str:
    """Dominio normalizzato (minuscolo, senza www.). App Android: «app:pacchetto». Vuoto se non si capisce."""
    url = (url or "").strip()
    m = re.match(r"android://[^@]*@([^/]+)", url)
    if m:
        return "app:" + m.group(1).lower()
    try:
        h = urlsplit(url if "://" in url else "https://" + url).hostname or ""
    except ValueError:
        return ""
    h = h.lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def _spazzatura(dom: str, r=None) -> str:
    """Motivo se la riga è di prova o spazzatura (localhost, IP privati). Gli IP in «ip_ammessi» delle regole restano buoni."""
    if not dom:
        return "senza indirizzo"
    if dom in ("localhost",) or dom.endswith(".local") or dom.endswith(".localhost"):
        return "localhost"
    try:
        ip = ipaddress.ip_address(dom)
    except ValueError:
        return ""
    if dom in set((r or regole()).get("ip_ammessi") or []):
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return "IP privato"
    return "IP"


def _combacia(dom: str, voce: str) -> bool:
    voce = voce.lower()
    if voce.startswith("."):
        return dom.endswith(voce) or dom == voce[1:]
    if "." in voce and not voce.endswith("."):
        return dom == voce or dom.endswith("." + voce)
    return voce in dom


def classifica_dominio(dom: str, r=None) -> dict:
    r = r or regole()
    motivo = _spazzatura(dom, r)
    categoria = next((c["categoria"] for c in r["categorie"] if any(_combacia(dom, x) for x in c["domini"])), "")
    spazio = next((s["spazio"] for s in r["spazi"] if any(_combacia(dom, x) for x in s["domini"])), "")
    if motivo:
        return {"spazio": "", "categoria": categoria or "Altro", "sezione": "Da riordinare", "problema": motivo,
                "suggerimento": f"riga di prova o interna ({motivo})"}
    if not categoria and spazio:
        return {"spazio": spazio, "categoria": "Altro", "sezione": f"{spazio} / Altro", "problema": "", "suggerimento": ""}
    if not categoria:
        tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
        sugg = "app Android: scegli la categoria" if dom.startswith("app:") else \
            f"dominio sconosciuto{' (.' + tld + ')' if tld else ''}: aggiungilo a «chrome» in vault-sezioni.json"
        return {"spazio": spazio, "categoria": "", "sezione": "Da riordinare", "problema": "sconosciuto",
                "suggerimento": sugg}
    spazio = spazio or r.get("spazio_predefinito") or "Altro"
    return {"spazio": spazio, "categoria": categoria, "sezione": f"{spazio} / {categoria}", "problema": "", "suggerimento": ""}


# ------------------------------------------------------------------------------------------------ piano
def _raggruppa(righe):
    """{(dominio, utente): [righe in ordine]} e i riusi: impronta password -> set di domini (in memoria)."""
    import hashlib
    gruppi, riusi = {}, {}
    for r in righe:
        dom = dominio(r["url"])
        chiave = (dom, r["username"].strip().lower())
        gruppi.setdefault(chiave, []).append(r)
        p = r["password"]
        if p and p.strip().lower() != "passkey":
            riusi.setdefault(hashlib.sha256(p.encode()).digest(), set()).add(dom)
    return gruppi, riusi


def piano(percorso, con_domini=False, testo=None) -> dict:
    """SOLO conteggi (e, con con_domini, i domini da riordinare senza utenti). Nessun valore, nessun utente."""
    import hashlib
    r = regole()
    righe = leggi_csv(percorso, testo)
    gruppi, riusi = _raggruppa(righe)
    per_sezione, per_categoria, problemi = {}, {}, {"doppioni uniti": 0, "conflitti di password": 0,
                                                     "senza password o passkey": 0, "di prova o interne": 0,
                                                     "domini sconosciuti": 0, "password riusata (voci)": 0}
    da_riordinare = set()
    riuso_di = {}
    for imp, domini in riusi.items():
        if len(domini) > 1:
            riuso_di[imp] = len(domini)
    for (dom, _u), rr in gruppi.items():
        c = classifica_dominio(dom, r)
        per_sezione[c["sezione"]] = per_sezione.get(c["sezione"], 0) + 1
        per_categoria[c["categoria"] or "(da riordinare)"] = per_categoria.get(c["categoria"] or "(da riordinare)", 0) + 1
        problemi["doppioni uniti"] += len(rr) - 1
        pw = {x["password"] for x in rr}
        if len(pw) > 1:
            problemi["conflitti di password"] += 1
        ultima = rr[-1]["password"]
        if not ultima or ultima.strip().lower() == "passkey":
            problemi["senza password o passkey"] += 1
        elif hashlib.sha256(ultima.encode()).digest() in riuso_di:
            problemi["password riusata (voci)"] += 1
        if c["problema"] in ("localhost", "IP privato", "senza indirizzo"):
            problemi["di prova o interne"] += 1
        if c["problema"] == "sconosciuto":
            problemi["domini sconosciuti"] += 1
        if c["sezione"] == "Da riordinare":
            da_riordinare.add(dom or "(senza indirizzo)")
    out = {"creato": time.strftime("%Y-%m-%d %H:%M"), "file": Path(percorso).name if percorso else "caricato dal browser", "righe": len(righe),
           "domini": len({d for d, _u in gruppi}), "voci": len(gruppi), "per_sezione": dict(sorted(per_sezione.items())),
           "per_categoria": dict(sorted(per_categoria.items())), "problemi": problemi,
           "gruppi_password_riusata": len(riuso_di), "siti_max_stessa_password": max(riuso_di.values(), default=0)}
    if con_domini:
        out["domini_da_riordinare"] = sorted(da_riordinare)
    return out


def piano_markdown(p: dict, con_domini=False) -> str:
    r = ["# Vault - piano di importazione da Chrome", "",
         f"*{p['creato']} · `command-center/vault_cc.py` + `vault_chrome.py` · solo conteggi: nessun utente, nessuna password"
         + ("" if con_domini else ", nessun dominio") + ". L'importazione si fa dal pulsante «Da Chrome (CSV)» dopo lo sblocco.*", "",
         f"Righe: {p['righe']} · domini: {p['domini']} · voci dopo l'unione dei doppioni: {p['voci']}.", "",
         "## Per sezione", "", "| Sezione | Voci |", "|---|---|"]
    r += [f"| {s} | {n} |" for s, n in p["per_sezione"].items()]
    r += ["", "## Per categoria", "", "| Categoria | Voci |", "|---|---|"]
    r += [f"| {s} | {n} |" for s, n in p["per_categoria"].items()]
    r += ["", "## Problemi", "", "| Tipo | Quante |", "|---|---|"]
    r += [f"| {s} | {n} |" for s, n in p["problemi"].items()]
    r += ["", f"Password uguali su più siti: {p['gruppi_password_riusata']} gruppi (al massimo {p['siti_max_stessa_password']} siti con la "
          "stessa password). Non si uniscono: ogni voce porta l'avviso.", ""]
    if con_domini and p.get("domini_da_riordinare"):
        r += ["## Domini da riordinare (solo in locale)", "", ", ".join(f"`{d}`" for d in p["domini_da_riordinare"]), ""]
    return "\n".join(r) + "\n"


# ------------------------------------------------------------------------------------------------ importazione
def importa(vault, chiavi, percorso, testo=None) -> dict:
    """Le righe diventano Accessi web cifrati. Restituisce SOLO conteggi. Backup cifrato del Vault prima."""
    import hashlib
    V = _vault()
    r = regole()
    righe = leggi_csv(percorso, testo)
    gruppi, riusi = _raggruppa(righe)
    riuso_di = {imp: len(d) for imp, d in riusi.items() if len(d) > 1}
    k = chiavi["hmac"]
    conti = {"importate": 0, "aggiornate": 0, "gia_presenti": 0, "modificate_a_mano": 0, "unite": 0,
             "da_riordinare": 0, "password_riusate": 0, "senza_password": 0, "conflitti": 0}
    with vault.mutex:
        d = vault._leggi()
        vault._backup_file(f"prima-chrome-{time.strftime('%Y%m%d-%H%M%S')}")
        imp = vault._impostazioni(d, chiavi)
        esistenti = {}
        for rec, v in vault._tutte(d, chiavi, anche_eliminate=True):
            if v["tipo"] == "accesso":
                ch = next((e.get("valore") for e in v.get("extra", []) if e.get("nome") == "Impronta Chrome"), None)
                if ch:
                    esistenti[ch] = (rec, v)
        for (dom, utente), rr in gruppi.items():
            c = classifica_dominio(dom, r)
            ultima = rr[-1]
            impronta_coppia = V.impronta(k, f"chrome|{dom}|{utente}")[:24]
            pw = ultima["password"]
            senza = not pw or pw.strip().lower() == "passkey"
            tag = ["chrome"]
            if senza:
                tag.append("senza password")
                conti["senza_password"] += 1
            else:
                n = riuso_di.get(hashlib.sha256(pw.encode()).digest())
                if n:
                    tag.append(f"password riusata su {n} siti")
                    conti["password_riusate"] += 1
            if c["sezione"] == "Da riordinare":
                tag.append("da riordinare")
                conti["da_riordinare"] += 1
            password_diverse = [x["password"] for x in rr if x["password"] != pw]
            if password_diverse:
                tag.append("conflitto di password")
                conti["conflitti"] += 1
            conti["unite"] += len(rr) - 1
            note = "\n\n".join(x["note"] for x in rr if x["note"].strip())
            link = ultima["url"].strip()
            titolo = (ultima["name"].strip() or dom or "Accesso senza nome")[:200]
            campi = {"link": link, "domini": "" if dom.startswith("app:") else dom, "utente": ultima["username"].strip(),
                     "mail": ultima["username"].strip() if "@" in ultima["username"] else "",
                     "password": "" if senza else pw, "metodo": "passkey" if pw.strip().lower() == "passkey" else "",
                     "note": note}
            extra = [{"nome": "Impronta Chrome", "valore": impronta_coppia, "segreto": False}]
            if c["suggerimento"]:
                extra.append({"nome": "Suggerimento", "valore": c["suggerimento"], "segreto": False})
            trovato = esistenti.get(impronta_coppia)
            if trovato:
                rec, v = trovato
                if v.get("origine") not in ("chrome",):
                    conti["modificate_a_mano"] += 1          # toccata a mano: non si sovrascrive
                    continue
                if V.impronta(k, v["campi"].get("password", "")) == V.impronta(k, campi["password"]) and \
                        v["campi"].get("note", "") == note and not v.get("eliminata"):
                    conti["gia_presenti"] += 1
                    continue
                v["campi"].update(password=campi["password"], note=note, link=link)
                v["eliminata"] = False
                vault._nuova_versione(d, chiavi, rec, v, "chrome")
                conti["aggiornate"] += 1
                continue
            voce = {"tipo": "accesso", "titolo": titolo, "classe": "personale", "sezione": c["sezione"], "tag": tag,
                    "preferito": False, "campi": campi, "extra": extra}
            # con password diverse per la stessa coppia: prima le vecchie (storico), poi l'ultima come attuale
            vecchie = list(dict.fromkeys(password_diverse))
            if vecchie:
                prima = vault._pulisci({**voce, "campi": {**campi, "password": vecchie[0]}})
                id_voce = vault._aggiungi(d, chiavi, prima, "chrome")
                rec = d["voci"][id_voce]
                for vp in vecchie[1:] + [campi["password"]]:
                    vv = vault._pulisci({**voce, "campi": {**campi, "password": vp}})
                    vv["creata"] = prima["creata"]
                    vault._nuova_versione(d, chiavi, rec, vv, "chrome")
            else:
                vault._aggiungi(d, chiavi, vault._pulisci(voce), "chrome")
            if c["sezione"] not in imp["sezioni"]:
                imp["sezioni"].append(c["sezione"])
            conti["importate"] += 1
        vault._scrivi_impostazioni(d, chiavi, imp)
        vault._salva(d)
    righe.clear()
    vault.registra("importa-chrome", campo=", ".join(f"{a} {b}" for a, b in conti.items()))
    return {**conti, "righe_lette": sum(len(x) for x in gruppi.values()), "backup_prima": True}


# ------------------------------------------------------------------------------------------------ file e cancellazione
def _casa():
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return Path(os.environ.get("HOME") or Path.home())


def file_csv_disponibili():
    """Solo i NOMI dei .csv in Download, Scrivania, Documenti (non si apre niente)."""
    out = []
    for c in CARTELLE_CSV:
        d = _casa() / c
        try:
            out += [{"cartella": c, "nome": f.name, "kb": round(f.stat().st_size / 1024)} for f in sorted(d.glob("*.csv"))[:50]]
        except OSError:
            pass
    return out


def percorso_sicuro(cartella, nome):
    if cartella not in CARTELLE_CSV or "/" in str(nome) or "\\" in str(nome) or str(nome).startswith(".") or \
            not str(nome).lower().endswith(".csv"):
        raise _vault().ErroreVault("Scegli un file .csv in Download, Scrivania o Documenti.")
    f = (_casa() / cartella / nome)
    if not f.is_file():
        raise _vault().ErroreVault("File non trovato.", 404)
    return f


def elimina_csv(f: Path):
    """Sovrascrive il file con byte casuali (stessa lunghezza), lo scarica sul disco e lo toglie. Va chiamata SOLO
    dopo la doppia conferma del proprietario (lo controlla gestisci). Nota onesta: su un SSD (APFS, NTFS) la
    sovrascrittura non garantisce che i blocchi vecchi spariscano; per questo la pagina ricorda Cestino ed esportazione."""
    n = f.stat().st_size
    with open(f, "r+b") as h:
        h.write(secrets.token_bytes(n))
        h.flush()
        os.fsync(h.fileno())
    f.unlink()


# ------------------------------------------------------------------------------------------------ caricamento dal browser
# Nel modo VPS il CSV non sta sul server: la pagina lo legge dal computer del proprietario e lo manda a pezzi (HTTPS, dietro
# il login del sito e la sessione del Vault). Il testo resta SOLO in memoria in questo processo, legato alla sessione,
# per al massimo 15 minuti; dopo l'importazione (o «scarta») si butta. Mai su disco, mai nei log, mai nelle risposte.
PEZZO_MAX = 100_000            # caratteri per pezzo (sotto i 400 KB di server.py anche con l'escape JSON)
PEZZI_MAX = 120                # ~12 milioni di caratteri
CARICAMENTO_S = 900
_CARICAMENTI = {}


def _pulisci_caricamenti():
    for k, c in list(_CARICAMENTI.items()):
        if time.time() - c["creato"] > CARICAMENTO_S:
            _CARICAMENTI.pop(k, None)


def carica(corpo, chiavi):
    V = _vault()
    _pulisci_caricamenti()
    pezzo = corpo.get("pezzo")
    try:
        parte, totale = int(corpo.get("parte")), int(corpo.get("totale"))
    except (TypeError, ValueError):
        raise V.ErroreVault("Pezzo non valido.")
    if not isinstance(pezzo, str) or len(pezzo) > PEZZO_MAX or not (1 <= totale <= PEZZI_MAX) or not (0 <= parte < totale):
        raise V.ErroreVault(f"File troppo grande o pezzo non valido (massimo {PEZZI_MAX * PEZZO_MAX // 1_000_000} milioni di caratteri).", 413)
    cid = str(corpo.get("caricamento") or "")
    if not cid:
        if len(_CARICAMENTI) >= 3:
            raise V.ErroreVault("Troppi caricamenti aperti: riprova fra qualche minuto.", 429)
        cid = secrets.token_urlsafe(12)
        _CARICAMENTI[cid] = {"chi": id(chiavi), "totale": totale, "parti": {}, "creato": time.time()}
    c = _CARICAMENTI.get(cid)
    if not c or c["chi"] != id(chiavi) or c["totale"] != totale:
        raise V.ErroreVault("Caricamento scaduto: ricomincia.", 410)
    c["parti"][parte] = pezzo
    return {"caricamento": cid, "ricevute": len(c["parti"]), "totale": totale}


def testo_caricato(cid, chiavi, togli=False):
    V = _vault()
    _pulisci_caricamenti()
    c = _CARICAMENTI.get(str(cid or ""))
    if not c or c["chi"] != id(chiavi):
        raise V.ErroreVault("Caricamento scaduto: scegli di nuovo il file.", 410)
    if len(c["parti"]) != c["totale"]:
        raise V.ErroreVault("Il file non è arrivato tutto: riprova.", 409)
    testo = "".join(c["parti"][i] for i in range(c["totale"]))
    if togli:
        _CARICAMENTI.pop(str(cid), None)
    return testo


# ------------------------------------------------------------------------------------------------ HTTP
def gestisci(metodo, percorso, query, corpo, vault, chiavi):
    V = _vault()
    sul_sito = V.modo_vps()
    if metodo == "GET" and percorso == "/api/vault/chrome/file":
        # nel modo VPS i file stanno sul computer del proprietario: la pagina mostra il selettore di file
        return 200, {"file": [] if sul_sito else file_csv_disponibili(), "carica": sul_sito}
    if metodo == "POST" and percorso == "/api/vault/chrome/carica":
        return 200, carica(corpo, chiavi)
    if metodo == "POST" and percorso == "/api/vault/chrome/scarta":
        _CARICAMENTI.pop(str(corpo.get("caricamento") or ""), None)
        return 200, {"scartato": True}
    if metodo == "POST" and percorso == "/api/vault/chrome/piano":
        return 200, piano(None, testo=testo_caricato(corpo.get("caricamento"), chiavi))
    if metodo == "POST" and percorso == "/api/vault/chrome/importa" and corpo.get("caricamento"):
        testo = testo_caricato(corpo.get("caricamento"), chiavi, togli=True)
        return 200, importa(vault, chiavi, None, testo=testo)
    if sul_sito:
        raise V.ErroreVault("Sul sito il file si sceglie dal tuo computer (selettore di file).", 400)
    if metodo == "GET" and percorso == "/api/vault/chrome/piano":
        f = percorso_sicuro((query.get("cartella") or [""])[0], (query.get("nome") or [""])[0])
        return 200, piano(f)
    if metodo == "POST" and percorso == "/api/vault/chrome/importa":
        f = percorso_sicuro(corpo.get("cartella"), corpo.get("nome"))
        return 200, importa(vault, chiavi, f)
    if metodo == "POST" and percorso == "/api/vault/chrome/elimina":
        f = percorso_sicuro(corpo.get("cartella"), corpo.get("nome"))
        if corpo.get("conferma_1") is not True or corpo.get("conferma_2") != "ELIMINA":
            raise V.ErroreVault("Servono le due conferme del proprietario.", 428)
        elimina_csv(f)
        vault.registra("csv-chrome-eliminato", campo=f"{f.parent.name}/…")
        return 200, {"eliminato": True}
    return 404, {"errore": "non trovato"}


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--piano"] and len(a) > 1:
        p = piano(a[1], con_domini=True)
        for opz, domini in (("--uscita", True), ("--conteggi", False)):
            if opz in a:
                dest = Path(a[a.index(opz) + 1]).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(piano_markdown(p, con_domini=domini), encoding="utf-8")
                print(f"scritto {dest}")
        print(f"{p['righe']} righe · {p['domini']} domini · {p['voci']} voci dopo l'unione dei doppioni")
        for s, n in p["per_sezione"].items():
            print(f"  {n:4d}  {s}")
        print("categorie:", ", ".join(f"{c} {n}" for c, n in p["per_categoria"].items()))
        print("problemi:", ", ".join(f"{c} {n}" for c, n in p["problemi"].items()))
        print(f"password uguali su più siti: {p['gruppi_password_riusata']} gruppi (max {p['siti_max_stessa_password']} siti)")
        sys.exit(0)
    print(__doc__)
