#!/usr/bin/env python3
"""Una sola fonte per i segreti: ~/.env.jarvis (l'utente, 2026-10-04: «tutti gli accessi devono andare in .env.jarvis»).

I servizi (docker compose, script, cron) vogliono ancora il loro file `.env` accanto al programma: quei file restano, ma
diventano GENERATI da ~/.env.jarvis. Chi vuole cambiare una chiave la cambia lì e lancia `env_sync.py applica`.

  env_sync.py migra <file> [<file>…] [--prefisso nome]   porta i valori di quei file in ~/.env.jarvis (blocco «servizio»)
                                                         e ricorda come rifarli (~/.env.mappa.json: solo struttura)
  env_sync.py verifica                                   rigenera in memoria e confronta con i file sul disco
  env_sync.py applica [--solo <file>]                    riscrive i file dei servizi da ~/.env.jarvis (copia prima in
                                                         ~/backup-env-AAAAMMGG/), modo 600
  env_sync.py importa [--solo <file>]                    riporta in ~/.env.jarvis i valori cambiati da un programma sul disco
  env_sync.py elenco                                     quali file sono generati e da quali chiavi (solo nomi)

Mai un valore in uscita: si stampano nomi di file e di chiavi. Un valore che ha già lo stesso testo identico in ~/.env.jarvis
sotto lo stesso nome non si duplica. I nuovi valori entrano come `PREFISSO__CHIAVE='…'` (virgolette shell, quindi la riga
si può anche `source`). Variabili per le prove: ENV_CENTRALE, ENV_MAPPA, ENV_BACKUP.
Solo libreria standard.
"""
import hashlib
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

CENTRALE = Path(os.environ.get("ENV_CENTRALE") or Path.home() / ".env.jarvis")
MAPPA = Path(os.environ.get("ENV_MAPPA") or Path.home() / ".env.mappa.json")
BACKUP = Path(os.environ.get("ENV_BACKUP") or Path.home() / f"backup-env-{time.strftime('%Y%m%d')}")
def _r(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def _w(p, testo):
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(testo)


ASSEGNAZIONE = re.compile(r"^(\s*)(export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*?)(\r?\n?)$", re.S)
INTESTAZIONE = "# GENERATO da env_sync.py a partire da ~/.env.jarvis: per cambiare una chiave modifica lì e lancia `env_sync.py applica`.\n"


def _leggi_centrale():
    righe = _r(CENTRALE).splitlines(keepends=True) if CENTRALE.exists() else []
    chiavi = {}
    for r in righe:
        m = ASSEGNAZIONE.match(r)
        if m:
            chiavi[m.group(3)] = m.group(4)
    return righe, chiavi


def _decodifica(raw, codifica):
    if codifica == "q":
        parti = shlex.split(raw)
        return parti[0] if parti else ""
    return raw


def _nome_servizio(percorso):
    p = Path(percorso)
    base = p.parent.name if p.name.startswith(".env") and p.parent.name not in ("", "/") else p.stem
    extra = p.name[4:].lstrip(".-_") if p.name.startswith(".env") and p.name != ".env" else ""
    n = re.sub(r"[^A-Za-z0-9]+", "_", base + ("_" + extra if extra else "")).strip("_").upper()
    return n or "SERVIZIO"


def _carica_mappa():
    try:
        return json.loads(_r(MAPPA))
    except (OSError, ValueError):
        return {"file": {}}


def _salva_mappa(m):
    MAPPA.parent.mkdir(parents=True, exist_ok=True)
    tmp = MAPPA.with_suffix(".tmp")
    _w(tmp, json.dumps(m, ensure_ascii=False, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, MAPPA)


def migra(file, prefisso=None):
    """Aggiunge a ~/.env.jarvis i valori di `file` e registra come rigenerarlo. Ritorna (nuove chiavi, riusate)."""
    f = Path(file).resolve()
    testo = _r(f)
    righe_c, chiavi_c = _leggi_centrale()
    pref = prefisso or _nome_servizio(f)
    voci, nuove, riusate, da_aggiungere = [], 0, 0, []
    for r in testo.splitlines(keepends=True):
        m = ASSEGNAZIONE.match(r)
        if not m:
            voci.append({"t": "lit", "testo": r})
            continue
        pre, exp, chiave, raw, eol = m.groups()
        # già in centrale con lo stesso nome e lo stesso testo? riuso
        cand = None
        if chiavi_c.get(chiave) == raw:
            cand = (chiave, "raw")
        else:
            for k, v in chiavi_c.items():
                if k.startswith(pref + "__") and k.endswith("__" + chiave) or k == f"{pref}__{chiave}":
                    if _decodifica(v, "q") == raw:
                        cand = (k, "q")
                        break
        if cand:
            riusate += 1
            ck, cod = cand
        else:
            ck, n = f"{pref}__{chiave}", 2
            while ck in chiavi_c:
                ck, n = f"{pref}__{chiave}__{n}", n + 1
            chiavi_c[ck] = shlex.quote(raw)
            da_aggiungere.append(f"{ck}={shlex.quote(raw)}\n")
            cod, nuove = "q", nuove + 1
        voci.append({"t": "kv", "pre": pre, "exp": bool(exp), "k": chiave, "c": ck, "cod": cod, "eol": eol})
    if da_aggiungere:
        BACKUP.mkdir(parents=True, exist_ok=True)
        os.chmod(BACKUP, 0o700)
        if CENTRALE.exists():
            _w(BACKUP / (CENTRALE.name + f".prima-{pref}"), _r(CENTRALE))
            os.chmod(BACKUP / (CENTRALE.name + f".prima-{pref}"), 0o600)
        testo_c = "".join(righe_c)
        if testo_c and not testo_c.endswith("\n"):
            testo_c += "\n"
        testo_c += f"\n# ---- {pref}: da {f} ({time.strftime('%Y-%m-%d %H:%M')}) ----\n" + "".join(da_aggiungere)
        tmp = CENTRALE.with_suffix(".tmp")
        _w(tmp, testo_c)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CENTRALE)
    m = _carica_mappa()
    m["file"][str(f)] = {"servizio": pref, "voci": voci}
    _salva_mappa(m)
    return nuove, riusate


def genera(percorso, scheda, chiavi_c):
    """Il testo del file dei servizi, rifatto dalla centrale (intestazione + righe nello stesso ordine di prima)."""
    out = [INTESTAZIONE]
    for v in scheda["voci"]:
        if v["t"] == "lit":
            out.append(v["testo"])
        else:
            raw_c = chiavi_c.get(v["c"])
            if raw_c is None:
                raise KeyError(v["c"])
            out.append(f"{v['pre']}{'export ' if v['exp'] else ''}{v['k']}={_decodifica(raw_c, v['cod'])}{v['eol']}")
    return "".join(out)


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def importa(solo=None):
    """I valori cambiati sul disco da un programma (rinnovo di un token) tornano in ~/.env.jarvis, nella riga che già c'è.
    Chiavi nuove o sparite dal file non si importano da sole: si dice quali, e si rilancia `migra`."""
    righe_c, chiavi_c = _leggi_centrale()
    mappa = _carica_mappa()
    cambi = 0
    testo_c = "".join(righe_c)
    for p, scheda in mappa["file"].items():
        if solo and Path(p).resolve() != Path(solo).resolve():
            continue
        try:
            disco = _r(Path(p))
        except OSError:
            print(f"ASSENTE  {p}")
            continue
        noti = {v["k"]: v for v in scheda["voci"] if v["t"] == "kv"}
        visti = set()
        for r in disco.splitlines(keepends=True):
            m = ASSEGNAZIONE.match(r)
            if not m:
                continue
            chiave, raw = m.group(3), m.group(4)
            visti.add(chiave)
            v = noti.get(chiave)
            if not v:
                print(f"NUOVA    {p}: la chiave {chiave} non era nella mappa (rilancia `migra`)")
                continue
            attuale = _decodifica(chiavi_c.get(v["c"], ""), v["cod"])
            if attuale != raw:
                nuova = f"{v['c']}={shlex.quote(raw)}"
                testo_c, n = re.subn(r"^%s=.*$" % re.escape(v["c"]), lambda _m: nuova, testo_c, count=1, flags=re.M)
                if n:
                    v["cod"] = "q"
                    chiavi_c[v["c"]] = shlex.quote(raw)
                    cambi += 1
                    print(f"AGGIORNATA {v['c']}  (da {p})")
        for k in noti:
            if k not in visti:
                print(f"SPARITA  {p}: la chiave {k} non è più nel file")
        scheda["sha"] = _sha(disco.replace(INTESTAZIONE, "", 1) if False else disco)
    if cambi:
        BACKUP.mkdir(parents=True, exist_ok=True)
        _w(BACKUP / (CENTRALE.name + ".prima-importa"), "".join(righe_c))
        os.chmod(BACKUP / (CENTRALE.name + ".prima-importa"), 0o600)
        tmp = CENTRALE.with_suffix(".tmp")
        _w(tmp, testo_c)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CENTRALE)
    _salva_mappa(mappa)
    return cambi


def _senza_intestazione(t):
    return t[len(INTESTAZIONE):] if t.startswith(INTESTAZIONE) else t


def verifica():
    _, chiavi_c = _leggi_centrale()
    brutto = 0
    for p, scheda in _carica_mappa()["file"].items():
        try:
            voluto = genera(p, scheda, chiavi_c)
        except KeyError as e:
            print(f"MANCA   {p}: la chiave {e} non c'è più in {CENTRALE}")
            brutto += 1
            continue
        try:
            reale = _r(Path(p))
        except OSError:
            print(f"ASSENTE {p}")
            brutto += 1
            continue
        if reale == voluto:
            print(f"ok      {p}")
        elif _senza_intestazione(reale) == _senza_intestazione(voluto):
            print(f"ok*     {p} (uguale, manca solo l'intestazione)")
        else:
            a = {l.split("=", 1)[0] for l in reale.splitlines() if "=" in l and not l.lstrip().startswith("#")}
            b = {l.split("=", 1)[0] for l in voluto.splitlines() if "=" in l and not l.lstrip().startswith("#")}
            print(f"DIVERSO {p}: chiavi solo sul disco {sorted(a - b)}, solo da centrale {sorted(b - a)}, "
                  f"{'stesse chiavi, valori diversi' if a == b else ''}")
            brutto += 1
    return brutto


def applica(solo=None):
    _, chiavi_c = _leggi_centrale()
    BACKUP.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUP, 0o700)
    fatti = 0
    mappa = _carica_mappa()
    for p, scheda in mappa["file"].items():
        if solo and Path(p).resolve() != Path(solo).resolve():
            continue
        voluto = genera(p, scheda, chiavi_c)
        f = Path(p)
        if f.exists() and _r(f) == voluto:
            print(f"già a posto  {p}")
            scheda["sha"] = _sha(voluto)
            continue
        if f.exists() and scheda.get("sha") and _sha(_r(f)) != scheda["sha"]:
            print(f"SALTATO      {p}: un programma l'ha modificato dopo l'ultima generazione (rinnovo di token?): "
                  f"lancia `env_sync.py importa --solo {p}` per portare i valori nuovi in {CENTRALE.name}")
            continue
        if f.exists():
            dest = BACKUP / (str(f).strip("/").replace("/", "__"))
            _w(dest, _r(f))
            os.chmod(dest, 0o600)
        tmp = f.with_name(f.name + ".nuovo")
        _w(tmp, voluto)
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)
        scheda["sha"] = _sha(voluto)
        print(f"riscritto    {p}")
        fatti += 1
    _salva_mappa(mappa)
    return fatti


def elenco():
    for p, s in _carica_mappa()["file"].items():
        chiavi = [v["k"] for v in s["voci"] if v["t"] == "kv"]
        print(f"{p}  [{s['servizio']}]  {len(chiavi)} chiavi: {', '.join(chiavi)[:160]}")


def main(a):
    if not a:
        print(__doc__)
        return 2
    cmd = a[0]
    if cmd == "migra":
        pref = None
        if "--prefisso" in a:
            i = a.index("--prefisso")
            pref = a[i + 1]
            a = a[:i] + a[i + 2:]
        for f in a[1:]:
            n, r = migra(f, pref)
            print(f"{f}: {n} chiavi nuove in {CENTRALE.name}, {r} già presenti")
        return 0
    if cmd == "verifica":
        return 1 if verifica() else 0
    if cmd == "applica":
        solo = a[a.index("--solo") + 1] if "--solo" in a else None
        applica(solo)
        return 1 if verifica() else 0
    if cmd == "importa":
        solo = a[a.index("--solo") + 1] if "--solo" in a else None
        print(f"{importa(solo)} valori riportati in {CENTRALE.name}")
        return 0
    if cmd == "elenco":
        elenco()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
