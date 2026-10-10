#!/usr/bin/env python3
"""
L'orb di Jarvis per Mac, portato da quello di Windows (jarvis_orb_windows.py, 29/09/2026).

Il logo (la J con le onde della voce) dentro l'anello dello stemma, fluttuante sul
desktop, senza cornice, con trasparenza vera e animazione continua. Il disegno è lo
stesso di Windows (Pillow); cambia solo la finestra, che qui è una NSWindow (PyObjC).

- trascina col tasto sinistro: si sposta dove vuoi, la posizione si ricorda
- un clic: menu (Command Center, Lavagna agenti, motore, blocca, chiudi) · anche il clic destro
- doppio clic: apre il Command Center
- stati: riposo = respiro turchese · ascolto = verde con barre · penso = archi gialli che
  girano · parlo = blu con onde · al lavoro = archi lavanda (Claude Code sta lavorando).
  Il puntino in basso è verde se il Command Center risponde, rosso se è spento.
- aspetto a specchio (05/10/2026): sotto il disco c'è il vetro vero di macOS (NSGlassEffectView su
  macOS 26, NSVisualEffectView prima) che sfoca il desktop; sopra, un velo scuro traslucido, il
  riflesso in alto, il filo di luce sul bordo (chiaro in alto, quasi spento in basso) e l'ombra.
  Quando ascolta, pensa o parla il vetro prende il colore dello stato.
- a riposo sparisce quasi (alfa 0,30 dopo 6 s senza niente, anche quando Claude Code lavora in sottofondo) e torna
  pieno appena cambia stato o quando ci passi sopra col mouse. Con «Riduci movimento» il passaggio
  è secco invece che sfumato.
- sopra compare una carta col testo vero: quello che hai detto, quello che Jarvis risponde,
  oppure «AL LAVORO» con quello che sta facendo adesso, da quanto, e gli agenti in corso uno per
  riga col loro tempo. Quando non ci sono ancora parole dice «Parla pure…» / «Un attimo…», e in
  fondo una riga grigia con cosa puoi fare adesso. In ascolto e in errore il bordo prende il colore
  dello stato. La carta compare scivolando verso l'orb, se ne va sfumando e segue la sua trasparenza.
  Idee (non codice: quel repository non ha licenza) dalla UI di riccardo-belli, 05/10/2026.
- VoiceOver legge lo stato («Jarvis, sto pensando»); col mouse fermo sopra compare l'aiuto dei comandi.

Legge i file che scrivono la voce e i ganci (nessun server del volto):
  backtalk/.voice_state, .voice_waveform, chat.jsonl   la voce (stato, onda, battute vere)
  backtalk/.jarvis_status                              il lavoro di Claude Code (jarvis_status.py)

Parte da solo quando si apre il Command Center (server.py, avvia_orb) e da start.sh.

Uso:
  python3 jarvis_widget.py
  python3 jarvis_widget.py --segnali DIR --chat FILE     per provarlo su file finti
"""

import datetime
import io
import json
import math
import random
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from AppKit import (
    NSApplication, NSWindow, NSBackingStoreBuffered, NSColor, NSScreen, NSFloatingWindowLevel,
    NSWindowStyleMaskBorderless, NSApplicationActivationPolicyAccessory, NSEvent,
    NSEventMaskLeftMouseDown, NSEventMaskLeftMouseDragged, NSEventMaskLeftMouseUp,
    NSEventMaskRightMouseDown, NSEventTypeLeftMouseDown, NSEventTypeLeftMouseDragged,
    NSEventTypeLeftMouseUp, NSEventTypeRightMouseDown, NSImage, NSImageView, NSMenu, NSMenuItem,
)
from Foundation import NSData, NSMakeRect, NSTimer, NSObject
import objc
import AppKit
from AppKit import NSView, NSVisualEffectView, NSWorkspace

QUI = Path(__file__).resolve().parent
JARVIS = QUI.parent
CONFIG = JARVIS / "command-center" / "configurazione.json"
POSIZIONE = QUI / "orb_posizione.json"
MOTORE_FILE = Path.home() / ".claude" / "skills" / "aggiorna-memoria" / "motore_attivo.json"


def _argomento(nome, predefinito):
    if nome in sys.argv:
        i = sys.argv.index(nome)
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return predefinito


SEGNALI = _argomento("--segnali", JARVIS / "backtalk")
CHAT_FILE = _argomento("--chat", JARVIS / "backtalk" / "chat.jsonl")
STATO_FILE = SEGNALI / ".voice_state"
ONDA_FILE = SEGNALI / ".voice_waveform"
BUS_LAVORO = SEGNALI / ".jarvis_status"      # scritto dai ganci jarvis_status.py

S = 168            # lato della finestra (punti)
SS = 2             # supersampling, che qui è anche il fattore retina: l'immagine è S*SS px
W = S * SS
C = W // 2
R_DISCO = 40 * SS
R_ANELLO = 47 * SS
FPS = 24
INTERVALLO_DATI_S = 0.12
INTERVALLO_CC_S = 4.0
DOPPIO_CLIC_S = 0.26
VOCE_SCADUTA_S = 180          # .voice_state più vecchio di così è di una sessione morta
ONDA_FRESCA_S = 1.0
CHAT_FRESCA_S = 180
LAVORO_FRESCO_S = 90
SOGLIA_CLIC = 3               # punti di movimento sotto i quali un mouse-down/up è un clic
LOCK_PORTA = 47771
ALFA_RIPOSO = 0.30            # a riposo resta appena visibile, ma cliccabile
ALFA_LAVORO = 0.30            # Claude Code lavora in sottofondo: come a riposo (l'utente, 05/10 10:3x)
RIPOSO_DOPO_S = 6.0           # dopo quanto tempo senza niente comincia a sparire
SFUMA_SU_S = 0.18             # costante di tempo del ritorno al pieno (veloce)
SFUMA_GIU_S = 1.1             # costante di tempo della dissolvenza (lenta, morbida)
ATTIVI = ("ascolto", "penso", "parlo", "errore")

# palette dello stemma e del logo
BG = (16, 20, 43)
BORDO = (58, 65, 112)
ANELLO = (91, 124, 250)
TURCHESE = (20, 214, 195)
LAVANDA = (180, 170, 240)
BIANCO = (245, 246, 252)
VERDE = (61, 220, 132)
ROSSO = (224, 82, 82)
BLU = (74, 158, 255)
GIALLO = (245, 197, 66)
COLORE = {"riposo": TURCHESE, "ascolto": VERDE, "penso": GIALLO, "parlo": BLU, "lavoro": LAVANDA, "errore": ROSSO}
ETICHETTA = {"ascolto": "ti ascolto", "penso": "sto pensando", "parlo": "Jarvis", "lavoro": "al lavoro",
             "errore": "qualcosa non va"}
STATO_BACKTALK = {"listening": "ascolto", "thinking": "penso", "speaking": "parlo", "error": "errore"}
# testo della carta quando la voce non ha ancora parole vere, e la riga grigia con cosa puoi fare adesso
RISERVA = {"ascolto": "Parla pure…", "penso": "Un attimo…", "errore": "La voce si è inceppata."}
SUGGERIMENTO = {"ascolto": "rilascia Cmd destro (o fai una pausa) per inviare",
                "errore": "riprova con Cmd destro · un clic sull'orb per il menu",
                "lavoro": "doppio clic sull'orb: Command Center"}
AGENTI_IN_CARTA = 3
PAUSA_LAVORO_S = 20           # una pausa di Claude Code più corta di così non azzera il tempo nella carta
CARTA_SU_S = 0.12             # la carta compare in fretta…
CARTA_GIU_S = 0.30            # …e se ne va un po' più piano
CARTA_SCIVOLA = 10            # punti di scivolata verso l'orb mentre compare (niente con Riduci movimento)

MOTORI = (("claude", "Claude Code", "claude"), ("gemini", "Gemini", "gemini"),
          ("cursor", "Cursor", "cursor-agent"), ("codex", "Codex", "codex"))
_RIFERIMENTI_VIVI = []  # controller PyObjC che altrimenti verrebbero raccolti dal garbage collector


# ------------------------------------------------------------------ disegno (come Windows)
def _font(dim, grassetto=False):
    for nome, indice in (("/System/Library/Fonts/Helvetica.ttc", 1 if grassetto else 0),
                         ("/System/Library/Fonts/HelveticaNeue.ttc", 1 if grassetto else 0)):
        try:
            return ImageFont.truetype(nome, dim, index=indice)
        except OSError:
            continue
    return ImageFont.load_default()


def _percorso_j():
    """La J del logo (logo.svg): dritto da (512,150) a (512,660), curva a sinistra."""
    pts = [(512 + 0.0, 150 + t * 510 / 40) for t in range(41)]

    def bez(p0, p1, p2, n=30):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
                for t in [i / n for i in range(n + 1)]]

    pts += bez((512, 660), (512, 866), (322, 866))
    pts += bez((322, 866), (196, 866), (172, 742))
    return pts


def crea_marchio(lato):
    """Il logo di Jarvis (J bianca + 4 onde) come immagine RGBA di `lato` px."""
    ss = 3
    L = 1024 * ss // 2
    im = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = L / 1024

    def T(x, y):     # coordinate del logo: gruppo scalato 0.93 attorno al centro
        return ((512 + (x - 512) * 0.93) * k, (505 + (y - 505) * 0.93 + 7) * k)

    def barra(x, y, w, h, col):
        x0, y0 = T(x, y)
        x1, y1 = T(x + w, y + h)
        d.rounded_rectangle([x0, y0, x1, y1], radius=(x1 - x0) / 2, fill=col)

    barra(160, 208, 104, 224, LAVANDA + (255,))
    barra(306, 150, 104, 330, TURCHESE + (255,))
    barra(614, 150, 104, 330, TURCHESE + (255,))
    barra(760, 208, 104, 224, LAVANDA + (255,))
    r = 134 / 2 * 0.93 * k
    for x, y in _percorso_j():
        px, py = T(x, y)
        d.ellipse([px - r, py - r, px + r, py + r], fill=BIANCO + (255,))
    return im.resize((lato, lato), Image.LANCZOS)


def _maschera_alone():
    y, x = np.ogrid[:W, :W]
    r = np.hypot(x - C, y - C)
    m = np.clip(1 - (r - R_ANELLO * 0.9) / (C - R_ANELLO * 0.9), 0, 1) ** 2.2
    m[r < R_ANELLO * 0.9] = 1
    return Image.fromarray((m * 255).astype(np.uint8), "L")


def _tinta(colore, maschera, k):
    im = Image.new("RGBA", (W, W), colore + (0,))
    im.putalpha(maschera.point(lambda v: int(v * max(0.0, min(1.0, k)))))
    return im


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def disco_a_specchio():
    """Il disco sopra il vetro di macOS: velo scuro traslucido (più chiaro in alto), riflesso, filo di
    luce sul bordo che si spegne verso il basso, ombra morbida fuori dal disco. Tutto RGBA W x W."""
    y, x = np.ogrid[:W, :W]
    r = np.hypot(x - C, y - C)
    dentro = np.clip(R_DISCO - r + 0.5, 0, 1)                      # disco con bordo antialias
    v = np.clip((y - (C - R_DISCO)) / (2 * R_DISCO), 0, 1)         # 0 in alto, 1 in basso

    # ombra: sotto e un po' più giù, sfocata, tolta dove c'è il disco (il vetro non va scurito)
    ombra = Image.new("L", (W, W), 0)
    ImageDraw.Draw(ombra).ellipse([C - R_DISCO, C - R_DISCO + 5 * SS, C + R_DISCO, C + R_DISCO + 5 * SS], fill=95)
    ombra = np.asarray(ombra.filter(ImageFilter.GaussianBlur(7 * SS)), dtype=np.float32) * (1 - dentro)

    # velo: il colore dello stemma, trasparente quanto basta per vedere il vetro sotto
    col = np.zeros((W, W, 4), dtype=np.float32)
    for i in range(3):
        col[..., i] = BG[i] + (255 - BG[i]) * 0.10 * (1 - v) ** 2
    col[..., 3] = (120 + 70 * v) * dentro                          # 120 in alto, 190 in basso

    # riflesso: una lente di luce nella metà alta, più forte al centro
    riflesso = Image.new("L", (W, W), 0)
    ImageDraw.Draw(riflesso).ellipse([C - R_DISCO * 0.78, C - R_DISCO * 0.94, C + R_DISCO * 0.78, C - R_DISCO * 0.05],
                                     fill=255)
    riflesso = np.asarray(riflesso.filter(ImageFilter.GaussianBlur(5 * SS)), dtype=np.float32) / 255
    riflesso *= np.clip(1 - v * 2.1, 0, 1) * 0.22 * dentro

    # filo di luce sul bordo: largo un punto, 45 % in alto, 5 % in basso; e un riverbero sul fondo
    filo = np.clip(1 - np.abs(r - (R_DISCO - 0.5 * SS)) / (0.8 * SS), 0, 1)
    filo_a = filo * (0.45 - 0.40 * v)
    fondo = filo * np.clip((v - 0.75) * 4, 0, 1) * 0.18

    luce = np.clip(riflesso + filo_a + fondo, 0, 1)                # luce bianca sopra il velo
    a_velo = col[..., 3] / 255
    a_tot = luce + a_velo * (1 - luce)
    out = np.zeros_like(col)
    for i in range(3):
        out[..., i] = (255 * luce + col[..., i] * a_velo * (1 - luce)) / np.maximum(a_tot, 1e-6)
    out[..., 3] = a_tot * 255
    # l'ombra va sotto tutto: dove non c'è disco conta solo lei
    a_om = ombra / 255
    a_fin = out[..., 3] / 255 + a_om * (1 - out[..., 3] / 255)
    for i in range(3):
        out[..., i] = out[..., i] * (out[..., 3] / 255) / np.maximum(a_fin, 1e-6)
    out[..., 3] = a_fin * 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


class Disegno:
    def __init__(self):
        self.alone = _maschera_alone()
        self.marchio = crea_marchio(int(R_DISCO * 1.62))
        self.disco = disco_a_specchio()

    def frame(self, t, stato, livello, cc_acceso):
        col = COLORE[stato]
        im = Image.new("RGBA", (W, W), (0, 0, 0, 0))

        if stato == "riposo":                       # alone che respira
            k = 0.30 + 0.16 * math.sin(t * 1.7)
        elif stato == "ascolto":
            k = 0.42 + 0.35 * livello
        elif stato in ("penso", "lavoro"):
            k = 0.38 + 0.12 * math.sin(t * 5)
        else:
            k = 0.40 + 0.25 * abs(math.sin(t * 4.2)) + 0.2 * livello
        im = Image.alpha_composite(im, _tinta(col, self.alone, k))

        d = ImageDraw.Draw(im)
        w_an = 3 * SS                               # anello dello stemma
        box = [C - R_ANELLO, C - R_ANELLO, C + R_ANELLO, C + R_ANELLO]
        d.ellipse(box, outline=ANELLO + (255,), width=w_an)

        if stato in ("penso", "lavoro"):            # arco luminoso che gira sull'anello
            v = 260 if stato == "penso" else 150
            for off in (0, 180):
                a0 = (t * v + off) % 360
                d.arc(box, a0, a0 + 80, fill=col + (255,), width=w_an + SS)
        else:
            v = 70 if stato == "riposo" else 130
            a0 = (t * v) % 360
            d.arc(box, a0, a0 + 55, fill=_mix(ANELLO, col, 0.85) + (255,), width=w_an + SS)
            d.arc(box, a0 + 180, a0 + 215, fill=_mix(ANELLO, col, 0.5) + (255,), width=w_an)

        if stato == "parlo":                        # onde del parlato: cerchi che si espandono
            for i in range(3):
                p = (t * 0.9 + i / 3) % 1
                rr = R_ANELLO + p * (C - R_ANELLO - 4 * SS)
                al = int(190 * (1 - p) ** 1.5)
                d.ellipse([C - rr, C - rr, C + rr, C + rr], outline=col + (al,), width=2 * SS)

        if stato == "ascolto":                      # barre attorno all'anello mentre ascolta
            n = 36
            for i in range(n):
                ang = 2 * math.pi * i / n + t * 0.4
                lung = (3 + (6 + 20 * livello) * abs(math.sin(t * 6 + i * 1.7)) * (0.5 + random.random() * 0.5)) * SS
                r0 = R_ANELLO + 5 * SS
                d.line([C + r0 * math.cos(ang), C + r0 * math.sin(ang),
                        C + (r0 + lung) * math.cos(ang), C + (r0 + lung) * math.sin(ang)],
                       fill=col + (230,), width=2 * SS)

        im = Image.alpha_composite(im, self.disco)  # disco e logo (il logo respira appena)
        scala = 1 + 0.025 * math.sin(t * 1.7) + (0.05 * livello if stato in ("ascolto", "parlo") else 0)
        m = self.marchio
        lato = int(m.width * scala)
        mm = m.resize((lato, lato), Image.BILINEAR) if lato != m.width else m
        im.alpha_composite(mm, (C - lato // 2, C - lato // 2 - 1 * SS))

        d = ImageDraw.Draw(im)                      # puntino di stato del Command Center
        px, py, pr = C + R_DISCO * 0.72, C + R_DISCO * 0.72, 5.5 * SS
        d.ellipse([px - pr - SS, py - pr - SS, px + pr + SS, py + pr + SS], fill=BG + (255,))
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(VERDE if cc_acceso else ROSSO) + (255,))
        return im


def durata(secondi):
    """2:05, 1:02:05: il tempo trascorso come lo legge un orologio."""
    secondi = max(0, int(secondi))
    h, resto = divmod(secondi, 3600)
    m, sec = divmod(resto, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _accorcia(testo, font, max_w):
    if font.getlength(testo) <= max_w:
        return testo
    while testo and font.getlength(testo + "…") > max_w:
        testo = testo[:-1]
    return testo.rstrip() + "…"


def carta_testo(stato, testo, larghezza=330, destra="", agenti=(), suggerimento=""):
    """La carta col testo, a risoluzione retina: (immagine, larghezza in punti, altezza in punti).
    destra = tempo in alto a destra; agenti = [(nome, tempo)] in righe con il pallino; suggerimento = riga grigia
    in fondo con cosa puoi fare adesso."""
    K = SS
    f_t, f_e, f_p = _font(13 * K), _font(11 * K, True), _font(11 * K)
    max_w = (larghezza - 36) * K
    righe, riga = [], ""
    for parola in testo.split():
        while f_t.getlength(parola) > max_w:        # una parola lunga (un percorso) va spezzata
            n = len(parola)
            while n > 1 and f_t.getlength(parola[:n]) > max_w:
                n -= 1
            if riga:
                righe.append(riga)
                riga = ""
            righe.append(parola[:n])
            parola = parola[n:]
        prova = (riga + " " + parola).strip()
        if f_t.getlength(prova) <= max_w:
            riga = prova
        else:
            righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    massimo = 3 if agenti else 6
    if len(righe) > massimo:
        righe = righe[:massimo]
        righe[-1] = righe[-1].rstrip() + " …"
    agenti = list(agenti)
    altri = len(agenti) - AGENTI_IN_CARTA
    agenti = agenti[:AGENTI_IN_CARTA] + ([("+ altri " + str(altri), "")] if altri > 0 else [])
    alt = 44 + 19 * len(righe) + (8 + 18 * len(agenti) if agenti else 0) + (20 if suggerimento else 0)
    col = COLORE.get(stato, TURCHESE)
    im = Image.new("RGBA", (larghezza * K, alt * K), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = [2 * K, 2 * K, (larghezza - 2) * K, (alt - 2) * K]
    d.rounded_rectangle(box, radius=16 * K, fill=(18, 22, 48, 165))     # sotto c'è il vetro di macOS
    if stato in ("ascolto", "errore"):              # microfono aperto o guasto: il bordo prende il colore dello stato
        d.rounded_rectangle(box, radius=16 * K, outline=col + (150,), width=K)
    else:
        d.rounded_rectangle(box, radius=16 * K, outline=(255, 255, 255, 70), width=K)   # filo di luce
    d.line([(18 * K, 2 * K + K // 2), ((larghezza - 18) * K, 2 * K + K // 2)], fill=(255, 255, 255, 120), width=K)
    d.rounded_rectangle([2 * K, 14 * K, 6 * K, (alt - 14) * K], radius=2 * K, fill=col + (255,))
    d.text((18 * K, 11 * K), ETICHETTA.get(stato, "").upper(), font=f_e, fill=col + (255,))
    if destra:
        d.text(((larghezza - 18) * K - f_p.getlength(destra), 11 * K), destra, font=f_p, fill=(170, 176, 205, 255))
    y = 32
    for r in righe:
        d.text((18 * K, y * K), r, font=f_t, fill=(238, 240, 250, 255))
        y += 19
    if agenti:
        y += 6
        for nome, tempo in agenti:                  # una riga per agente: pallino, nome, da quanto lavora
            cy = (y + 6) * K
            if tempo:
                d.ellipse([20 * K, cy - 3 * K, 26 * K, cy + 3 * K], fill=col + (255,))
            tw = f_p.getlength(tempo) if tempo else 0
            nome = _accorcia(nome, f_p, (larghezza - 54) * K - tw)
            d.text((32 * K, y * K), nome, font=f_p, fill=(205, 210, 232, 255))
            if tempo:
                d.text(((larghezza - 18) * K - tw, y * K), tempo, font=f_p, fill=(150, 156, 188, 255))
            y += 18
        y += 2
    if suggerimento:
        d.text((18 * K, (y + 3) * K), _accorcia(suggerimento, f_p, max_w), font=f_p, fill=(165, 171, 202, 255))
    return im, larghezza, alt


def a_nsimage(img, punti_w, punti_h):
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=1)
    dati = buf.getvalue()
    immagine = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(dati, len(dati)))
    immagine.setSize_((punti_w, punti_h))
    return immagine


# ------------------------------------------------------------------ dati
def porta():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("porta", 7777)
    except Exception:
        return 7777


def cc_risponde(p):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/", timeout=0.8):
            return True
    except Exception:
        return False


def _ultime_battute():
    """Le battute di chat.jsonl da ora indietro, le più recenti in fondo (solo la coda del file)."""
    try:
        with open(CHAT_FILE, "rb") as f:
            f.seek(0, 2)
            inizio = max(0, f.tell() - 8192)
            f.seek(inizio)
            righe = f.read().decode("utf-8", "replace").splitlines()
            if inizio:
                righe = righe[1:]           # la prima riga può essere tagliata a metà
    except OSError:
        return []
    battute = []
    for r in righe:
        try:
            d = json.loads(r)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("testo"):
            battute.append(d)
    return battute


def _fresca(battuta):
    try:
        t = datetime.datetime.fromisoformat(battuta.get("ts", ""))
    except ValueError:
        return False
    return abs((datetime.datetime.now() - t).total_seconds()) < CHAT_FRESCA_S


def _testo_voce(stato):
    """Quello che hai detto (penso) o quello che Jarvis sta dicendo (parlo): le battute vere."""
    if stato in ("ascolto", "errore"):         # in errore la risposta vecchia confonderebbe: c'è il testo di riserva
        return ""
    battute = _ultime_battute()
    ultimo_utente = max((i for i, b in enumerate(battute) if b.get("chi") == "utente"), default=-1)
    if stato == "penso":
        if ultimo_utente >= 0 and _fresca(battute[ultimo_utente]):
            return battute[ultimo_utente]["testo"]
        return ""
    risposta = [b for b in battute[ultimo_utente + 1:] if b.get("chi") == "jarvis" and _fresca(b)]
    return " ".join(b["testo"] for b in risposta)


def _livello_voce():
    """0..1: l'onda vera mentre l'audio suona."""
    try:
        d = json.loads(ONDA_FILE.read_text(encoding="utf-8"))
        if time.time() - float(d.get("ts", 0)) < ONDA_FRESCA_S:
            campioni = [abs(float(x)) for x in d.get("samples", [])]
            if campioni:
                return min(1.0, (sum(campioni) / len(campioni)) * 4.0)
    except Exception:
        pass
    return 0.0


def leggi_voce():
    """(stato, testo, livello): stato è riposo | ascolto | penso | parlo."""
    try:
        nome = STATO_FILE.read_text(encoding="utf-8").strip()
        vecchio = time.time() - STATO_FILE.stat().st_mtime > VOCE_SCADUTA_S
    except OSError:
        return "riposo", "", 0.0
    stato = STATO_BACKTALK.get(nome)
    if stato is None or vecchio:
        return "riposo", "", 0.0
    livello = _livello_voce()
    if livello == 0.0 and stato in ("ascolto", "penso"):
        livello = 0.30 + 0.20 * math.sin(time.time() * 4.0)     # un respiro, l'onda vera c'è solo mentre suona
    return stato, _testo_voce(stato), livello


def leggi_lavoro():
    """(True, testo, agenti) se una sessione di Claude Code sta lavorando adesso (bus dei ganci).
    agenti = ((descrizione, inizio in epoch), …) di quelli ancora attivi, dal più vecchio."""
    try:
        d = json.loads(BUS_LAVORO.read_text(encoding="utf-8"))
    except Exception:
        return False, "", ()
    if not d.get("lavorando") or time.time() - d.get("ts", 0) > LAVORO_FRESCO_S:
        return False, "", ()
    attivi = [a for a in d.get("agenti") or [] if a.get("stato") == "attivo"]
    riga = (d.get("azione") or "lavoro") + (f" · {d['dettaglio']}" if d.get("dettaglio") else "")
    agenti = tuple((a.get("descrizione") or a.get("nodo") or a.get("tipo") or "agente", float(a.get("ts") or 0))
                   for a in sorted(attivi, key=lambda a: a.get("ts") or 0))
    return True, riga, agenti


def leggi_motore():
    try:
        return json.loads(MOTORE_FILE.read_text(encoding="utf-8")).get("motore", "claude")
    except Exception:
        return "claude"


def scrivi_motore(m):
    comando = {i: c for i, _, c in MOTORI}.get(m)
    if not comando or not shutil.which(comando):
        return False
    MOTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOTORE_FILE.write_text(json.dumps({"motore": m}), encoding="utf-8")
    return True


# ------------------------------------------------------------------ app
def _vetro(cornice, raggio):
    """Il vetro di macOS dietro il disegno: Liquid Glass su macOS 26, il materiale HUD prima."""
    classe = getattr(AppKit, "NSGlassEffectView", None)
    if classe is not None:
        v = classe.alloc().initWithFrame_(cornice)
        v.setCornerRadius_(raggio)
        try:
            v.setStyle_(1)              # «clear»: il più trasparente, quello che riflette di più
        except Exception:
            pass
        return v
    v = NSVisualEffectView.alloc().initWithFrame_(cornice)
    v.setMaterial_(13)                  # HUD
    v.setBlendingMode_(0)               # sfoca quello che c'è dietro la finestra
    v.setState_(1)                      # sempre attivo, anche se l'app non ha il fuoco
    v.setWantsLayer_(True)
    v.layer().setCornerRadius_(raggio)
    v.layer().setMasksToBounds_(True)
    return v


def _tinta_vetro(vetro, colore, forza):
    """Il vetro prende il colore dello stato (solo Liquid Glass ha la tinta)."""
    if vetro is None or not hasattr(vetro, "setTintColor_"):
        return
    vetro.setTintColor_(None if colore is None else
                        NSColor.colorWithSRGBRed_green_blue_alpha_(colore[0] / 255, colore[1] / 255,
                                                                   colore[2] / 255, forza))


def _finestra_trasparente(rect, ignora_mouse, vetro=None):
    """vetro = (cornice in punti, raggio): il vetro di macOS sotto l'immagine."""
    finestra = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
    finestra.setLevel_(NSFloatingWindowLevel)
    finestra.setOpaque_(False)
    finestra.setBackgroundColor_(NSColor.clearColor())
    finestra.setHasShadow_(False)
    finestra.setIgnoresMouseEvents_(ignora_mouse)
    finestra.setCollectionBehavior_(1 << 0 | 1 << 8)  # CanJoinAllSpaces | FullScreenAuxiliary
    vista = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, rect.size.width, rect.size.height))
    if vetro is None:
        finestra.setContentView_(vista)
        return finestra, vista, None
    contenitore = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, rect.size.width, rect.size.height))
    v = _vetro(*vetro)
    contenitore.addSubview_(v)          # prima il vetro, sopra l'immagine
    contenitore.addSubview_(vista)
    finestra.setContentView_(contenitore)
    _RIFERIMENTI_VIVI.append(v)
    return finestra, vista, v


class Orb(NSObject):
    def init(self):
        self = objc.super(Orb, self).init()
        if self is None:
            return None
        self.porta = porta()
        schermo = NSScreen.mainScreen().frame()
        x, y = schermo.size.width - S - 30, 90
        try:
            p = json.loads(POSIZIONE.read_text(encoding="utf-8"))
            x, y = float(p["x"]), float(p["y"])
        except Exception:
            pass
        x = max(-S / 3, min(schermo.size.width - S * 2 / 3, x))
        y = max(-S / 3, min(schermo.size.height - S * 2 / 3, y))
        r = R_DISCO / SS
        self.finestra, self.vista, self.vetro = _finestra_trasparente(
            NSMakeRect(x, y, S, S), ignora_mouse=False, vetro=(NSMakeRect(S / 2 - r, S / 2 - r, 2 * r, 2 * r), r))
        self.finestra.makeKeyAndOrderFront_(None)
        self.vista.setToolTip_("Jarvis · clic: menu · doppio clic: Command Center · trascina per spostarlo")
        self.vista.setAccessibilityLabel_("Jarvis, a riposo")
        self.disegno = Disegno()
        self.carta_win = None
        self.carta_vista = None
        self.carta_chiave = None
        self.carta_dim = (0, 0)
        self.carta_vetro = None
        self.carta_alfa = 0.0           # la carta compare e se ne va sfumando, come l'orb
        self.carta_meta = 0.0
        self.carta_scivola = 0.0        # 1 = ancora scostata dall'orb, 0 = al suo posto
        self.agenti = ()
        self.lavoro_visto = 0.0
        self.lavoro_dal = None          # da quando l'orb vede Claude Code al lavoro (per il tempo nella carta)
        self.stato, self.testo, self.livello = "riposo", "", 0.0
        self.liv_liscio = 0.0
        self.cc = False
        self.t0 = time.time()
        self.offset = None
        self.mosso = 0.0
        self.timer_clic = None
        self.evento_clic = None
        self.bloccato = False
        self._ultimo_cc = 0.0
        self.alfa = 1.0                 # trasparenza attuale della finestra (si avvicina a alfa_meta)
        self.alfa_meta = 1.0
        self.ultimo_vivo = time.time()  # l'ultima volta che c'era qualcosa da mostrare (o il mouse sopra)
        self.stato_prima = "riposo"
        self.t_frame = time.time()
        self.riduci = False
        self._ultimo_riduci = 0.0
        return self

    # --- cicli
    def tickDati_(self, timer):
        adesso = time.time()
        if adesso - self._ultimo_cc >= INTERVALLO_CC_S:
            self._ultimo_cc = adesso
            threading.Thread(target=self._controlla_cc, daemon=True).start()
        self.stato, self.testo, self.livello = leggi_voce()
        self.agenti = ()
        if self.stato == "riposo":
            al_lavoro, riga, agenti = leggi_lavoro()
            if al_lavoro:
                self.stato, self.testo, self.agenti = "lavoro", riga, agenti
        if self.stato == "lavoro":
            self.lavoro_dal = self.lavoro_dal or adesso
            self.lavoro_visto = adesso
        elif self.stato != "riposo" or adesso - self.lavoro_visto > PAUSA_LAVORO_S:
            self.lavoro_dal = None      # una pausa breve fra due turni non azzera il tempo
        self.aggiorna_carta(adesso)
        self.aggiorna_trasparenza(adesso)

    @objc.python_method
    def aggiorna_trasparenza(self, adesso):
        """Pieno quando ascolta/pensa/parla, quando cambia stato o col mouse sopra; poi sparisce piano."""
        if adesso - self._ultimo_riduci > 10:
            self._ultimo_riduci = adesso
            try:
                self.riduci = bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
            except Exception:
                self.riduci = False
        sopra = AppKit.NSPointInRect(NSEvent.mouseLocation(), self.finestra.frame())
        if self.stato in ATTIVI or self.stato != self.stato_prima or sopra or self.offset is not None:
            self.ultimo_vivo = adesso
        if self.stato != self.stato_prima:
            _tinta_vetro(self.vetro, COLORE.get(self.stato) if self.stato in ATTIVI else None, 0.22)
            self.vista.setAccessibilityLabel_("Jarvis, " + ETICHETTA.get(self.stato, "a riposo"))   # VoiceOver
            self.stato_prima = self.stato
        if adesso - self.ultimo_vivo < RIPOSO_DOPO_S:
            self.alfa_meta = 1.0
        else:
            self.alfa_meta = ALFA_LAVORO if self.stato == "lavoro" else ALFA_RIPOSO

    @objc.python_method
    def sfuma(self):
        adesso = time.time()
        dt, self.t_frame = adesso - self.t_frame, adesso
        if abs(self.alfa_meta - self.alfa) >= 0.004:
            if self.riduci:
                self.alfa = self.alfa_meta          # Riduci movimento: niente dissolvenza
            else:
                tau = SFUMA_SU_S if self.alfa_meta > self.alfa else SFUMA_GIU_S
                self.alfa += (self.alfa_meta - self.alfa) * (1 - math.exp(-dt / tau))
            self.finestra.setAlphaValue_(self.alfa)
        self.sfuma_carta(dt)

    @objc.python_method
    def sfuma_carta(self, dt):
        """La carta segue la trasparenza dell'orb; compare scivolando verso di lui e se ne va sfumando."""
        if self.carta_win is None:
            return
        meta = self.carta_meta * self.alfa
        if abs(meta - self.carta_alfa) < 0.004 and self.carta_scivola < 0.01:
            if meta == 0.0:
                self.carta_win.orderOut_(None)      # sparita del tutto: via la finestra
                self.carta_win = self.carta_vista = self.carta_vetro = None
            return
        if self.riduci:
            self.carta_alfa, self.carta_scivola = meta, 0.0
        else:
            k = 1 - math.exp(-dt / (CARTA_SU_S if meta > self.carta_alfa else CARTA_GIU_S))
            self.carta_alfa += (meta - self.carta_alfa) * k
            self.carta_scivola -= self.carta_scivola * (1 - math.exp(-dt / CARTA_SU_S))
            if abs(meta - self.carta_alfa) < 0.004:
                self.carta_alfa = meta
        self.carta_win.setAlphaValue_(self.carta_alfa)
        self.posiziona_carta()

    @objc.python_method
    def _controlla_cc(self):
        self.cc = cc_risponde(self.porta)

    def tickFrame_(self, timer):
        self.sfuma()
        self.giro = getattr(self, "giro", 0) + 1
        if self.stato == "riposo" and self.giro % 2:    # a riposo il respiro è lento: metà dei fotogrammi bastano
            return
        self.liv_liscio += (self.livello - self.liv_liscio) * 0.35
        img = self.disegno.frame(time.time() - self.t0, self.stato, self.liv_liscio, self.cc)
        self.vista.setImage_(a_nsimage(img, S, S))

    # --- carta col testo
    @objc.python_method
    def aggiorna_carta(self, adesso):
        testo = self.testo or RISERVA.get(self.stato, "")
        destra, agenti = "", ()
        if self.stato == "lavoro":
            destra = durata(adesso - self.lavoro_dal) if self.lavoro_dal else ""
            agenti = tuple((nome, durata(adesso - inizio) if inizio else "") for nome, inizio in self.agenti)
        chiave = ((self.stato, testo, destra, agenti, SUGGERIMENTO.get(self.stato, ""))
                  if (self.stato != "riposo" and testo) else None)
        if chiave == self.carta_chiave:
            return
        self.carta_chiave = chiave
        if chiave is None:
            self.carta_meta = 0.0               # se ne va sfumando (sfuma_carta la chiude a zero)
            return
        img, lw, lh = carta_testo(self.stato, testo, destra=destra, agenti=agenti,
                                  suggerimento=SUGGERIMENTO.get(self.stato, ""))
        nuova = self.carta_win is None
        if not nuova and self.carta_dim != (lw, lh):        # cambia l'altezza: si ridimensiona sul posto
            self.carta_win.setContentSize_((lw, lh))
            self.carta_vista.setFrame_(NSMakeRect(0, 0, lw, lh))
            if self.carta_vetro is not None:
                self.carta_vetro.setFrame_(NSMakeRect(2, 2, lw - 4, lh - 4))
        self.carta_dim = (lw, lh)
        if nuova:
            self.carta_win, self.carta_vista, self.carta_vetro = _finestra_trasparente(
                NSMakeRect(0, 0, lw, lh), ignora_mouse=True, vetro=(NSMakeRect(2, 2, lw - 4, lh - 4), 14))
            self.carta_win.setHasShadow_(True)              # un'ombra sola, morbida, come le finestre di macOS
            self.carta_alfa, self.carta_scivola = 0.0, (0.0 if self.riduci else 1.0)
            self.carta_win.setAlphaValue_(0.0)
        self.carta_vista.setImage_(a_nsimage(img, lw, lh))
        self.carta_meta = 1.0
        self.posiziona_carta()
        if nuova:
            self.carta_win.orderFrontRegardless()

    @objc.python_method
    def posiziona_carta(self):
        if self.carta_win is None:
            return
        cw, ch = self.carta_dim
        o = self.finestra.frame().origin
        larghezza_schermo = NSScreen.mainScreen().frame().size.width
        a_sinistra = o.x - cw + 20 > 4
        x = o.x - cw + 20 if a_sinistra else o.x + S - 20             # a sinistra dell'orb, o a destra se non c'è posto
        if x + cw > larghezza_schermo:
            x = larghezza_schermo - cw - 4
        x += (-1 if a_sinistra else 1) * CARTA_SCIVOLA * self.carta_scivola   # parte scostata e scivola verso l'orb
        self.carta_win.setFrameOrigin_((x, o.y + S / 2 - ch / 2))

    # --- menu e azioni
    @objc.python_method
    def _voce(self, menu, titolo, azione, oggetto=None, spuntata=False):
        v = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titolo, azione, "")
        v.setTarget_(self)
        if oggetto is not None:
            v.setRepresentedObject_(oggetto)
        menu.addItem_(v)
        return v

    @objc.python_method
    def mostra_menu(self, evento):
        self.ultimo_vivo = time.time()
        self.alfa = self.alfa_meta = 1.0
        self.finestra.setAlphaValue_(1.0)
        menu = NSMenu.alloc().init()
        base = f"http://127.0.0.1:{self.porta}"
        self._voce(menu, "Apri Command Center", "apri:", base + "/#home")
        self._voce(menu, "Lavagna agenti", "apri:", base + "/#lavagna")
        menu.addItem_(NSMenuItem.separatorItem())
        attivo = leggi_motore()
        for mid, nome, _ in MOTORI:
            self._voce(menu, ("●  " if mid == attivo else "○  ") + nome, "motore:", mid)
        menu.addItem_(NSMenuItem.separatorItem())
        self._voce(menu, "Sblocca posizione" if self.bloccato else "Blocca posizione", "blocca:")
        self._voce(menu, "Chiudi Jarvis widget", "chiudi:")
        NSMenu.popUpContextMenu_withEvent_forView_(menu, evento, self.vista)

    def apri_(self, voce):
        webbrowser.open(voce.representedObject())

    def motore_(self, voce):
        scrivi_motore(voce.representedObject())

    def blocca_(self, voce):
        self.bloccato = not self.bloccato

    def chiudi_(self, voce):
        NSApplication.sharedApplication().terminate_(None)

    def clicSingolo_(self, timer):
        self.timer_clic = None
        if self.evento_clic is not None:
            self.mostra_menu(self.evento_clic)

    @objc.python_method
    def salva_posizione(self):
        o = self.finestra.frame().origin
        try:
            POSIZIONE.write_text(json.dumps({"x": o.x, "y": o.y}), encoding="utf-8")
        except Exception:
            pass

    # --- mouse
    def gestisci_(self, evento):
        if evento.window() is not self.finestra:
            return evento
        tipo = evento.type()
        if tipo == NSEventTypeRightMouseDown:
            self.mostra_menu(evento)
            return None
        if tipo == NSEventTypeLeftMouseDown:
            punto = NSEvent.mouseLocation()
            origine = self.finestra.frame().origin
            self.offset = (punto.x - origine.x, punto.y - origine.y)
            self.mosso = 0.0
        elif tipo == NSEventTypeLeftMouseDragged and self.offset is not None:
            if self.bloccato:
                self.mosso += SOGLIA_CLIC       # bloccato: il trascinamento non sposta e non conta come clic
                return evento
            punto = NSEvent.mouseLocation()
            nuova = (punto.x - self.offset[0], punto.y - self.offset[1])
            vecchia = self.finestra.frame().origin
            self.mosso += abs(nuova[0] - vecchia.x) + abs(nuova[1] - vecchia.y)
            self.finestra.setFrameOrigin_(nuova)
            self.posiziona_carta()
        elif tipo == NSEventTypeLeftMouseUp:
            if self.offset is not None:
                if self.mosso >= SOGLIA_CLIC:
                    self.salva_posizione()
                elif evento.clickCount() >= 2:      # doppio clic: il Command Center
                    if self.timer_clic is not None:
                        self.timer_clic.invalidate()
                        self.timer_clic = None
                    webbrowser.open(f"http://127.0.0.1:{self.porta}/#home")
                else:                               # un clic: il menu, dopo un attimo (il doppio lo annulla)
                    self.evento_clic = evento
                    self.timer_clic = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        DOPPIO_CLIC_S, self, "clicSingolo:", None, False)
            self.offset = None
        return evento


def istanza_unica():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORTA))
    except OSError:
        return None
    return s


def main():
    lock = istanza_unica()
    if lock is None:
        print("L'orb di Jarvis è già acceso.")
        sys.exit(0)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # niente icona nel Dock
    orb = Orb.alloc().init()
    _RIFERIMENTI_VIVI.append(orb)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        INTERVALLO_DATI_S, orb, "tickDati:", None, True)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0 / FPS, orb, "tickFrame:", None, True)
    NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        NSEventMaskLeftMouseDown | NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp | NSEventMaskRightMouseDown,
        orb.gestisci_)
    app.run()


if __name__ == "__main__":
    main()
