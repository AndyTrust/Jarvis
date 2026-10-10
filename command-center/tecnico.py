#!/usr/bin/env python3
"""Il banco tecnico dell'app Android, per il Command Center.

Serve all'utente quando programma l'app: dice com'è messo il telefono e permette
le poche cose che servono davvero per capire dove intervenire. Sta separato dal
resto del pannello apposta — decisione dell'utente del 2026-09-20 — perché mescolare
il collaudo dell'app con i comandi di tutti i giorni fa credere che l'app
funzioni solo perché funziona il Mac.

Regola che vale per tutto quello che c'è qui: **si guarda, non si comanda il
telefono**. Le uniche due cose che scrivono sono accendere e spegnere il modo
tecnico, e riavviare l'app. Toccare lo schermo da qui non si fa: per quello c'è
telefono/android/agisci.sh, che è un'altra cosa e parte da un incarico dell'utente.

Uso a mano:
    python3 command-center/tecnico.py stato
    python3 command-center/tecnico.py log 40
"""
import json
import re
import subprocess
import sys
from pathlib import Path

CASA = Path(__file__).resolve().parent.parent
PACCHETTO = "com.jarvis.app"
CHIAVE_DEBUG = "debug_sbloccato"


def _adb(*args, timeout=12):
    """Lancia adb e torna (esito, uscita). Non solleva: qui niente deve esplodere."""
    try:
        r = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"


def collegato():
    ok, out = _adb("devices")
    if not ok:
        return None
    for riga in out.splitlines()[1:]:
        pezzi = riga.split()
        if len(pezzi) >= 2 and pezzi[1] == "device":
            return pezzi[0]
    return None


def _prop(chiave):
    ok, out = _adb("shell", "getprop", chiave)
    return out.strip() if ok else ""


def versione():
    ok, out = _adb("shell", "dumpsys", "package", PACCHETTO)
    if not ok:
        return {}
    nome = re.search(r"versionName=(\S+)", out)
    codice = re.search(r"versionCode=(\d+)", out)
    return {"nome": nome.group(1) if nome else "?", "codice": int(codice.group(1)) if codice else 0}


def servizio_acceso():
    """True solo se JarvisService gira davvero dentro un processo dell'app.

    Cercare il nome nel dump non basta: resta un ServiceRecord anche per una
    richiesta rifiutata, e lì `app=null`. Il 20/09/2026 quel controllo dava
    «acceso» mentre Jarvis sul telefono era spento.
    """
    ok, out = _adb("shell", "dumpsys", "activity", "services", PACCHETTO)
    if not ok:
        return False
    dentro = False
    for riga in out.splitlines():
        spoglia = riga.strip()
        if spoglia.startswith("* ServiceRecord"):
            dentro = "/.JarvisService" in spoglia
        elif dentro and spoglia.startswith("app="):
            return spoglia != "app=null"
    return False


def accessibilita_attiva():
    ok, out = _adb("shell", "settings", "get", "secure", "enabled_accessibility_services")
    return ok and PACCHETTO in out


def batteria():
    ok, out = _adb("shell", "dumpsys", "battery")
    if not ok:
        return None
    m = re.search(r"level:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def debug_acceso():
    """Legge la preferenza dentro l'app. Funziona perché è una build di debug."""
    ok, out = _adb("shell", "run-as", PACCHETTO, "cat", "shared_prefs/jarvis_prefs.xml")
    if not ok:
        return None
    m = re.search(rf'name="{CHIAVE_DEBUG}"\s+value="(true|false)"', out)
    return m.group(1) == "true" if m else False


def imposta_debug(acceso: bool):
    """Accende o spegne il modo tecnico sul telefono, e riavvia l'app perché lo legga.

    Non chiede la password: da qui la porta l'ha già aperta l'utente entrando nel
    suo Mac. La password serve sul telefono, dove chiunque lo prenda in mano
    potrebbe premere il pulsante.
    """
    if collegato() is None:
        return False, "Nessun telefono collegato"
    prima = debug_acceso()
    if prima is None:
        return False, "Non riesco a leggere le preferenze dell'app (è una build di release?)"
    valore = "true" if acceso else "false"
    # Si riscrive il file delle preferenze con sed dentro il sandbox dell'app.
    comando = (
        f"run-as {PACCHETTO} sh -c "
        f"\"if grep -q '{CHIAVE_DEBUG}' shared_prefs/jarvis_prefs.xml; then "
        f"sed -i 's|name=\\\"{CHIAVE_DEBUG}\\\" value=\\\"[a-z]*\\\"|name=\\\"{CHIAVE_DEBUG}\\\" value=\\\"{valore}\\\"|' shared_prefs/jarvis_prefs.xml; "
        f"else sed -i 's|</map>|<boolean name=\\\"{CHIAVE_DEBUG}\\\" value=\\\"{valore}\\\" /></map>|' shared_prefs/jarvis_prefs.xml; fi\""
    )
    ok, out = _adb("shell", comando)
    if not ok:
        return False, f"Non riuscito: {out.strip()[:200]}"
    riavvia()
    dopo = debug_acceso()
    if dopo != acceso:
        return False, "Scritto, ma l'app legge ancora il valore di prima"
    return True, f"Modo tecnico {'acceso' if acceso else 'spento'}"


SERVIZIO_ACCESSIBILITA = f"{PACCHETTO}/{PACCHETTO}.JarvisAccessibilityService"


def riavvia():
    """Chiude e riapre l'app: serve perché rilegga le preferenze.

    C'è un dettaglio che costa caro se lo si ignora. `am force-stop` mette il
    pacchetto nello stato «fermato», e Android in quel momento **toglie
    l'Accessibilità**: l'app resta viva ma non può più comandare il telefono, e
    per rimetterla bisogna andare nelle impostazioni a mano. È successo il
    20/09/2026 mentre si provava questo pannello. Perciò qui si guarda com'era
    prima e la si rimette com'era.
    """
    era_attiva = accessibilita_attiva()
    _adb("shell", "am", "force-stop", PACCHETTO)
    ok, out = _adb("shell", "monkey", "-p", PACCHETTO, "-c", "android.intent.category.LAUNCHER", "1")
    if era_attiva and not accessibilita_attiva():
        _adb("shell", "settings", "put", "secure", "enabled_accessibility_services", SERVIZIO_ACCESSIBILITA)
        _adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
        if not accessibilita_attiva():
            return False, "Riaperta, ma l'Accessibilità non è tornata: rimettila a mano nelle impostazioni"
    return ok, out.strip()[:200]


def log_ponte(righe=40):
    """Le diagnosi che il telefono manda alla VPS: è lì che si vede cosa è successo."""
    script = CASA / "strumenti" / "vps-leggi.sh"
    if not script.exists():
        return []
    try:
        r = subprocess.run(["bash", str(script), "log", "jarvis-agent", str(max(righe * 4, 80))],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    fuori = []
    for riga in (r.stdout or "").splitlines():
        if "diag:" in riga:
            fuori.append(riga.split("diag:", 1)[1].strip())
        elif "[ws]" in riga and ("connessione" in riga or "chiusa" in riga or "autenticato" in riga):
            fuori.append(riga.split("]", 1)[-1].strip())
    return fuori[-righe:]


def stato():
    apparecchio = collegato()
    if apparecchio is None:
        return {
            "collegato": False,
            "perche": "Nessun telefono: serve il Debug wireless acceso e la stessa Wi-Fi",
        }
    v = versione()
    return {
        "collegato": True,
        "apparecchio": apparecchio,
        "modello": _prop("ro.product.model"),
        "android": _prop("ro.build.version.release"),
        "batteria": batteria(),
        "versione": v.get("nome"),
        "codice": v.get("codice"),
        "servizio": servizio_acceso(),
        "accessibilita": accessibilita_attiva(),
        "debug": debug_acceso(),
    }


if __name__ == "__main__":
    cosa = sys.argv[1] if len(sys.argv) > 1 else "stato"
    if cosa == "stato":
        print(json.dumps(stato(), indent=1, ensure_ascii=False))
    elif cosa == "log":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        for r in log_ponte(n):
            print(" ", r)
    elif cosa in ("accendi", "spegni"):
        print(imposta_debug(cosa == "accendi")[1])
    elif cosa == "riavvia":
        print(riavvia()[1] or "riavviata")
    else:
        sys.exit(__doc__)
