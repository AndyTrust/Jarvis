#!/usr/bin/env python3
"""Talk to Jarvis, per Windows: tieni premuto Shift destro per parlare, rilascia per
inviare la richiesta (se durante la pressione tocchi un altro tasto, e' una
maiuscola: l'audio si scarta, cosi' Shift+lettera resta libero).

Motore costruito da zero per questa macchina, perche' l'unico completo nel
repo (telefono/ponte_locale.py) e' escluso su richiesta, e
avvio/Talk to Jarvis.command dipende da fullstack-agent (repo di terzi
assente):

  microfono (sounddevice) -> trascrizione locale (faster-whisper, italiano)
  -> Claude Code in modo lavoro (claude -p ... --dangerously-skip-permissions)
  -> voce italiana Sara (strumenti/kokoro/parla.py, Kokoro).

Non tocca telefono/ ne' backtalk.

Uso: python3 strumenti/talk_to_jarvis_windows.py
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "command-center")); import senza_finestre  # noqa: E402,F401  (Windows: niente finestre di terminale)
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import winsound
from pathlib import Path

import numpy as np
import sounddevice as sd
from pynput import keyboard

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI / "kokoro"))

# Stato condiviso col widget (strumenti/jarvis_widget_windows.py): stessa idea del
# "volto" sul Mac (state/state), qui un solo file JSON con stato + testo + livello
# audio vero (0-1), cosi' la bolla del widget disegna una forma d'onda vera, non finta.
STATO_FILE = QUI / "stato_voce.json"


def scrivi_stato(stato, testo="", livello=0.0):
    try:
        STATO_FILE.write_text(
            json.dumps({"stato": stato, "testo": testo, "livello": round(float(livello), 3), "ts": time.time()}),
            encoding="utf-8")
    except OSError:
        pass


def carica_env_jarvis():
    """Le credenziali (token di Claude Code, ecc.) stanno in ~/.env.jarvis,
    fuori da ogni repository (vedi README.md). Non sovrascrive variabili
    gia' impostate nell'ambiente."""
    f = Path.home() / ".env.jarvis"
    if not f.exists():
        return
    for riga in f.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, valore = riga.split("=", 1)
        chiave, valore = chiave.strip(), valore.strip().strip('"').strip("'")
        os.environ.setdefault(chiave, valore)


carica_env_jarvis()

TARGET = keyboard.Key.shift_r
FREQUENZA = 16000
MODELLO_WHISPER = "small"
LIMITE_CARATTERI_VOCE = 800
PROPORZIONE_RUMORE = 0.85  # 0-1: quanto rumore togliere; più alto pulisce di più ma può "metallizzare" la voce
SOGLIA_VOCE = 0.005        # RMS sotto cui, dopo il filtro, c'è solo rumore: da tarare sul microfono vero

_registrando = False
_frammenti = []
_stream = None
_press_t = None
_chord = False
_lock = threading.Lock()
_whisper = None
_livello_corrente = 0.0
_thread_livello = None


def log(msg):
    print(f"[talk-to-jarvis] {msg}", flush=True)


def modello_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        log("carico il modello Whisper (la prima volta scarica ~500MB)...")
        _whisper = WhisperModel(MODELLO_WHISPER, device="cpu", compute_type="int8")
    return _whisper


def filtra_rumore(audio):
    """Filtro del rumore ambientale prima di Whisper: taglia i bassi sotto 80 Hz (ventole,
    vibrazioni) e toglie il rumore costante (ronzio, condizionatore) con noisereduce.
    Se il filtro non c'è o fallisce, si trascrive l'audio com'è."""
    try:
        import noisereduce as nr
        from scipy.signal import butter, sosfilt
        audio = sosfilt(butter(4, 80, btype="highpass", fs=FREQUENZA, output="sos"), audio)
        return nr.reduce_noise(y=audio, sr=FREQUENZA, stationary=True,
                               prop_decrease=PROPORZIONE_RUMORE).astype(np.float32)
    except Exception as e:
        log(f"filtro rumore non applicato: {e}")
        return audio


def callback_audio(indata, frames, tempo, stato):
    global _livello_corrente
    if _registrando:
        _frammenti.append(indata.copy())
        # RMS del blocco appena arrivato, con un minimo di guadagno: il microfono
        # a riposo e' quasi silenzioso, senza *6 la barra non si vedrebbe muovere
        _livello_corrente = min(1.0, float(np.sqrt(np.mean(indata ** 2))) * 6)


def _scrivi_livello_in_ciclo():
    """Mentre si registra, scrive il livello vero ~10 volte al secondo: la bolla
    del widget disegna una forma d'onda vera, non un'animazione finta."""
    while _registrando:
        scrivi_stato("ascolto", "", _livello_corrente)
        time.sleep(0.08)


def inizia_registrazione():
    global _stream, _frammenti, _thread_livello
    _frammenti = []
    _stream = sd.InputStream(samplerate=FREQUENZA, channels=1, dtype="float32", callback=callback_audio)
    _stream.start()
    scrivi_stato("ascolto", "", 0.0)
    _thread_livello = threading.Thread(target=_scrivi_livello_in_ciclo, daemon=True)
    _thread_livello.start()
    log("ascolto... (rilascia Shift destro per inviare)")


def ferma_e_elabora():
    global _stream
    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None
    if not _frammenti:
        log("nessun audio registrato")
        scrivi_stato("inattivo")
        return
    audio = np.concatenate(_frammenti, axis=0).flatten()
    durata = len(audio) / FREQUENZA
    if durata < 0.4:
        log("registrazione troppo breve, ignorata")
        scrivi_stato("inattivo")
        return
    scrivi_stato("penso", "trascrivo...")
    log(f"trascrivo ({durata:.1f}s)...")
    audio = filtra_rumore(audio)
    if float(np.sqrt(np.mean(audio ** 2))) < SOGLIA_VOCE:
        log("solo rumore di fondo, ignorato")
        scrivi_stato("inattivo")
        return
    try:
        # vad_filter: Whisper non vede i tratti senza voce, dove inventa frasi dal rumore
        segmenti, _ = modello_whisper().transcribe(audio, language="it", vad_filter=True,
                                                   condition_on_previous_text=False)
        testo = " ".join(s.text.strip() for s in segmenti).strip()
    except Exception as e:
        log(f"errore nella trascrizione: {e}")
        scrivi_stato("inattivo")
        return
    if not testo:
        log("non ho capito nulla")
        scrivi_stato("inattivo")
        return
    log(f"tu: {testo}")
    scrivi_stato("penso", testo)
    chiedi_a_claude(testo)


def chiedi_a_claude(testo):
    # CLAUDE_CODE_OAUTH_TOKEN e ANTHROPIC_API_KEY insieme mandano in conflitto
    # l'autenticazione (401 "API key is invalid", verificato il 28/09/2026):
    # il primo e' quello giusto per la CLI, il secondo si toglie dall'ambiente del figlio.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    try:
        r = subprocess.run(
            ["claude", "-p", testo, "--dangerously-skip-permissions"],  # modo lavoro (30/09: tolto il piano)
            capture_output=True, text=True, timeout=120, cwd=str(QUI.parent), env=env,
        )
        risposta = (r.stdout or r.stderr or "").strip()
    except Exception as e:
        risposta = f"Errore chiamando Claude Code: {e}"
    if not risposta:
        risposta = "Non ho ricevuto risposta."
    log(f"jarvis: {risposta}")
    scrivi_stato("parlo", risposta)
    parla(risposta)
    scrivi_stato("inattivo")


def parla(testo):
    try:
        from parla import parla as sintetizza, per_voce  # strumenti/kokoro/parla.py
    except Exception as e:
        log(f"Kokoro non disponibile: {e}")
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        dest = f.name
    try:
        sintetizza(per_voce(testo)[:LIMITE_CARATTERI_VOCE], dest)
        _riproduci_con_livello(dest, testo)
    except Exception as e:
        log(f"errore nella voce: {e}")
    finally:
        Path(dest).unlink(missing_ok=True)


def _riproduci_con_livello(percorso_wav, testo):
    """Riproduce il wav di Kokoro e, mentre suona, scrive il livello vero a blocchi
    di ~80ms: la bolla del widget disegna la forma d'onda della voce, non una finta."""
    try:
        import soundfile as sf
        dati, sr = sf.read(percorso_wav, dtype="float32")
    except Exception:
        winsound.PlaySound(percorso_wav, winsound.SND_FILENAME)  # fallback senza livello
        return
    sd.play(dati, sr)
    passo = max(1, int(sr * 0.08))
    for i in range(0, len(dati), passo):
        blocco = dati[i:i + passo]
        livello = min(1.0, float(np.sqrt(np.mean(blocco ** 2))) * 4) if len(blocco) else 0.0
        scrivi_stato("parlo", testo, livello)
        time.sleep(0.08)
    sd.wait()


def annulla_registrazione():
    """Shift destro usato per una maiuscola (o con un altro tasto): scarta l'audio, non invia nulla."""
    global _stream
    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None
    _frammenti.clear()
    scrivi_stato("inattivo")
    log("annullato: Shift destro era usato con un altro tasto")


def on_press(key):
    """Tieni premuto Shift destro per parlare (push-to-talk)."""
    global _press_t, _chord, _registrando
    if key == TARGET:
        if _press_t is None:  # la ripetizione automatica del tasto tenuto giù non riparte
            _press_t = time.monotonic()
            _chord = False
            with _lock:
                _registrando = True
            inizia_registrazione()
        return
    if _press_t is not None:
        _chord = True


def on_release(key):
    """Rilascia Shift destro per inviare la richiesta."""
    global _press_t, _chord, _registrando
    if key != TARGET:
        return
    era_combinazione = _chord
    _press_t, _chord = None, False
    with _lock:
        _registrando = False
    if era_combinazione:
        annulla_registrazione()
    else:
        threading.Thread(target=ferma_e_elabora, daemon=True).start()


def main():
    scrivi_stato("inattivo")
    log("pronto: tieni premuto Shift destro per parlare, rilascia per inviare (Ctrl+C per uscire)")
    with keyboard.Listener(on_press=on_press, on_release=on_release) as lis:
        lis.join()


if __name__ == "__main__":
    main()
