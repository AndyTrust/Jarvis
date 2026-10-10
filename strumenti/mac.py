#!/usr/bin/env python3
"""Le mani di Jarvis sul Mac: schermo, mouse, tastiera, app, finestre, sistema.

Uso: python3 strumenti/mac.py <comando> [argomenti]

Guardare (non cambiano niente):
  guarda [file.png]          screenshot; stampa il file e la misura in punti (le coordinate per clic)
  app                        app aperte, quella in primo piano per prima
  finestre [app]             finestre visibili con posizione e misura, in punti
  mouse                      dov'è il puntatore
  appunti                    testo negli appunti
  stato                      batteria, volume, Wi-Fi, disco, app in primo piano
  trova "<testo>" [app]      dove sta un testo o un bottone: Accessibilità dell'app, poi OCR dello schermo
  posizioni [app]            i punti imparati per ogni app (relativi alla finestra)

Calibrare e ricordare (strumenti/mac-memoria.json):
  calibra                    misura schermi e scala, prova il puntatore, salva la calibrazione
  clicca "<testo>" [app]     trova e clicca; se riesce ricorda il punto per quella app
  ricorda <app> <nome> <x> <y>   salva un punto a mano (x,y dello schermo, in punti)
  vai <app> <nome>           clicca un punto imparato, ricalcolato su dove sta ora la finestra

Agire:
  apri <app|url|file>        apre un'app per nome, un indirizzo web o un file
  attiva <app>               porta un'app in primo piano
  esci <app>                 chiude un'app come Cmd+Q (se c'è da salvare, l'app lo chiede)
  clic <x> <y> [doppio|destro]   clic in punti (misura data da «guarda»)
  muovi <x> <y>
  trascina <x1> <y1> <x2> <y2>
  scrivi "<testo>"           digita il testo nell'app in primo piano
  tasto <combinazione>       es. cmd+c, cmd+shift+4, invio, esc, tab, su, giu, f5
  scorri <su|giu> [passi]
  volume <0-100|muto|audio>
  copia "<testo>"            mette il testo negli appunti
  notifica "<testo>" [titolo]
  menu <app> "<Menu>" "<Voce>"   sceglie una voce dal menu di un'app
  scorciatoia "<nome>"       lancia un Comando rapido di macOS
  applescript "<codice>"     AppleScript libero, per quello che non ha un comando

Le coordinate sono in punti, non in pixel: lo screenshot Retina è grande il
doppio e «guarda» stampa già la misura giusta. Serve il permesso di
Accessibilità (mouse e tastiera) e di Registrazione schermo (screenshot) al
programma che lancia Jarvis: «mac.py permessi» dice cosa manca.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CLICLICK = shutil.which("cliclick") or "/opt/homebrew/bin/cliclick"
CARTELLA_SCHERMATE = Path("/tmp/jarvis-schermate")
QUI = Path(__file__).resolve().parent
OCCHI = QUI / "bin" / "occhi"
MEMORIA = QUI / "mac-memoria.json"

TASTI = {  # nome -> key code di macOS
    "invio": 36, "enter": 36, "return": 36, "tab": 48, "spazio": 49, "space": 49,
    "canc": 51, "backspace": 51, "delete": 51, "esc": 53, "escape": 53,
    "cancdx": 117, "forwarddelete": 117, "home": 115, "fine": 119, "end": 119,
    "pagsu": 116, "pageup": 116, "paggiu": 121, "pagedown": 121,
    "sinistra": 123, "left": 123, "destra": 124, "right": 124,
    "giu": 125, "down": 125, "su": 126, "up": 126,
    **{f"f{i}": c for i, c in zip(range(1, 13), [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111])},
}
MODIFICATORI = {"cmd": "command down", "command": "command down", "shift": "shift down",
                "alt": "option down", "opt": "option down", "option": "option down",
                "ctrl": "control down", "control": "control down", "fn": "function down"}


def esci_con(msg, codice=1):
    print(msg, file=sys.stderr)
    sys.exit(codice)


def osa(codice, controlla=True):
    r = subprocess.run(["osascript", "-e", codice], capture_output=True, text=True)
    if controlla and r.returncode != 0:
        esci_con(f"AppleScript: {r.stderr.strip()}")
    return r.stdout.strip()


def stringa_as(testo):
    return '"' + testo.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cli(*argomenti):
    if not Path(CLICLICK).exists():
        esci_con("manca cliclick: brew install cliclick")
    r = subprocess.run([CLICLICK, *argomenti], capture_output=True, text=True)
    if r.returncode != 0:
        esci_con(f"cliclick: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def misura_schermo():
    """Misura dello schermo principale in punti."""
    b = osa('tell application "Finder" to get bounds of window of desktop')
    x1, y1, x2, y2 = (int(v) for v in b.split(", "))
    return x2 - x1, y2 - y1


SEGRETI = re.compile(r"\b(sk-ant-[\w-]+|sk-[\w-]{20,}|gh[pousr]_\w{20,}|github_pat_\w+|xox[abpr]-[\w-]+|"
                     r"AKIA[0-9A-Z]{16}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+)")


def nascondi_segreti(testo):
    """Chiavi e token negli appunti non finiscono nella conversazione."""
    return SEGRETI.sub(lambda m: m.group(0)[:7] + "…[nascosto]", testo)


# ---------- guardare ----------

def guarda(dest=None):
    CARTELLA_SCHERMATE.mkdir(exist_ok=True)
    f = Path(dest) if dest else CARTELLA_SCHERMATE / time.strftime("schermo-%H%M%S.png")
    subprocess.run(["screencapture", "-x", "-C", str(f)], check=True)
    larghezza, altezza = misura_schermo()
    # rimpicciolisce a misura di punti: l'immagine costa meno e le coordinate coincidono
    subprocess.run(["sips", "-z", str(altezza), str(larghezza), str(f)], capture_output=True)
    print(json.dumps({"file": str(f), "punti": [larghezza, altezza],
                      "nota": "l'immagine è già in punti: le coordinate valgono per clic"}))


def app_aperte():
    s = osa('tell application "System Events" to get name of every application process '
            'whose background only is false')
    primo = osa('tell application "System Events" to get name of first application process '
                'whose frontmost is true')
    nomi = [n for n in s.split(", ") if n]
    print("\n".join([f"* {primo}"] + [f"  {n}" for n in nomi if n != primo]))


def finestre(app=None):
    filtro = f' whose name is {stringa_as(app)}' if app else ' whose background only is false'
    codice = f'''
set out to ""
tell application "System Events"
  repeat with p in (every application process{filtro})
    repeat with w in (every window of p)
      try
        set {{x, y}} to position of w
        set {{l, h}} to size of w
        set out to out & (name of p) & " | " & (name of w) & " | " & x & "," & y & " " & l & "x" & h & linefeed
      end try
    end repeat
  end repeat
end tell
return out'''
    print(osa(codice) or "nessuna finestra")


def stato():
    batteria = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    righe = batteria.strip().splitlines()
    # il nome della rete macOS lo nasconde ai programmi senza permesso di posizione: basta sapere se c'è rete
    ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
    disco = shutil.disk_usage("/")
    vol = osa("output volume of (get volume settings)", False)
    muto = osa("output muted of (get volume settings)", False) == "true"
    primo = osa('tell application "System Events" to get name of first application process '
                'whose frontmost is true', False)
    print(f"batteria: {righe[-1].split(chr(9))[-1] if righe else '?'}")
    print(f"Wi-Fi: {'connesso, ' + ip if ip else 'non connesso'}")
    print(f"disco libero: {disco.free // 2**30} GB su {disco.total // 2**30}")
    print(f"volume: {vol}{' (muto)' if muto else ''}")
    print(f"in primo piano: {primo}")


def permessi():
    ok = True
    r = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of '
                        'first application process whose frontmost is true'], capture_output=True, text=True)
    if r.returncode != 0:
        ok = False
        print("✗ Accessibilità / Automazione: manca (Impostazioni > Privacy e sicurezza > Accessibilità)")
    else:
        print("✓ Accessibilità / Automazione")
    f = CARTELLA_SCHERMATE / "prova-permessi.png"
    CARTELLA_SCHERMATE.mkdir(exist_ok=True)
    subprocess.run(["screencapture", "-x", str(f)], capture_output=True)
    # senza permesso lo screenshot esce ma mostra solo lo sfondo: file piccolo o vuoto
    if not f.exists() or f.stat().st_size < 20000:
        ok = False
        print("✗ Registrazione schermo: manca o lo screenshot è vuoto")
    else:
        print(f"✓ Registrazione schermo (controllare a occhio {f}: se si vedono solo sfondo e barra, manca)")
    print("✓ cliclick" if Path(CLICLICK).exists() else "✗ cliclick: brew install cliclick")
    sys.exit(0 if ok else 1)


# ---------- occhi, calibrazione, memoria delle posizioni ----------

def occhi(*argomenti, controlla=True):
    if not OCCHI.exists() or OCCHI.stat().st_mtime < (QUI / "occhi.swift").stat().st_mtime:
        r = subprocess.run(["swiftc", "-O", str(QUI / "occhi.swift"), "-o", str(OCCHI)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            esci_con(f"compilazione di occhi fallita: {r.stderr[-500:]}")
    r = subprocess.run([str(OCCHI), *argomenti], capture_output=True, text=True)
    if r.returncode != 0:
        if controlla:
            esci_con(f"occhi: {r.stderr.strip()}")
        return None
    return json.loads(r.stdout)


def leggi_memoria():
    try:
        return json.loads(MEMORIA.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"calibrazione": {}, "app": {}}


def salva_memoria(m):
    tmp = MEMORIA.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False))
    tmp.replace(MEMORIA)


def adesso():
    return time.strftime("%Y-%m-%d %H:%M")


def calibra():
    """Misura quello che serve per non sbagliare i clic e verifica il puntatore."""
    schermi = occhi("schermi")
    principale = schermi[0]
    CARTELLA_SCHERMATE.mkdir(exist_ok=True)
    grezzo = CARTELLA_SCHERMATE / "calibra.png"
    subprocess.run(["screencapture", "-x", "-m", str(grezzo)], check=True)
    px = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(grezzo)],
                        capture_output=True, text=True).stdout
    lpx, hpx = (int(v) for v in re.findall(r": (\d+)", px))
    scala = round(lpx / principale["l"], 2)
    # prova del puntatore: va in quattro punti e rilegge dove è arrivato
    vecchio = cli("p:.")
    scarti = []
    for fx, fy in [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.5)]:
        x, y = int(principale["l"] * fx), int(principale["h"] * fy)
        cli(f"m:{x},{y}")
        time.sleep(0.05)
        rx, ry = (int(float(v)) for v in cli("p:.").split(","))
        scarti.append(abs(rx - x) + abs(ry - y))
    cli(f"m:{vecchio}")
    cal = {"quando": adesso(), "schermi": schermi, "pixel_screenshot": [lpx, hpx], "scala": scala,
           "punti": [principale["l"], principale["h"]], "scarto_puntatore_max": max(scarti),
           "regola": "coordinate dei clic = pixel dello screenshot grezzo / scala; "
                     "«guarda» rimpicciolisce già a punti"}
    m = leggi_memoria()
    vecchia = m.get("calibrazione", {})
    m["calibrazione"] = cal
    salva_memoria(m)
    cambiata = vecchia and (vecchia.get("scala"), vecchia.get("punti")) != (scala, cal["punti"])
    print(json.dumps(cal, ensure_ascii=False))
    if cambiata:
        print(f"ATTENZIONE: prima era scala {vecchia.get('scala')} e {vecchia.get('punti')}: "
              "i punti imparati per le app vanno riverificati")
    if max(scarti) > 2:
        esci_con(f"il puntatore non arriva dove lo mando (scarto {max(scarti)} punti)")


def finestra_di(app):
    return occhi("finestra", app, controlla=False) if app else None


def app_davanti():
    """Nome nella lingua del sistema (Calcolatrice, non Calculator): lo stesso che usa «occhi»."""
    return occhi("davanti")["davanti"]


def ocr_schermo():
    """OCR sullo screenshot a piena risoluzione (più preciso), coordinate già in punti."""
    CARTELLA_SCHERMATE.mkdir(exist_ok=True)
    f = CARTELLA_SCHERMATE / "ocr.png"
    subprocess.run(["screencapture", "-x", "-m", str(f)], check=True)
    l, h = occhi("schermi")[0]["l"], occhi("schermi")[0]["h"]
    return occhi("ocr", str(f), str(l), str(h))


def trova_testo(testo, app=None):
    """Prima l'albero di Accessibilità (esatto), poi l'OCR (vede tutto, anche le app che non si descrivono)."""
    cerca = testo.lower()
    trovati = []
    if app:
        for e in occhi("ax", app, controlla=False) or []:
            if cerca in e["testo"].lower():
                trovati.append({**e, "via": "ax", "esatto": e["testo"].lower() == cerca})
    if not trovati:
        # con l'app indicata l'OCR guarda solo dentro la sua finestra: fuori ci sono altre app,
        # compreso il terminale di Jarvis che contiene il testo stesso che si cerca
        w = finestra_di(app)
        parola = re.compile(r"(?<!\w)" + re.escape(cerca) + r"(?!\w)")
        for e in ocr_schermo():
            if cerca not in e["testo"].lower():
                continue
            if w and not (w["x"] <= e["cx"] <= w["x"] + w["l"] and w["y"] <= e["cy"] <= w["y"] + w["h"]):
                continue
            trovati.append({**e, "via": "ocr", "esatto": e["testo"].lower().strip() == cerca,
                            "parola": bool(parola.search(e["testo"].lower()))})
    # prima le corrispondenze esatte, poi le parole intere, poi i testi più corti (meno ambigui)
    trovati.sort(key=lambda e: (not e["esatto"], not e.get("parola", True), len(e["testo"])))
    return trovati


def trova(testo, app=None):
    t = trova_testo(testo, app)
    print(json.dumps(t[:10], ensure_ascii=False) if t else f"«{testo}» non trovato")
    sys.exit(0 if t else 1)


def ricorda_punto(app, nome, x, y, via):
    """Il punto si salva relativo alla finestra: se la finestra si sposta resta giusto."""
    w = finestra_di(app)
    m = leggi_memoria()
    voce = m.setdefault("app", {}).setdefault(app, {}).get(nome, {"usi": 0})
    voce.update({"usi": voce.get("usi", 0) + 1, "via": via, "ultimo": adesso(),
                 "schermo": [int(x), int(y)]})
    if w:
        voce["relativo"] = [int(x) - w["x"], int(y) - w["y"]]
        voce["finestra"] = [w["l"], w["h"]]
    m["app"][app][nome] = voce
    salva_memoria(m)
    return voce


def clic_sicuro(x, y, app=None):
    """Porta l'app davanti prima del clic: sulle app native il primo clic su una finestra
    non attiva serve solo a darle il fuoco e non arriva al bottone."""
    if app and app_davanti().lower() != app.lower():
        r = occhi("attiva", app)
        if not r["ok"]:
            esci_con(f"{app} non è venuta davanti (davanti c'è {r['davanti']}): clic annullato")
        time.sleep(0.3)
    occhi("clic", str(x), str(y))


def clicca(testo, app=None):
    app = app or app_davanti()
    t = trova_testo(testo, app)
    if not t:
        esci_con(f"«{testo}» non trovato né nell'Accessibilità di {app} né sullo schermo")
    e = t[0]
    prima = app_davanti()
    clic_sicuro(e["cx"], e["cy"], app)
    voce = ricorda_punto(app, testo, e["cx"], e["cy"], e["via"])
    print(json.dumps({"cliccato": testo, "app": app, "punto": [e["cx"], e["cy"]], "via": e["via"],
                      "alternative": len(t) - 1, "davanti_prima": prima, "usi": voce["usi"]},
                     ensure_ascii=False))
    print("verifica con «guarda»: il punto è ricordato, ma che il clic abbia fatto effetto lo dice solo lo schermo")


def vai(app, nome):
    voce = leggi_memoria().get("app", {}).get(app, {}).get(nome)
    if not voce:
        esci_con(f"nessun punto «{nome}» ricordato per {app}. «posizioni {app}» per l'elenco")
    w = finestra_di(app)
    if w and "relativo" in voce:
        x, y = w["x"] + voce["relativo"][0], w["y"] + voce["relativo"][1]
        if voce.get("finestra") and voce["finestra"] != [w["l"], w["h"]]:
            print(f"nota: la finestra ha cambiato misura ({voce['finestra']} → {[w['l'], w['h']]}): "
                  f"se il clic non va, «clicca \"{nome}\" {app}» lo ritrova e lo aggiorna")
    else:
        x, y = voce["schermo"]
    clic_sicuro(x, y, app)
    ricorda_punto(app, nome, x, y, voce.get("via", "memoria"))
    print(f"clic su «{nome}» di {app} in {x},{y}")


def posizioni(app=None):
    m = leggi_memoria()
    dati = {app: m.get("app", {}).get(app, {})} if app else m.get("app", {})
    print(json.dumps({"calibrazione": m.get("calibrazione", {}).get("quando"), "app": dati},
                     indent=1, ensure_ascii=False))


# ---------- agire ----------

def apri(bersaglio):
    if "://" in bersaglio or bersaglio.startswith("www."):
        url = bersaglio if "://" in bersaglio else "https://" + bersaglio
        subprocess.run(["open", url], check=True)
    elif Path(bersaglio).expanduser().exists():
        subprocess.run(["open", str(Path(bersaglio).expanduser())], check=True)
    else:
        r = subprocess.run(["open", "-a", bersaglio], capture_output=True, text=True)
        if r.returncode != 0:
            esci_con(f"non trovo l'app «{bersaglio}»: {r.stderr.strip()}")
    print(f"aperto: {bersaglio}")


def attiva(app):
    osa(f"tell application {stringa_as(app)} to activate")
    time.sleep(0.4)
    print(f"in primo piano: {app}")


def esci_app(app):
    osa(f"tell application {stringa_as(app)} to quit")
    print(f"chiesto a {app} di chiudersi")


def clic(x, y, tipo=None):
    comando = {"doppio": "dc", "destro": "rc"}.get(tipo, "c")
    cli(f"{comando}:{int(float(x))},{int(float(y))}")
    print(f"clic {tipo or 'singolo'} su {x},{y}")


def scrivi(testo):
    # la via degli appunti regge accenti, emoji e testi lunghi meglio di keystroke
    vecchi = subprocess.run(["pbpaste"], capture_output=True).stdout
    subprocess.run(["pbcopy"], input=testo.encode(), check=True)
    osa('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.3)
    subprocess.run(["pbcopy"], input=vecchi)
    print(f"scritto {len(testo)} caratteri")


def tasto(combinazione):
    parti = combinazione.lower().replace("-", "+").split("+")
    mod = [MODIFICATORI[p] for p in parti[:-1] if p in MODIFICATORI]
    sconosciuti = [p for p in parti[:-1] if p not in MODIFICATORI]
    if sconosciuti:
        esci_con(f"modificatori sconosciuti: {sconosciuti}")
    finale = parti[-1]
    using = f" using {{{', '.join(mod)}}}" if mod else ""
    if finale in TASTI:
        osa(f'tell application "System Events" to key code {TASTI[finale]}{using}')
    elif len(finale) == 1:
        osa(f'tell application "System Events" to keystroke {stringa_as(finale)}{using}')
    else:
        esci_con(f"tasto sconosciuto: {finale}")
    print(f"premuto {combinazione}")


def scorri(verso, passi=5):
    tasto_code = 125 if verso in ("giu", "down") else 126
    for _ in range(int(passi)):
        osa(f'tell application "System Events" to key code {tasto_code}')
    print(f"scorso {verso} di {passi}")


def volume(valore):
    if valore == "muto":
        osa("set volume output muted true")
    elif valore == "audio":
        osa("set volume output muted false")
    else:
        osa(f"set volume output volume {max(0, min(100, int(valore)))} without output muted")
    print(f"volume: {valore}")


def menu(app, *voci):
    if len(voci) < 2:
        esci_con('uso: menu <app> "<Menu>" "<Voce>" ["<Sottovoce>"]')
    percorso = f"menu item {stringa_as(voci[-1])}"
    for v in reversed(voci[1:-1]):
        percorso += f" of menu {stringa_as(v)} of menu item {stringa_as(v)}"
    percorso += f" of menu {stringa_as(voci[0])} of menu bar item {stringa_as(voci[0])} of menu bar 1"
    osa(f'tell application {stringa_as(app)} to activate\n'
        f'tell application "System Events" to tell process {stringa_as(app)} to click {percorso}')
    print(f"menu {app}: {' > '.join(voci)}")


# I comandi che AGISCONO sullo schermo: due che muovono lo stesso mouse si
# rubano il primo piano a vicenda, ed è già successo il 20/09/2026 fra due
# sessioni. Guardare (`guarda`, `stato`, `trova`, `app`) non dà fastidio a
# nessuno e resta libero.
AGISCONO = ("clic", "clicca", "muovi", "trascina", "scrivi", "tasto", "scorri",
            "vai", "menu", "apri", "attiva", "esci", "copia", "scorciatoia",
            "applescript", "volume", "calibra")


def chiave_o_fermati():
    """La serratura dello schermo. Una regola in un profilo è solo un prompt: il
    modello che se la dimentica muove il mouse lo stesso. Qui il comando si
    ferma da solo se `mac-schermo` è in mano a un altro.

    Non chiede di aver preso la chiave: ferma solo lo scontro vero. Chi lavora
    da solo non deve dichiarare niente per muovere il mouse."""
    lavori = Path(__file__).resolve().parent / "lavori.py"
    if not lavori.is_file():
        return
    try:
        r = subprocess.run([sys.executable, str(lavori), "libera", "mac-schermo"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return            # il registro non deve mai poter bloccare il Mac
    if r.returncode == 3:
        print(r.stdout.strip())
        print("\nNon tocco lo schermo: aspetta che finisca, o prenditi la chiave con\n"
              '  python3 strumenti/lavori.py prendo "<progetto>" "<cosa>" --risorse mac-schermo')
        sys.exit(3)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "aiuto"):
        print(__doc__)
        return
    c, a = sys.argv[1], sys.argv[2:]
    if c in AGISCONO:
        chiave_o_fermati()
    comandi = {
        "guarda": lambda: guarda(*a[:1]),
        "app": app_aperte,
        "finestre": lambda: finestre(*a[:1]),
        "mouse": lambda: print(cli("p:.")),
        "appunti": lambda: print(nascondi_segreti(
            subprocess.run(["pbpaste"], capture_output=True, text=True).stdout)),
        "stato": stato,
        "calibra": calibra,
        "trova": lambda: trova(a[0], *a[1:2]),
        "clicca": lambda: clicca(a[0], *a[1:2]),
        "ricorda": lambda: print(json.dumps(ricorda_punto(a[0], a[1], a[2], a[3], "a mano"), ensure_ascii=False)),
        "vai": lambda: vai(a[0], a[1]),
        "posizioni": lambda: posizioni(*a[:1]),
        "permessi": permessi,
        "apri": lambda: apri(" ".join(a)),
        "attiva": lambda: attiva(" ".join(a)),
        "esci": lambda: esci_app(" ".join(a)),
        "clic": lambda: clic(*a[:3]),
        "muovi": lambda: (cli(f"m:{int(float(a[0]))},{int(float(a[1]))}"), print("mosso")),
        "trascina": lambda: (cli(f"dd:{a[0]},{a[1]}", f"du:{a[2]},{a[3]}"), print("trascinato")),
        "scrivi": lambda: scrivi(" ".join(a)),
        "tasto": lambda: tasto(a[0]),
        "scorri": lambda: scorri(*a[:2]),
        "volume": lambda: volume(a[0]),
        "copia": lambda: (subprocess.run(["pbcopy"], input=" ".join(a).encode(), check=True),
                          print("copiato negli appunti")),
        "notifica": lambda: (osa(f"display notification {stringa_as(a[0])} with title "
                                 f"{stringa_as(a[1] if len(a) > 1 else 'Jarvis')}"), print("notifica mandata")),
        "menu": lambda: menu(*a),
        "scorciatoia": lambda: subprocess.run(["shortcuts", "run", " ".join(a)], check=True),
        "applescript": lambda: print(osa(" ".join(a))),
    }
    if c not in comandi:
        esci_con(f"comando sconosciuto: {c}. «mac.py aiuto» per l'elenco")
    try:
        comandi[c]()
    except (IndexError, ValueError):
        esci_con(f"argomenti sbagliati per «{c}». «mac.py aiuto» per l'elenco")


if __name__ == "__main__":
    main()
