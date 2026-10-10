#!/usr/bin/env python3
"""Controlla che questa copia di Jarvis sia installata e funzioni, senza toccare niente di tuo.
  python3 strumenti/verifica_installazione.py            [--home CARTELLA per una casa finta] [--veloce: senza accendere il pannello]
Stampa OK / AVVISO / ERRORE per ogni cosa; esce con 1 se c'è almeno un ERRORE. Gli AVVISO sono pezzi facoltativi
spenti (voce, telefono, credenziali): non fermano il Command Center."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parents[1]
MAC = sys.platform == "darwin"


def opzione(nome, predefinito=None):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return predefinito


HOME = Path(opzione("--home", str(Path.home()))).expanduser()
righe = []


def esito(livello, cosa, dettaglio=""):
    righe.append(livello)
    print(f"{livello:8} {cosa}" + (f" — {dettaglio}" if dettaglio else ""))


def controlla_python():
    v = sys.version_info
    esito("OK" if v >= (3, 10) else "ERRORE", f"Python {v.major}.{v.minor}.{v.micro}", "serve 3.10 o più nuovo" if v < (3, 10) else "")
    for c in ("git", "curl"):
        esito("OK" if shutil.which(c) else "ERRORE", c)
    esito("OK" if shutil.which("claude") else "AVVISO", "Claude Code", "" if shutil.which("claude") else "npm i -g @anthropic-ai/claude-code, poi «claude» per il login")
    for c, perche in (("node", "controllo del JavaScript e Passbolt"), ("uv", "ambiente della voce"), ("espeak-ng", "voce italiana"),
                      ("ffmpeg", "audio dei vocali"), ("tmux", "Telegram"), ("ttyd", "terminale nel pannello"), ("cliclick", "mani sul Mac"), ("gh", "GitHub")):
        esito("OK" if shutil.which(c) else "AVVISO", c, "" if shutil.which(c) else f"facoltativo ({perche}): brew bundle --file=Brewfile")


def controlla_codice():
    sbagliati, n = [], 0
    for cartella in ("command-center", "strumenti", "sincro", "claude-config", ".claude/hooks"):
        for f in sorted((QUI / cartella).rglob("*.py")):
            if any(p in f.parts for p in (".venv", "node_modules", "__pycache__")):
                continue
            n += 1
            try:
                compile(f.read_text(encoding="utf-8"), str(f), "exec")     # solo la sintassi, senza scrivere .pyc
            except (SyntaxError, UnicodeDecodeError) as e:
                sbagliati.append(f"{f.relative_to(QUI)}: {str(e)[:80]}")
    esito("OK" if not sbagliati else "ERRORE", f"{n} file Python si compilano", "; ".join(sbagliati[:3]))
    js = QUI / "command-center" / "static" / "app.js"
    if shutil.which("node") and js.exists():
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        esito("OK" if r.returncode == 0 else "ERRORE", "app.js (la pagina) è JavaScript valido", r.stderr.strip()[:100])
    sh = [QUI / "installa.sh"] + sorted((QUI / "avvio").glob("*.command"))
    for f in sh:
        if f.exists():
            r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
            if r.returncode:
                esito("ERRORE", f"{f.name}: sintassi shell", r.stderr.strip()[:100])


def controlla_config():
    for f in ("configurazione", "spazi"):
        vero, esempio = QUI / "command-center" / f"{f}.json", QUI / "command-center" / f"{f}.esempio.json"
        if vero.exists():
            try:
                json.loads(vero.read_text(encoding="utf-8"))
                esito("OK", f"{f}.json valido")
            except ValueError as e:
                esito("ERRORE", f"{f}.json non è JSON valido", str(e)[:80])
        elif esempio.exists():
            esito("AVVISO", f"{f}.json manca", "il pannello usa l'esempio; ./installa.sh lo crea")
        else:
            esito("AVVISO", f"{f}.json e il suo esempio mancano")
    esito("OK" if (QUI / ".env.jarvis").exists() or (HOME / ".env.jarvis").exists() else "AVVISO", "credenziali (.env.jarvis)",
          "" if (QUI / ".env.jarvis").exists() or (HOME / ".env.jarvis").exists() else "facoltative: servono a Telegram, Gemini, Passbolt...")


def controlla_ambienti():
    if MAC:
        w = HOME / ".locale-onedrive" / "jarvis-widget-venv" / "bin" / "python3"
        if w.exists():
            r = subprocess.run([str(w), "-c", "import PIL, numpy, AppKit, Quartz"], capture_output=True, text=True)
            esito("OK" if r.returncode == 0 else "ERRORE", "orb: Pillow, numpy, PyObjC nel suo ambiente", r.stderr.strip()[-80:])
        else:
            esito("AVVISO", "orb: ambiente non creato", "./installa.sh (senza --senza-widget)")
    b = QUI / "backtalk" / ".venv" / "bin" / "python3"
    if b.exists():
        r = subprocess.run([str(b), "-c", "import claude_agent_sdk"], capture_output=True, text=True)
        esito("OK" if r.returncode == 0 else "ERRORE", "missioni: claude-agent-sdk", r.stderr.strip()[-80:])
        r = subprocess.run([str(b), "-c", "import faster_whisper, kokoro"], capture_output=True, text=True)
        esito("OK" if r.returncode == 0 else "AVVISO", "voce: Whisper e Kokoro", "" if r.returncode == 0 else "solo se vuoi la voce: backtalk/install.sh")
    else:
        esito("AVVISO", "missioni: ambiente non creato", "./installa.sh")


def controlla_claude_config():
    for f in ("hooks/guardia_comandi.py", "hooks/sessioni.py", "skills/aggiorna-memoria/SKILL.md", "agents/esecutore.md"):
        esito("OK" if (HOME / ".claude" / f).exists() else "AVVISO", f"~/.claude/{f}", "" if (HOME / ".claude" / f).exists() else "./installa.sh la copia")
    try:
        s = json.loads((HOME / ".claude" / "settings.json").read_text(encoding="utf-8"))
        testo = json.dumps(s.get("hooks", {}))
        for gancio in ("jarvis_status.py", "guardia_comandi.py", "sessioni.py"):
            esito("OK" if gancio in testo else "AVVISO", f"gancio {gancio} in settings.json")
    except (OSError, ValueError):
        esito("AVVISO", "~/.claude/settings.json non c'è o non è leggibile", "./installa.sh lo prepara")


def porta_libera():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def controlla_pannello():
    porta = porta_libera()
    env = {**os.environ, "CC_PROVA": "1", "CC_PORTA": str(porta), "JARVIS_STATUS_MUTO": "1"}
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    p = subprocess.Popen([sys.executable, str(QUI / "command-center" / "server.py"), "--no-open"], env=env, cwd=str(QUI),
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        pagina = None
        for _ in range(60):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                pagina = urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=2).read().decode("utf-8", "replace")
                break
            except OSError:
                continue
        if pagina is None:
            log.seek(0)
            esito("ERRORE", "il Command Center in prova non risponde", log.read()[-200:].replace("\n", " "))
            return
        esito("OK", f"il Command Center in prova risponde (porta {porta})")
        m = re.search(r'CC_TOKEN = "([^"]+)"', pagina)
        if m:
            for api in ("spazi", "stato", "catalogo"):
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{porta}/api/{api}", headers={"X-Token": m.group(1)})
                    json.loads(urllib.request.urlopen(req, timeout=60).read())
                    esito("OK", f"/api/{api} risponde con JSON valido")
                except Exception as e:  # noqa: BLE001
                    esito("ERRORE", f"/api/{api}", str(e)[:80])
    finally:
        try:
            os.killpg(p.pid, 15)
        except OSError:
            pass
        log.close()
        os.unlink(log.name)


def main():
    for titolo, f in (("Programmi", controlla_python), ("Codice", controlla_codice), ("Configurazione", controlla_config),
                      ("Ambienti Python", controlla_ambienti), ("Claude Code (~/.claude)", controlla_claude_config)):
        print(f"\n# {titolo}")
        f()
    if "--veloce" not in sys.argv:
        print("\n# Pannello")
        controlla_pannello()
    ko = righe.count("ERRORE")
    print(f"\n{righe.count('OK')} OK · {righe.count('AVVISO')} avvisi · {ko} errori")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    main()
