#!/usr/bin/env python3
"""Installa e controlla la voce di Jarvis: filtro rumore, impronta, Whisper, Kokoro «Sara».

    python3 strumenti/installa_voce.py            scarica quello che manca e controlla
    python3 strumenti/installa_voce.py --prova    dice cosa manca, non scarica
    python3 strumenti/installa_voce.py --controlla   solo il controllo, esce 1 se manca qualcosa

Cosa mette a posto (scritto il 2026-09-30, ordine dell'utente: «accertati di fare installare il filtro
rumore di sottofondo»):
  1. il filtro del rumore GTCRN (backtalk/backtalk/assets/denoise-model/gtcrn_simple.onnx, ~500 KB);
  2. il modello che riconosce chi parla (backtalk/backtalk/assets/speaker-model/…eres2net…onnx, ~77 MB);
  3. i pacchetti Python della voce nell'ambiente backtalk/.venv (sherpa-onnx per il filtro e per
     «Jarvis», webrtcvad, sounddevice, kokoro, e un Whisper: mlx_whisper sul Mac Apple, faster_whisper altrove);
  4. che nel file backtalk/backtalk.json ci siano la voce Sara (if_sara) e il blocco mani_libere
     con il filtro acceso. Il file è personale (mai su GitHub): se manca lo crea dall'esempio.
La guida per far imparare la tua voce e regolare la reattività è docs/wiki/Voce.md.
"""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
BT = QUI / "backtalk"
PY = BT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python3")
MODELLI = {
    BT / "backtalk/assets/denoise-model/gtcrn_simple.onnx":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",
    BT / "backtalk/assets/speaker-model/eres2net_base_3dspeaker_16k.onnx":
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
}
PACCHETTI = {"sherpa_onnx": "sherpa-onnx", "webrtcvad": "webrtcvad-wheels", "sounddevice": "sounddevice",
             "numpy": "numpy", "kokoro": "kokoro"}


def scarica(dest, url):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)


def main():
    prova, solo = "--prova" in sys.argv, "--controlla" in sys.argv
    manca, ok = [], []
    if not BT.is_dir():
        print("🔴 manca la cartella backtalk/: questa copia di Jarvis non ha la voce")
        sys.exit(1)
    for f, url in MODELLI.items():
        if f.is_file() and f.stat().st_size > 100_000:
            ok.append(f"modello {f.name} ({f.stat().st_size // 1024} KB)")
        elif prova or solo:
            manca.append(f"modello {f.name}")
        else:
            print(f"   scarico {f.name}…")
            try:
                scarica(f, url); ok.append(f"modello {f.name} scaricato")
            except Exception as e:                       # rete assente, GitHub giù
                manca.append(f"modello {f.name} (download fallito: {e})")
    if not PY.exists():
        manca.append("ambiente Python della voce (backtalk/.venv): lancia backtalk/install.sh")
    else:
        for modulo, pacchetto in PACCHETTI.items():
            r = subprocess.run([str(PY), "-c", f"import {modulo}"], capture_output=True)
            if r.returncode == 0:
                ok.append(f"pacchetto {modulo}")
            elif prova or solo:
                manca.append(f"pacchetto {pacchetto}")
            else:
                print(f"   installo {pacchetto}…")
                r = subprocess.run([str(PY), "-m", "pip", "install", "-q", pacchetto], capture_output=True, text=True)
                (ok if r.returncode == 0 else manca).append(
                    f"pacchetto {pacchetto}" + ("" if r.returncode == 0 else f" (pip: {r.stderr.strip()[-80:]})"))
    if PY.exists():                                      # un Whisper qualsiasi
        r = [subprocess.run([str(PY), "-c", f"import {m}"], capture_output=True).returncode == 0 for m in ("mlx_whisper", "faster_whisper")]
        (ok if any(r) else manca).append("Whisper (ascolto)" if any(r) else "Whisper: lancia backtalk/install.sh")
    cfg, esempio = BT / "backtalk.json", BT / "backtalk.json.example"
    if not cfg.exists() and esempio.exists() and not (prova or solo):
        cfg.write_text(esempio.read_text(encoding="utf-8"), encoding="utf-8")
        ok.append("backtalk.json creato dall'esempio")
    if cfg.exists():
        d = json.loads(cfg.read_text(encoding="utf-8"))
        cambiato = False
        if d.get("voice") != "if_sara":
            d["voice"] = "if_sara"; cambiato = True
        ml = d.setdefault("mani_libere", {})
        if ml.get("filtro_rumore") is False:            # se manca la chiave vale True (default di backtalk)
            ml["filtro_rumore"] = True; cambiato = True
        if cambiato and not (prova or solo):
            cfg.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ok.append("backtalk.json: voce Sara e filtro rumore accesi")
        elif cambiato:
            manca.append("backtalk.json: voce Sara / filtro rumore da impostare")
        else:
            ok.append("backtalk.json: voce Sara e filtro rumore già a posto")
    else:
        manca.append("backtalk/backtalk.json")
    for x in ok:
        print("🟢", x)
    for x in manca:
        print("🔴", x)
    print("Per far imparare la tua voce: avvio/Registra la voce dell'utente.command · guida: docs/wiki/Voce.md")
    sys.exit(1 if manca else 0)


main()
