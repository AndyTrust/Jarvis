#!/usr/bin/env python3
"""Il Vault del Command Center: accessi, carte, PIN, variabili e note sicure, cifrati sul tuo computer.

Un solo file, senza dipendenze dal resto del Command Center (solo la libreria «cryptography»). Parte VUOTO.
Lo usano server.py (rotte /api/vault/*) e le prove (prova_vault.py). Guida: docs/wiki/Vault.md.

Cosa fa
- Voci cifrate a riposo: Accesso web, Carta, PIN, Variabile, Nota sicura (+ campi personalizzati).
- Due classi: «servizio» (variabili, token dei programmi) e «personale» (carte, PIN, password dei siti).
- Cifratura: AES-256-GCM per ogni voce (chiave della voce casuale, avvolta dalla chiave della sua classe), IV di
  12 byte, dati associati = id + versione. Formato del blob: [versione 1][IV 12][cifrato+tag], in base64.
- Chiavi della classe avvolte da HKDF(PBKDF2-SHA256(password, 600 000 giri) || chiave del dispositivo). La chiave del
  dispositivo sta nel portachiavi del sistema: su macOS il Portachiavi (comando `security`), su Windows un file
  protetto con DPAPI (legato al tuo account di Windows). Il file del Vault rubato da solo non si apre nemmeno con un
  attacco a forza bruta sulla password. Il PIN fa lo stesso, con 5 tentativi. Un codice di recupero di 24 parole
  (mostrato una volta alla creazione) apre il Vault anche su un computer nuovo.
- Storico di 20 versioni per voce, «Annulla», eliminazione annullabile, esportazione cifrata, backup del file cifrato.
- Registro degli usi (usi.jsonl): solo id, campo, azione, esito. MAI un valore.
- Ambiente (~/.env.jarvis): il file vero si legge SOLTANTO (nomi, presenza, impronta HMAC); il valore si vede solo con
  «Mostra» a Vault sbloccato. La scrittura va sulla copia di prova; sul file vero solo se in config.json (nella
  cartella del Vault) c'è "scrittura_file_vero": true, scritto a mano dal proprietario.
- Lucchetto per file: «<file>.lock» creato in modo esclusivo (O_CREAT|O_EXCL), dentro «pid host epoch chi»; più
  vecchio di 30 s = abbandonato, si toglie.
- Le carte si salvano e si mostrano al proprietario, ma gli agenti non le usano mai (vedi UsoAgenti).

Percorsi (tutti cambiabili con variabili d'ambiente, le prove usano una casa finta):
  JARVIS_VAULT_DIR         cartella del Vault (macOS ~/Library/Application Support/Jarvis/vault,
                           Windows %APPDATA%\Jarvis\vault, altrove ~/.jarvis-vault)
  JARVIS_VAULT_ENV_VERO    il file vero, solo lettura (default ~/.env.jarvis)
  JARVIS_VAULT_ENV_PROVA   la copia di prova (default <cartella>/prova/env.jarvis.prova)
  JARVIS_VAULT_PORTACHIAVI «login» (default su macOS) o il percorso di un portachiavi; «dpapi» (default su Windows);
                           «file» (ripiego: chiave in un file con i permessi del solo utente, avviso nella pagina)
  JARVIS_VAULT_PROFILO     il profilo dell'assistente (nome dell'assistente e del proprietario)
  JARVIS_VAULT_PROVA=1     solo per le prove: permette JARVIS_VAULT_GIRI più bassi

Modo VPS (AVANZATO, facoltativo, solo Linux): lo stesso file sul Command Center di un server tuo. Si accende SOLO con
JARVIS_VAULT_MODO=vps nel servizio; senza, tutto resta in locale.
  JARVIS_VAULT_MODO          «locale» (default) | «vps»
  JARVIS_VAULT_CHIAVI_DIR    cartella delle chiavi in file, separata dai dati (vps: <cartella>/../.jarvis-vault-chiavi)
  JARVIS_VAULT_URL_PUBBLICO  l'indirizzo https del tuo sito (vps): il ritorno di Google è <url>/api/vault/google/callback
  JARVIS_VAULT_BROWSER_PORTE JSON {"nome": porta DevTools} dei Chrome che gli agenti possono usare (o «browser» in config.json)
  JARVIS_VAULT_NOTIFICA      comando che avvisa il proprietario di una richiesta di uso (default: strumenti/notifica.py manda)
In più, nel modo vps: avvolgimento «servizio» (le sole chiavi servizio e hmac, cifrate con un file 0400) per i giri
automatici senza nessuno collegato, e l'uso delle voci da parte degli agenti (UsoAgenti: nome della voce → campo del
browser, il valore non torna mai a chi chiede). Sul computer locale, config.json {"remoto": "<url>"} fa della pagina un
rimando al Vault del sito.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

def _ambiente_vault():
    """macOS: il Command Center gira con il python3 di sistema, che di solito non ha «cryptography». L'installatore la
    mette in ~/.jarvis/vault-venv (requirements/vault.txt): se la versione di Python è la stessa, la si usa
    da lì. Su Windows il server gira già nell'ambiente .venv di Jarvis, che la contiene."""
    v = f"python{sys.version_info[0]}.{sys.version_info[1]}"
    casa = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())
    for d in (casa / ".jarvis" / "vault-venv" / "lib" / v / "site-packages",):
        if d.is_dir() and str(d) not in sys.path:
            sys.path.append(str(d))


try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    CRITTO_OK = True
except ImportError:
    _ambiente_vault()
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        CRITTO_OK = True
    except ImportError:   # il Vault resta spento e la pagina dice come installarla
        CRITTO_OK = False

FORMATO = "jarvis-vault"
VERSIONE_FORMATO = 1
GIRI_MINIMI = 600_000
MAX_STORICO = 20
TENTATIVI_PIN = 5
BLOCCO_MINUTI = 5
SVUOTA_APPUNTI_S = 30
SERVIZIO_PORTACHIAVI = "jarvis-vault"

TIPI = ("accesso", "carta", "pin", "variabile", "nota")
CATEGORIE = {"accesso": "Accessi web", "carta": "Carte", "pin": "PIN", "variabile": "Ambiente", "nota": "Note sicure"}
CLASSI = ("servizio", "personale")
SEZIONI_GENERICHE = ["Lavoro", "Personale", "Famiglia", "Casa", "Soldi", "Altro"]


def file_sezioni():
    """Le regole delle sezioni: vault-sezioni.json accanto a questo file (il TUO, fuori da git) se c'è, altrimenti
    l'esempio generico vault-sezioni.esempio.json. Si copia l'esempio e lo si cambia: l'aggiornamento non lo tocca."""
    qui = Path(__file__).resolve().parent
    for nome in ("vault-sezioni.json", "vault-sezioni.esempio.json"):
        if (qui / nome).is_file():
            return qui / nome
    return None


def _leggi_sezioni():
    f = file_sezioni()
    if not f:
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sezioni_partenza():
    """Le sezioni del Vault appena creato (dal file delle sezioni, altrimenti quelle generiche)."""
    d = _leggi_sezioni()
    if isinstance(d, dict):
        d = d.get("sezioni_partenza") or []
    if isinstance(d, list) and d and all(isinstance(x, str) for x in d):
        return [x[:200] for x in d][:50]
    return list(SEZIONI_GENERICHE)


METODI = ("password", "google", "apple", "microsoft", "sso", "passkey")
DUE_FA = ("nessuno", "totp", "sms", "mail", "push", "passkey", "chiave")
DESTINAZIONI = ("nessuna", "prova", "vero")

# Per ogni tipo: i campi, se sono segreti, e se il «Mostra» vuole uno sblocco a parte (frase o PIN ogni volta).
CAMPI = {
    "accesso": {"link": 0, "domini": 0, "utente": 0, "mail": 0, "password": 1, "metodo": 0, "account_collegato": 0,
                "due_fa": 0, "due_fa_dove": 0, "due_fa_chi": 0, "codici_recupero": 2, "note": 1},
    "carta": {"intestatario": 0, "circuito": 0, "numero": 1, "scadenza_mese": 0, "scadenza_anno": 0, "cvv": 2,
              "pin_carta": 2, "banca": 0, "iban": 1, "assistenza": 0, "limite": 0, "tre_ds": 0, "colore": 0,
              "note": 1},
    "pin": {"uso": 0, "codice": 1, "note": 1},
    "variabile": {"nome": 0, "valore": 1, "destinazione": 0, "alias": 0, "descrizione": 0, "riuso": 0, "servizi": 0, "note": 1},
    "nota": {"testo": 1},
}
NOME_VARIABILE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CARTELLE_VIETATE = ("/library/cloudstorage/", "onedrive", "obsidian", "icloud", "dropbox", "google drive",
                    "mobile documents")


class ErroreVault(Exception):
    """Errore da mostrare nella pagina. Il testo non contiene MAI un valore."""

    def __init__(self, testo, codice=400, **extra):
        super().__init__(testo)
        self.codice = codice
        self.extra = extra


# ===================================================================================================== percorsi

def _casa():
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())


def cartella():
    if os.environ.get("JARVIS_VAULT_DIR"):
        return Path(os.environ["JARVIS_VAULT_DIR"]).expanduser()
    if sys.platform == "darwin":
        return _casa() / "Library" / "Application Support" / "Jarvis" / "vault"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or _casa()) / "Jarvis" / "vault"
    return _casa() / ".jarvis-vault"


def file_vault():
    return cartella() / "vault.json"


def file_vero():
    return Path(os.environ.get("JARVIS_VAULT_ENV_VERO") or (_casa() / ".env.jarvis")).expanduser()


def file_prova():
    return Path(os.environ.get("JARVIS_VAULT_ENV_PROVA") or (cartella() / "prova" / "env.jarvis.prova")).expanduser()


def modo_vps():
    return os.environ.get("JARVIS_VAULT_MODO", "mac").strip().lower() == "vps"


def cartella_chiavi():
    """Dove stanno le chiavi in file (modo «file» del Portachiavi). Nel modo vps una cartella DIVERSA dai dati."""
    if os.environ.get("JARVIS_VAULT_CHIAVI_DIR"):
        return Path(os.environ["JARVIS_VAULT_CHIAVI_DIR"]).expanduser()
    if modo_vps():
        return cartella().parent / ".jarvis-vault-chiavi"
    return cartella()


def url_pubblico():
    return (os.environ.get("JARVIS_VAULT_URL_PUBBLICO") or "").strip().rstrip("/")


def _config():
    try:
        c = json.loads((cartella() / "config.json").read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def scrittura_vera_accesa():
    """L'interruttore: SOLO config.json, scritto a mano dal proprietario. La pagina non lo può cambiare."""
    return _config().get("scrittura_file_vero") is True


def _profilo():
    """Il frontmatter del profilo dell'assistente (profilo-jarvis.md), o {}. I segnaposto {{...}} non valgono."""
    qui = Path(__file__).resolve().parent.parent
    candidati = [os.environ.get("JARVIS_VAULT_PROFILO"), qui / "profilo-jarvis.md",      # macOS
                 qui / "utente.json"]                                                     # Windows (cartella installata)
    for c in candidati:
        if not c:
            continue
        try:
            testo = Path(c).read_text(encoding="utf-8")
        except OSError:
            continue
        if str(c).endswith(".json"):
            try:
                d = json.loads(testo)
                return {k: v for k, v in d.items() if isinstance(v, str) and v and "@@" not in v} if isinstance(d, dict) else {}
            except ValueError:
                continue
        campi = {}
        for m in re.finditer(r"^([a-z_]+):\s*([^\n]*)$", testo.split("\n---", 1)[0], re.M):
            v = m.group(2).strip()
            if v and "{{" not in v:
                campi[m.group(1)] = v
        return campi
    return {}


def nome_assistente():
    """Il nome dell'assistente dal profilo («nome_assistente», poi «name»), con la maiuscola. Senza: «l'assistente»."""
    p = _profilo()
    n = p.get("nome_assistente") or p.get("assistente") or p.get("name") or ""
    return (n[:1].upper() + n[1:]) if n else "l'assistente"


def nome_proprietario():
    """Come l'assistente chiama il proprietario («chiamami» nel profilo). Senza: «il proprietario»."""
    p = _profilo()
    return p.get("chiamami") or p.get("nome") or "il proprietario"


def controlla_cartella(p=None):
    """Il Vault rifiuta di vivere in un repo git, in OneDrive/iCloud/Dropbox o nel vault di Obsidian."""
    p = Path(p or cartella()).expanduser()
    vero = p.resolve() if p.exists() else (p.parent.resolve() / p.name)
    testo = (str(p) + "|" + str(vero)).lower() + "/"
    for vietata in CARTELLE_VIETATE:
        if vietata in testo:
            raise ErroreVault(f"Il Vault non può stare in una cartella sincronizzata ({vietata.strip('/')}).", 500)
    for su in [vero, *vero.parents]:
        if (su / ".git").exists():
            raise ErroreVault("Il Vault non può stare dentro un repository git.", 500)
        if (su / ".obsidian").is_dir():
            raise ErroreVault("Il Vault non può stare dentro un vault di Obsidian.", 500)


def _prepara_cartella():
    d = cartella()
    controlla_cartella(d)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


# ===================================================================================================== cifratura

def _b64(b):
    return base64.b64encode(b).decode()


def _unb64(s):
    return base64.b64decode(s.encode() if isinstance(s, str) else s)


def _giri():
    if os.environ.get("JARVIS_VAULT_PROVA") == "1" and os.environ.get("JARVIS_VAULT_GIRI"):
        return max(1000, int(os.environ["JARVIS_VAULT_GIRI"]))
    return GIRI_MINIMI


def deriva(segreto: str, sale: bytes, giri: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", segreto.encode("utf-8"), sale, giri, 32)


def combina(k_frase: bytes, k_disp: bytes, etichetta: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"jarvis-vault/" + etichetta.encode()).derive(k_frase + k_disp)


def cifra(chiave: bytes, dati: bytes, aad: bytes) -> str:
    iv = os.urandom(12)
    return _b64(bytes([1]) + iv + AESGCM(chiave).encrypt(iv, dati, aad))


def decifra(chiave: bytes, blob: str, aad: bytes) -> bytes:
    raw = _unb64(blob)
    if len(raw) < 1 + 12 + 16 or raw[0] != 1:
        raise ValueError("formato del blob sconosciuto")
    return AESGCM(chiave).decrypt(raw[1:13], raw[13:], aad)


def impronta(chiave_hmac: bytes, valore) -> str:
    """Impronta di un valore: HMAC-SHA256 con una chiave del Vault (non sha256 nudo: un valore corto non si indovina)."""
    if valore is None:
        return ""
    return hmac.new(chiave_hmac, str(valore).encode("utf-8"), hashlib.sha256).hexdigest()


# ===================================================================================================== portachiavi

def _dpapi(dati: bytes, proteggi: bool) -> bytes:
    """Windows: CryptProtectData / CryptUnprotectData (crypt32.dll, ambito dell'utente) con ctypes, senza librerie.
    Il blob si apre solo dallo stesso account di Windows. Fuori da Windows alza OSError."""
    if sys.platform != "win32":
        raise OSError("DPAPI esiste solo su Windows")
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    firma = [ctypes.POINTER(BLOB), wintypes.LPCWSTR, ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p,
             wintypes.DWORD, ctypes.POINTER(BLOB)]
    crypt32.CryptProtectData.argtypes = firma
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.POINTER(BLOB),
                                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    ingresso, _b1 = blob(dati)
    entropia, _b2 = blob(b"jarvis-vault/dispositivo")
    uscita = BLOB()
    NIENTE_FINESTRE = 0x01                              # CRYPTPROTECT_UI_FORBIDDEN
    if proteggi:
        ok = crypt32.CryptProtectData(ctypes.byref(ingresso), "Jarvis Vault", ctypes.byref(entropia), None, None,
                                      NIENTE_FINESTRE, ctypes.byref(uscita))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(ingresso), None, ctypes.byref(entropia), None, None,
                                        NIENTE_FINESTRE, ctypes.byref(uscita))
    if not ok:
        raise OSError(f"DPAPI non riuscita (errore {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(uscita.pbData, uscita.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(uscita.pbData, ctypes.c_void_p))


_DPAPI_OK = {"v": None}


def dpapi_disponibile():
    """True se DPAPI funziona qui (prova andata e ritorno, una volta per processo)."""
    if _DPAPI_OK["v"] is None:
        try:
            _DPAPI_OK["v"] = _dpapi(_dpapi(b"prova", True), False) == b"prova"
        except Exception:  # noqa: BLE001
            _DPAPI_OK["v"] = False
    return _DPAPI_OK["v"]


def _togli_sola_lettura(f: Path):
    """Windows: un file 0400 ha l'attributo «sola lettura» e os.replace/unlink falliscono. Lo si toglie prima."""
    try:
        if f.exists():
            os.chmod(f, 0o600)
    except OSError:
        pass


class Portachiavi:
    """La chiave del dispositivo.
    - macOS: Portachiavi via `security` (il valore passa da stdin di `security -i`, mai nella riga di comando).
    - Windows: file con la chiave protetta da DPAPI (si apre solo dal tuo account di Windows).
    - Ripiego («file», o Windows senza DPAPI): file con i permessi del solo utente nella cartella del Vault. La chiave del
      Vault resta derivata ANCHE dalla password (PBKDF2 600 000 giri): il file da solo non basta. La pagina lo segnala."""

    def __init__(self):
        scelto = os.environ.get("JARVIS_VAULT_PORTACHIAVI")
        if scelto:
            self.modo = scelto
        elif modo_vps():
            self.modo = "file"
        elif sys.platform == "darwin":
            self.modo = "login"
        elif sys.platform == "win32":
            self.modo = "dpapi"
        else:
            self.modo = "file"

    @property
    def debole(self):
        # nel modo vps il file è la scelta voluta (cartella delle chiavi separata, 0400): la pagina lo spiega a parte
        if modo_vps():
            return False
        if self.modo == "dpapi":
            return not dpapi_disponibile()
        return self.modo == "file"

    @property
    def nome(self):
        if self.modo == "dpapi":
            return "DPAPI di Windows" if dpapi_disponibile() else "file protetto (ripiego)"
        if self.modo == "file":
            return "file protetto" if modo_vps() else "file protetto (ripiego)"
        return "Portachiavi di macOS"

    def _coda(self):
        return [] if self.modo == "login" else [self.modo]

    @staticmethod
    def _file(conto):
        return cartella_chiavi() / f"dispositivo-{conto}.chiave"

    @staticmethod
    def _file_dpapi(conto):
        return cartella_chiavi() / f"dispositivo-{conto}.dpapi"

    @staticmethod
    def scrivi_file_chiave(f: Path, chiave: bytes, testo=None):
        """Chiave in un file 0400 in una cartella 0700 (fuori da git e dalle cartelle sincronizzate: controlla_cartella)."""
        d = f.parent
        controlla_cartella(d)
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        tmp = d / f".{f.name}.{secrets.token_hex(4)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as h:
            h.write(testo if testo is not None else _b64(chiave))
        os.chmod(tmp, 0o400)
        _togli_sola_lettura(f)
        _togli_sola_lettura(tmp)            # Windows: os.replace con il file d'origine in sola lettura fallisce
        os.replace(tmp, f)
        try:
            os.chmod(f, 0o400)
        except OSError:
            pass

    def leggi(self, conto: str):
        if self.modo == "dpapi":
            fd = self._file_dpapi(conto)
            if fd.exists():
                try:
                    return _dpapi(_unb64(fd.read_text().strip()), False)
                except (OSError, ValueError):
                    return None
            f = self._file(conto)                       # ripiego usato quando DPAPI non c'era
            return _unb64(f.read_text().strip()) if f.exists() else None
        if self.modo == "file":
            f = self._file(conto)
            return _unb64(f.read_text().strip()) if f.exists() else None
        r = subprocess.run(["security", "find-generic-password", "-a", conto, "-s", SERVIZIO_PORTACHIAVI, "-w",
                            *self._coda()], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        try:
            return bytes.fromhex(r.stdout.strip())
        except ValueError:
            return None

    def scrivi(self, conto: str, chiave: bytes):
        if self.modo == "dpapi":
            if dpapi_disponibile():
                self.scrivi_file_chiave(self._file_dpapi(conto), chiave, testo=_b64(_dpapi(chiave, True)))
                _togli_sola_lettura(self._file(conto))
                try:
                    self._file(conto).unlink()
                except OSError:
                    pass
            else:
                self.scrivi_file_chiave(self._file(conto), chiave)
            if self.leggi(conto) != chiave:
                raise ErroreVault("Il portachiavi di Windows non ha salvato la chiave del Vault.", 500)
            return
        if self.modo == "file":
            self.scrivi_file_chiave(self._file(conto), chiave)
            return
        coda = (" " + shlex.quote(self.modo)) if self.modo != "login" else ""
        comando = (f"add-generic-password -U -a {shlex.quote(conto)} -s {SERVIZIO_PORTACHIAVI} "
                   f"-l {shlex.quote('Jarvis Vault (chiave del dispositivo)')} -w {chiave.hex()}{coda}\n")
        try:
            r = subprocess.run(["security", "-i"], input=comando, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            raise ErroreVault("Il Portachiavi di macOS non risponde: sbloccalo (o rispondi alla finestra) e riprova.", 503)
        if r.returncode != 0 or self.leggi(conto) != chiave:
            raise ErroreVault("Il Portachiavi di macOS non ha salvato la chiave del Vault.", 500)

    def togli(self, conto: str):
        if self.modo in ("file", "dpapi"):
            for f in (self._file(conto), self._file_dpapi(conto)):
                _togli_sola_lettura(f)
                try:
                    f.unlink()
                except OSError:
                    pass
            return
        subprocess.run(["security", "delete-generic-password", "-a", conto, "-s", SERVIZIO_PORTACHIAVI,
                        *self._coda()], capture_output=True, timeout=20)


# ===================================================================================================== lucchetto

class Lucchetto:
    """Lucchetto per un file (.env.jarvis, vault.json): «<file>.lock» creato in modo esclusivo. Chi lo trova più
    vecchio di 30 s lo toglie. Un altro programma che scrive lo stesso file può usare lo stesso protocollo."""
    VECCHIO_S = 30

    def __init__(self, file, chi="vault", attesa=10.0):
        self.lock = Path(str(file) + ".lock")
        self.chi = chi
        self.attesa = attesa
        self.firma = None

    def __enter__(self):
        fine = time.monotonic() + self.attesa
        self.firma = f"{os.getpid()} {socket.gethostname()} {time.time():.3f} {self.chi} {secrets.token_hex(4)}"
        while True:
            try:
                fd = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as h:
                    h.write(self.firma)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > self.VECCHIO_S:
                        via = Path(f"{self.lock}.vecchio-{os.getpid()}-{secrets.token_hex(3)}")
                        os.replace(self.lock, via)
                        via.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > fine:
                    raise ErroreVault("Il file è occupato da un altro programma: riprova fra poco.", 423)
                time.sleep(0.03)

    def __exit__(self, *a):
        try:
            if self.lock.read_text() == self.firma:
                self.lock.unlink()
        except OSError:
            pass


def scrivi_atomico(file: Path, testo: str, modo=0o600):
    tmp = file.with_name(f".{file.name}.tmp-{os.getpid()}-{secrets.token_hex(3)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, modo)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(testo)
            h.flush()
            os.fsync(h.fileno())
        os.chmod(tmp, modo)
        os.replace(tmp, file)
    finally:
        if tmp.exists():
            tmp.unlink()


# ===================================================================================================== file .env

def leggi_valore_env(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        try:
            return "".join(shlex.split(raw, posix=True))
        except ValueError:
            return raw.strip("'\"")
    return raw


def scrivi_valore_env(valore: str) -> str:
    return valore if re.fullmatch(r"[A-Za-z0-9_./:@%+,=-]*", valore) else shlex.quote(valore)


def analizza_env(testo: str) -> dict:
    """{nome: (riga 1-based, valore)}. Vince la prima riga che combacia (come posta.py e account.js)."""
    out = {}
    for n, riga in enumerate(testo.splitlines(), 1):
        s = riga.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if NOME_VARIABILE.match(k) and k not in out:
            out[k] = (n, leggi_valore_env(v))
    return out


def imposta_in_env(testo: str, nome: str, valore) -> str:
    """Sostituisce la prima riga di «nome» (e toglie i doppioni) o aggiunge in fondo; valore None = toglie."""
    righe = testo.split("\n")
    out, fatto = [], False
    for r in righe:
        s = r.strip()
        s2 = s[7:].lstrip() if s.startswith("export ") else s
        if s2.startswith(nome + "=") and not s.startswith("#"):
            if not fatto and valore is not None:
                pre = "export " if s.startswith("export ") else ""
                out.append(f"{pre}{nome}={scrivi_valore_env(valore)}")
            fatto = True
            continue
        out.append(r)
    if not fatto and valore is not None:
        while out and out[-1] == "":
            out.pop()
        out += [f"{nome}={scrivi_valore_env(valore)}", ""]
    return "\n".join(out)


def _backup_env(f: Path):
    if not f.exists():
        return None
    d = f.parent / f"backup-env-{time.strftime('%Y%m%d')}"
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o700)
    dest = d / f"{f.name}.{time.strftime('%H%M%S')}-{int(time.time() * 1e6) % 1_000_000:06d}-{secrets.token_hex(4)}"
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as h:
        h.write(f.read_bytes())
    vecchi = sorted(d.glob(f.name + ".*"))
    for v in vecchi[:-50]:
        v.unlink()
    return dest


def scrivi_variabile_su_file(f: Path, nome: str, valore, chi="vault"):
    """Con lucchetto comune, backup, scrittura atomica 0600. Il chiamante decide se il file è scrivibile."""
    if not NOME_VARIABILE.match(nome):
        raise ErroreVault("Nome di variabile non valido.")
    f.parent.mkdir(parents=True, exist_ok=True)
    with Lucchetto(f, chi=chi):
        testo = f.read_text(encoding="utf-8") if f.exists() else ""
        _backup_env(f)
        scrivi_atomico(f, imposta_in_env(testo, nome, valore))


# ===================================================================================================== barriere

NOMI_DEL_VAULT = re.compile(r"(\.vault$|^vault-esportazione-.*\.json$|^(dispositivo|servizio)-.*\.(chiave|dpapi)$|"
                            r"^env\.jarvis\.prova$|^usi\.jsonl$|^\.env\.jarvis(\.lock)?$|^vault-sezioni\.json$|"
                            r"^google-client\.json$|^\.jarvis-vault|password.*\.csv$|^chrome.*password.*\.csv$)", re.I)


def file_del_vault(nome: str, contenuto: bytes = b"") -> str:
    """Il motivo per cui un file non deve uscire (repo, cartelle sincronizzate, memoria), o "" se è pulito. Usato dal
    gancio pre-commit (strumenti/ganci_git.py → «vault_cc.py barriera-git»). Non legge né restituisce valori."""
    base = Path(nome).name
    if NOMI_DEL_VAULT.search(base):
        return "nome da file del Vault o dei segreti"
    if base.lower().endswith((".json", ".jsonl")) and contenuto:
        try:
            d = json.loads(contenuto[:5_000_000])
        except ValueError:
            d = None
        if isinstance(d, dict) and d.get("formato") in (FORMATO, "jarvis-vault-esportazione"):
            return "contenuto del Vault (formato jarvis-vault)"
    return ""


def _barriera_git():
    """Per il pre-commit: controlla i file messi in stage (la versione nell'indice, non quella sul disco)."""
    nomi = subprocess.run(["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], capture_output=True,
                          check=True).stdout.decode("utf-8", "replace").split("\0")
    trovati = []
    for n in filter(None, nomi):
        blob = b""
        if n.lower().endswith((".json", ".jsonl")):
            blob = subprocess.run(["git", "show", f":{n}"], capture_output=True).stdout
        motivo = file_del_vault(n, blob)
        if motivo:
            trovati.append(f"{n}  ({motivo})")
    return trovati


# ===================================================================================================== il Vault

def _ora():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _nuovo_id():
    return "v_" + secrets.token_hex(8)


_PAROLE = sorted(set("""acqua alba albero alce ampio anello angolo anima anno ape arco argento aria arpa asse astro atlante
attimo aula avena azzurro baffo bagno balena banco barca basso baule becco bello bianco bimbo bisonte bocca bosco botte
bravo brezza bruco buio burro busta cactus caldo calma campo cane canto capra carta casa castoro cavallo cedro cento cervo
chiave cielo cigno cima cinque cipolla circo cobra coda colle colore conca corda corvo costa cotone crema croce cubo cuore
curva dado danza delfino dente diamante dieci dito dolce domani drago duna eco edera elmo erba esca estate falco faro
farfalla felce ferro festa fiamma fico filo fiore fiume foca foglia fonte forno forte foto fragola freccia fresco frutto
fumo fungo gallo gamba gatto gelo gemma giallo giglio giorno gioco giraffa goccia gomma grano grillo grotta guanto gufo
isola lago lama lampo lana larice latte lavanda legno leone lepre libro lima limone linea lince lino lontra luce luna
lupo madre mago mandorla mare marmo masso mela melone menta mese miele mille mirtillo molla mondo monte mora mosca mulino
muro musica nave nebbia neve nido noce nodo notte nove nube nuoto oasi occhio olio olmo ombra onda oro orso ortica
ostrica otto pace padre palla palma pane panda passo pasta pecora penna pepe pera perla pesce piano pietra pino pioggia
piuma polpo ponte porta prato prugna pugno quarzo radice ragno rame rana remo riccio riso roccia rosa rovo rubino ruota
sabbia sale salice salmone sasso scala scoglio sedia segno seme sette sole spiga stella storia sughero tavolo tazza tela
tigre topo torre trave treno tulipa uovo uva valle vaso vela vento verde vetro viola vite volpe zaino zebra zucca""".split()))[:256]
PAROLE_RECUPERO = 24                 # 24 parole da 256 = 192 bit


def _codice_recupero():
    return " ".join(secrets.choice(_PAROLE) for _ in range(PAROLE_RECUPERO))


def _normalizza_codice(c: str) -> str:
    parole = re.findall(r"[a-z]+", str(c or "").lower())
    if len(parole) != PAROLE_RECUPERO or any(p not in _PAROLE for p in parole):
        return ""
    return " ".join(parole)


def _normalizza_email(e) -> str:
    e = str(e or "").strip().lower()
    return e if re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[a-z0-9-]{2,24}", e) else ""


def forza_password(p: str) -> str:
    """Solo un suggerimento (nessun blocco oltre ai 12 caratteri): debole, media, buona."""
    p = str(p or "")
    classi = sum(bool(re.search(x, p)) for x in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    punti = len(p) + 4 * (classi - 1) - (8 if len(set(p)) < len(p) / 2 else 0)
    return "buona" if punti >= 22 else "media" if punti >= 15 else "debole"


class Vault:
    """Lo stato del file e le sessioni aperte. Un solo oggetto per processo (VAULT, in fondo).

    Accesso (niente «frase segreta» a parte: email e password, Google facoltativo):
    - email e password: la password (con l'email nel sale) passa da PBKDF2 600 000 giri ed è combinata con la chiave
      del dispositivo (Portachiavi). Avvolgimento «frase» (nome interno rimasto per compatibilità del formato).
    - Google: Google dà l'IDENTITÀ (token ID verificato), non una chiave. I dati restano cifrati con la chiave del
      dispositivo: avvolgimento «dispositivo», che il server apre SOLO dopo un token Google valido dell'account
      consentito. Con «google_con_password» acceso l'avvolgimento «dispositivo» non c'è e serve anche la password.
    - Codice di recupero di 24 parole (mostrato una volta), PIN breve per lo sblocco rapido.
    """

    def __init__(self):
        self.mutex = threading.RLock()
        self.sessioni = {}           # token -> {chiavi, ultimo}
        self.errori = 0              # tentativi sbagliati di fila (password, Google, recupero)
        self.fermo_fino = 0.0
        self.portachiavi = Portachiavi()
        self.biglietti = {}          # biglietto Google -> {email, sub, creato, scade}

    # ---------------------------------------------------------------- file
    def esiste(self):
        return file_vault().exists()

    def _leggi(self):
        try:
            d = json.loads(file_vault().read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ErroreVault("Il Vault non è ancora stato creato.", 404)
        if d.get("formato") != FORMATO or d.get("versione") != VERSIONE_FORMATO:
            raise ErroreVault("Formato del Vault sconosciuto.", 500)
        d.setdefault("account", {})
        d["avvolte"].setdefault("dispositivo", None)
        d["avvolte"].setdefault("servizio", None)
        return d

    # ---------------------------------------------------------------- modo vps: avvolgimento «servizio»
    # Le sole chiavi «servizio» e «hmac», cifrate con un file 0400 in cartella_chiavi(). Servono ai giri automatici e
    # all'uso delle voci di servizio senza nessuno collegato. La chiave «personale» qui non c'è mai.
    def _file_servizio(self, d):
        return cartella_chiavi() / f"servizio-{d['id']}.chiave"

    def _avvolgi_servizio(self, d, chiavi):
        """Crea (o rifà) l'avvolgimento «servizio». Solo nel modo vps. True se d è cambiato."""
        if not modo_vps():
            return False
        f = self._file_servizio(d)
        if f.exists():
            k = _unb64(f.read_text().strip())
        else:
            k = os.urandom(32)
            Portachiavi.scrivi_file_chiave(f, k)
        dati = json.dumps({"servizio": chiavi["servizio"].hex(), "hmac": chiavi["hmac"].hex()}).encode()
        aad = b"avvolta/servizio/" + d["id"].encode()
        vecchio = d["avvolte"].get("servizio")
        if vecchio:
            try:
                if json.loads(decifra(k, vecchio, aad)) == json.loads(dati):
                    return False
            except Exception:  # noqa: BLE001  (file della chiave cambiato: si rifà)
                pass
        d["avvolte"]["servizio"] = cifra(k, dati, aad)
        return True

    def chiavi_servizio(self):
        """Le chiavi della classe servizio senza sessione (modo vps). Mai la chiave personale."""
        if not modo_vps():
            raise ErroreVault("Le chiavi di servizio senza sblocco esistono solo sulla VPS.", 403)
        d = self._leggi()
        blob = d["avvolte"].get("servizio")
        f = self._file_servizio(d)
        if not blob or not f.exists():
            raise ErroreVault("Le voci di servizio si aprono dopo il primo sblocco del Vault sulla VPS.", 409)
        try:
            dati = json.loads(decifra(_unb64(f.read_text().strip()), blob, b"avvolta/servizio/" + d["id"].encode()))
        except Exception:  # noqa: BLE001
            raise ErroreVault("La chiave di servizio non apre il Vault: sblocca il Vault dal sito per rifarla.", 409)
        return {k: bytes.fromhex(v) for k, v in dati.items()}

    def _salva(self, d, backup_giornaliero=True):
        _prepara_cartella()
        f = file_vault()
        with Lucchetto(f, chi="vault"):
            if backup_giornaliero and f.exists():
                self._backup_file(f"auto-{time.strftime('%Y%m%d')}", se_manca=True)
            d["serie"] = int(d.get("serie", 0)) + 1
            scrivi_atomico(f, json.dumps(d, ensure_ascii=False, indent=1))

    def _backup_file(self, nome, se_manca=False):
        f = file_vault()
        d = cartella() / "backup"
        d.mkdir(exist_ok=True)
        os.chmod(d, 0o700)
        dest = d / f"vault-{nome}.json"
        if se_manca and dest.exists():
            return dest
        scrivi_atomico(dest, f.read_text(encoding="utf-8"))
        for v in sorted(d.glob("vault-*.json"))[:-30]:
            v.unlink()
        return dest

    # ---------------------------------------------------------------- registro degli usi
    def registra(self, azione, id_voce="", campo="", esito="ok"):
        try:
            _prepara_cartella()
            riga = json.dumps({"quando": _ora(), "azione": azione, "id": id_voce, "campo": campo, "esito": esito},
                              ensure_ascii=False)
            fd = os.open(cartella() / "usi.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as h:
                h.write(riga + "\n")
        except (OSError, ErroreVault):
            pass

    def usi(self, id_voce=None, quanti=100):
        try:
            righe = (cartella() / "usi.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for r in reversed(righe):
            try:
                u = json.loads(r)
            except ValueError:
                continue
            if id_voce and u.get("id") != id_voce:
                continue
            out.append(u)
            if len(out) >= quanti:
                break
        return out

    # ---------------------------------------------------------------- tentativi: ritardo crescente
    def _controlla_fermo(self):
        if time.time() < self.fermo_fino:
            resta = int(self.fermo_fino - time.time()) + 1
            raise ErroreVault(f"Troppi tentativi: riprova fra {resta} secondi.", 429, attesa_s=resta)

    def _sbagliato(self):
        """Dal 3° errore di fila: 5 s, 10 s, 20 s… fino a 15 minuti."""
        self.errori += 1
        if self.errori >= 3:
            self.fermo_fino = time.time() + min(900, 5 * 2 ** (self.errori - 3))

    def _giusto(self):
        self.errori = 0
        self.fermo_fino = 0.0

    # ---------------------------------------------------------------- chiavi
    def _conto(self, d):
        return "dispositivo-" + d["id"]

    def _sale_password(self, d):
        return _unb64(d["kdf"]["sale_frase"]) + d["account"].get("email", "").encode()

    def _avvolgi(self, d, chiavi: dict, k_disp: bytes, password=None, pin=None, codice=None, dispositivo=False):
        dati = json.dumps({k: v.hex() for k, v in chiavi.items()}).encode()
        giri = d["kdf"]["giri"]
        if password is not None:
            k = combina(deriva(password, self._sale_password(d), giri), k_disp, "frase")
            d["avvolte"]["frase"] = cifra(k, dati, b"avvolta/frase/" + d["id"].encode())
        if pin is not None:
            k = combina(deriva(pin, _unb64(d["kdf"]["sale_pin"]), giri), k_disp, "pin")
            d["avvolte"]["pin"] = cifra(k, dati, b"avvolta/pin/" + d["id"].encode())
            d["pin_errori"] = 0
        if codice is not None:
            k = deriva(_normalizza_codice(codice), _unb64(d["kdf"]["sale_recupero"]), giri)
            d["avvolte"]["recupero"] = cifra(k, dati, b"avvolta/recupero/" + d["id"].encode())
        if dispositivo:
            k = combina(b"\0" * 32, k_disp, "dispositivo")
            d["avvolte"]["dispositivo"] = cifra(k, dati, b"avvolta/dispositivo/" + d["id"].encode())

    def _k_disp(self, d):
        k_disp = self.portachiavi.leggi(self._conto(d))
        if not k_disp:
            raise ErroreVault("Manca la chiave del dispositivo nel portachiavi del sistema: usa le 24 parole di recupero.", 409,
                              serve_recupero=True)
        return k_disp

    def _svolgi(self, d, modo, segreto=""):
        giri = d["kdf"]["giri"]
        aad = f"avvolta/{modo}/".encode() + d["id"].encode()
        blob = d["avvolte"].get(modo)
        if not blob:
            raise ErroreVault("Questo modo di sblocco non è attivo.", 400)
        if modo == "recupero":
            norm = _normalizza_codice(segreto)
            if not norm:
                return None
            k = deriva(norm, _unb64(d["kdf"]["sale_recupero"]), giri)
        elif modo == "dispositivo":
            k = combina(b"\0" * 32, self._k_disp(d), "dispositivo")
        elif modo == "frase":
            k = combina(deriva(segreto, self._sale_password(d), giri), self._k_disp(d), "frase")
        else:
            k = combina(deriva(segreto, _unb64(d["kdf"]["sale_pin"]), giri), self._k_disp(d), "pin")
        try:
            dati = json.loads(decifra(k, blob, aad))
        except Exception:  # noqa: BLE001  (tag sbagliato = segreto sbagliato)
            return None
        return {k2: bytes.fromhex(v) for k2, v in dati.items()}

    def _verifica(self, d, password=None, pin=None, biglietto=None):
        """Conferma a parte (CVV, PIN della carta, codici di recupero, cambi di accesso): password, PIN o un accesso
        Google appena fatto (biglietto di meno di 2 minuti) dell'account consentito."""
        if password:
            return bool(d["avvolte"].get("frase")) and self._svolgi(d, "frase", password) is not None
        if pin and d["avvolte"].get("pin"):
            ok = self._svolgi(d, "pin", pin) is not None
            self._conta_pin(d, ok)
            return ok
        if biglietto:
            b = self._usa_biglietto(biglietto, massimo_s=120)
            return bool(b) and self._google_ammesso(d, b)
        return False

    def _conta_pin(self, d, ok):
        if ok:
            if d.get("pin_errori"):
                d["pin_errori"] = 0
                self._salva(d, backup_giornaliero=False)
            return
        d["pin_errori"] = int(d.get("pin_errori", 0)) + 1
        if d["pin_errori"] >= TENTATIVI_PIN:
            d["avvolte"]["pin"] = None
            self.registra("pin-spento", esito="troppi errori")
        self._salva(d, backup_giornaliero=False)

    # ---------------------------------------------------------------- Google: biglietti e lista consentita
    def nuovo_biglietto(self, identita):
        b = secrets.token_urlsafe(24)
        self.biglietti = {k: v for k, v in self.biglietti.items() if v["scade"] > time.time()}
        self.biglietti[b] = {**identita, "creato": time.time(), "scade": time.time() + 300}
        return b

    def _usa_biglietto(self, b, massimo_s=300):
        v = self.biglietti.pop(str(b or ""), None)
        if not v or v["scade"] < time.time() or time.time() - v["creato"] > massimo_s:
            return None
        return v

    @staticmethod
    def _consentiti():
        return [x for x in (_normalizza_email(e) for e in (_config().get("google_consentiti") or [])) if x]

    def _google_ammesso(self, d, ident):
        """Lista in config.json («google_consentiti») se non è vuota; altrimenti solo l'account proprietario
        (quello che ha creato il Vault con Google o che è stato collegato), riconosciuto dal «sub» di Google."""
        consentiti = self._consentiti()
        acc = d.get("account", {}) if d else {}
        if consentiti:
            return ident["email"] in consentiti
        if acc.get("google_sub"):
            return ident["sub"] == acc["google_sub"]
        return False

    # ---------------------------------------------------------------- creazione, sblocco, blocco
    def crea(self, email=None, password=None, biglietto=None):
        """Con email e password, oppure con un biglietto Google (identità verificata). Restituisce la sessione e le
        24 parole di recupero (mostrate UNA volta)."""
        if not CRITTO_OK:
            raise ErroreVault("Manca la libreria «cryptography»: il Vault non può partire.", 500)
        ident = None
        if biglietto:
            ident = self._usa_biglietto(biglietto)
            if not ident:
                raise ErroreVault("Accesso Google scaduto: riprova.", 401)
            consentiti = self._consentiti()
            if consentiti and ident["email"] not in consentiti:
                self.registra("creato", campo="google", esito="account non consentito")
                raise ErroreVault("Questo account Google non è nella lista consentita del Vault.", 403)
            email = ident["email"]
        else:
            email = _normalizza_email(email)
            if not email:
                raise ErroreVault("Scrivi un indirizzo email valido.")
            if len(str(password or "")) < 12:
                raise ErroreVault("La password deve avere almeno 12 caratteri.")
        with self.mutex:
            if self.esiste():
                raise ErroreVault("Il Vault esiste già.", 409)
            _prepara_cartella()
            d = {"formato": FORMATO, "versione": VERSIONE_FORMATO, "id": secrets.token_hex(8), "creato": _ora(),
                 "account": {"email": email, "google_sub": ident["sub"] if ident else None,
                             "google_con_password": False},
                 "kdf": {"alg": "pbkdf2-sha256+hkdf", "giri": _giri(), "sale_frase": _b64(os.urandom(16)),
                         "sale_pin": _b64(os.urandom(16)), "sale_recupero": _b64(os.urandom(16))},
                 "avvolte": {"frase": None, "pin": None, "recupero": None, "dispositivo": None}, "pin_errori": 0,
                 "impostazioni": None, "voci": {}, "storico": {}, "serie": 0}
            chiavi = {"servizio": os.urandom(32), "personale": os.urandom(32), "hmac": os.urandom(32)}
            k_disp = os.urandom(32)
            self.portachiavi.scrivi(self._conto(d), k_disp)
            codice = _codice_recupero()
            self._avvolgi(d, chiavi, k_disp, password=None if ident else str(password), codice=codice,
                          dispositivo=bool(ident))
            self._scrivi_impostazioni(d, chiavi, {"sezioni": sezioni_partenza(), "categorie": {},
                                                  "sincronia": {"prova": {}, "vero": {}}})
            self._avvolgi_servizio(d, chiavi)
            self._salva(d, backup_giornaliero=False)
            self.registra("creato", campo="google" if ident else "password")
            return {"sessione": self._apri_sessione(chiavi), "codice_recupero": codice}

    def _apri_sessione(self, chiavi):
        token = secrets.token_urlsafe(32)
        self.sessioni[token] = {"chiavi": chiavi, "ultimo": time.time()}
        return token

    def sblocca(self, email=None, password=None, pin=None, biglietto=None):
        with self.mutex:
            self._controlla_fermo()
            d = self._leggi()
            if pin:
                if not d["avvolte"].get("pin"):
                    raise ErroreVault("Il PIN non è attivo su questo Vault.", 400)
                chiavi = self._svolgi(d, "pin", str(pin))
                self._conta_pin(d, chiavi is not None)
                if chiavi is None:
                    self.registra("sblocco", campo="pin", esito="sbagliato")
                    rimasti = TENTATIVI_PIN - int(d.get("pin_errori", 0))
                    raise ErroreVault(f"PIN sbagliato. Tentativi rimasti: {max(0, rimasti)}." if d["avvolte"].get("pin")
                                      else "PIN sbagliato troppe volte: il PIN è spento, usa email e password o Google.",
                                      401)
                modo = "pin"
            elif biglietto:
                ident = self._usa_biglietto(biglietto)
                if not ident or not self._google_ammesso(d, ident):
                    self._sbagliato()
                    self.registra("sblocco", campo="google", esito="account non consentito" if ident else "scaduto")
                    raise ErroreVault("Questo account Google non può aprire il Vault." if ident else
                                      "Accesso Google scaduto: riprova.", 403 if ident else 401)
                if d["avvolte"].get("dispositivo"):
                    chiavi = self._svolgi(d, "dispositivo")
                elif not password:
                    raise ErroreVault("Con Google serve anche la password di questo Vault.", 401, serve_password=True)
                else:
                    chiavi = self._svolgi(d, "frase", str(password)) if d["avvolte"].get("frase") else None
                modo = "google"
            else:
                if not d["avvolte"].get("frase"):
                    raise ErroreVault("Questo Vault non ha una password: usa «Accedi con Google» o il PIN.", 400)
                chiavi = (self._svolgi(d, "frase", str(password or ""))
                          if _normalizza_email(email) == d["account"].get("email") else None)
                modo = "password"
            if chiavi is None:
                if modo != "pin":
                    self._sbagliato()
                self.registra("sblocco", campo=modo, esito="sbagliato")
                raise ErroreVault("Email o password sbagliate." if modo == "password" else "Accesso non riuscito.", 401)
            self._giusto()
            if self._avvolgi_servizio(d, chiavi):
                self._salva(d, backup_giornaliero=False)
            self.registra("sblocco", campo=modo)
            return {"sessione": self._apri_sessione(chiavi)}

    def recupera(self, codice, nuova_password=None):
        """24 parole → nuova chiave del dispositivo (Portachiavi perso) e, se data, una password nuova."""
        if nuova_password and len(str(nuova_password)) < 12:
            raise ErroreVault("La password deve avere almeno 12 caratteri.")
        with self.mutex:
            self._controlla_fermo()
            d = self._leggi()
            con_google = bool(d["account"].get("google_sub"))
            if not nuova_password and not con_google:
                raise ErroreVault("Scegli una password nuova.")
            chiavi = self._svolgi(d, "recupero", codice)
            if chiavi is None:
                self._sbagliato()
                self.registra("recupero", esito="parole sbagliate")
                raise ErroreVault("Le 24 parole non sono giuste.", 401)
            self._giusto()
            k_disp = os.urandom(32)
            self.portachiavi.scrivi(self._conto(d), k_disp)
            d["avvolte"]["pin"] = None
            if nuova_password:
                self._avvolgi(d, chiavi, k_disp, password=str(nuova_password))
            else:
                d["avvolte"]["frase"] = None
            if con_google and not d["account"].get("google_con_password"):
                self._avvolgi(d, chiavi, k_disp, dispositivo=True)
            else:
                d["avvolte"]["dispositivo"] = None
            self._avvolgi_servizio(d, chiavi)
            self._salva(d)
            self.registra("recupero")
            return {"sessione": self._apri_sessione(chiavi)}

    def blocca(self, token=None):
        with self.mutex:
            if token:
                self.sessioni.pop(token, None)
            else:
                self.sessioni.clear()
        self.registra("blocco")

    def sessione(self, token, tocca=True):
        """Le chiavi della sessione, o 401. Ogni uso (non di sfondo) sposta il blocco automatico di BLOCCO_MINUTI:
        le richieste automatiche della pagina (X-Vault-Sfondo: 1, l'osservatore ogni 5 s) non lo spostano."""
        with self.mutex:
            s = self.sessioni.get(token or "")
            minuti = int(_config().get("blocco_minuti") or BLOCCO_MINUTI)
            if not s or time.time() - s["ultimo"] > minuti * 60:
                self.sessioni.pop(token or "", None)
                raise ErroreVault("Vault bloccato.", 401, bloccato=True)
            if tocca:
                s["ultimo"] = time.time()
            return s["chiavi"]

    def resta_s(self, token):
        s = self.sessioni.get(token or "")
        minuti = int(_config().get("blocco_minuti") or BLOCCO_MINUTI)
        return max(0, int(minuti * 60 - (time.time() - s["ultimo"]))) if s else 0

    def imposta_pin(self, chiavi, conferma, pin):
        pin = str(pin or "")
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ErroreVault("Il PIN è fatto di 4-8 cifre.")
        with self.mutex:
            d = self._leggi()
            if not self._verifica(d, **conferma):
                raise ErroreVault("Conferma sbagliata: serve la password o un nuovo accesso con Google.", 401)
            self._avvolgi(d, chiavi, self._k_disp(d), pin=pin)
            self._salva(d)
            self.registra("pin-impostato")

    def imposta_password(self, chiavi, conferma, nuova):
        """Nuova password, o la prima per chi ha creato il Vault con Google. Conferma: password attuale o Google."""
        if len(str(nuova or "")) < 12:
            raise ErroreVault("La password deve avere almeno 12 caratteri.")
        with self.mutex:
            d = self._leggi()
            if not self._verifica(d, **conferma):
                raise ErroreVault("Conferma sbagliata: serve la password attuale o un nuovo accesso con Google.", 401)
            self._avvolgi(d, chiavi, self._k_disp(d), password=str(nuova))
            self._salva(d)
            self.registra("password-impostata")

    def google_con_password(self, chiavi, conferma, acceso):
        """Seconda protezione: con Google serve anche la password (toglie l'avvolgimento «dispositivo»)."""
        with self.mutex:
            d = self._leggi()
            if not self._verifica(d, **conferma):
                raise ErroreVault("Conferma sbagliata.", 401)
            if acceso:
                if not d["avvolte"].get("frase"):
                    raise ErroreVault("Imposta prima una password.")
                d["avvolte"]["dispositivo"] = None
            else:
                if not d["account"].get("google_sub"):
                    raise ErroreVault("Questo Vault non ha un account Google collegato.")
                self._avvolgi(d, chiavi, self._k_disp(d), dispositivo=True)
            d["account"]["google_con_password"] = bool(acceso)
            self._salva(d)
            self.registra("google-con-password", campo="acceso" if acceso else "spento")
            return {"google_con_password": bool(acceso)}

    def collega_google(self, chiavi, biglietto):
        """Collega un account Google a un Vault creato con email e password."""
        with self.mutex:
            d = self._leggi()
            ident = self._usa_biglietto(biglietto)
            if not ident:
                raise ErroreVault("Accesso Google scaduto: riprova.", 401)
            consentiti = self._consentiti()
            if (consentiti and ident["email"] not in consentiti) or \
                    (not consentiti and ident["email"] != d["account"].get("email")):
                raise ErroreVault("Questo account Google non è consentito: deve essere l'email del Vault "
                                  "o stare nella lista consentita.", 403)
            d["account"]["google_sub"] = ident["sub"]
            if not d["account"].get("google_con_password"):
                self._avvolgi(d, chiavi, self._k_disp(d), dispositivo=True)
            self._salva(d)
            self.registra("google-collegato")
            return {"google": True}

    def info_account(self):
        """Per la pagina: email (non è un segreto) e modi di accesso attivi. Nessun valore."""
        if not self.esiste():
            return {}
        d = self._leggi()
        a = d["avvolte"]
        return {"email": d["account"].get("email", ""), "password": bool(a.get("frase")), "pin": bool(a.get("pin")),
                "google": bool(d["account"].get("google_sub")),
                "google_con_password": bool(d["account"].get("google_con_password"))}

    # ---------------------------------------------------------------- importazione degli accessi attuali
    @staticmethod
    def _nomi_voce(v):
        return [v["campi"].get("nome", "")] + [x.strip() for x in v["campi"].get("alias", "").split(",") if x.strip()]

    def importa_attuali(self, chiavi):
        """Porta nel Vault le chiavi di ~/.env.jarvis (il file NON si tocca). Regola: stesso valore = UNA voce con tutti
        i nomi come alias. Ripetibile e migrante: una voce già importata che ora è un alias di un'altra si unisce (la
        vecchia diventa «eliminata», annullabile dallo storico) con un backup cifrato del Vault PRIMA; un nome che non
        condivide più il valore esce dagli alias e diventa una voce sua. Restituisce SOLO conteggi."""
        p = piano_import(chiavi, con_valori=True)
        valori = p.pop("_valori")
        k = chiavi["hmac"]
        conti = {"nuove": 0, "aggiornate": 0, "gia_presenti": 0, "unite": 0, "separate": 0, "alias": 0}
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            variabili = [(rec, v) for rec, v in self._tutte(d, chiavi) if v["tipo"] == "variabile"]
            per_nome = {v["campi"].get("nome", ""): (rec, v) for rec, v in variabili}
            per_alias = {}
            for rec, v in variabili:
                for a in self._nomi_voce(v)[1:]:
                    per_alias[a] = (rec, v)
            backup_fatto = False
            sinc = imp["sincronia"].setdefault("vero", {})
            usate = set()                      # id delle voci che restano (destinazione di un gruppo)
            for x in p["voci"]:
                nomi = [x["nome"]] + x["alias"]
                valore = valori.get(x["nome"], "")
                campi = {"nome": x["nome"], "valore": valore, "destinazione": "vero", "alias": ", ".join(x["alias"]),
                         "descrizione": x["descrizione"], "servizi": x["servizio"], "riuso": str(x.get("riuso") or ""),
                         "note": ""}
                conti["alias"] += len(x["alias"])
                # la voce di destinazione: quella col nome canonico, altrimenti una che già porta uno di questi nomi
                cand = [per_nome[n] for n in nomi if n in per_nome and per_nome[n][0]["id"] not in usate]
                cand += [per_alias[n] for n in nomi if n in per_alias and per_alias[n][0]["id"] not in usate]
                dest = cand[0] if cand else None
                if dest:
                    rec, v = dest
                    usate.add(rec["id"])
                    cambi = (impronta(k, v["campi"].get("valore", "")) != impronta(k, valore) or
                             v["campi"].get("nome") != x["nome"] or v["campi"].get("alias", "") != campi["alias"] or
                             v["campi"].get("riuso", "") != campi["riuso"])
                    if cambi:
                        conti["separate"] += len([n for n in self._nomi_voce(v) if n not in nomi])
                        v["campi"].update(campi)
                        v["titolo"] = x["nome"]
                        self._nuova_versione(d, chiavi, rec, v, "import")
                        conti["aggiornate"] += 1
                    else:
                        conti["gia_presenti"] += 1
                    # le altre voci che portano questi nomi si uniscono qui: eliminate (annullabili), backup prima
                    for altro_rec, altro in {id(c[1]): c for c in cand[1:]}.values():
                        if altro_rec["id"] in usate or altro.get("eliminata"):
                            continue
                        if not backup_fatto:
                            self._backup_file(f"prima-unione-{time.strftime('%Y%m%d-%H%M%S')}")
                            backup_fatto = True
                        resto = [n for n in self._nomi_voce(altro) if n not in nomi]
                        if resto:          # porta anche nomi che non sono di questo gruppo: si tolgono solo i nostri
                            altro["campi"]["nome"], altro["campi"]["alias"] = resto[0], ", ".join(resto[1:])
                            altro["titolo"] = resto[0]
                            self._nuova_versione(d, chiavi, altro_rec, altro, "unione")
                        else:
                            altro["eliminata"] = True
                            altro["unita_in"] = rec["id"]
                            self._nuova_versione(d, chiavi, altro_rec, altro, "unione")
                            conti["unite"] += 1
                else:
                    voce = {"tipo": "variabile", "titolo": x["nome"], "classe": "servizio", "sezione": x["sezione"],
                            "tag": x["tag"], "preferito": x["preferito"], "campi": campi, "extra": []}
                    nuovo = self._aggiungi(d, chiavi, self._pulisci(voce), "import")
                    usate.add(nuovo)
                    conti["nuove"] += 1
                if x["sezione"] not in imp["sezioni"]:
                    imp["sezioni"].append(x["sezione"])
                for n in nomi:
                    sinc[n] = impronta(k, valore)
            # nomi rimasti come alias in voci di un altro gruppo (valore cambiato nel file): escono dagli alias
            gruppo_di = {n: x["nome"] for x in p["voci"] for n in [x["nome"]] + x["alias"]}
            for rec, v in variabili:
                if rec["id"] not in usate or v.get("eliminata"):
                    continue
                alias = [a for a in self._nomi_voce(v)[1:] if gruppo_di.get(a, v["campi"]["nome"]) == v["campi"]["nome"]]
                if len(alias) != len(self._nomi_voce(v)) - 1:
                    conti["separate"] += len(self._nomi_voce(v)) - 1 - len(alias)
                    v["campi"]["alias"] = ", ".join(alias)
                    self._nuova_versione(d, chiavi, rec, v, "import")
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
        valori.clear()
        self.registra("importa-attuali", campo=", ".join(f"{a} {b}" for a, b in conti.items()))
        return {**conti, "righe_env": p["righe_env"], "backup_prima": backup_fatto}

    def separa_alias(self, chiavi, id_voce, alias):
        """«Separa un alias»: il nome esce dalla voce unita e diventa una voce sua, con lo stesso valore di adesso.
        Da qui in poi la sincronia di quel nome riguarda SOLO la voce nuova; l'importazione non lo riunisce più
        (elenco «separati» nelle impostazioni cifrate). Annullabile: due versioni nello storico."""
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            if not rec:
                raise ErroreVault("Voce non trovata.", 404)
            v = self._apri(chiavi, rec)
            nomi = self._nomi_voce(v)
            if v["tipo"] != "variabile" or alias not in nomi[1:]:
                raise ErroreVault("Questo nome non è un alias della voce.")
            imp = self._impostazioni(d, chiavi)
            resto = [n for n in nomi[1:] if n != alias]
            v["campi"]["alias"] = ", ".join(resto)
            v["campi"]["riuso"] = str(len(resto) + 1) if v["campi"].get("riuso") and resto else ""
            self._nuova_versione(d, chiavi, rec, v, "separa")
            c = classifica(alias)
            nuova = {"tipo": "variabile", "titolo": alias, "classe": rec["classe"], "sezione": c["sezione"],
                     "tag": c["tag"], "preferito": c["preferito"], "extra": [],
                     "campi": {"nome": alias, "valore": v["campi"].get("valore", ""), "destinazione": v["campi"].get("destinazione", "vero"),
                               "alias": "", "descrizione": c["descrizione"], "servizi": c["servizio"], "riuso": "", "note": ""}}
            id_nuovo = self._aggiungi(d, chiavi, self._pulisci(nuova), "separa")
            sep = imp.setdefault("separati", [])
            if alias not in sep:
                sep.append(alias)
            if nuova["sezione"] not in imp["sezioni"]:
                imp["sezioni"].append(nuova["sezione"])
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
        self.registra("separa-alias", id_voce, alias)
        return {"id": id_voce, "nuova": id_nuovo}

    def _aggiungi(self, d, chiavi, voce, origine):
        id_voce = _nuovo_id()
        rec = {"id": id_voce, "classe": voce["classe"], "versione": 1,
               "dek": cifra(chiavi[voce["classe"]], os.urandom(32), b"dek/" + id_voce.encode())}
        voce.update(creata=_ora(), modificata=_ora(), origine=origine)
        self._chiudi(chiavi, rec, voce)
        d["voci"][id_voce] = rec
        return id_voce

    # ---------------------------------------------------------------- impostazioni (sezioni, categorie, sincronia)
    def _scrivi_impostazioni(self, d, chiavi, imp):
        d["impostazioni"] = cifra(chiavi["servizio"], json.dumps(imp, ensure_ascii=False).encode(),
                                  b"impostazioni/" + d["id"].encode())

    def _impostazioni(self, d, chiavi):
        imp = json.loads(decifra(chiavi["servizio"], d["impostazioni"], b"impostazioni/" + d["id"].encode()))
        imp.setdefault("sezioni", [])
        imp.setdefault("categorie", {})
        imp.setdefault("sincronia", {"prova": {}, "vero": {}})
        return imp

    # ---------------------------------------------------------------- voci
    def _dek(self, chiavi, rec):
        return decifra(chiavi[rec["classe"]], rec["dek"], b"dek/" + rec["id"].encode())

    def _apri(self, chiavi, rec, dati_blob=None, versione=None):
        dek = self._dek(chiavi, rec)
        v = rec["versione"] if versione is None else versione
        return json.loads(decifra(dek, dati_blob or rec["dati"], f"voce/{rec['id']}/{v}".encode()))

    def _chiudi(self, chiavi, rec, voce):
        dek = self._dek(chiavi, rec)
        rec["dati"] = cifra(dek, json.dumps(voce, ensure_ascii=False).encode(),
                            f"voce/{rec['id']}/{rec['versione']}".encode())

    def _tutte(self, d, chiavi, anche_eliminate=False):
        out = []
        for rec in d["voci"].values():
            v = self._apri(chiavi, rec)
            if v.get("eliminata") and not anche_eliminate:
                continue
            out.append((rec, v))
        return out

    @staticmethod
    def _riassunto(rec, v, imp, n_storico=0):
        """Quello che la lista e il dettaglio possono vedere: mai un valore segreto (solo «presente»)."""
        tipo = v["tipo"]
        campi = {}
        for nome, livello in CAMPI[tipo].items():
            val = v["campi"].get(nome)
            if livello:
                campi[nome] = {"segreto": True, "presente": bool(val), "a_parte": livello == 2}
            else:
                campi[nome] = val if val not in (None, "") else ""
        if tipo == "carta":
            num = re.sub(r"\D", "", v["campi"].get("numero") or "")
            campi["ultime4"] = num[-4:] if len(num) >= 8 else ""
        extra = [{"nome": e.get("nome", ""), "segreto": bool(e.get("segreto")),
                  "valore": None if e.get("segreto") else e.get("valore", ""),
                  "presente": bool(e.get("valore"))} for e in v.get("extra", [])]
        return {"id": rec["id"], "versione": rec["versione"], "classe": rec["classe"], "tipo": tipo,
                "categoria": imp["categorie"].get(tipo) or CATEGORIE[tipo], "titolo": v.get("titolo", ""),
                "sezione": v.get("sezione", ""), "tag": v.get("tag", []), "preferito": bool(v.get("preferito")),
                "campi": campi, "extra": extra, "creata": v.get("creata"), "modificata": v.get("modificata"),
                "origine": v.get("origine", "app"), "versioni": 1 + n_storico}

    def elenco(self, chiavi):
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            voci = [self._riassunto(rec, v, imp, len(d["storico"].get(rec["id"], [])))
                    for rec, v in self._tutte(d, chiavi)]
            voci.sort(key=lambda x: (not x["preferito"], x["titolo"].lower()))
            return {"voci": voci, "sezioni": imp["sezioni"],
                    "categorie": {t: imp["categorie"].get(t) or CATEGORIE[t] for t in TIPI},
                    "pin_attivo": bool(d["avvolte"].get("pin"))}

    def _pulisci(self, corpo, vecchia=None):
        """Dal modulo alla voce: tipi controllati; i campi segreti assenti (o «invariato») restano quelli di prima."""
        tipo = corpo.get("tipo") or (vecchia or {}).get("tipo")
        if tipo not in TIPI:
            raise ErroreVault("Tipo di voce sconosciuto.")
        titolo = str(corpo.get("titolo") or "").strip()[:200]
        if not titolo:
            raise ErroreVault("Serve un titolo.")
        classe = corpo.get("classe") or (vecchia or {}).get("classe") or \
            ("servizio" if tipo == "variabile" else "personale")
        if classe not in CLASSI:
            raise ErroreVault("Classe sconosciuta.")
        prima = (vecchia or {}).get("campi", {})
        dati_campi = corpo.get("campi") if isinstance(corpo.get("campi"), dict) else {}
        campi = {}
        for nome, livello in CAMPI[tipo].items():
            if nome in dati_campi and not (isinstance(dati_campi[nome], dict) and dati_campi[nome].get("invariato")):
                val = dati_campi[nome]
                val = "" if val is None else val
                if not isinstance(val, (str, int, float)):
                    raise ErroreVault(f"Campo {nome}: valore non valido.")
                campi[nome] = str(val)[:20000]
            else:
                campi[nome] = prima.get(nome, "")
        if tipo == "accesso":
            if campi["metodo"] and campi["metodo"] not in METODI:
                raise ErroreVault("Metodo di accesso sconosciuto.")
            if campi["due_fa"] and campi["due_fa"] not in DUE_FA:
                raise ErroreVault("Tipo di 2FA sconosciuto.")
            if campi["metodo"] == "google":
                campi["password"] = ""
        if tipo == "variabile":
            if not NOME_VARIABILE.match(campi["nome"]):
                raise ErroreVault("Nome di variabile non valido (lettere, cifre, _).")
            if campi["destinazione"] and campi["destinazione"] not in DESTINAZIONI:
                raise ErroreVault("Destinazione sconosciuta.")
        if tipo == "carta" and campi["numero"] and not re.fullmatch(r"[\d ]{8,23}", campi["numero"]):
            raise ErroreVault("Numero della carta: solo cifre.")
        extra_vecchi = {e.get("nome"): e for e in (vecchia or {}).get("extra", [])}
        extra = []
        if "extra" not in corpo and vecchia:
            corpo = {**corpo, "extra": [{"nome": e.get("nome"), "segreto": e.get("segreto"), "valore": {"invariato": True}}
                                        for e in vecchia.get("extra", [])]}
        for e in (corpo.get("extra") or [])[:30]:
            if not isinstance(e, dict) or not str(e.get("nome") or "").strip():
                continue
            nome = str(e["nome"]).strip()[:80]
            val = e.get("valore")
            if val is None or (isinstance(val, dict) and val.get("invariato")):
                val = extra_vecchi.get(nome, {}).get("valore", "")
            extra.append({"nome": nome, "valore": str(val)[:20000], "segreto": bool(e.get("segreto"))})
        tag = sorted({str(t).strip().lstrip("#")[:40] for t in (corpo.get("tag") or []) if str(t).strip()})[:20]
        return {"tipo": tipo, "titolo": titolo, "classe": classe, "sezione": str(corpo.get("sezione") or "")[:200],
                "tag": tag, "preferito": bool(corpo.get("preferito")), "campi": campi, "extra": extra}

    def salva(self, chiavi, corpo, origine="app"):
        """Nuova voce o nuova versione. «versione_base» = la versione che la pagina ha letto: se è cambiata, 409."""
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            id_voce = corpo.get("id")
            if id_voce:
                rec = d["voci"].get(id_voce)
                if not rec:
                    raise ErroreVault("Voce non trovata.", 404)
                if corpo.get("versione_base") is not None and int(corpo["versione_base"]) != rec["versione"]:
                    raise ErroreVault("La voce è cambiata nel frattempo: ricarica.", 409, conflitto=True)
                vecchia = self._apri(chiavi, rec)
                nuova = self._pulisci(corpo, vecchia)
                if nuova["tipo"] == "variabile" and nuova["campi"].get("alias") and \
                        nuova["campi"].get("valore") != vecchia["campi"].get("valore") and corpo.get("conferma_alias") is not True:
                    nomi = [nuova["campi"]["nome"]] + [x.strip() for x in nuova["campi"]["alias"].split(",") if x.strip()]
                    raise ErroreVault("Questo valore è usato da più nomi: conferma.", 409, serve_conferma_alias=True,
                                      cambiera_in=nomi, file_vero_scrivibile=scrittura_vera_accesa())
                if nuova["classe"] != rec["classe"]:
                    raise ErroreVault("La classe di una voce non si cambia: creane una nuova.")
                nuova["creata"] = vecchia.get("creata")
                self._nuova_versione(d, chiavi, rec, nuova, origine)
                azione = "modifica"
            else:
                nuova = self._pulisci(corpo)
                nuova["creata"] = _ora()
                id_voce = _nuovo_id()
                rec = {"id": id_voce, "classe": nuova["classe"], "versione": 1}
                rec["dek"] = cifra(chiavi[nuova["classe"]], os.urandom(32), b"dek/" + id_voce.encode())
                nuova["modificata"] = _ora()
                nuova["origine"] = origine
                self._chiudi(chiavi, rec, nuova)
                d["voci"][id_voce] = rec
                azione = "nuova"
            if nuova["sezione"] and nuova["sezione"] not in imp["sezioni"]:
                imp["sezioni"].append(nuova["sezione"])
                self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
            self.registra(azione, id_voce)
            esito = {"id": id_voce, "versione": rec["versione"]}
            if nuova["tipo"] == "variabile":
                esito["sincronia"] = self._sincronizza_voce(chiavi, id_voce, spinta=True)
            return esito

    def _nuova_versione(self, d, chiavi, rec, nuova, origine):
        st = d["storico"].setdefault(rec["id"], [])
        st.append({"versione": rec["versione"], "dati": rec["dati"], "quando": _ora(), "origine": origine})
        del st[:-MAX_STORICO]
        rec["versione"] += 1
        nuova["modificata"] = _ora()
        nuova["origine"] = origine
        self._chiudi(chiavi, rec, nuova)

    def voce(self, chiavi, id_voce):
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            if not rec:
                raise ErroreVault("Voce non trovata.", 404)
            imp = self._impostazioni(d, chiavi)
            r = self._riassunto(rec, self._apri(chiavi, rec), imp, len(d["storico"].get(id_voce, [])))
            r["usi"] = self.usi(id_voce, 10)
            return r

    def mostra(self, chiavi, id_voce, campo, conferma=None, azione="mostra"):
        """Il solo punto che restituisce un valore. Campi «a parte» (CVV, PIN carta, codici): frase o PIN ogni volta."""
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            if not rec:
                raise ErroreVault("Voce non trovata.", 404)
            v = self._apri(chiavi, rec)
            if campo.startswith("extra:"):
                nome = campo[6:]
                e = next((x for x in v.get("extra", []) if x.get("nome") == nome), None)
                if not e:
                    raise ErroreVault("Campo non trovato.", 404)
                valore = e.get("valore", "")
            else:
                livello = CAMPI[v["tipo"]].get(campo)
                if livello is None:
                    raise ErroreVault("Campo non trovato.", 404)
                if livello == 2 and not self._verifica(d, **(conferma or {})):
                    self.registra(azione, id_voce, campo, "sblocco a parte sbagliato")
                    raise ErroreVault("Per questo campo serve di nuovo la frase o il PIN.", 403, serve_conferma=True)
                valore = v["campi"].get(campo, "")
            self.registra(azione, id_voce, campo)
            return {"valore": valore, "svuota_dopo_s": SVUOTA_APPUNTI_S}

    def elimina(self, chiavi, id_voce):
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            if not rec:
                raise ErroreVault("Voce non trovata.", 404)
            v = self._apri(chiavi, rec)
            v["eliminata"] = True
            self._nuova_versione(d, chiavi, rec, v, "app")
            self._salva(d)
            self.registra("elimina", id_voce)
            return {"id": id_voce, "versione": rec["versione"]}

    def storico(self, chiavi, id_voce):
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            if not rec:
                raise ErroreVault("Voce non trovata.", 404)
            v = self._apri(chiavi, rec)
            righe = [{"versione": rec["versione"], "quando": v.get("modificata"), "origine": v.get("origine", "app"),
                      "attuale": True, "eliminata": bool(v.get("eliminata"))}]
            for s in reversed(d["storico"].get(id_voce, [])):
                try:                          # data e origine della versione stessa (non del cambio che l'ha sostituita)
                    vv = self._apri(chiavi, rec, s["dati"], s["versione"])
                except Exception:  # noqa: BLE001
                    vv = {}
                righe.append({"versione": s["versione"], "quando": vv.get("modificata") or s["quando"],
                              "origine": vv.get("origine") or "app", "attuale": False,
                              "eliminata": bool(vv.get("eliminata"))})
            return {"id": id_voce, "versioni": righe}

    def annulla(self, chiavi, id_voce, versione=None):
        """Rimette la versione di prima (o quella scelta) come versione nuova: anche l'annulla si può annullare."""
        with self.mutex:
            d = self._leggi()
            rec = d["voci"].get(id_voce)
            st = d["storico"].get(id_voce, [])
            if not rec or not st:
                raise ErroreVault("Non c'è una versione precedente.", 404)
            scelta = st[-1] if versione is None else next((s for s in st if s["versione"] == int(versione)), None)
            if not scelta:
                raise ErroreVault("Versione non trovata.", 404)
            vecchia = self._apri(chiavi, rec, scelta["dati"], scelta["versione"])
            self._nuova_versione(d, chiavi, rec, vecchia, "annulla")
            self._salva(d)
            self.registra("annulla", id_voce, str(scelta["versione"]))
            esito = {"id": id_voce, "versione": rec["versione"]}
            if vecchia["tipo"] == "variabile" and not vecchia.get("eliminata"):
                esito["sincronia"] = self._sincronizza_voce(chiavi, id_voce, spinta=True)
            return esito

    def sezione(self, chiavi, corpo):
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            nome = str(corpo.get("nome") or "").strip()[:200]
            if corpo.get("azione") == "togli":
                usata = any(v.get("sezione") == nome for _r, v in self._tutte(d, chiavi))
                if usata:
                    raise ErroreVault("La sezione ha delle voci: spostale prima.")
                imp["sezioni"] = [s for s in imp["sezioni"] if s != nome]
            elif corpo.get("azione") == "rinomina":
                nuovo = str(corpo.get("nuovo") or "").strip()[:200]
                if not nuovo:
                    raise ErroreVault("Serve il nome nuovo.")
                imp["sezioni"] = [nuovo if s == nome else s for s in imp["sezioni"]]
                for rec, v in self._tutte(d, chiavi):
                    if v.get("sezione") == nome:
                        v["sezione"] = nuovo
                        self._nuova_versione(d, chiavi, rec, v, "app")
            else:
                if not nome:
                    raise ErroreVault("Serve un nome.")
                if nome not in imp["sezioni"]:
                    imp["sezioni"].append(nome)
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
            return {"sezioni": imp["sezioni"]}

    def categoria(self, chiavi, tipo, nome):
        if tipo not in TIPI:
            raise ErroreVault("Categoria sconosciuta.")
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            nome = str(nome or "").strip()[:60]
            if nome:
                imp["categorie"][tipo] = nome
            else:
                imp["categorie"].pop(tipo, None)
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
            return {"categorie": {t: imp["categorie"].get(t) or CATEGORIE[t] for t in TIPI}}

    # ---------------------------------------------------------------- esportazione, importazione, backup
    def esporta(self, chiavi, frase_export):
        frase_export = str(frase_export or "")
        if len(frase_export) < 12:
            raise ErroreVault("La frase dell'esportazione deve avere almeno 12 caratteri.")
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            voci = [{"id": rec["id"], **v} for rec, v in self._tutte(d, chiavi)]
            sale = os.urandom(16)
            giri = _giri()
            pacco = json.dumps({"voci": voci, "sezioni": imp["sezioni"], "categorie": imp["categorie"]},
                               ensure_ascii=False).encode()
            file = {"formato": "jarvis-vault-esportazione", "versione": 1, "creato": _ora(),
                    "kdf": {"alg": "pbkdf2-sha256", "giri": giri, "sale": _b64(sale)},
                    "dati": cifra(deriva(frase_export, sale, giri), pacco, b"jarvis-vault-esportazione/1")}
            self.registra("esporta", campo=str(len(voci)))
            return {"nome": f"vault-esportazione-{time.strftime('%Y%m%d-%H%M')}.json",
                    "contenuto": json.dumps(file, indent=1)}

    def importa(self, chiavi, contenuto, frase_export):
        try:
            file = json.loads(contenuto) if isinstance(contenuto, str) else contenuto
            assert file.get("formato") == "jarvis-vault-esportazione"
            k = deriva(str(frase_export or ""), _unb64(file["kdf"]["sale"]), int(file["kdf"]["giri"]))
        except Exception:  # noqa: BLE001
            raise ErroreVault("Il file non è un'esportazione del Vault.")
        try:
            pacco = json.loads(decifra(k, file["dati"], b"jarvis-vault-esportazione/1"))
        except Exception:  # noqa: BLE001
            raise ErroreVault("Frase dell'esportazione sbagliata.", 401)
        nuove = saltate = 0
        with self.mutex:
            d = self._leggi()
            for v in pacco.get("voci", []):
                if v.get("id") in d["voci"]:
                    saltate += 1
                    continue
                try:
                    pulita = self._pulisci(v)
                except ErroreVault:
                    saltate += 1
                    continue
                id_voce = v.get("id") if re.fullmatch(r"v_[0-9a-f]{16}", str(v.get("id"))) else _nuovo_id()
                rec = {"id": id_voce, "classe": pulita["classe"], "versione": 1,
                       "dek": cifra(chiavi[pulita["classe"]], os.urandom(32), b"dek/" + id_voce.encode())}
                pulita.update(creata=v.get("creata") or _ora(), modificata=_ora(), origine="import")
                self._chiudi(chiavi, rec, pulita)
                d["voci"][id_voce] = rec
                nuove += 1
            imp = self._impostazioni(d, chiavi)
            for s in pacco.get("sezioni", []):
                if s not in imp["sezioni"]:
                    imp["sezioni"].append(s)
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
        self.registra("importa", campo=f"{nuove} nuove, {saltate} saltate")
        return {"nuove": nuove, "saltate": saltate}

    def backup(self):
        with self.mutex:
            self._leggi()
            dest = self._backup_file(time.strftime("%Y%m%d-%H%M%S"))
        self.registra("backup")
        return {"file": str(dest).replace(str(_casa()), "~"), "cifrato": True}

    # ---------------------------------------------------------------- ambiente («simbiosi» con .env.jarvis)
    def _file_di(self, destinazione):
        if destinazione == "prova":
            return file_prova(), True
        if destinazione == "vero":
            return file_vero(), scrittura_vera_accesa()
        return None, False

    @staticmethod
    def _leggi_env(f):
        try:
            return analizza_env(f.read_text(encoding="utf-8"))
        except OSError:
            return None

    def _stato_variabile(self, chiavi, imp, nome, valore, destinazione, cache=None):
        f, scrivibile = self._file_di(destinazione)
        if not f:
            return {"stato": "nessuna"}
        if cache is not None:
            if str(f) not in cache:
                cache[str(f)] = self._leggi_env(f)
            righe = cache[str(f)]
        else:
            righe = self._leggi_env(f)
        k = chiavi["hmac"]
        ultimo = imp["sincronia"].setdefault(destinazione, {}).get(nome)
        if righe is None:
            return {"stato": "file assente", "scrivibile": scrivibile}
        riga = righe.get(nome)
        i_file = impronta(k, riga[1]) if riga else ""
        i_app = impronta(k, valore)
        if riga and i_file == i_app:
            stato = "allineata"
        elif not riga:
            stato = "assente nel file"
        elif ultimo and i_app == ultimo:
            stato = "cambiata nel file"
        elif ultimo and i_file == ultimo:
            stato = "da scrivere"
        elif ultimo:
            stato = "conflitto"
        else:
            stato = "diversa"
        return {"stato": stato, "scrivibile": scrivibile, "riga": riga[0] if riga else None,
                "impronta_file": i_file[:8], "impronta_app": i_app[:8]}

    def _sincronizza_voce(self, chiavi, id_voce, spinta=False, tieni=None):
        """Un giro di sincronia per una variabile. spinta=True: l'app è appena cambiata (scrive se il file non è
        cambiato a sua volta). tieni="file"|"app": scelta del proprietario su un conflitto."""
        d = self._leggi()
        rec = d["voci"].get(id_voce)
        if not rec:
            raise ErroreVault("Voce non trovata.", 404)
        v = self._apri(chiavi, rec)
        if v["tipo"] != "variabile" or v.get("eliminata"):
            return {"stato": "nessuna"}
        imp = self._impostazioni(d, chiavi)
        nome, valore, dest = v["campi"]["nome"], v["campi"]["valore"], v["campi"].get("destinazione") or "nessuna"
        st = self._stato_variabile(chiavi, imp, nome, valore, dest)
        f, scrivibile = self._file_di(dest)
        sinc = imp["sincronia"].setdefault(dest, {}) if f else {}
        k = chiavi["hmac"]
        cambiato = False
        if st["stato"] == "allineata":
            if sinc.get(nome) != impronta(k, valore):
                sinc[nome] = impronta(k, valore)
                cambiato = True
        elif st["stato"] == "cambiata nel file" or (tieni == "file" and st["stato"] in ("conflitto", "diversa")):
            valore_file = self._leggi_env(f)[nome][1]
            v["campi"]["valore"] = valore_file
            self._nuova_versione(d, chiavi, rec, v, "file")
            sinc[nome] = impronta(k, valore_file)
            cambiato = True
            self.registra("dal-file", id_voce, nome)
        elif scrivibile and (st["stato"] in ("da scrivere", "assente nel file", "file assente") or
                             (tieni == "app" and st["stato"] in ("conflitto", "diversa"))):
            scrivi_variabile_su_file(f, nome, valore)
            sinc[nome] = impronta(k, valore)
            cambiato = True
            self.registra("sul-file", id_voce, f"{nome}@{dest}")
        if cambiato:
            self._scrivi_impostazioni(d, chiavi, imp)
            self._salva(d)
        return self._stato_variabile(chiavi, imp, nome, v["campi"]["valore"], dest)

    def ambiente(self, chiavi, giro=True):
        """Il quadro: righe del file vero (solo nomi e impronte), della copia di prova, e lo stato di ogni variabile
        del Vault. giro=True fa anche un giro di sincronia (l'«osservatore»: la pagina lo chiama ogni 5 s).
        Un solo passaggio: file letti una volta; _sincronizza_voce solo per le variabili che hanno qualcosa da fare
        (con 200 variabili importate il giro resta di pochi millisecondi)."""
        da_fare = ("cambiata nel file", "da scrivere", "assente nel file", "file assente")
        with self.mutex:
            d = self._leggi()
            imp = self._impostazioni(d, chiavi)
            cache, stati, variabili = {}, {}, []
            for rec, v in self._tutte(d, chiavi):
                if v["tipo"] != "variabile":
                    continue
                variabili.append((rec, v))
                c = v["campi"]
                stati[rec["id"]] = self._stato_variabile(chiavi, imp, c.get("nome", ""), c.get("valore", ""),
                                                         c.get("destinazione") or "nessuna", cache)
            if giro:
                for rec, v in variabili:
                    st = stati[rec["id"]]
                    dest = v["campi"].get("destinazione") or "nessuna"
                    sinc = imp["sincronia"].get(dest, {})
                    if st["stato"] in da_fare and (st["stato"] == "cambiata nel file" or st.get("scrivibile")) or \
                            (st["stato"] == "allineata" and sinc.get(v["campi"].get("nome")) is None):
                        stati[rec["id"]] = self._sincronizza_voce(chiavi, rec["id"])
            k = chiavi["hmac"]
            nel_vault = {}
            d = self._leggi()
            for rec, v in self._tutte(d, chiavi):
                if v["tipo"] == "variabile":
                    for n in [v["campi"].get("nome", "")] + [x.strip() for x in v["campi"].get("alias", "").split(",") if x.strip()]:
                        nel_vault.setdefault(n, []).append((rec, v))

            def quadro(f, scrivibile):
                righe = self._leggi_env(f)
                elenco = []
                for nome, (n, val) in sorted((righe or {}).items()):
                    voci = nel_vault.get(nome, [])
                    uguale = any(impronta(k, v["campi"]["valore"]) == impronta(k, val) for _r, v in voci)
                    elenco.append({"nome": nome, "riga": n, "impronta": impronta(k, val)[:8],
                                   "vuota": val == "", "nel_vault": "importata" if uguale else
                                   ("diversa" if voci else "nuova nel file"), "id": voci[0][0]["id"] if voci else None})
                conti = {s: sum(1 for x in elenco if x["nel_vault"] == s) for s in ("importata", "diversa", "nuova nel file")}
                return {"percorso": str(f).replace(str(_casa()), "~"), "presente": righe is not None,
                        "scrivibile": scrivibile, "righe": elenco, "quante": len(elenco), "conti": conti}

            return {"vero": quadro(file_vero(), scrittura_vera_accesa()), "prova": quadro(file_prova(), True),
                    "scrittura_file_vero": scrittura_vera_accesa(),
                    "variabili": {i: s for i, s in stati.items()}}

    def mostra_file(self, chiavi, quale, nome):
        f = file_vero() if quale == "vero" else file_prova() if quale == "prova" else None
        if not f or not NOME_VARIABILE.match(str(nome or "")):
            raise ErroreVault("Richiesta non valida.")
        righe = self._leggi_env(f)
        if not righe or nome not in righe:
            raise ErroreVault("La variabile non c'è nel file.", 404)
        self.registra("mostra-file", campo=f"{nome}@{quale}")
        return {"valore": righe[nome][1], "svuota_dopo_s": SVUOTA_APPUNTI_S}

    def importa_da_file(self, chiavi, nome, sezione=""):
        """Porta una variabile della COPIA DI PROVA nel Vault (le chiavi del file vero passano da «Importa le chiavi
        di .env.jarvis», sempre in sola lettura sul file)."""
        righe = self._leggi_env(file_prova()) or {}
        if nome not in righe:
            raise ErroreVault("La variabile non c'è nella copia di prova.", 404)
        sez = sezione or ("Servizi" if "__" not in nome else nome.split("__", 1)[0])
        return self.salva(chiavi, {"tipo": "variabile", "titolo": nome, "classe": "servizio", "sezione": sez,
                                   "campi": {"nome": nome, "valore": righe[nome][1], "destinazione": "prova"}},
                          origine="file")

    def risolvi(self, chiavi, id_voce, tieni):
        if tieni not in ("file", "app"):
            raise ErroreVault("Scegli «file» o «app».")
        with self.mutex:
            st = self._sincronizza_voce(chiavi, id_voce, tieni=tieni)
        self.registra("conflitto-risolto", id_voce, tieni)
        return st


# ===================================================================================================== Google (OIDC)
# Accesso con Google: OAuth 2.0 «authorization code» con PKCE (S256), stato e nonce casuali, scope minimi
# «openid email», redirect loopback http://127.0.0.1:<porta>/api/vault/google/callback. Il token ID si verifica qui:
# firma RS256 con le chiavi pubbliche dell'emittente (JWKS), «iss», «aud» = ID client, «exp», «iat», «nonce»,
# «email_verified». ID e segreto del client sono del PROPRIETARIO (ognuno crea il suo client OAuth: docs/wiki/Vault.md)
# e si leggono da ~/.env.jarvis (VAULT__GOOGLE_CLIENT_ID, VAULT__GOOGLE_CLIENT_SECRET) oppure dal file locale
# <cartella del Vault>/google-client.json ({"client_id": "...", "client_secret": "..."}): mai nel repo, mai nei log,
# mai nelle risposte. Senza, il pulsante «Accedi con Google» resta spento e dice perché.
# Prove: con JARVIS_VAULT_PROVA=1 e JARVIS_VAULT_OIDC_EMITTENTE=http://127.0.0.1:<porta> si usa un emittente finto
# (prova_vault_google.py) con gli stessi controlli.

GOOGLE = {"emittenti": ("https://accounts.google.com", "accounts.google.com"),
          "auth": "https://accounts.google.com/o/oauth2/v2/auth",
          "token": "https://oauth2.googleapis.com/token",
          "jwks": "https://www.googleapis.com/oauth2/v3/certs"}
CHIAVI_CLIENT = ("VAULT__GOOGLE_CLIENT_ID", "VAULT__GOOGLE_CLIENT_SECRET")


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def oidc_conf():
    """Endpoint e client. Restituisce anche «pronto» e il motivo, per il pulsante della pagina."""
    finto = os.environ.get("JARVIS_VAULT_OIDC_EMITTENTE") if os.environ.get("JARVIS_VAULT_PROVA") == "1" else None
    if finto:
        base = finto.rstrip("/")
        ep = {"emittenti": (base,), "auth": base + "/auth", "token": base + "/token", "jwks": base + "/jwks"}
    else:
        ep = dict(GOOGLE)
    try:
        env = analizza_env(file_vero().read_text(encoding="utf-8"))
    except OSError:
        env = {}
    cid = (env.get(CHIAVI_CLIENT[0]) or (0, ""))[1]
    seg = (env.get(CHIAVI_CLIENT[1]) or (0, ""))[1]
    if not cid:
        try:
            locale = json.loads((cartella() / "google-client.json").read_text(encoding="utf-8"))
            cid, seg = str(locale.get("client_id") or ""), str(locale.get("client_secret") or "")
        except (OSError, ValueError, AttributeError):
            pass
    motivo = "" if cid else ("Accesso con Google spento: serve un tuo client OAuth di Google (guida in docs/wiki/Vault.md, "
                             "«Accesso con Google»). Intanto usa email e password.")
    return {**ep, "client_id": cid, "client_secret": seg, "pronto": bool(cid), "motivo": motivo, "finto": bool(finto)}


_JWKS = {"url": None, "chiavi": {}, "quando": 0.0}


def _jwks(url):
    if _JWKS["url"] != url or time.time() - _JWKS["quando"] > 3600:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read())
        _JWKS.update(url=url, chiavi={k["kid"]: k for k in d.get("keys", []) if k.get("kty") == "RSA"}, quando=time.time())
    return _JWKS["chiavi"]


def verifica_id_token(token: str, conf: dict, nonce: str) -> dict:
    """Controlla il token ID e restituisce {email, sub}. Ogni rifiuto alza ErroreVault con un motivo SENZA il token."""
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    try:
        testa_b, corpo_b, firma_b = token.split(".")
        testa = json.loads(_unb64url(testa_b))
        corpo = json.loads(_unb64url(corpo_b))
        firma = _unb64url(firma_b)
    except Exception:  # noqa: BLE001
        raise ErroreVault("Token Google non leggibile.", 401)
    if testa.get("alg") != "RS256":
        raise ErroreVault("Token Google: algoritmo non ammesso.", 401)
    chiavi = _jwks(conf["jwks"])
    if testa.get("kid") not in chiavi:
        _JWKS["quando"] = 0.0                       # chiavi ruotate: si rilegge una volta
        chiavi = _jwks(conf["jwks"])
    k = chiavi.get(testa.get("kid"))
    if not k:
        raise ErroreVault("Token Google: chiave di firma sconosciuta.", 401)
    pub = rsa.RSAPublicNumbers(int.from_bytes(_unb64url(k["e"]), "big"), int.from_bytes(_unb64url(k["n"]), "big")).public_key()
    try:
        pub.verify(firma, f"{testa_b}.{corpo_b}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception:  # noqa: BLE001
        raise ErroreVault("Token Google: firma non valida.", 401)
    ora = time.time()
    aud = corpo.get("aud")
    if corpo.get("iss") not in conf["emittenti"]:
        raise ErroreVault("Token Google: emittente sbagliato.", 401)
    if (aud if isinstance(aud, list) else [aud]).count(conf["client_id"]) != 1 or \
            (isinstance(aud, list) and corpo.get("azp") != conf["client_id"]):
        raise ErroreVault("Token Google: destinatario (aud) sbagliato.", 401)
    if not isinstance(corpo.get("exp"), (int, float)) or corpo["exp"] < ora - 60:
        raise ErroreVault("Token Google scaduto.", 401)
    if isinstance(corpo.get("iat"), (int, float)) and corpo["iat"] > ora + 300:
        raise ErroreVault("Token Google dal futuro.", 401)
    if not nonce or not hmac.compare_digest(str(corpo.get("nonce") or ""), nonce):
        raise ErroreVault("Token Google: nonce sbagliato.", 401)
    if corpo.get("email_verified") not in (True, "true"):
        raise ErroreVault("L'email di questo account Google non è verificata.", 403)
    email = _normalizza_email(corpo.get("email"))
    if not email or not corpo.get("sub"):
        raise ErroreVault("Token Google senza email.", 401)
    return {"email": email, "sub": str(corpo["sub"])}


class AccessoGoogle:
    """I flussi in corso (stato → verifier, nonce, redirect) e gli esiti pronti per la pagina (stato → biglietto)."""

    def __init__(self, vault):
        self.vault = vault
        self.flussi = {}
        self.esiti = {}
        self.mutex = threading.Lock()

    def inizio(self, redirect_uri):
        conf = oidc_conf()
        if not conf["pronto"]:
            raise ErroreVault(conf["motivo"], 503, manca_client=True)
        self.vault._controlla_fermo()
        stato, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        sfida = _b64url(hashlib.sha256(verifier.encode()).digest())
        with self.mutex:
            self.flussi = {k: v for k, v in self.flussi.items() if v["scade"] > time.time()}
            self.flussi[stato] = {"verifier": verifier, "nonce": nonce, "redirect": redirect_uri, "scade": time.time() + 600}
        from urllib.parse import urlencode
        q = urlencode({"client_id": conf["client_id"], "response_type": "code", "scope": "openid email",
                       "redirect_uri": redirect_uri, "state": stato, "nonce": nonce, "code_challenge": sfida,
                       "code_challenge_method": "S256", "prompt": "select_account"})
        return {"url": f"{conf['auth']}?{q}", "stato": stato}

    def callback(self, query):
        """La pagina che Google apre alla fine. Restituisce HTML; l'esito la pagina del Vault lo legge con «esito»."""
        stato = (query.get("state") or [""])[0]
        with self.mutex:
            flusso = self.flussi.pop(stato, None)
        if not flusso or flusso["scade"] < time.time():
            return self._pagina("Accesso non valido o scaduto: riprova dal Vault.")
        if (query.get("error") or [""])[0]:
            self._esito(stato, {"errore": "Accesso con Google annullato."})
            return self._pagina("Accesso annullato.")
        conf = oidc_conf()
        try:
            import urllib.request
            from urllib.parse import urlencode
            dati = urlencode({"code": (query.get("code") or [""])[0], "client_id": conf["client_id"],
                              "client_secret": conf["client_secret"], "redirect_uri": flusso["redirect"],
                              "grant_type": "authorization_code", "code_verifier": flusso["verifier"]}).encode()
            r = urllib.request.Request(conf["token"], data=dati, method="POST",
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(r, timeout=15) as x:
                risposta = json.loads(x.read())
            ident = verifica_id_token(str(risposta.get("id_token") or ""), conf, flusso["nonce"])
        except ErroreVault as e:
            self.vault._sbagliato()
            self.vault.registra("google", esito=str(e))
            self._esito(stato, {"errore": str(e), "codice": e.codice})
            return self._pagina(str(e))
        except Exception as e:  # noqa: BLE001  (solo il tipo: il messaggio potrebbe contenere un pezzo di risposta)
            self.vault.registra("google", esito=f"scambio non riuscito ({type(e).__name__})")
            self._esito(stato, {"errore": "Google non risponde: usa email e password."})
            return self._pagina("Google non risponde: torna al Vault e usa email e password.")
        self.vault.registra("google", esito="ok")
        self._esito(stato, {"biglietto": self.vault.nuovo_biglietto(ident), "email": ident["email"]})
        return self._pagina("Accesso fatto. Puoi chiudere questa finestra e tornare al Vault.", chiudi=True)

    def _esito(self, stato, d):
        with self.mutex:
            self.esiti = {k: v for k, v in self.esiti.items() if v["scade"] > time.time()}
            self.esiti[stato] = {**d, "scade": time.time() + 300}

    def esito(self, stato):
        with self.mutex:
            e = self.esiti.pop(str(stato or ""), None)
        if not e:
            return {"in_attesa": True}
        e.pop("scade", None)
        return e

    @staticmethod
    def _pagina(testo, chiudi=False):
        import html as _h
        js = "<script>setTimeout(function(){window.close()},1200)</script>" if chiudi else ""
        return ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                "<title>Vault</title><body style='font:16px system-ui;padding:24px;background:#fff;color:#161616'>"
                f"<p>{_h.escape(testo)}</p>{js}").encode()


# ===================================================================================================== uso da parte degli agenti
# Solo macOS (con "uso_agenti": true in config.json) e modo vps (Linux). Su Windows non c'è.
# Un agente chiede «compila il campo password con la voce Amazon nel browser X» dando SOLO il nome
# (strumenti/vault.py usa). Il valore resta qui: va a strumenti/vault_compila.mjs per stdin e da lì a Chrome per il
# socket DevTools locale. Non torna mai a chi chiede, non va nei log, non va nella riga di comando.
# - classe servizio nel modo vps: si compila subito (chiavi di servizio, nessuna sessione serve);
# - classe personale (e tutto, sul computer locale): richiesta in attesa per 5 minuti, notifica al proprietario,
#   «Consenti una volta» o «Nega» nella pagina #vault a Vault sbloccato; una richiesta alla volta.
# Il dominio ammesso lo dice la VOCE (campi «domini» e «link»), mai chi chiede: una pagina finta non riceve niente.
# Carte (numero, CVV, PIN della carta) MAI: i pagamenti passano da un servizio di pagamento con la conferma del
# proprietario. Registro: usi.jsonl, senza valori.

CAMPI_USO = {"accesso": ("password", "utente", "mail", "codice")}
USO_ATTESA_S = 300
USO_TIENI_S = 1800
# Codice di verifica per mail (vault.py codice): casella e dominio dalla voce, solo mail degli ultimi 5 minuti dal
# dominio del sito; in automatico SOLO la casella scritta in config.json («casella_automatica») con una voce di
# servizio nel modo vps, ogni altro caso con il «Consenti». Serve strumenti/posta.py (lettura IMAP): se manca, il
# codice per mail non c'è.
CODICE_FINESTRA_S = 300
CODICE_ATTESA_S = 150
METODI_SENZA_PASSWORD = {"google": "Google", "apple": "Apple", "microsoft": "Microsoft", "sso": "SSO", "passkey": "passkey"}
MOTIVO_CARTA = ("le carte non si usano dagli agenti: i pagamenti passano da un servizio di pagamento, con la conferma "
                "del proprietario")


def casella_automatica():
    return str(_config().get("casella_automatica") or "").strip()


def uso_agenti_attivo():
    """Dove gli agenti possono chiedere di usare una voce: modo vps (Linux) e macOS con "uso_agenti": true in
    config.json. Mai su Windows."""
    if sys.platform == "win32":
        return False
    return modo_vps() or (sys.platform == "darwin" and _config().get("uso_agenti") is True)


def _prova_int(nome, predefinito):
    if os.environ.get("JARVIS_VAULT_PROVA") == "1" and os.environ.get(nome):
        return max(2, int(os.environ[nome]))
    return predefinito


def provider_mappa():
    """Pagine di accesso dei fornitori di identità (strumenti/vault-provider.json, fonte unica anche per vault_compila.mjs)."""
    f = Path(__file__).resolve().parent.parent / "strumenti" / "vault-provider.json"
    try:
        return {str(k).lower(): str(v) for k, v in json.loads(f.read_text(encoding="utf-8")).get("provider", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _uso_attesa_s():
    if os.environ.get("JARVIS_VAULT_PROVA") == "1" and os.environ.get("JARVIS_VAULT_USO_ATTESA_S"):
        return max(2, int(os.environ["JARVIS_VAULT_USO_ATTESA_S"]))
    return USO_ATTESA_S


def porte_browser():
    """I Chrome (porta DevTools) che l'agente può usare: «browser» in config.json ({"nome": porta}) oppure
    JARVIS_VAULT_BROWSER_PORTE (JSON). Nessun browser predefinito: senza configurazione non si compila niente."""
    fonti = [os.environ.get("JARVIS_VAULT_BROWSER_PORTE")]
    try:
        cfg = _config().get("browser")
        if isinstance(cfg, dict):
            fonti.append(json.dumps(cfg))
    except (TypeError, ValueError):
        pass
    for f in fonti:
        if not f:
            continue
        try:
            return {str(k): int(v) for k, v in json.loads(f).items() if 1024 <= int(v) <= 65535}
        except (ValueError, TypeError, AttributeError):
            continue
    return {}


def _host(url):
    from urllib.parse import urlsplit
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def scheda_attiva(porta):
    """L'host della scheda in primo piano del Chrome su quella porta (solo l'host, per la domanda al proprietario)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(porta)}/json/list", timeout=3) as r:
            pagine = [p for p in json.loads(r.read()) if p.get("type") == "page"]
        return _host(pagine[0].get("url")) if pagine else ""
    except Exception:  # noqa: BLE001
        return ""


def domini_voce(campi):
    out = []
    for d in re.split(r"[\s,;]+", str(campi.get("domini") or "")):
        d = d.strip().lower().rstrip(".")
        if d.startswith("http"):
            d = _host(d)
        if d and re.fullmatch(r"[a-z0-9.-]+", d) and "." in d:
            out.append(d)
    h = _host(campi.get("link"))
    if h:
        out.append(h)
    return sorted(set(out))


_NODE = {"versione": None}


def compila_nel_browser(porta, domini, selettore, invio, valore, campo="password"):
    """Scrive il valore nel campo della scheda del Chrome su «porta» che sta su uno dei domini (scelta per dominio).
    Il valore passa per stdin. Restituisce {ok, host, motivo, verificato, verifica} senza valori."""
    import shutil
    node = os.environ.get("JARVIS_VAULT_NODE") or shutil.which("node") or "/usr/bin/node"
    script = Path(__file__).resolve().parent.parent / "strumenti" / "vault_compila.mjs"
    if not script.exists():
        return {"ok": False, "motivo": "manca strumenti/vault_compila.mjs"}
    if _NODE["versione"] is None:
        try:
            v = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout
            _NODE["versione"] = int(re.findall(r"\d+", v)[0])
        except Exception:  # noqa: BLE001
            _NODE["versione"] = 0
    opz = ["--experimental-websocket"] if 0 < _NODE["versione"] < 22 else []
    arg = json.dumps({"porta": int(porta), "domini": list(domini), "campo": campo, "selettore": selettore or "",
                      "invio": bool(invio)})
    try:
        r = subprocess.run([node, *opz, "--no-warnings", str(script), arg], input=valore, capture_output=True,
                           text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return {"ok": False, "motivo": "il browser non ha risposto in tempo"}
    righe = [x for x in (r.stdout or "").splitlines() if x.strip()]
    try:
        esito = json.loads(righe[-1])
    except (IndexError, ValueError):
        return {"ok": False, "motivo": f"compilazione non riuscita (uscita {r.returncode})"}
    return {k: esito.get(k) for k in ("ok", "host", "motivo", "verificato", "verifica") if k in esito}


# ----------------------------------------------------------------------------------- codice di verifica dalla posta
_POSTA = {"m": None}


def _posta():
    """strumenti/posta.py caricato dal suo percorso (lettura IMAP, sola lettura). Se non c'è: ErroreVault."""
    if _POSTA["m"] is None:
        import importlib.util
        f = Path(__file__).resolve().parent.parent / "strumenti" / "posta.py"
        if not f.is_file():
            raise ErroreVault("La lettura della posta (strumenti/posta.py) non è installata: niente codici per mail.", 501)
        spec = importlib.util.spec_from_file_location("posta_vault", f)
        import socket
        prima = socket.getdefaulttimeout()
        m = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(m)
        finally:
            socket.setdefaulttimeout(prima)   # posta.py la mette a 20 s: nel server non deve cambiare per tutti
        if os.environ.get("JARVIS_VAULT_POSTA_ENV"):
            m.ENV = Path(os.environ["JARVIS_VAULT_POSTA_ENV"])
        _POSTA["m"] = m
    return _POSTA["m"]


def caselle_posta():
    """{indirizzo: id} delle caselle configurate in strumenti/posta.py (nessuna password)."""
    try:
        return {str(v.get("indirizzo", "")).lower(): k for k, v in _posta().caselle().items() if v.get("indirizzo")}
    except Exception:  # noqa: BLE001
        return {}


def casella_voce(campi):
    """La casella dove arriva il codice: il primo indirizzo noto fra «2FA: dove», «mail», «utente» della voce."""
    noti = caselle_posta()
    for nome in ("due_fa_dove", "mail", "utente"):
        for ind in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(campi.get(nome) or "")):
            if ind.lower() in noti:
                return noti[ind.lower()], ind.lower()
    return None, ""


def mittente_ok(dominio_mittente, domini):
    s = (dominio_mittente or "").lower().strip(".")
    if s.count(".") < 1:
        return False
    return any(s == d or s.endswith("." + d) or d.endswith("." + s) for d in domini)


_CODICE_RE = re.compile(r"(?<![\w:/+-])(?<!\d[.,])(\d{4,8})(?![\w:/-])(?![.,]\d)")


def estrai_codice(oggetto, testo):
    """Il codice nella mail: prima un numero di 6 cifre, poi uno di 4-8 (niente anni). Nessun valore va nei log."""
    cand = [c for c in _CODICE_RE.findall(f"{oggetto}\n{testo}") if not re.fullmatch(r"(19|20)\d\d", c)]
    sei = [c for c in cand if len(c) == 6]
    return (sei or cand or [None])[0]


def _testo_mail(msg):
    parti = msg.walk() if msg.is_multipart() else [msg]
    piano, html = [], []
    for p in parti:
        if p.get_content_maintype() != "text" or p.get_filename():
            continue
        try:
            t = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        (piano if p.get_content_subtype() == "plain" else html).append(t)
    if piano:
        return "\n".join(piano)
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", " ", "\n".join(html))))


def _cartelle_codici(m):
    """Dove cercare: su Gmail «Tutti i messaggi» (\\All), altrimenti INBOX."""
    r, righe = m.list()
    nomi = []
    for x in righe or []:
        s = x.decode(errors="replace") if isinstance(x, bytes) else str(x)
        mm = re.match(r'\((?P<f>[^)]*)\) "(?P<sep>[^"]*)" (?P<n>.+)$', s)
        if mm:
            n = mm.group("n").strip().strip('"')
            if "\\All" in mm.group("f"):
                return [n]
            nomi.append(n)
    return ["INBOX"]


def _domini_ricerca(domini):
    out = set()
    for d in domini:
        out.add(d)
        if d.count(".") >= 2:
            out.add(d.split(".", 1)[1])
    return sorted(out)


def mail_recenti(casella, finestra_s, domini=()):
    """[(ricevuta_epoch, dominio_mittente, oggetto, testo)] delle mail arrivate negli ultimi finestra_s secondi dai
    domini indicati. IMAP in sola lettura (EXAMINE, BODY.PEEK): nessuna mail cambia stato.
    In prova: JARVIS_VAULT_POSTA_FINTA (file JSON al posto della casella)."""
    import email
    import email.utils
    ora = time.time()
    finta = os.environ.get("JARVIS_VAULT_POSTA_FINTA") if os.environ.get("JARVIS_VAULT_PROVA") == "1" else None
    if finta:
        out = []
        for m in json.loads(Path(finta).read_text(encoding="utf-8")):
            if m.get("casella") == casella and 0 <= ora - float(m.get("ricevuta", 0)) <= finestra_s:
                out.append((float(m["ricevuta"]), str(m.get("mittente", "")).lower().rsplit("@", 1)[-1],
                            str(m.get("oggetto", "")), str(m.get("corpo", ""))))
        return out
    import imaplib
    posta = _posta()
    try:
        m = posta.collega(casella, scrittura=False)
    except SystemExit:
        raise ErroreVault(f"casella sconosciuta: {casella}")
    out = []
    try:
        dal = time.strftime("%d-%b-%Y", time.gmtime(ora - max(finestra_s, 86400)))
        for cartella in _cartelle_codici(m):
            if m.select(f'"{cartella}"', readonly=True)[0] != "OK":
                continue
            uids = set()
            for d in _domini_ricerca(domini) or [""]:
                crit = ["SINCE", dal] + (["FROM", f'"{d}"'] if d else [])
                r, dd = m.uid("SEARCH", None, *crit)
                if r == "OK":
                    uids.update((dd[0] or b"").split())
            uids = sorted(uids, key=int)[-30:]
            if not uids:
                continue
            r, dati = m.uid("FETCH", b",".join(uids).decode(), "(INTERNALDATE BODY.PEEK[])")
            for parte in dati or []:
                if not isinstance(parte, tuple):
                    continue
                t = imaplib.Internaldate2tuple(parte[0])
                quando = time.mktime(t) if t else 0
                if not (0 <= ora - quando <= finestra_s):
                    continue
                msg = email.message_from_bytes(parte[1])
                da = email.utils.parseaddr(str(msg.get("From") or ""))[1].lower()
                out.append((quando, da.rsplit("@", 1)[-1], posta.decodifica(msg.get("Subject")), _testo_mail(msg)))
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


def cerca_codice(casella, domini, finestra_s, attesa_s, ferma=lambda: False):
    """Aspetta fino ad attesa_s il codice nelle mail recenti della casella, solo da mittenti del sito.
    Restituisce (codice | None, motivo). Il codice resta in memoria: chi chiama lo passa a compila_nel_browser."""
    fine = time.time() + attesa_s
    scartate = 0
    while True:
        try:
            mail = mail_recenti(casella, finestra_s, domini)
        except ErroreVault:
            raise
        except Exception as e:  # noqa: BLE001  (solo il tipo: il messaggio potrebbe contenere testo della mail)
            return None, f"lettura della casella non riuscita ({type(e).__name__})"
        buone = sorted([x for x in mail if mittente_ok(x[1], domini)], key=lambda x: -x[0])
        scartate = len(mail) - len(buone)
        for _, _, ogg, testo in buone:
            c = estrai_codice(ogg, testo)
            if c:
                return c, ""
        if time.time() >= fine or ferma():
            extra = f" ({scartate} mail recenti da altri mittenti scartate)" if scartate else ""
            return None, f"nessun codice dal sito nelle mail degli ultimi {finestra_s // 60} minuti{extra}"
        time.sleep(4)


class UsoAgenti:
    def __init__(self, vault):
        self.vault = vault
        self.richieste = {}
        self.mutex = threading.Lock()
        self.notifica = self._notifica_predefinita

    # ---------------------------------------------------------------- supporto
    @staticmethod
    def _notifica_predefinita(testo):
        cmd = os.environ.get("JARVIS_VAULT_NOTIFICA")
        if cmd in ("0", "spenta"):
            return
        if cmd:
            argv = [*shlex.split(cmd), testo]
        else:
            argv = [sys.executable, str(Path(__file__).resolve().parent.parent / "strumenti" / "notifica.py"), "manda",
                    "--chi", "jarvis", "--titolo", "Vault: richiesta di uso", "--testo", testo]

        def via():
            try:
                subprocess.run(argv, capture_output=True, timeout=60)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=via, daemon=True).start()

    def _pulisci(self):
        ora = time.time()
        for i, r in list(self.richieste.items()):
            if r["stato"] == "attesa" and r["scade"] < ora:
                r["stato"], r["motivo"] = "scaduta", "nessuna risposta entro 5 minuti"
                self.vault.registra("uso-scaduto", campo=r["campo"], esito=f"{r['browser']}")
            if r["stato"] != "attesa" and ora - r["creato"] > USO_TIENI_S:
                self.richieste.pop(i, None)

    @staticmethod
    def _pubblica(r):
        return {"id": r["id"], "stato": r["stato"], "nome": r["nome"], "campo": r["campo"], "browser": r["browser"],
                "chi": r["chi"], "host_scheda": r.get("host_scheda", ""), "host": r.get("host", ""),
                "motivo": r.get("motivo", ""), "verificato": r.get("verificato"), "verifica": r.get("verifica", ""),
                "casella": r.get("casella", ""),
                "scade_s": max(0, int(r["scade"] - time.time())) if r["stato"] == "attesa" else 0}

    def _trova(self, chiavi, nome, solo_classe=None):
        """(rec, voce) per titolo (maiuscole a parte) o «id:<id>»; None se non c'è; errore se ce n'è più d'una."""
        d = self.vault._leggi()
        nome_c = nome.strip().casefold()
        trovate = []
        for rec in d["voci"].values():
            if solo_classe and rec["classe"] != solo_classe:
                continue
            if rec["classe"] not in chiavi:
                continue
            v = self.vault._apri(chiavi, rec)
            if v.get("eliminata"):
                continue
            if nome_c == f"id:{rec['id']}".casefold() or str(v.get("titolo", "")).strip().casefold() == nome_c:
                trovate.append((rec, v))
        if len(trovate) > 1:
            raise ErroreVault("Più voci con questo nome: usa «id:<id>» della voce.", 409)
        return trovate[0] if trovate else None

    @staticmethod
    def voce_su_provider(v):
        """True se fra i domini della voce c'è la pagina di un fornitore di identità (accounts.google.com, ...)."""
        prov = provider_mappa()
        return any(d in prov for d in domini_voce(v.get("campi", {})))

    def _codice(self, r, domini, casella):
        """Nel suo thread: aspetta il codice nella casella e lo scrive nel campo. Il codice non esce da qui."""
        try:
            codice, motivo = cerca_codice(casella, domini, _prova_int("JARVIS_VAULT_CODICE_FINESTRA_S", CODICE_FINESTRA_S),
                                          _prova_int("JARVIS_VAULT_CODICE_ATTESA_S", CODICE_ATTESA_S))
            if not codice:
                r["stato"], r["motivo"] = "errore", motivo
            else:
                esito = compila_nel_browser(r["porta"], domini, r["selettore"], r["invio"], codice, campo="codice")
                codice = None
                r["host"], r["verificato"], r["verifica"] = esito.get("host") or "", esito.get("verificato"), esito.get("verifica") or ""
                if esito.get("ok"):
                    r["stato"], r["motivo"] = "compilata", ""
                else:
                    r["stato"], r["motivo"] = "errore", str(esito.get("motivo") or "compilazione non riuscita")[:200]
        except ErroreVault as e:
            r["stato"], r["motivo"] = "errore", str(e)[:200]
        except Exception as e:  # noqa: BLE001
            r["stato"], r["motivo"] = "errore", f"errore interno ({type(e).__name__})"
        self.vault.registra("uso-codice-" + {"compilata": "compilato"}.get(r["stato"], r["stato"]), r.get("id_voce", ""), "codice",
                            f"{r['browser']} {casella} {r.get('host') or ''} {r.get('motivo') or ''}".strip()[:200])

    def _esegui(self, r, rec, v):
        """Controlli sulla voce, poi la compilazione. Aggiorna r. Nessun valore esce da qui."""
        tipo = v.get("tipo")
        metodo = str(v.get("campi", {}).get("metodo") or "")
        if tipo == "carta":
            r["stato"], r["motivo"] = "rifiutata", MOTIVO_CARTA
        elif r["campo"] not in CAMPI_USO.get(tipo, ()):
            r["stato"], r["motivo"] = "rifiutata", f"campo «{r['campo']}» non usabile per una voce di tipo {tipo}"
        elif r["campo"] == "password" and metodo in METODI_SENZA_PASSWORD:
            r["stato"], r["motivo"] = "rifiutata", (f"la voce si apre con {METODI_SENZA_PASSWORD[metodo]}, non con una password: "
                                                    f"usa il pulsante «Accedi con {METODI_SENZA_PASSWORD[metodo]}» (sessione del browser); "
                                                    "se chiede password, verifica in due passaggi o captcha, fermati e avvisa il proprietario")
        elif r["campo"] == "codice":
            domini = domini_voce(v.get("campi", {}))
            casella, ind = casella_voce(v.get("campi", {}))
            r["id_voce"], r["casella"] = rec["id"], casella or ""
            if not domini:
                r["stato"], r["motivo"] = "rifiutata", "la voce non ha un dominio (campo Domini o Link): aggiungilo nel Vault"
            elif not casella:
                r["stato"], r["motivo"] = "rifiutata", ("la voce non dice in quale casella arriva il codice (campo «2FA: dove», "
                                                        "«mail» o «utente» con l'indirizzo di una casella configurata)")
            else:
                r["stato"] = "in corso"
                threading.Thread(target=self._codice, args=(r, domini, casella), daemon=True).start()
                return
        else:
            domini = domini_voce(v.get("campi", {}))
            valore = str(v.get("campi", {}).get(r["campo"]) or "")
            if not domini:
                r["stato"], r["motivo"] = "rifiutata", "la voce non ha un dominio (campo Domini o Link): aggiungilo nel Vault"
            elif not valore:
                r["stato"], r["motivo"] = "rifiutata", f"la voce non ha il campo «{r['campo']}»"
            else:
                esito = compila_nel_browser(r["porta"], domini, r["selettore"], r["invio"], valore, campo=r["campo"])
                valore = None
                r["host"] = esito.get("host") or ""
                r["verificato"] = esito.get("verificato")
                r["verifica"] = esito.get("verifica") or ""
                if esito.get("ok"):
                    r["stato"], r["motivo"] = "compilata", ""
                else:
                    r["stato"], r["motivo"] = "errore", str(esito.get("motivo") or "compilazione non riuscita")[:200]
        r["id_voce"] = rec["id"]
        self.vault.registra("uso-" + {"compilata": "compilato"}.get(r["stato"], r["stato"]), rec["id"], r["campo"],
                            f"{r['browser']} {r.get('host') or ''} {r.get('motivo') or ''}".strip()[:200])

    # ---------------------------------------------------------------- dall'agente
    def richiedi(self, corpo):
        if not uso_agenti_attivo():
            raise ErroreVault("L'uso delle voci da parte degli agenti c'è solo su macOS (con «uso_agenti» acceso in "
                              "config.json) e nel modo VPS (Linux). Su Windows no.", 403)
        nome = str(corpo.get("nome") or "").strip()[:200]
        campo = str(corpo.get("campo") or "password").strip()
        browser = str(corpo.get("browser") or "").strip().lower()
        selettore = str(corpo.get("selettore") or "")[:300]
        chi = re.sub(r"[^\w .@-]", "", str(corpo.get("chi") or "agente"))[:60] or "agente"
        if not nome:
            raise ErroreVault("Serve il nome della voce.")
        if campo not in {c for t in CAMPI_USO.values() for c in t}:
            raise ErroreVault(f"Campo «{campo}» non usabile: password, utente, mail o codice.")
        porte = porte_browser()
        if not porte:
            raise ErroreVault("Nessun browser configurato per gli agenti («browser» in config.json del Vault).", 409)
        if not browser and len(porte) == 1:
            browser = next(iter(porte))
        if browser not in porte:
            raise ErroreVault(f"Browser sconosciuto: {browser or '(nessuno)'} (ci sono: {', '.join(sorted(porte))}).")
        if not self.vault.esiste():
            raise ErroreVault("Il Vault non è ancora stato creato.", 404)
        with self.mutex:
            self._pulisci()
            if any(x["stato"] in ("attesa", "in corso") for x in self.richieste.values()):
                raise ErroreVault("C'è già una richiesta di uso in attesa: una alla volta.", 409)
            r = {"id": secrets.token_hex(6), "stato": "in corso", "nome": nome, "campo": campo, "browser": browser,
                 "porta": porte[browser], "selettore": selettore, "invio": corpo.get("invio") is True, "chi": chi,
                 "creato": time.time(), "scade": time.time() + _uso_attesa_s()}
            self.richieste[r["id"]] = r
        r["host_scheda"] = scheda_attiva(r["porta"])
        trovata = None
        try:
            trovata = self._trova(self.vault.chiavi_servizio(), nome, solo_classe="servizio") if modo_vps() else None
        except ErroreVault as e:
            if e.codice == 409 and "Più voci" in str(e):
                r["stato"], r["motivo"] = "rifiutata", str(e)
                return self._pubblica(r)
        if trovata:
            # Voce di servizio (modo vps): subito, tranne due casi che vogliono sempre il «Consenti» del proprietario:
            # la pagina di un fornitore di identità e il codice da una casella che non è quella automatica.
            rec, v = trovata
            if v.get("tipo") == "carta":
                r["stato"], r["motivo"] = "rifiutata", MOTIVO_CARTA
                self.vault.registra("uso-rifiutata", rec["id"], campo, "carta")
                return self._pubblica(r)
            serve_consenso = self.voce_su_provider(v) or (
                campo == "codice" and (casella_voce(v.get("campi", {}))[0] or "") != (casella_automatica() or None))
            if not serve_consenso:
                self._esegui(r, rec, v)
                return self._pubblica(r)
            v = None
        r["stato"] = "attesa"
        self.vault.registra("uso-richiesto", campo=campo, esito=f"{browser} {r['host_scheda']} da {chi}"[:200])
        self.notifica(f"{nome_assistente()} chiede di usare «{nome}» ({campo}) nel browser «{browser}»"
                      f"{' su ' + r['host_scheda'] if r['host_scheda'] else ''}. Apri il Command Center, sezione Vault, e scegli "
                      f"Consenti o Nega entro 5 minuti.")
        return self._pubblica(r)

    def stato(self, id_r):
        with self.mutex:
            self._pulisci()
            r = self.richieste.get(str(id_r or ""))
        if not r:
            raise ErroreVault("Richiesta non trovata.", 404)
        return self._pubblica(r)

    # ---------------------------------------------------------------- dalla pagina (Vault sbloccato)
    def in_attesa(self):
        with self.mutex:
            self._pulisci()
            r = next((x for x in self.richieste.values() if x["stato"] == "attesa"), None)
        return {"richiesta": self._pubblica(r) if r else None}

    def c_e_attesa(self):
        with self.mutex:
            self._pulisci()
            return any(x["stato"] == "attesa" for x in self.richieste.values())

    def decidi(self, chiavi, id_r, consenti):
        with self.mutex:
            self._pulisci()
            r = self.richieste.get(str(id_r or ""))
            if not r:
                raise ErroreVault("Richiesta non trovata.", 404)
            if r["stato"] != "attesa":
                raise ErroreVault(f"La richiesta non è più in attesa ({r['stato']}).", 409)
            r["stato"] = "in corso" if consenti else "negata"
        if not consenti:
            r["motivo"] = "negata dal proprietario"
            self.vault.registra("uso-negato", campo=r["campo"], esito=r["browser"])
            return self._pubblica(r)
        self.vault.registra("uso-consentito", campo=r["campo"], esito=r["browser"])
        try:
            trovata = self._trova(chiavi, r["nome"])
        except ErroreVault as e:
            r["stato"], r["motivo"] = "rifiutata", str(e)
            return self._pubblica(r)
        if not trovata:
            r["stato"], r["motivo"] = "rifiutata", "nessuna voce con questo nome"
            self.vault.registra("uso-rifiutata", campo=r["campo"], esito="voce non trovata")
            return self._pubblica(r)
        self._esegui(r, *trovata)
        return self._pubblica(r)


# ===================================================================================================== importazione delle chiavi di .env.jarvis
# Fonte (SOLO LETTURA): ~/.env.jarvis (file_vero). I valori restano in memoria nel server: si confrontano per impronta
# (doppioni), si cifrano, non tornano mai al browser, non vanno nei log, non vanno nel piano.

REGOLE_GENERICHE = {"sezione_predefinita": "Altro", "spazi": [], "servizi": [
    {"servizio": "Google", "parole": ["GOOGLE", "GMAIL", "GEMINI"]}, {"servizio": "Posta/IMAP", "parole": ["IMAP", "SMTP", "MAIL"]},
    {"servizio": "GitHub", "parole": ["GITHUB"]}, {"servizio": "Database", "parole": ["DB_", "POSTGRES", "MYSQL"]},
    {"servizio": "Modelli AI", "parole": ["ANTHROPIC", "OPENAI", "OPENROUTER"]}], "preferiti": [],
    "tag_prova": ["TEST", "PROVA", "SANDBOX", "DEMO"], "tag_scaduto": ["_EXP", "EXPIR", "_OLD"]}
SEGRETO_NEL_NOME = re.compile(r"(PASSWORD|PASS\b|_PASS$|TOKEN|SECRET|SEGRETO|_KEY|API_KEY|PIN$|CHIAVE|ACCESS_CODE)")
COSA = [("CLIENT_SECRET", "segreto del client"), ("CLIENT_ID", "ID del client"), ("REFRESH_TOKEN", "token di rinnovo"),
        ("ACCESS_TOKEN", "token di accesso"), ("ACCESS_EXP", "scadenza del token"), ("APP_PASSWORD", "password per app"),
        ("ROOT_PASSWORD", "password di root"), ("ADMIN_PASSWORD", "password di amministratore"), ("PASSWORD", "password"),
        ("PASS", "password"), ("API_KEY", "chiave API"), ("API_TOKEN", "token API"), ("TOKEN", "token"), ("SECRET", "segreto"),
        ("SEGRETO", "segreto"), ("CHIAVE_PRIVATA", "chiave privata"), ("KEY", "chiave"), ("USERNAME", "utente"), ("USER", "utente"),
        ("UTENTE", "utente"), ("EMAIL", "email"), ("LOGIN_URL", "indirizzo di accesso"), ("URL", "indirizzo"), ("HOST", "host"),
        ("PORT", "porta"), ("IMAP", "server IMAP"), ("SMTP", "server SMTP"), ("POP3", "server POP3"), ("CHAT_ID", "ID chat"),
        ("PIN", "PIN"), ("DB", "database"), ("NAME", "nome"), ("ID", "ID")]


def carica_regole():
    d = _leggi_sezioni()
    if not isinstance(d, dict):
        return dict(REGOLE_GENERICHE)
    return {**REGOLE_GENERICHE, **{k: v for k, v in d.items() if k in ("spazi", "servizi", "preferiti", "tag_prova",
                                                                        "tag_scaduto", "sezione_predefinita")}}


def classifica(nome: str, regole=None) -> dict:
    """Spazio dal prefisso più lungo, servizio dalla prima regola, tag, preferito, descrizione. Solo dal NOME."""
    r = regole or carica_regole()
    N = nome.upper()
    spazio, pref = "", ""
    for s in r.get("spazi", []):
        for p in s.get("prefissi", []):
            if (N == p or N.startswith(p + "_")) and len(p) > len(pref):
                spazio, pref = s["spazio"], p
    servizio = next((s["servizio"] for s in r.get("servizi", []) if any(w in N for w in s.get("parole", []))), "")
    tag = ["prova" if any(w in N for w in r.get("tag_prova", [])) else "produzione"]
    if any(w in N for w in r.get("tag_scaduto", [])):
        tag.append("scaduto?")
    resto = N[len(pref):].lstrip("_") if pref else N
    cosa = next((t for k, t in COSA if resto == k or resto.endswith("_" + k) or resto.endswith("__" + k)), "")
    chiave = next((k for k, t in COSA if resto == k or resto.endswith("_" + k)), "")
    ente = resto[: len(resto) - len(chiave)].strip("_") if chiave else resto
    ente = " ".join(w.capitalize() for w in re.split(r"_+", ente) if w) or (servizio or "")
    descr = " · ".join(x for x in (ente, cosa, spazio) if x)
    if spazio:
        sezione, sugg = f"{spazio} / {servizio or 'Altro'}", ""
    else:
        sezione = "Da riordinare"
        sugg = (f"forse «{r.get('sezione_predefinita') or 'Altro'} / {servizio}»" if servizio
                else "aggiungi il prefisso in vault-sezioni.json (copia di vault-sezioni.esempio.json)")
    return {"spazio": spazio, "servizio": servizio, "sezione": sezione, "tag": tag, "ruolo": cosa or next((t for kk, t in COSA if kk in resto), resto),
            "preferito": any(N == p or re.fullmatch(p, N) for p in r.get("preferiti", [])),
            "descrizione": descr[:160], "suggerimento": sugg, "segreto": bool(SEGRETO_NEL_NOME.search(N))}


def _valori_env():
    """{nome: valore} dal file vero (prima riga che combacia, come posta.py). SOLO LETTURA."""
    try:
        return {k: v for k, (_n, v) in analizza_env(file_vero().read_text(encoding="utf-8")).items()}
    except OSError:
        return None


def _gruppi_doppioni(valori: dict, regole=None, separati=()):
    """(gruppi, riusi). Regola («niente doppioni»): stesso valore = UNA voce, con tutti gli
    altri nomi come alias. riusi: i gruppi i cui nomi sono di servizi o ruoli diversi (password riusata da più
    account): restano uniti e la voce porta l'avviso. Contano solo i valori che sembrano segreti (nome da segreto o
    valore lungo): «true» o una porta uguali in due servizi non sono doppioni. I nomi «separati» a mano (pulsante
    «Separa un alias») restano voci proprie. Le impronte si confrontano in memoria."""
    per_impronta = {}
    for nome, v in valori.items():
        if nome in separati or not v or len(v) < 6:
            continue
        if not (SEGRETO_NEL_NOME.search(nome.upper()) or len(v) >= 16):
            continue
        per_impronta.setdefault(hashlib.sha256(v.encode()).digest(), []).append(nome)
    gruppi, riusi = {}, []
    ordina = lambda n: (classifica(n, regole)["sezione"] == "Da riordinare", len(n), n)  # noqa: E731
    for nomi in per_impronta.values():
        if len(nomi) < 2:
            continue
        nomi = sorted(nomi, key=ordina)
        gruppi[nomi[0]] = nomi[1:]
        tipi = {(classifica(n, regole)["servizio"], classifica(n, regole)["ruolo"]) for n in nomi}
        if len(tipi) > 1:
            riusi.append(nomi)
    return gruppi, riusi


def piano_import(chiavi=None, con_valori=False):
    """Il piano: SOLO nomi, sezioni, tag, conteggi, doppioni, da riordinare. Con chiavi (Vault aperto) anche lo stato
    rispetto al Vault: importata / diversa / nuova nel file. Con con_valori=True restituisce anche i valori in una
    chiave a parte («_valori»), che l'importazione usa e che NON esce mai da questo processo."""
    regole = carica_regole()
    valori = _valori_env()
    voci, alias_di = [], {}
    riusi, separati = [], []
    if chiavi is not None and VAULT.esiste():
        separati = VAULT._impostazioni(VAULT._leggi(), chiavi).get("separati", [])
    if valori is not None:
        gruppi, riusi = _gruppi_doppioni(valori, regole, separati)
        for canon, als in gruppi.items():
            for a in als:
                alias_di[a] = canon
        for nome in sorted(valori):
            if nome in alias_di:
                continue
            c = classifica(nome, regole)
            if not valori[nome]:
                c["tag"] = c["tag"] + ["vuota"]
            riuso = next((len(g) for g in riusi if g[0] == nome), 0)
            voci.append({"nome": nome, "alias": gruppi.get(nome, []), "riuso": riuso, **c})
    nel_vault = {}
    if chiavi is not None and VAULT.esiste():
        d = VAULT._leggi()
        k = chiavi["hmac"]
        for _rec, v in VAULT._tutte(d, chiavi):
            if v["tipo"] == "variabile":
                for n in [v["campi"].get("nome", "")] + [x.strip() for x in v["campi"].get("alias", "").split(",") if x.strip()]:
                    nel_vault[n] = impronta(k, v["campi"].get("valore", ""))
        voci_per_nome = {}
        for rec, v in VAULT._tutte(d, chiavi):
            if v["tipo"] == "variabile":
                voci_per_nome[v["campi"].get("nome", "")] = rec["id"]
        for x in voci:
            x["da_unire"] = max(0, len({voci_per_nome[n] for n in [x["nome"]] + x["alias"] if n in voci_per_nome}) - 1)
        for x in voci:
            if x["nome"] in nel_vault:
                x["stato"] = "importata" if nel_vault[x["nome"]] == impronta(k, valori.get(x["nome"], "")) else "diversa"
            else:
                x["stato"] = "nuova nel file"
    conteggi = {}
    for x in voci:
        conteggi[x["sezione"]] = conteggi.get(x["sezione"], 0) + 1
    piano = {
        "creato": _ora(), "fonte_env": str(file_vero()).replace(str(_casa()), "~"), "env_presente": valori is not None,
        "righe_env": len(valori or {}), "voci": voci, "conteggi": dict(sorted(conteggi.items())),
        "doppioni": [{"voce": x["nome"], "alias": x["alias"]} for x in voci if x["alias"]],
        "riusi": riusi, "voci_unite": sum(len(x["alias"]) for x in voci),
        "da_riordinare": [{"nome": x["nome"], "suggerimento": x["suggerimento"]} for x in voci if x["sezione"] == "Da riordinare"],
        "preferiti": [x["nome"] for x in voci if x["preferito"]],
    }
    if chiavi is not None:
        piano["stati"] = {s: sum(1 for x in voci if x.get("stato") == s) for s in ("importata", "diversa", "nuova nel file")}
        piano["stati"]["da unire"] = sum(x.get("da_unire", 0) for x in voci)
    if con_valori:
        piano["_valori"] = valori or {}
    return piano


def piano_markdown(p: dict) -> str:
    """Il piano leggibile: solo nomi. Nessun valore (il piano non li contiene)."""
    r = [f"# Vault - piano di importazione", "",
         f"*{p['creato'][:16]} · generato da `command-center/vault_cc.py --piano-import` · solo nomi, nessun valore. "
         f"L'importazione vera si fa dal pulsante «Importa le chiavi di .env.jarvis» dopo aver creato e sbloccato il Vault.*", "",
         f"Fonte: `{p['fonte_env']}` ({p['righe_env']} righe con un nome). Voci nel Vault dopo l'importazione: {len(p['voci'])} "
         f"variabili ({len(p['doppioni'])} con alias).", "", "## Conteggi per sezione", "", "| Sezione | Voci |", "|---|---|"]
    r += [f"| {s} | {n} |" for s, n in p["conteggi"].items()]
    r += ["", f"## Doppioni: stesso valore = una voce con alias ({p.get('voci_unite', 0)} nomi uniti)", ""]
    r += [f"- `{d['voce']}` ← alias " + ", ".join(f"`{a}`" for a in d["alias"]) for d in p["doppioni"]] or ["- nessuno"]
    r += ["", "## Password riusata da più account (unite in una voce, con avviso)", ""]
    r += [f"- {len(g)} account: " + ", ".join(f"`{n}`" for n in g) for g in p.get("riusi", [])] or ["- nessuno"]
    r += ["", "## Da riordinare", ""]
    r += [f"- `{d['nome']}`: {d['suggerimento']}" for d in p["da_riordinare"]] or ["- nessuna"]
    r += ["", "## Preferiti", "", ", ".join(f"`{n}`" for n in p["preferiti"]) or "nessuno", "", "## Voci per sezione", ""]
    per = {}
    for x in p["voci"]:
        per.setdefault(x["sezione"], []).append(x)
    for s in sorted(per):
        r += [f"### {s}", "", "| Nome | Descrizione | Tag | Alias |", "|---|---|---|---|"]
        r += [f"| `{x['nome']}`{' ★' if x['preferito'] else ''} | {x['descrizione']} | {', '.join(x['tag'])} | "
              f"{', '.join(x['alias'])} |" for x in per[s]]
        r.append("")
    r += ["## Regole", "", "Sezione dal prefisso, servizio dalla prima parola che combacia: `command-center/vault-sezioni.json` "
          "(copia di `vault-sezioni.esempio.json`). Le chiavi senza prefisso noto vanno in «Da riordinare»."]
    return "\n".join(r) + "\n"


VAULT = Vault()
GOOGLE_ACC = AccessoGoogle(VAULT)
USO = UsoAgenti(VAULT)


# ===================================================================================================== HTTP

def stato_pubblico(token=None):
    """GET /api/vault/stato: niente di segreto, nemmeno i titoli. L'email del Vault non è un segreto (serve a
    precompilare lo sblocco); id e segreto del client Google non escono mai."""
    p = VAULT.portachiavi
    cfg = _config()
    try:
        controlla_cartella()
        posto_ok, posto_errore = True, ""
    except ErroreVault as e:
        posto_ok, posto_errore = False, str(e)
    try:
        acc = VAULT.info_account()
    except ErroreVault:
        acc = {}
    g = oidc_conf()
    sbloccato = bool(token and token in VAULT.sessioni and VAULT.resta_s(token) > 0)
    return {"creato": VAULT.esiste(), "sbloccato": sbloccato, "resta_s": VAULT.resta_s(token) if sbloccato else 0,
            "email": acc.get("email", ""), "accesso": {k: acc.get(k, False) for k in ("password", "pin", "google",
                                                                                     "google_con_password")},
            "pin_attivo": acc.get("pin", False), "google_pronto": g["pronto"], "google_motivo": g["motivo"],
            "assistente": nome_assistente(), "proprietario": nome_proprietario(), "cifratura": CRITTO_OK,
            "posto_ok": posto_ok, "posto_errore": posto_errore, "piattaforma": sys.platform,
            "portachiavi": p.nome, "uso_agenti": uso_agenti_attivo(),
            "portachiavi_debole": p.debole, "blocco_minuti": int(cfg.get("blocco_minuti") or BLOCCO_MINUTI),
            "svuota_appunti_s": SVUOTA_APPUNTI_S, "scrittura_file_vero": scrittura_vera_accesa(),
            "modo": "vps" if modo_vps() else "locale", "remoto": _remoto(cfg),
            "richiesta_uso": USO.c_e_attesa() if uso_agenti_attivo() else False}


def _remoto(cfg):
    """Sul computer locale, se il Vault vive sul tuo server: il suo indirizzo (config.json «remoto», https soltanto)."""
    r = str(cfg.get("remoto") or "").strip()
    return r if (not modo_vps() and re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?(/[^\s\"'<>]*)?", r)) else ""


def _redirect(intestazioni):
    if modo_vps():
        # dietro un proxy l'Host è quello locale: l'indirizzo pubblico viene SOLO dalla configurazione del servizio
        base = url_pubblico()
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", base) and not (
                os.environ.get("JARVIS_VAULT_PROVA") == "1" and re.fullmatch(r"http://127\.0\.0\.1:\d+", base)):
            raise ErroreVault("Manca JARVIS_VAULT_URL_PUBBLICO (https) nel servizio: Google non sa dove tornare.", 503)
        return base + "/api/vault/google/callback"
    host = str(intestazioni.get("Host") or "")
    if not re.fullmatch(r"(127\.0\.0\.1|localhost):\d{2,5}", host):
        raise ErroreVault("L'accesso con Google si avvia solo da questo computer (127.0.0.1).", 403)
    return f"http://{host}/api/vault/google/callback"


def _conferma(corpo):
    """La conferma a parte: password, PIN o biglietto di un accesso Google appena fatto."""
    return {k: corpo.get(k) for k in ("password", "pin", "biglietto") if corpo.get(k)}


def _solo_agente(intestazioni):
    """Le rotte dell'agente (uso/richiedi, uso/stato): solo da un processo di questa macchina, mai dal sito."""
    if intestazioni.get("X-CC-Ponte") == "1":
        raise ErroreVault("Questa rotta è solo per gli strumenti locali.", 403)


def _modulo(nome):
    """Un modulo del Vault accanto a questo file (vault_chrome, vault_gruppi), caricato dal suo percorso."""
    import importlib.util
    m = sys.modules.get(nome)
    if m is None or not hasattr(m, "gestisci"):
        with _CARICA_MODULI:          # registrato solo a caricamento finito: due richieste insieme non lo vedono a metà
            m = sys.modules.get(nome)
            if m is None or not hasattr(m, "gestisci"):
                spec = importlib.util.spec_from_file_location(nome, Path(__file__).resolve().parent / f"{nome}.py")
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                sys.modules[nome] = m
    return m


_CARICA_MODULI = threading.Lock()


def _chrome(metodo, percorso, query, corpo, chiavi):
    """«Da Chrome (CSV)»: command-center/vault_chrome.py, caricato dal suo percorso (niente collisioni di nomi)."""
    return _modulo("vault_chrome").gestisci(metodo, percorso, query, corpo, VAULT, chiavi)


def gestisci(metodo: str, percorso: str, query: dict, corpo: dict, intestazioni) -> tuple:
    """(codice, corpo JSON) oppure (codice, bytes HTML, tipo) per la pagina di ritorno di Google.
    intestazioni: dict-like (X-Vault-Sessione, Host). Nessun valore finisce mai in un errore."""
    token = (intestazioni.get("X-Vault-Sessione") or "").strip()
    corpo = corpo if isinstance(corpo, dict) else {}
    try:
        if not CRITTO_OK and percorso != "/api/vault/stato":
            raise ErroreVault("Manca la libreria «cryptography».", 500)
        if metodo == "GET":
            if percorso == "/api/vault/stato":
                return 200, stato_pubblico(token)
            if percorso == "/api/vault/forza":
                return 200, {"forza": forza_password((query.get("p") or [""])[0])}
            if percorso == "/api/vault/google/inizio":
                return 200, GOOGLE_ACC.inizio(_redirect(intestazioni))
            if percorso == "/api/vault/google/callback":
                return 200, GOOGLE_ACC.callback(query), "text/html; charset=utf-8"
            if percorso == "/api/vault/google/esito":
                return 200, GOOGLE_ACC.esito((query.get("stato") or [""])[0])
            if percorso == "/api/vault/uso/stato":
                _solo_agente(intestazioni)
                return 200, USO.stato((query.get("id") or [""])[0])
            chiavi = VAULT.sessione(token, tocca=intestazioni.get("X-Vault-Sfondo") != "1")
            if percorso == "/api/vault/voci":
                r = VAULT.elenco(chiavi)
                r["resta_s"] = VAULT.resta_s(token)
                return 200, r
            if percorso == "/api/vault/voce":
                return 200, VAULT.voce(chiavi, (query.get("id") or [""])[0])
            if percorso == "/api/vault/storico":
                return 200, VAULT.storico(chiavi, (query.get("id") or [""])[0])
            if percorso == "/api/vault/usi":
                return 200, {"usi": VAULT.usi(None, 200)}
            if percorso == "/api/vault/ambiente":
                return 200, VAULT.ambiente(chiavi, giro=(query.get("giro") or ["1"])[0] == "1")
            if percorso == "/api/vault/piano-import":
                return 200, piano_import(chiavi)
            if percorso.startswith("/api/vault/chrome/"):
                return _chrome(metodo, percorso, query, corpo, chiavi)
            if percorso.startswith("/api/vault/gruppo/"):
                return _modulo("vault_gruppi").gestisci(metodo, percorso, query, corpo, VAULT, chiavi)
            if percorso == "/api/vault/uso/attesa":
                return 200, USO.in_attesa()
            return 404, {"errore": "non trovato"}
        if metodo != "POST":
            return 405, {"errore": "metodo non ammesso"}
        if percorso == "/api/vault/crea":
            return 200, VAULT.crea(email=corpo.get("email"), password=corpo.get("password"),
                                   biglietto=corpo.get("biglietto"))
        if percorso == "/api/vault/sblocca":
            return 200, VAULT.sblocca(email=corpo.get("email"), password=corpo.get("password"), pin=corpo.get("pin"),
                                      biglietto=corpo.get("biglietto"))
        if percorso == "/api/vault/recupera":
            return 200, VAULT.recupera(corpo.get("codice"), corpo.get("nuova_password"))
        if percorso == "/api/vault/blocca":
            VAULT.blocca(token or None)
            return 200, {"bloccato": True}
        if percorso == "/api/vault/uso/richiedi":
            _solo_agente(intestazioni)
            return 200, USO.richiedi(corpo)
        chiavi = VAULT.sessione(token)
        if percorso == "/api/vault/tocca":
            return 200, {"resta_s": VAULT.resta_s(token)}
        if percorso == "/api/vault/salva":
            return 200, VAULT.salva(chiavi, corpo)
        if percorso == "/api/vault/mostra":
            if corpo.get("file"):
                return 200, VAULT.mostra_file(chiavi, corpo.get("file"), corpo.get("nome"))
            return 200, VAULT.mostra(chiavi, str(corpo.get("id") or ""), str(corpo.get("campo") or ""),
                                     conferma=_conferma(corpo), azione="copia" if corpo.get("copia") else "mostra")
        if percorso == "/api/vault/elimina":
            return 200, VAULT.elimina(chiavi, str(corpo.get("id") or ""))
        if percorso == "/api/vault/annulla":
            return 200, VAULT.annulla(chiavi, str(corpo.get("id") or ""), corpo.get("versione"))
        if percorso == "/api/vault/sezione":
            return 200, VAULT.sezione(chiavi, corpo)
        if percorso == "/api/vault/categoria":
            return 200, VAULT.categoria(chiavi, corpo.get("tipo"), corpo.get("nome"))
        if percorso == "/api/vault/pin":
            VAULT.imposta_pin(chiavi, _conferma(corpo), corpo.get("nuovo_pin"))
            return 200, {"pin_attivo": True}
        if percorso == "/api/vault/password":
            VAULT.imposta_password(chiavi, _conferma(corpo), corpo.get("nuova"))
            return 200, {"password": True}
        if percorso == "/api/vault/google/con-password":
            return 200, VAULT.google_con_password(chiavi, _conferma(corpo), corpo.get("acceso") is True)
        if percorso == "/api/vault/google/collega":
            return 200, VAULT.collega_google(chiavi, corpo.get("biglietto_google"))
        if percorso == "/api/vault/esporta":
            return 200, VAULT.esporta(chiavi, corpo.get("frase"))
        if percorso == "/api/vault/importa":
            return 200, VAULT.importa(chiavi, corpo.get("contenuto"), corpo.get("frase"))
        if percorso == "/api/vault/backup":
            return 200, VAULT.backup()
        if percorso == "/api/vault/ambiente/importa":
            return 200, VAULT.importa_da_file(chiavi, str(corpo.get("nome") or ""), str(corpo.get("sezione") or ""))
        if percorso == "/api/vault/separa":
            return 200, VAULT.separa_alias(chiavi, str(corpo.get("id") or ""), str(corpo.get("alias") or ""))
        if percorso.startswith("/api/vault/chrome/"):
            return _chrome(metodo, percorso, query, corpo, chiavi)
        if percorso.startswith("/api/vault/gruppo/"):
            return _modulo("vault_gruppi").gestisci(metodo, percorso, query, corpo, VAULT, chiavi)
        if percorso == "/api/vault/importa-attuali":
            return 200, VAULT.importa_attuali(chiavi)
        if percorso == "/api/vault/uso/decidi":
            return 200, USO.decidi(chiavi, str(corpo.get("id") or ""), corpo.get("consenti") is True)
        if percorso == "/api/vault/ambiente/risolvi":
            return 200, VAULT.risolvi(chiavi, str(corpo.get("id") or ""), corpo.get("tieni"))
        return 404, {"errore": "non trovato"}
    except ErroreVault as e:
        return e.codice, {"errore": str(e), **e.extra}
    except Exception as e:  # noqa: BLE001  (il tipo sì, il messaggio no: potrebbe contenere un pezzo di dato)
        return 500, {"errore": f"errore interno del Vault ({type(e).__name__})"}

if __name__ == "__main__":
    if sys.argv[1:2] == ["--piano-import"]:
        # Solo nomi: legge ~/.env.jarvis. Scrive il piano in Markdown dove dice --uscita. Non crea il Vault, non stampa valori.
        a = sys.argv[2:]
        p = piano_import()
        testo = piano_markdown(p)
        for opz in ("--uscita",):
            if opz in a:
                dest = Path(a[a.index(opz) + 1]).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(testo, encoding="utf-8")
                print(f"scritto {dest}")
        print(f"{p['righe_env']} righe in {p['fonte_env']} · {len(p['voci'])} voci · {len(p['doppioni'])} con alias · "
              f"{len(p['da_riordinare'])} da riordinare")
        for sez, n in p["conteggi"].items():
            print(f"  {n:4d}  {sez}")
        sys.exit(0)
    if sys.argv[1:2] == ["barriera-git"]:
        trovati = _barriera_git()
        if trovati:
            print("Commit fermato: questi file appartengono al Vault o ai segreti e non vanno in git:", file=sys.stderr)
            for t in trovati:
                print("  " + t, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    print("Uso: python3 vault_cc.py barriera-git        (lo lancia il gancio pre-commit)\n"
          "     python3 vault_cc.py --piano-import [--uscita F.md]   (piano di importazione da ~/.env.jarvis, solo nomi)")
