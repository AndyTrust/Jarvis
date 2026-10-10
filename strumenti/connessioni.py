#!/usr/bin/env python3
"""Le connessioni a tre posizioni (l'utente, 2026-10-04): ogni servizio che Jarvis può usare è «consentito»,
«chiedi» (prima di usarlo) oppure «spento». Vale anche con il bypass dei permessi, perché il controllo sta
nell'hook PreToolUse ~/.claude/hooks/connessioni_guardia.py e non nel gestore delle approvazioni.

Dati: ~/.locale-onedrive/jarvis-cc/connessioni.json (0600, fuori da git e da OneDrive).
Uso (da Jarvis, dopo il sì dell'utente):
    python3 ~/Jarvis/strumenti/connessioni.py lista
    python3 ~/Jarvis/strumenti/connessioni.py imposta <servizio> consentito|chiedi|spento
    python3 ~/Jarvis/strumenti/connessioni.py via <servizio> [--minuti 30]   # finestra dopo il sì dell'utente
    python3 ~/Jarvis/strumenti/connessioni.py chiudi <servizio>              # chiude la finestra
    python3 ~/Jarvis/strumenti/connessioni.py prova

Come si riconosce un servizio (chiavi di «corr», basta una):
  mcp      prefissi del nome dello strumento (mcp__claude_ai_Gmail__...)
  programmi primo comando di un segmento Bash (gh, vercel)
  token    una parola intera di un segmento Bash (vps-tuo)
  inizia   un segmento Bash che comincia con queste parole (git push)
  url      un testo contenuto in un segmento Bash (api.telegram.org)
Un segmento è un pezzo di comando separato da ; & | o a capo. Il testo fra virgolette è una sola parola,
quindi un messaggio di commit che nomina un servizio non lo fa scattare.

Solo libreria standard. Un errore nella lettura del file NON blocca niente (la guardia dei comandi è un'altra).
"""
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

STATI = ("consentito", "chiedi", "spento")
CARTELLA = Path(os.environ.get("CC_CONNESSIONI_DIR", Path.home() / ".locale-onedrive" / "jarvis-cc"))
FILE = CARTELLA / "connessioni.json"
FILE_USO = CARTELLA / "connessioni-uso.json"
MAX_FINESTRA_MIN = 240

PREDEFINITE = [
    {"id": "vps", "nome": "VPS (ssh)", "stato": "chiedi", "corr": {"token": ["vps-tuo"]}},
    {"id": "database", "nome": "Database e gestionali dei progetti", "stato": "chiedi",
     "corr": {"token": ["psql", "mysql", "docker exec"]}},
    {"id": "github", "nome": "GitHub (gh e git push)", "stato": "chiedi",
     "corr": {"programmi": ["gh"], "inizia": ["git push"]}},
    {"id": "gmail", "nome": "Posta Gmail", "stato": "chiedi", "corr": {"mcp": ["mcp__claude_ai_Gmail__"]}},
    {"id": "telegram", "nome": "Telegram", "stato": "chiedi",
     "corr": {"url": ["api.telegram.org"], "mcp": ["mcp__plugin_telegram"]}},
    {"id": "vercel", "nome": "Vercel", "stato": "chiedi",
     "corr": {"mcp": ["mcp__claude_ai_Vercel__"], "programmi": ["vercel"]}},
    {"id": "meta-ads", "nome": "Meta Ads", "stato": "chiedi", "corr": {"mcp": ["mcp__claude_ai_Meta__"]}},
    {"id": "slack", "nome": "Slack", "stato": "chiedi", "corr": {"mcp": ["mcp__claude_ai_Slack__"]}},
    {"id": "canva", "nome": "Canva", "stato": "chiedi", "corr": {"mcp": ["mcp__claude_ai_Canva__"]}},
    {"id": "calendario", "nome": "Google Calendar", "stato": "chiedi",
     "corr": {"mcp": ["mcp__claude_ai_Google_Calendar__"]}},
    {"id": "pienissimo", "nome": "Pienissimo (dati dei locali)", "stato": "consentito",
     "corr": {"mcp": ["mcp__claude_ai_Pienissimo_"]}},
]


class FileNonValido(ValueError):
    pass


def _scrivi(f, dati):
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{f.name}.", dir=str(f.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(dati, h, ensure_ascii=False, indent=1)
            h.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _controlla(dati):
    if not isinstance(dati, dict) or not isinstance(dati.get("servizi"), list):
        raise FileNonValido("manca l'elenco «servizi»")
    visti = set()
    for s in dati["servizi"]:
        if not isinstance(s, dict) or not re.fullmatch(r"[a-z0-9-]{1,40}", str(s.get("id", ""))):
            raise FileNonValido("servizio senza id valido")
        if s["id"] in visti:
            raise FileNonValido(f"id doppio: {s['id']}")
        visti.add(s["id"])
        if s.get("stato") not in STATI:
            raise FileNonValido(f"{s['id']}: stato {s.get('stato')!r} non valido")
        if not isinstance(s.get("corr"), dict):
            raise FileNonValido(f"{s['id']}: manca «corr»")
    via = dati.get("via", {})
    if not isinstance(via, dict) or any(not isinstance(v, (int, float)) for v in via.values()):
        raise FileNonValido("«via» non valida")
    return dati


def leggi(crea=False):
    """Il file validato. Se manca: i predefiniti (e, con crea=True, li scrive)."""
    if not FILE.exists():
        dati = {"versione": 1, "servizi": json.loads(json.dumps(PREDEFINITE)), "via": {}}
        if crea:
            _scrivi(FILE, dati)
        return dati
    with open(FILE, encoding="utf-8") as f:
        return _controlla(json.load(f))


def _segmenti(cmd):
    return [s.strip() for s in re.split(r"[;&|\n]+", cmd or "") if s.strip()]


def _parole(seg):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def _programma(parole):
    for p in parole:                                  # salta VAR=valore davanti al comando
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", p):
            return os.path.basename(p)
    return ""


def _host(parola):
    """scp e rsync scrivono utente@host:percorso: ne esce solo l'host."""
    p = parola.split("@", 1)[-1]
    return p.split(":", 1)[0]


def corrisponde(servizio, strumento, ingresso):
    c = servizio["corr"]
    strumento = str(strumento or "")
    if any(strumento.startswith(p) for p in c.get("mcp", []) if isinstance(p, str) and p):
        return True
    if strumento != "Bash":
        return False
    cmd = str((ingresso or {}).get("command") or "")
    for seg in _segmenti(cmd):
        parole = _parole(seg)
        if not parole:
            continue
        if _programma(parole) in c.get("programmi", []):
            return True
        if any(_host(p) in c.get("token", []) or p in c.get("token", []) for p in parole):
            return True
        for ini in c.get("inizia", []):
            n = ini.split()
            if parole[:len(n)] == n:
                return True
        if any(u and u in seg for u in c.get("url", [])):
            return True
    return False


def trova(strumento, ingresso, dati=None):
    dati = dati or leggi()
    for s in dati["servizi"]:
        if corrisponde(s, strumento, ingresso):
            return s
    return None


def finestra_aperta(dati, servizio_id, adesso=None):
    adesso = time.time() if adesso is None else adesso
    return float(dati.get("via", {}).get(servizio_id, 0)) > adesso


def valuta(strumento, ingresso, modo=None, dati=None, adesso=None):
    """(esito, servizio, motivo). esito: «passa», «chiedi» (lascia il gestore normale), «blocca»."""
    dati = dati or leggi()
    try:                                             # un passo irreversibile dichiarato in un piano: serve la conferma finale
        import piano as _piano
        motivo_piano = _piano.blocca_irreversibile(strumento, ingresso, adesso)
        if motivo_piano:
            return "blocca", trova(strumento, ingresso, dati), motivo_piano
    except Exception:  # noqa: BLE001 — i piani non devono mai rompere le connessioni
        pass
    s = trova(strumento, ingresso, dati)
    if not s:
        return "passa", None, ""
    nome = s.get("nome") or s["id"]
    if s["stato"] == "consentito":
        return "passa", s, ""
    if s["stato"] == "spento":
        return "blocca", s, (f"La connessione «{nome}» è SPENTA dall'utente. Non usarla e non cercare strade diverse: "
                             "se serve davvero, dillo all'utente.")
    if finestra_aperta(dati, s["id"], adesso):
        return "passa", s, ""
    if modo in ("bypassPermissions", "dontAsk", "auto"):
        return "blocca", s, (f"La connessione «{nome}» è su «Chiedi prima». Scrivi all'utente, in chat, cosa stai per fare "
                             "(servizio, azione, cosa cambia, cosa non tocchi) e aspetta il suo sì. Dopo il sì apri la "
                             f"finestra con: python3 ~/Jarvis/strumenti/connessioni.py via {s['id']} --minuti 30. "
                             "Per un lavoro in più passi scrivi invece un piano (python3 ~/Jarvis/strumenti/piano.py): "
                             "L'utente lo approva una volta e le finestre si aprono da sole.")
    return "chiedi", s, f"La connessione «{nome}» è su «Chiedi prima»."


def segna_uso(servizio_id, adesso=None):
    try:
        uso = json.load(open(FILE_USO, encoding="utf-8")) if FILE_USO.exists() else {}
        uso[servizio_id] = int(time.time() if adesso is None else adesso)
        _scrivi(FILE_USO, uso)
    except Exception:  # noqa: BLE001 — l'ultimo uso è un'informazione, mai un blocco
        pass


def stato_pubblico(adesso=None):
    adesso = time.time() if adesso is None else adesso
    dati = leggi()
    try:
        uso = json.load(open(FILE_USO, encoding="utf-8")) if FILE_USO.exists() else {}
    except Exception:  # noqa: BLE001
        uso = {}
    out = []
    for s in dati["servizi"]:
        scad = float(dati.get("via", {}).get(s["id"], 0))
        out.append({"id": s["id"], "nome": s.get("nome") or s["id"], "stato": s["stato"],
                    "ultimo_uso": uso.get(s["id"]), "finestra_fino": int(scad) if scad > adesso else None})
    return {"servizi": out, "stati": list(STATI), "creato": FILE.exists()}


def _registra_cambio(riga):
    """Ogni cambio lascia una riga in connessioni.log (chi, cosa, da cosa a cosa): una politica di permesso che
    cambia senza che si sappia perché è peggio di una che non cambia."""
    try:
        with open(CARTELLA / "connessioni.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} CAMBIO {riga}\n")
    except OSError:
        pass


def imposta(servizio_id, stato, origine="cli"):
    if stato not in STATI:
        raise ValueError(f"stato: {', '.join(STATI)}")
    dati = leggi(crea=True)
    for s in dati["servizi"]:
        if s["id"] == servizio_id:
            _registra_cambio(f"{servizio_id} {s['stato']}->{stato} da={origine}")
            s["stato"] = stato
            if stato != "chiedi":
                dati.setdefault("via", {}).pop(servizio_id, None)
            _scrivi(FILE, _controlla(dati))
            return s
    raise KeyError(f"servizio sconosciuto: {servizio_id}")


def via(servizio_id, minuti, origine="cli"):
    minuti = max(1, min(int(minuti), MAX_FINESTRA_MIN))
    dati = leggi(crea=True)
    if not any(s["id"] == servizio_id for s in dati["servizi"]):
        raise KeyError(f"servizio sconosciuto: {servizio_id}")
    _registra_cambio(f"{servizio_id} finestra {minuti}min da={origine}")
    dati.setdefault("via", {})[servizio_id] = time.time() + minuti * 60
    _scrivi(FILE, _controlla(dati))
    return minuti


def chiudi(servizio_id, origine="cli"):
    dati = leggi(crea=True)
    _registra_cambio(f"{servizio_id} finestra chiusa da={origine}")
    dati.setdefault("via", {}).pop(servizio_id, None)
    _scrivi(FILE, _controlla(dati))


def prova():
    d = {"servizi": json.loads(json.dumps(PREDEFINITE)), "via": {}}
    ok = True

    def v(nome, atteso, *a, **k):
        nonlocal ok
        r = valuta(*a, dati=d, **k)[0]
        bene = r == atteso
        ok &= bene
        print(("  ok   " if bene else "  FAIL ") + f"{nome}: {r}")
    v("ssh alla VPS in bypass", "blocca", "Bash", {"command": "ssh vps-tuo 'ls /'"}, "bypassPermissions")
    v("ssh alla VPS in modo normale", "chiedi", "Bash", {"command": "ssh vps-tuo uptime"}, "default")
    v("commit che nomina la VPS", "passa", "Bash", {"command": 'git commit -m "sistemata la vps-tuo"'}, "bypassPermissions")
    v("git push", "blocca", "Bash", {"command": "cd x && git push origin main"}, "bypassPermissions")
    v("git status", "passa", "Bash", {"command": "git status"}, "bypassPermissions")
    v("gh con variabile davanti", "blocca", "Bash", {"command": "GH_TOKEN=x gh pr list"}, "bypassPermissions")
    v("Gmail", "blocca", "mcp__claude_ai_Gmail__send_message", {}, "bypassPermissions")
    v("Pienissimo consentito", "passa", "mcp__claude_ai_Pienissimo_Ma__get-products", {}, "bypassPermissions")
    v("Read qualunque", "passa", "Read", {"file_path": "/etc/hosts"}, "bypassPermissions")
    d["via"]["vps"] = time.time() + 60
    v("VPS con finestra aperta", "passa", "Bash", {"command": "ssh vps-tuo uptime"}, "bypassPermissions")
    d["via"]["vps"] = time.time() - 1
    v("finestra scaduta", "blocca", "Bash", {"command": "ssh vps-tuo uptime"}, "bypassPermissions")
    d["servizi"][0]["stato"] = "spento"
    v("VPS spenta, anche con finestra", "blocca", "Bash", {"command": "scp a vps-tuo:/x"}, "default")
    v("rsync con utente@host:percorso, VPS spenta", "blocca", "Bash", {"command": "rsync -a x root@vps-tuo:/tmp/"}, "bypassPermissions")
    d["servizi"][0]["stato"] = "consentito"
    v("VPS consentita", "passa", "Bash", {"command": "ssh vps-tuo uptime"}, "bypassPermissions")
    print("tutto ok" if ok else "CI SONO ERRORI")
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "lista":
            for s in stato_pubblico()["servizi"]:
                extra = f"  (finestra aperta fino alle {time.strftime('%H:%M', time.localtime(s['finestra_fino']))})" if s["finestra_fino"] else ""
                print(f"{s['id']:<11} {s['stato']:<11} {s['nome']}{extra}")
        elif cmd == "imposta" and len(argv) == 3:
            s = imposta(argv[1], argv[2])
            print(f"{s['id']} → {s['stato']}")
        elif cmd == "via" and len(argv) >= 2:
            minuti = int(argv[argv.index("--minuti") + 1]) if "--minuti" in argv else 30
            print(f"{argv[1]}: finestra aperta per {via(argv[1], minuti)} minuti")
        elif cmd == "chiudi" and len(argv) == 2:
            chiudi(argv[1])
            print(f"{argv[1]}: finestra chiusa")
        elif cmd == "prova":
            return prova()
        else:
            print(__doc__)
            return 2
    except (KeyError, ValueError, FileNonValido) as e:
        print(f"errore: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
