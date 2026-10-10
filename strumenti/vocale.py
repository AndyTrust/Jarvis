#!/usr/bin/env python3
"""Vocali di Telegram per Jarvis, solo in locale: faster-whisper per il testo, Kokoro (if_sara) per la voce.

Uso: python3 strumenti/vocale.py testo <file_id>     trascrive un vocale del bot
     python3 strumenti/vocale.py voce "<testo>"     lo legge con la voce di Jarvis e lo manda all'utente come nota vocale
     python3 strumenti/vocale.py file "<testo>" <out.ogg|out.wav>   salva soltanto l'audio, non manda niente

file_id è l'attachment_file_id del messaggio Telegram: non serve scaricare il file a mano.
Il motore vero è /opt/jarvis-voce/locale.py (faster-whisper + Kokoro, solo sulla VPS). ffmpeg fa
il WAV in OGG/Opus e sendVoice lo manda col token del bot (TELEGRAM_BOT_TOKEN nel .env di
TELEGRAM_STATE_DIR, o telegram-vps / telegram-jarviutente). Il token non si stampa.

28/09/2026, decisione dell'utente: Gemini via n8n-jarvis è tolto, non si usa più per i vocali —
né come motore principale né come riserva. Su una macchina senza /opt/jarvis-voce (oggi: il Mac)
questo script si ferma e lo dice, non prova più a chiamare n8n.
"""
import json
import subprocess
import sys
import tempfile
import uuid
import wave
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

CHAT_UTENTE = ""
# VPS e Mac hanno ognuno la sua copia (stessa interfaccia: trascrivi/parla), nel posto giusto
# per ciascuna macchina — /opt/ non esiste sul Mac, ~/Jarvis non esiste sulla VPS.
LOCALE = next((p for p in (Path("/opt/jarvis-voce/locale.py"),
                            Path.home() / "Jarvis" / "jarvis-voce" / "locale.py") if p.exists()),
              Path("/opt/jarvis-voce/locale.py"))
CARTELLE_BOT = [os.environ.get("TELEGRAM_STATE_DIR", ""), "~/.claude/channels/telegram-vps", "~/.claude/channels/telegram-jarviutente"]
COMANDI = ("testo", "voce", "file")


def motore(nome):
    print(f"motore: {nome}", file=sys.stderr)


def locale(*argomenti):
    """Lancia /opt/jarvis-voce/locale.py (si mette da solo a nice 10 e 2 thread) e restituisce lo stdout."""
    if not LOCALE.exists():
        sys.exit(f"manca {LOCALE}: qui non c'è la voce locale (Gemini non si usa più per i vocali)")
    r = subprocess.run([sys.executable, str(LOCALE), *argomenti], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        sys.exit(f"la voce locale ha fallito: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout.strip()


def scarica_da_telegram(file_id, dest):
    """getFile e download col token del bot. Gli errori non riportano l'indirizzo, che contiene il token."""
    base = f"https://api.telegram.org/bot{token()}"
    try:
        with urllib.request.urlopen(f"{base}/getFile?file_id={urllib.parse.quote(file_id)}", timeout=30) as r:
            percorso = json.loads(r.read())["result"]["file_path"]
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token()}/{percorso}", timeout=60) as r:
            dest.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Telegram non ha dato il file: {e.code}")
    except (urllib.error.URLError, KeyError, ValueError) as e:
        sys.exit(f"Telegram non ha dato il file: {type(e).__name__}")


def trascrivi(file_id):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "vocale.oga"
        scarica_da_telegram(file_id, f)
        testo = locale("trascrivi", str(f))
    motore("locale (faster-whisper small)")
    return testo


def token():
    for c in CARTELLE_BOT:
        f = Path(c).expanduser() / ".env" if c else None
        if f and f.exists():
            for riga in f.read_text().splitlines():
                if riga.startswith("TELEGRAM_BOT_TOKEN="):
                    return riga.split("=", 1)[1].strip().strip('"')
    sys.exit("token del bot non trovato")


def audio(testo, dest):
    """Genera la voce con Kokoro locale e la salva in dest (.wav così com'è, .ogg in Opus)."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "voce.wav"
        locale("parla", testo, str(f))
        wav = f.read_bytes()
        with wave.open(str(f)) as w:
            secondi = round(w.getnframes() / w.getframerate(), 1)
    motore("locale (kokoro if_sara)")
    if dest.suffix == ".wav":
        dest.write_bytes(wav)
    else:
        with tempfile.NamedTemporaryFile(suffix=".wav") as t:
            t.write(wav)
            t.flush()
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", t.name, "-c:a", "libopus",
                            "-b:a", "32k", "-application", "voip", str(dest)], check=True)
    return secondi


def manda_vocale(ogg, secondi):
    confine = uuid.uuid4().hex
    parti = [f'--{confine}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_UTENTE}\r\n'.encode(),
             f'--{confine}\r\nContent-Disposition: form-data; name="duration"\r\n\r\n{secondi or 0}\r\n'.encode(),
             f'--{confine}\r\nContent-Disposition: form-data; name="voice"; filename="jarvis.ogg"\r\n'
             f'Content-Type: audio/ogg\r\n\r\n'.encode() + ogg.read_bytes() + b"\r\n",
             f"--{confine}--\r\n".encode()]
    req = urllib.request.Request(f"https://api.telegram.org/bot{token()}/sendVoice", data=b"".join(parti),
                                 headers={"Content-Type": f"multipart/form-data; boundary={confine}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["result"]["message_id"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Telegram ha risposto {e.code}: {e.read().decode()[:200]}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in COMANDI:
        sys.exit(__doc__)
    if sys.argv[1] == "testo":
        print(trascrivi(sys.argv[2]))
    elif sys.argv[1] == "file":
        if len(sys.argv) < 4:
            sys.exit(__doc__)
        dest = Path(sys.argv[3])
        secondi = audio(sys.argv[2], dest)
        print(f"{dest} ({secondi} s)")
    else:
        with tempfile.TemporaryDirectory() as d:
            ogg = Path(d) / "jarvis.ogg"
            secondi = audio(" ".join(sys.argv[2:]), ogg)
            mid = manda_vocale(ogg, secondi)
        print(f"nota vocale mandata all'utente ({secondi} s, messaggio {mid})")


if __name__ == "__main__":
    main()
