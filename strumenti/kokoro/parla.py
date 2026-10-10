#!/usr/bin/env python3
"""Sintesi vocale locale con Kokoro, voce italiana Sara (if_sara).

Modulo standalone, scollegato da telefono/ e da backtalk: usa kokoro-onnx
(pip install kokoro-onnx "misaki[it]" soundfile) ed espeak-ng come motore
di fonemizzazione per l'italiano.

I due file modello (kokoro-v1.0.onnx, voices-v1.0.bin) stanno in questa
cartella e non entrano in git (vedi .gitignore).

Uso: python3 strumenti/kokoro/parla.py "testo da leggere" [out.wav]
"""
import re
import sys
from pathlib import Path

CARTELLA = Path(__file__).parent
MODELLO = CARTELLA / "kokoro-v1.0.onnx"
VOCI = CARTELLA / "voices-v1.0.bin"
VOCE = "if_sara"


def per_voce(testo):
    """Toglie il markdown e i simboli che a voce non hanno senso (* # ` | _ ~ > e simili):
    la voce deve parlare come una persona, non leggere la punteggiatura del testo."""
    t = re.sub(r"```.*?```", " ", testo, flags=re.S)             # blocchi di codice
    t = re.sub(r"`([^`]*)`", r"\1", t)                            # codice in linea: resta il testo
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)                # link: resta il titolo
    t = re.sub(r"https?://\S+", "", t)                            # indirizzi web
    t = re.sub(r"^\s*[-=_*|+]{3,}\s*$", " ", t, flags=re.M)       # righe di separazione
    t = re.sub(r"^\s*(?:#{1,6}|>|[-*+•])\s+", "", t, flags=re.M)  # titoli, citazioni, elenchi
    t = re.sub(r"[*#`|_~^<>\\]+", " ", t)                         # simboli rimasti
    t = re.sub(r"[ \t]*\n+[ \t]*", ". ", t)                       # a capo = pausa
    t = re.sub(r"([.!?:;,])(\s*[.:;,])+", r"\1", t)               # punteggiatura doppia
    return re.sub(r"\s{2,}", " ", t).strip()


def parla(testo, dest="output.wav"):
    from kokoro_onnx import Kokoro
    import soundfile as sf

    testo = per_voce(testo)
    kokoro = Kokoro(str(MODELLO), str(VOCI))
    campioni, frequenza = kokoro.create(testo, voice=VOCE, speed=1.0, lang="it")
    sf.write(dest, campioni, frequenza)
    return dest


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    testo = sys.argv[1]
    dest = sys.argv[2] if len(sys.argv) > 2 else "output.wav"
    percorso = parla(testo, dest)
    print(f"salvato: {percorso}")


if __name__ == "__main__":
    main()
