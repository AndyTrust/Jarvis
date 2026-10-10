#!/usr/bin/env python3
"""Una sola fonte, sulla VPS, per lo stato condiviso del Command Center (l'utente, 2026-10-05: «procedi»).

Prima: lavagna (pannello.json), fili delle chat, aspetto e barra vivevano due volte, sul Mac e sulla VPS, e la
VPS ogni 10 minuti tornava alla copia committata dal Mac (reset --hard di jarvis-repo-sync.sh). Due lavagne,
due storie. Da qui: il cervello è la VPS. Questo modulo gira SOLO sul Mac (il server lo accende con avvia()).

  tunnel   ssh -N -L 127.0.0.1:17777 → 127.0.0.1:7777 della VPS (lo stesso «ssh vps-tuo» degli altri ponti);
           il token della pagina della VPS si legge da ~/.locale-onedrive/jarvis-cc/token-locale sulla VPS.
  lavagna  le scritture del Mac vanno alla VPS (inoltra / scrivi_pannello_remoto); pannello.json del Mac è
           lo SPECCHIO dell'ultima versione della VPS, rinfrescato ogni OGNI_S secondi (la pagina del Mac
           lo legge come sempre e il flusso si sveglia da solo, sorveglia_file guarda il file).
  VPS giù  il Mac scrive in locale come prima (niente blocchi: dopo un errore la VPS non si richiama per
           PAUSA_S secondi). Al ritorno: fusione a tre vie (base = ultima versione della VPS vista, locale,
           VPS di adesso), per scheda/filo/gruppo; se tutte e due hanno toccato la stessa cosa vince la VPS.
  fili     ogni macchina scrive i suoi (la chat gira dove è partita); i file del Mac vanno sulla VPS in
           ~/.locale-onedrive/jarvis-cc/fili-remoti/mac/, quelli della VPS arrivano qui in fili-remoti/vps/.
           fili.elenco_unito() li mostra tutti; il filo locale vince su quello remoto con la stessa sessione.
  aspetto e barra in alto: si leggono e si scrivono sulla VPS, copia locale per quando la VPS non risponde.

Stato del ponte: ~/.locale-onedrive/jarvis-cc/fonte-vps.json (impronta dell'ultimo allineamento) e
pannello-base-vps.json (la base della fusione). Nessun segreto esce: il token è della VPS e resta in memoria.

Prove: python3 prove/prova_fonte_vps.py
"""
import hashlib
import http.client
import io
import json
import os
import socket
import subprocess
import tarfile
import threading
import re
import time
from pathlib import Path

HOST = os.environ.get("JARVIS_VPS_SSH", "vps-tuo")
PORTA_VPS = int(os.environ.get("CC_FONTE_PORTA_VPS") or 7777)   # la porta del server sulla VPS (le prove la cambiano)
PORTA_LOCALE = int(os.environ.get("CC_FONTE_PORTA") or 17777)
SSH_OPZ = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=20",
           "-o", "ServerAliveCountMax=3"]
OGNI_S = 2.0           # ogni quanto il Mac rilegge la lavagna della VPS
FILI_OGNI_S = 3.0      # ogni quanto si allineano i fili
PAUSA_S = 10.0         # dopo un errore: niente chiamate alla VPS per tanti secondi (il Mac non si blocca)
TIMEOUT_S = 4.0
CASA = Path(os.environ.get("CC_FONTE_DIR") or Path.home() / ".locale-onedrive" / "jarvis-cc")   # HOME del processo
REMOTO_FILI = os.environ.get("CC_FONTE_FILI_REMOTI") or "~/.locale-onedrive/jarvis-cc/fili-remoti/mac"
# Solo per le prove (prove/prova_fonte_vps.py): «ssh» diventa una shell locale e il token si legge con un comando
SSH_LOCALE = os.environ.get("CC_FONTE_SSH_LOCALE") == "1"
TOKEN_CMD = os.environ.get("CC_FONTE_TOKEN_CMD") or ""
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class NonRaggiungibile(Exception):
    """La VPS non risponde (tunnel giù, rete assente, server spento): si lavora in locale."""


def impronta(d):
    """Impronta del contenuto (senza «aggiornato», che cambia a ogni scrittura)."""
    if not isinstance(d, dict):
        return ""
    x = {k: v for k, v in d.items() if k not in ("aggiornato",)}
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


# ---------------------------------------------------------------- fusione a tre vie della lavagna
def _per_chiave(d):
    """pannello → {chiave: valore} per le parti che si fondono una a una."""
    out = {}
    for g in d.get("gruppi") or []:
        if isinstance(g, dict) and g.get("id"):
            out[("G", g["id"])] = g
    for k, v in (d.get("aspetto") or {}).items():
        out[("A", k)] = v
    for k, L in (d.get("lavagne") or {}).items():
        if not isinstance(L, dict):
            continue
        out[("L", k)] = True                            # la lavagna esiste
        for n in L.get("nodi") or []:
            if isinstance(n, dict) and n.get("id"):
                out[("N", k, n["id"])] = n
        for f in L.get("fili") or []:
            if isinstance(f, dict):
                out[("F", k, f.get("da"), f.get("a"))] = True
        for campo in ("vista", "bolle", "titolo"):
            if campo in L:
                out[("C", k, campo)] = L[campo]
    return out


def fondi(base, locale, remoto):
    """Fusione a tre vie: quello che il Mac ha cambiato rispetto alla base entra, il resto resta come sulla VPS.
    Stessa cosa cambiata da tutte e due le parti: vince la VPS. Ordine di gruppi e schede: quello della VPS,
    le cose nuove del Mac in coda."""
    B, Lc, R = _per_chiave(base or {}), _per_chiave(locale or {}), _per_chiave(remoto or {})
    J = lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False)  # noqa: E731
    fuso = dict(R)
    for k in set(B) | set(Lc):
        in_b, in_l, in_r = k in B, k in Lc, k in R
        if in_l and (not in_b or J(Lc[k]) != J(B[k])):          # il Mac l'ha aggiunta o cambiata
            if in_b and in_r and J(R[k]) != J(B[k]):
                continue                                         # cambiata anche sulla VPS: vince la VPS
            if not in_b and in_r:
                continue                                         # nata da tutte e due le parti: vince la VPS
            fuso[k] = Lc[k]
        elif in_b and not in_l and in_r and J(R[k]) == J(B[k]):  # il Mac l'ha tolta, la VPS non l'ha toccata
            fuso.pop(k, None)
    # di nuovo in forma di pannello, con l'ordine della VPS
    out = {k: v for k, v in (remoto or {}).items() if k not in ("gruppi", "aspetto", "lavagne")}
    ordine_g = [g["id"] for g in (remoto or {}).get("gruppi") or [] if isinstance(g, dict) and g.get("id")]
    ordine_g += [g["id"] for g in (locale or {}).get("gruppi") or [] if isinstance(g, dict) and g.get("id")
                 and g["id"] not in ordine_g]
    out["gruppi"] = [fuso[("G", i)] for i in ordine_g if ("G", i) in fuso]
    out["aspetto"] = {k[1]: v for k, v in fuso.items() if k[0] == "A"}
    lavagne = {}
    nomi_l = [k for k in (remoto or {}).get("lavagne") or {}] + \
             [k for k in (locale or {}).get("lavagne") or {} if k not in ((remoto or {}).get("lavagne") or {})]
    for nome in nomi_l:
        if ("L", nome) not in fuso:
            continue
        L = {"nodi": [], "fili": []}
        for fonte in ((remoto or {}).get("lavagne") or {}).get(nome) or {}, ((locale or {}).get("lavagne") or {}).get(nome) or {}:
            for n in fonte.get("nodi") or []:
                k = ("N", nome, n.get("id"))
                if k in fuso and all(x.get("id") != n.get("id") for x in L["nodi"]):
                    L["nodi"].append(fuso[k])
            for f in fonte.get("fili") or []:
                k = ("F", nome, f.get("da"), f.get("a"))
                if k in fuso and {"da": f.get("da"), "a": f.get("a")} not in L["fili"]:
                    L["fili"].append({"da": f.get("da"), "a": f.get("a")})
        for campo in ("vista", "bolle", "titolo"):
            if ("C", nome, campo) in fuso:
                L[campo] = fuso[("C", nome, campo)]
        ids = {n.get("id") for n in L["nodi"]}
        L["fili"] = [f for f in L["fili"] if f["da"] in ids and f["a"] in ids]
        lavagne[nome] = L
    out["lavagne"] = lavagne
    return out


def conta(d):
    """Numeri da mostrare all'utente: gruppi, agenti nei gruppi, schede, note, fili, lavagne."""
    L = (d or {}).get("lavagne") or {}
    return {"gruppi": len((d or {}).get("gruppi") or []),
            "agenti": sum(len(g.get("agenti") or []) for g in (d or {}).get("gruppi") or []),
            "lavagne": len(L), "schede": sum(len(v.get("nodi") or []) for v in L.values()),
            "note": sum(1 for v in L.values() for n in v.get("nodi") or [] if n.get("tipo") == "nota"),
            "fili": sum(len(v.get("fili") or []) for v in L.values())}


# ---------------------------------------------------------------- il ponte
class Fonte:
    def __init__(self, comando_ssh=None, porta_locale=PORTA_LOCALE, casa=CASA, log=print):
        self.comando_ssh = comando_ssh or (lambda remoto: ["ssh", *SSH_OPZ, HOST, remoto])
        self.porta = porta_locale
        self.casa = Path(casa)
        self.log = log
        self.token = None
        self.tunnel = None
        self.giu_fino = 0.0
        self.ultimo_ok = 0.0
        self.ultimo_errore = ""
        self._lock = threading.Lock()

    # --- stato del ponte
    def stato(self):
        return {"vps": time.time() - self.ultimo_ok < 3 * OGNI_S + TIMEOUT_S, "ultimo_ok": self.ultimo_ok,
                "errore": self.ultimo_errore, "in_pausa": time.time() < self.giu_fino}

    def _file_stato(self):
        return self.casa / "fonte-vps.json"

    def leggi_stato(self):
        try:
            return json.loads(self._file_stato().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def metti_stato(self, **kv):
        d = self.leggi_stato()
        d.update(kv)
        self.casa.mkdir(parents=True, exist_ok=True)
        tmp = self._file_stato().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._file_stato())

    # --- tunnel e token
    def _porta_aperta(self):
        try:
            with socket.create_connection(("127.0.0.1", self.porta), timeout=1):
                return True
        except OSError:
            return False

    def _apri_tunnel(self):
        if self.tunnel and self.tunnel.poll() is None and self._porta_aperta():
            return
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.kill()
        if self._porta_aperta():          # c'è già un tunnel (un altro pannello del Mac): si usa quello
            return
        cmd = self.comando_ssh(None)
        self.tunnel = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        for _ in range(40):
            if self._porta_aperta():
                return
            if self.tunnel.poll() is not None:
                break
            time.sleep(0.25)
        raise NonRaggiungibile("tunnel verso la VPS non aperto")

    def _leggi_token(self):
        cmd = ["bash", "-c", TOKEN_CMD] if TOKEN_CMD else self.comando_ssh("cat ~/.locale-onedrive/jarvis-cc/token-locale")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise NonRaggiungibile(f"token della VPS non letto: {type(e).__name__}")
        t = (r.stdout or "").strip()
        if r.returncode != 0 or not t:
            raise NonRaggiungibile("token della VPS non letto")
        self.token = t

    def chiama(self, metodo, percorso, corpo=None, forza=False, timeout=TIMEOUT_S):
        """(codice, dati) dal server della VPS. NonRaggiungibile se la VPS non risponde (o se è in pausa
        dopo un errore recente, salvo forza=True: lo usa il giro periodico per accorgersi che è tornata)."""
        if not forza and time.time() < self.giu_fino:
            raise NonRaggiungibile(self.ultimo_errore or "VPS in pausa dopo un errore")
        with self._lock:
            try:
                self._apri_tunnel()
                if not self.token:
                    self._leggi_token()
                for tentativo in (1, 2):
                    codice, dati = self._http(metodo, percorso, corpo, timeout)
                    if codice == 403 and isinstance(dati, dict) and dati.get("token_scaduto") and tentativo == 1:
                        self._leggi_token()                  # la VPS è ripartita: token nuovo
                        continue
                    break
            except NonRaggiungibile as e:
                self._giu(str(e))
                raise
            except (OSError, http.client.HTTPException, ValueError) as e:
                self._giu(f"{type(e).__name__}: {str(e)[:120]}")
                raise NonRaggiungibile(self.ultimo_errore)
        if codice >= 500 or codice == 403:
            self._giu(f"la VPS risponde {codice}")
            raise NonRaggiungibile(self.ultimo_errore)
        self.ultimo_ok, self.ultimo_errore, self.giu_fino = time.time(), "", 0.0
        return codice, dati

    def _giu(self, motivo):
        self.ultimo_errore = motivo
        self.giu_fino = time.time() + PAUSA_S

    def _http(self, metodo, percorso, corpo, timeout):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=timeout)
        try:
            testo = json.dumps(corpo).encode() if corpo is not None else None
            intest = {"Host": f"127.0.0.1:{PORTA_VPS}", "X-Token": self.token or "", "Accept": "application/json"}
            if testo is not None:
                intest["Content-Type"] = "application/json"
            c.request(metodo, percorso, body=testo, headers=intest)
            r = c.getresponse()
            dati = r.read()
            try:
                return r.status, json.loads(dati or b"{}")
            except ValueError:
                return r.status, {"errore": dati[:200].decode(errors="replace")}
        finally:
            c.close()

    def chiudi(self):
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.kill()


# ---------------------------------------------------------------- la lavagna (le funzioni le passa il server)
class Lavagna:
    """Tiene pannello.json del Mac uguale a quello della VPS. Il server passa:
       leggi()            il pannello locale (dict)
       scrivi_specchio(d) scrive d così com'è in pannello.json (sotto il lock del server)
       lock               il PANNELLO_LOCK del server
       avviso(testo)      un evento per l'utente"""

    def __init__(self, fonte, leggi, scrivi_specchio, lock, avviso):
        self.f, self.leggi, self.scrivi_specchio, self.lock, self.avviso = fonte, leggi, scrivi_specchio, lock, avviso
        self.base_file = fonte.casa / "pannello-base-vps.json"

    def _base(self):
        try:
            return json.loads(self.base_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _segna_allineato(self, d):
        """Sotto il lock: la VPS e il Mac hanno lo stesso pannello d."""
        self.scrivi_specchio(d)
        self.f.casa.mkdir(parents=True, exist_ok=True)
        tmp = self.base_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.base_file)
        self.f.metti_stato(impronta=impronta(d), versione_vps=d.get("versione"))

    def sporco(self, locale):
        """Il Mac ha cambiato la lavagna senza la VPS (VPS giù, file toccato a mano)?"""
        return impronta(locale) != self.f.leggi_stato().get("impronta")

    def ricevuto(self, d):
        """Una risposta della VPS con il pannello intero (dopo un inoltro): diventa lo specchio."""
        if isinstance(d, dict) and isinstance(d.get("lavagne"), dict):
            with self.lock:
                if not self.sporco(self.leggi()):      # modifiche del Mac non ancora fuse: ci pensa giro()
                    self._segna_allineato(d)

    def giro(self):
        """Un giro: rilegge la VPS; se il Mac ha modifiche sue (fatte con la VPS giù) le fonde e le manda.
        Torna 'uguale', 'specchio', 'fuso' o solleva NonRaggiungibile."""
        codice, remoto = self.f.chiama("GET", "/api/pannello", forza=True)
        if codice != 200 or not isinstance(remoto, dict):
            raise NonRaggiungibile(f"lavagna della VPS: {codice}")
        with self.lock:
            locale = self.leggi()
            if self.f.leggi_stato().get("impronta") is None and impronta(locale) != impronta(remoto):
                # primo giro in assoluto: il Mac aveva la sua lavagna; si fonde con la base = quella committata
                base = self._base() or locale
            elif not self.sporco(locale):
                if impronta(locale) == impronta(remoto) and locale.get("versione") == remoto.get("versione"):
                    return "uguale"
                self._segna_allineato(remoto)
                return "specchio"
            else:
                base = self._base() or remoto
            fuso = fondi(base, locale, remoto)
            if impronta({**fuso, "versione": remoto.get("versione")}) == impronta(remoto):
                self._segna_allineato(remoto)
                return "specchio"
            fuso["versione"] = remoto.get("versione")
            fuso["svuota"] = False
            codice, risposta = self.f.chiama("POST", "/api/pannello", fuso, forza=True)
            if codice == 409 and isinstance(risposta, dict) and risposta.get("pannello"):
                return "riprova"                 # la VPS è cambiata in questo istante: al giro dopo
            if codice != 200:
                self.avviso(f"lavagna: le modifiche fatte col VPS spento non sono passate ({codice}: "
                            f"{str((risposta or {}).get('errore'))[:120]}); restano sul Mac")
                return "rifiutato"
            self._segna_allineato(risposta)
        self.avviso(f"lavagna: modifiche del Mac riportate sulla VPS (versione {risposta.get('versione')})")
        return "fuso"


# ---------------------------------------------------------------- i fili delle chat
class Fili:
    """Mac → VPS: i file dei fili del Mac, con tar su ssh, in fili-remoti/mac della VPS.
       VPS → Mac: /api/fili della VPS (solo i fili nati là), in fili-remoti/vps del Mac."""

    def __init__(self, fonte, cartella_locale, avvisa=None):
        self.f = fonte
        self.loc = Path(cartella_locale)
        self.dest = self.loc.parent / "fili-remoti" / "vps"
        self.mandati = {}          # nome → (mtime_ns, dimensione) già sulla VPS
        self.avvisa = avvisa

    def manda(self):
        if not self.loc.is_dir():
            return 0
        attuali = {}
        for p in self.loc.glob("*.json"):
            if not UUID_RE.fullmatch(p.stem):        # solo i fili (niente notifiche-telefono.json o altro)
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            attuali[p.name] = (st.st_mtime_ns, st.st_size)
        nuovi = [n for n, v in attuali.items() if self.mandati.get(n) != v]
        tolti = set(self.mandati) - set(attuali)
        if not nuovi and not tolti:
            return 0
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            for n in nuovi:
                t.add(str(self.loc / n), arcname=n)
            elenco = "\n".join(sorted(attuali)).encode() + b"\n"
            ti = tarfile.TarInfo(".elenco")
            ti.size = len(elenco)
            t.addfile(ti, io.BytesIO(elenco))
        remoto = (f"d={REMOTO_FILI}; mkdir -p $d && chmod 700 $d && cd $d && tar --no-same-owner -xf - && "
                  f"for f in *.json; do [ -e \"$f\" ] || continue; grep -qxF \"$f\" .elenco || rm -f \"$f\"; done")
        try:
            r = subprocess.run(self.f.comando_ssh(remoto), input=buf.getvalue(), capture_output=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise NonRaggiungibile(f"fili verso la VPS: {type(e).__name__}")
        if r.returncode != 0:
            raise NonRaggiungibile(f"fili verso la VPS: {(r.stderr or b'').decode(errors='replace')[:120]}")
        self.mandati = attuali
        return len(nuovi)

    def ricevi(self):
        codice, d = self.f.chiama("GET", "/api/fili", forza=True)
        if codice != 200 or not isinstance(d, dict):
            raise NonRaggiungibile(f"fili della VPS: {codice}")
        self.dest.mkdir(parents=True, exist_ok=True)
        locali = {p.stem for p in self.loc.glob("*.json")}
        voluti, cambiati = set(), 0
        for r in d.get("fili") or []:
            s = r.get("sessione")
            if not s or r.get("origine") or s in locali:     # nati altrove (anche sul Mac) o già qui: no
                continue
            voluti.add(s)
            f = self.dest / f"{s}.json"
            try:
                vecchio = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                vecchio = None
            if vecchio and vecchio.get("versione") == r.get("versione") and vecchio.get("aggiornato") == r.get("aggiornato"):
                continue
            c2, filo = self.f.chiama("GET", f"/api/fili/{s}", forza=True)
            if c2 != 200 or not isinstance(filo, dict):
                continue
            tmp = f.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                json.dump(filo, h, ensure_ascii=False)
            os.replace(tmp, f)
            cambiati += 1
        for p in self.dest.glob("*.json"):
            if p.stem not in voluti:
                p.unlink(missing_ok=True)
                cambiati += 1
        if cambiati and self.avvisa:
            self.avvisa({"remoti": cambiati})
        return cambiati


# ---------------------------------------------------------------- accensione (dal server, solo sul Mac)
FONTE = None
LAVAGNA = None
FILI = None


def configurato():
    """Questo Mac sa raggiungere la VPS? (la riga «Host vps-tuo» in ~/.ssh/config). Le copie del template
    su altri Mac non ce l'hanno: lì la fonte resta spenta e niente ssh parte."""
    if SSH_LOCALE:
        return True
    try:
        righe = (Path.home() / ".ssh" / "config").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return any(r.strip().split()[:1] == ["Host"] and HOST in r.split()[1:] for r in righe if r.strip())


def attiva():
    return FONTE is not None


def avvia(leggi, scrivi_specchio, lock, avviso, cartella_fili, avvisa_fili, porta_locale=PORTA_LOCALE):
    """Accende il ponte e i due giri (lavagna ogni OGNI_S, fili ogni FILI_OGNI_S). Torna la Fonte."""
    global FONTE, LAVAGNA, FILI

    def ssh(remoto):
        if SSH_LOCALE:
            return ["false"] if remoto is None else ["bash", "-c", remoto]
        if remoto is None:
            return ["ssh", "-N", *SSH_OPZ, "-o", "ExitOnForwardFailure=yes",
                    "-L", f"127.0.0.1:{porta_locale}:127.0.0.1:{PORTA_VPS}", HOST]
        return ["ssh", *SSH_OPZ, HOST, remoto]

    avviso_pagina = avviso

    def avviso(testo):          # all'evento della pagina e in fonte-vps.log (gli eventi della pagina sono solo 60)
        try:
            CASA.mkdir(parents=True, exist_ok=True)
            with open(CASA / "fonte-vps.log", "a", encoding="utf-8") as h:
                h.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {testo}\n")
        except OSError:
            pass
        avviso_pagina(testo)

    FONTE = Fonte(comando_ssh=ssh, porta_locale=porta_locale)
    LAVAGNA = Lavagna(FONTE, leggi, scrivi_specchio, lock, avviso)
    FILI = Fili(FONTE, cartella_fili, avvisa_fili)
    stato = {"giu_detto": False}

    def ciclo(fn, ogni, nome):
        while True:
            try:
                fn()
                if stato["giu_detto"] and nome == "lavagna":
                    stato["giu_detto"] = False
                    avviso("fonte unica: la VPS risponde di nuovo, lavagna e chat riallineate")
            except NonRaggiungibile as e:
                if nome == "lavagna" and not stato["giu_detto"]:
                    stato["giu_detto"] = True
                    avviso(f"fonte unica: la VPS non risponde ({str(e)[:100]}); il Mac lavora in locale e riallinea dopo")
            except Exception as e:  # noqa: BLE001 — il giro non deve mai morire
                avviso(f"fonte unica ({nome}): {type(e).__name__}: {str(e)[:140]}")
            time.sleep(ogni)

    threading.Thread(target=ciclo, args=(LAVAGNA.giro, OGNI_S, "lavagna"), daemon=True).start()
    threading.Thread(target=ciclo, args=(lambda: (FILI.manda(), FILI.ricevi()), FILI_OGNI_S, "fili"),
                     daemon=True).start()
    return FONTE


def inoltra(metodo, percorso, corpo=None):
    """(codice, dati) dalla VPS, o None se la fonte è spenta o la VPS non risponde (allora si fa in locale)."""
    if FONTE is None:
        return None
    try:
        return FONTE.chiama(metodo, percorso, corpo)
    except NonRaggiungibile:
        return None
