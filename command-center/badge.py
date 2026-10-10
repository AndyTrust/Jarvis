#!/usr/bin/env python3
"""Il badge di lavoro (l'utente, 2026-10-04): «se il custode ha problemi apre un badge che scade ogni 30 minuti,
lo fa riprendere fino al termine, poi lo revoca».

Il badge è il permesso a lavorare di UNA sessione dentro UNA richiesta dell'utente. Lo apre il sistema (conformita.py)
quando il controllo morbido (il modello, o una cartella «privata») dice no a un agente che sta eseguendo una richiesta
vera dell'utente: l'agente non lo apre da solo, perché il file sta in jarvis-cc/, che per i permessi è un posto protetto.

  durata        30 minuti dall'ultimo uso: ogni azione autorizzata lo rinnova (così il lavoro lungo non si ferma);
  chiusura      `lavori.py finito` lo revoca; `badge.py giro` revoca quelli senza più una presa attiva o scaduti;
  cosa toglie   il giudizio del modello e il «privato» (Documents, ~/.claude/settings.json, cartelle fuori dal lavoro);
  cosa NON toglie (paletti duri, sempre): segreti e credenziali, comandi che la guardia blocca (rm -rf, push forzati,
                DROP…), scritture nel file delle regole, nell'archivio, nel registro, in ~/.claude e in .git,
                servizi delle Connessioni su «spento», passi irreversibili senza la conferma finale.

Uso: badge.py stato | apri <chiave> "<richiesta>" | revoca <chiave> | giro
Solo libreria standard.
"""
import json
import os
import sys
import time
from pathlib import Path

DURATA_S = 30 * 60
CARTELLA = Path(os.environ.get("CC_BADGE_DIR") or Path.home() / ".locale-onedrive" / "jarvis-cc" / "badge")


def _file(chiave):
    sicura = "".join(c for c in str(chiave) if c.isalnum() or c in "-_")[:80]
    return CARTELLA / f"{sicura}.json" if sicura else None


def _leggi(chiave):
    f = _file(chiave)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return None


def _scrivi(chiave, d):
    f = _file(chiave)
    if not f:
        return False
    try:
        CARTELLA.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
        return True
    except OSError:
        return False


def chiave_di(sessione=None, lavoro_id=None):
    """La sessione se c'è (un lavoro lungo ne attraversa molti turni), altrimenti il lavoro."""
    return str(sessione or lavoro_id or "").strip().lower() or None


def valido(chiave, adesso=None):
    """Il badge di `chiave` se esiste e non è scaduto, altrimenti None. Non lo rinnova."""
    d = _leggi(chiave) if chiave else None
    if not d or float(d.get("scade", 0)) <= (adesso or time.time()):
        return None
    return d


def apri(chiave, richiesta, motivo="", adesso=None):
    """Apre (o riapre) il badge. Una richiesta dell'utente vuota non apre niente: senza richiesta non c'è lavoro."""
    if not chiave or not str(richiesta or "").strip():
        return None
    t = adesso or time.time()
    vecchio = _leggi(chiave) or {}
    d = {"chiave": chiave, "aperto": vecchio.get("aperto") or int(t), "scade": t + DURATA_S, "usi": vecchio.get("usi", 0),
         "richiesta": str(richiesta)[:300], "motivo": str(motivo)[:200]}
    return d if _scrivi(chiave, d) else None


def usa(chiave, adesso=None):
    """Un uso del badge valido: lo rinnova di altri 30 minuti. None se non c'è o è scaduto."""
    d = valido(chiave, adesso)
    if not d:
        return None
    d["scade"] = (adesso or time.time()) + DURATA_S
    d["usi"] = int(d.get("usi", 0)) + 1
    _scrivi(chiave, d)
    return d


def revoca(chiave):
    f = _file(chiave)
    try:
        if f and f.exists():
            f.unlink()
            return True
    except OSError:
        pass
    return False


def tutti():
    out = []
    try:
        for f in sorted(CARTELLA.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return out


def giro(sessioni_con_presa=None, adesso=None):
    """Revoca i badge scaduti e quelli la cui sessione non ha più una presa attiva (`sessioni_con_presa` = insieme di
    sessioni con un lavoro aperto in lavori.py; None = si guarda solo la scadenza). Un badge di un lavoro ancora aperto
    viene rinnovato: il lavoro lungo riprende da solo. Ritorna (revocati, rinnovati)."""
    t = adesso or time.time()
    revocati = rinnovati = 0
    for d in tutti():
        k = d.get("chiave")
        viva = sessioni_con_presa is None or k in sessioni_con_presa
        if not viva:
            revocati += bool(revoca(k))
        elif float(d.get("scade", 0)) <= t:
            if sessioni_con_presa is None:
                revocati += bool(revoca(k))
            else:
                d["scade"] = t + DURATA_S
                _scrivi(k, d)
                rinnovati += 1
    return revocati, rinnovati


def _sessioni_con_presa():
    """Le sessioni che hanno una presa aperta nel registro dei lavori (lavori.py), o None se non si riesce a leggerlo."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "strumenti"))
        import lavori  # noqa: PLC0415
        return {str(d.get("sessione") or "").lower() for d in lavori.leggi_attivi()}
    except Exception:  # noqa: BLE001
        return None


def main(argv):
    cmd = argv[0] if argv else "stato"
    if cmd == "stato":
        t = time.time()
        for d in tutti():
            print(f"{d.get('chiave')}  scade fra {int((float(d.get('scade', 0)) - t) / 60)} min  usi {d.get('usi', 0)}  «{d.get('richiesta', '')[:70]}»")
        return 0
    if cmd == "apri" and len(argv) >= 3:
        print("aperto" if apri(argv[1], argv[2], "a mano") else "non aperto")
        return 0
    if cmd == "revoca" and len(argv) >= 2:
        print("revocato" if revoca(argv[1]) else "non c'era")
        return 0
    if cmd == "giro":
        r, n = giro(_sessioni_con_presa())
        print(f"revocati {r}, rinnovati {n}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
