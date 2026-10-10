#!/usr/bin/env python3
"""L'orb di Jarvis per Windows: il logo (la J con le onde della voce) dentro
l'anello dello stemma, fluttuante sul desktop, senza cornice, con trasparenza
vera per pixel (UpdateLayeredWindow) e animazione continua.

- trascina con il tasto sinistro: si sposta dove vuoi, la posizione si ricorda
- clic: menu (Command Center, Lavagna agenti, motore, blocca, chiudi)
- doppio clic: apre il Command Center
- stati (letti da strumenti/stato_voce.json, scritto da talk_to_jarvis_windows.py):
  riposo = respiro turchese · ascolto = verde con barre · penso = archi gialli
  che girano · parlo = blu con onde. Il puntino in basso e' verde se il
  Command Center risponde, rosso se e' spento.
- quando parli/rispondi compare una carta col testo vero

Uso:  python strumenti\\jarvis_orb_windows.py
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "command-center")); import senza_finestre  # noqa: E402,F401  (Windows: niente finestre di terminale)
import ctypes
import json
import math
import random
import socket
import sys
import time
import tkinter as tk
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

QUI = Path(__file__).resolve().parent
CONFIG = QUI.parent / "command-center" / "configurazione.json"
STATO_VOCE = QUI / "stato_voce.json"
BUS_LAVORO = QUI.parent / "backtalk" / ".jarvis_status"   # scritto dai ganci jarvis_status.py
POSIZIONE = QUI / "orb_posizione.json"
MOTORE_FILE = Path.home() / ".claude" / "skills" / "aggiorna-memoria" / "motore_attivo.json"

S = 168            # lato finestra (px)
SS = 2             # supersampling
W = S * SS
C = W // 2
R_DISCO = 40 * SS
R_ANELLO = 47 * SS
FPS = 30
VOCE_SCADUTA_S = 40
LOCK_PORTA = 47771

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
COLORE = {"riposo": TURCHESE, "ascolto": VERDE, "penso": GIALLO, "parlo": BLU, "lavoro": LAVANDA}
ETICHETTA = {"ascolto": "ti ascolto", "penso": "sto pensando", "parlo": "Jarvis", "lavoro": "al lavoro"}

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


# ------------------------------------------------------------------ Win32
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.HDC, ctypes.c_void_p, wintypes.COLORREF,
                                       ctypes.c_void_p, wintypes.DWORD]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TOOLWINDOW = 0x80
ULW_ALPHA = 2


class Superficie:
    """Una finestra Tk resa 'layered': mostra un'immagine RGBA con alpha per pixel."""

    def __init__(self, finestra, w, h):
        self.w, self.h = w, h
        self.hwnd = user32.GetParent(finestra.winfo_id()) or finestra.winfo_id()
        ex = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        self.dc_schermo = user32.GetDC(None)
        self.dc = gdi32.CreateCompatibleDC(self.dc_schermo)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h  # top-down
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        self.bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.dc_schermo, ctypes.byref(bmi), 0,
                                          ctypes.byref(self.bits), None, 0)
        self.vecchio = gdi32.SelectObject(self.dc, self.bmp)
        self.size = (ctypes.c_long * 2)(w, h)
        self.src = (ctypes.c_long * 2)(0, 0)
        self.blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, alpha per pixel

    def mostra(self, img_rgba):
        a = np.asarray(img_rgba, dtype=np.uint8)
        alpha = a[..., 3:4].astype(np.uint16)
        pre = np.empty_like(a)
        pre[..., 0] = (a[..., 2] * alpha[..., 0] // 255)  # B
        pre[..., 1] = (a[..., 1] * alpha[..., 0] // 255)  # G
        pre[..., 2] = (a[..., 0] * alpha[..., 0] // 255)  # R
        pre[..., 3] = a[..., 3]
        ctypes.memmove(self.bits, pre.tobytes(), self.w * self.h * 4)
        user32.UpdateLayeredWindow(self.hwnd, self.dc_schermo, None, ctypes.byref(self.size),
                                   self.dc, ctypes.byref(self.src), 0, ctypes.byref(self.blend), ULW_ALPHA)


# ------------------------------------------------------------------ disegno
def _font(dim, grassetto=False):
    for nome in (("segoeuib.ttf" if grassetto else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(nome, dim)
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
    # coordinate del logo: gruppo scalato 0.93 attorno al centro
    def T(x, y):
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


class Disegno:
    def __init__(self):
        self.alone = _maschera_alone()
        self.marchio = crea_marchio(int(R_DISCO * 1.62))
        self.disco = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.disco)
        d.ellipse([C - R_DISCO, C - R_DISCO, C + R_DISCO, C + R_DISCO], fill=BG + (255,), outline=BORDO + (255,),
                  width=2 * SS)
        # riflesso in alto: un velo di luce
        vel = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        ImageDraw.Draw(vel).ellipse([C - R_DISCO * 0.86, C - R_DISCO * 0.95, C + R_DISCO * 0.86, C - R_DISCO * 0.1],
                                    fill=(255, 255, 255, 20))
        self.disco = Image.alpha_composite(self.disco, vel.filter(ImageFilter.GaussianBlur(6 * SS)))

    def frame(self, t, stato, livello, cc_acceso):
        col = COLORE[stato]
        im = Image.new("RGBA", (W, W), (0, 0, 0, 0))

        # alone che respira
        if stato == "riposo":
            k = 0.30 + 0.16 * math.sin(t * 1.7)
        elif stato == "ascolto":
            k = 0.42 + 0.35 * livello
        elif stato in ("penso", "lavoro"):
            k = 0.38 + 0.12 * math.sin(t * 5)
        else:
            k = 0.40 + 0.25 * abs(math.sin(t * 4.2)) + 0.2 * livello
        im = Image.alpha_composite(im, _tinta(col, self.alone, k))

        d = ImageDraw.Draw(im)
        # anello dello stemma
        w_an = 3 * SS
        box = [C - R_ANELLO, C - R_ANELLO, C + R_ANELLO, C + R_ANELLO]
        d.ellipse(box, outline=ANELLO + (255,), width=w_an)

        # arco luminoso che gira sull'anello
        if stato in ("penso", "lavoro"):
            v = 260 if stato == "penso" else 150
            for off in (0, 180):
                a0 = (t * v + off) % 360
                d.arc(box, a0, a0 + 80, fill=col + (255,), width=w_an + SS)
        else:
            v = 70 if stato == "riposo" else 130
            a0 = (t * v) % 360
            d.arc(box, a0, a0 + 55, fill=_mix(ANELLO, col, 0.85) + (255,), width=w_an + SS)
            d.arc(box, a0 + 180, a0 + 215, fill=_mix(ANELLO, col, 0.5) + (255,), width=w_an)

        # onde del parlato: cerchi che si espandono
        if stato == "parlo":
            for i in range(3):
                p = (t * 0.9 + i / 3) % 1
                rr = R_ANELLO + p * (C - R_ANELLO - 4 * SS)
                al = int(190 * (1 - p) ** 1.5)
                d.ellipse([C - rr, C - rr, C + rr, C + rr], outline=col + (al,), width=2 * SS)

        # barre attorno all'anello mentre ascolta
        if stato == "ascolto":
            n = 36
            for i in range(n):
                ang = 2 * math.pi * i / n + t * 0.4
                lung = (3 + (6 + 20 * livello) * abs(math.sin(t * 6 + i * 1.7)) * (0.5 + random.random() * 0.5)) * SS
                r0 = R_ANELLO + 5 * SS
                d.line([C + r0 * math.cos(ang), C + r0 * math.sin(ang),
                        C + (r0 + lung) * math.cos(ang), C + (r0 + lung) * math.sin(ang)],
                       fill=col + (230,), width=2 * SS)

        # disco e logo (il logo respira appena)
        im = Image.alpha_composite(im, self.disco)
        scala = 1 + 0.025 * math.sin(t * 1.7) + (0.05 * livello if stato in ("ascolto", "parlo") else 0)
        m = self.marchio
        lato = int(m.width * scala)
        mm = m.resize((lato, lato), Image.BILINEAR) if lato != m.width else m
        im.alpha_composite(mm, (C - lato // 2, C - lato // 2 - 1 * SS))

        # puntino di stato del Command Center
        d = ImageDraw.Draw(im)
        px, py, pr = C + R_DISCO * 0.72, C + R_DISCO * 0.72, 5.5 * SS
        d.ellipse([px - pr - SS, py - pr - SS, px + pr + SS, py + pr + SS], fill=BG + (255,))
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(VERDE if cc_acceso else ROSSO) + (255,))

        return im.resize((S, S), Image.LANCZOS)


def carta_testo(stato, testo, larghezza=330):
    """La carta col testo (a sinistra o a destra dell'orb)."""
    f_t, f_e = _font(13), _font(11, True)
    max_w = larghezza - 32
    righe, riga = [], ""
    for parola in testo.split():
        prova = (riga + " " + parola).strip()
        if f_t.getlength(prova) <= max_w:
            riga = prova
        else:
            righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    righe = righe[:6]
    alt = 44 + 19 * len(righe)
    k = 2
    im = Image.new("RGBA", (larghezza * k, alt * k), (0, 0, 0, 0))
    col = COLORE.get(stato, TURCHESE)
    ImageDraw.Draw(im).rounded_rectangle([2 * k, 2 * k, (larghezza - 2) * k, (alt - 2) * k], radius=16 * k,
                                         fill=(18, 22, 48, 238), outline=BORDO + (255,), width=k)
    ImageDraw.Draw(im).rounded_rectangle([2 * k, 14 * k, 6 * k, (alt - 14) * k], radius=2 * k, fill=col + (255,))
    im = im.resize((larghezza, alt), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    d.text((18, 11), ETICHETTA.get(stato, "").upper(), font=f_e, fill=col + (255,))
    for i, r in enumerate(righe):
        d.text((18, 32 + 19 * i), r, font=f_t, fill=(238, 240, 250, 255))
    return im


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


def leggi_voce():
    try:
        d = json.loads(STATO_VOCE.read_text(encoding="utf-8"))
    except Exception:
        return "riposo", "", 0.0
    if time.time() - d.get("ts", 0) > VOCE_SCADUTA_S or d.get("stato") not in ("ascolto", "penso", "parlo"):
        return "riposo", "", 0.0
    return d["stato"], d.get("testo", ""), float(d.get("livello", 0.0) or 0.0)


def leggi_lavoro():
    """(True, testo) se una sessione di Claude Code sta lavorando adesso (bus dei ganci)."""
    try:
        d = json.loads(BUS_LAVORO.read_text(encoding="utf-8"))
    except Exception:
        return False, ""
    if not d.get("lavorando") or time.time() - d.get("ts", 0) > 90:
        return False, ""
    attivi = [a for a in d.get("agenti") or [] if a.get("stato") == "attivo"]
    riga = (d.get("azione") or "lavoro") + (f" · {d['dettaglio']}" if d.get("dettaglio") else "")
    if attivi:
        riga += f"  ({len(attivi)} agenti: " + ", ".join(a.get("nodo") or a.get("tipo") or "?" for a in attivi[:4]) + ")"
    return True, riga


def apri_app(url):
    """Apre l'indirizzo come app di Windows (finestra propria di Chrome/Edge, senza barra), non come scheda."""
    import os
    import subprocess
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            exe = Path(base) / rel
            if base and exe.exists():
                subprocess.Popen([str(exe), f"--app={url}"])
                return
    webbrowser.open(url)


def leggi_motore():
    try:
        return json.loads(MOTORE_FILE.read_text(encoding="utf-8")).get("motore", "claude")
    except Exception:
        return "claude"


def scrivi_motore(m):
    import shutil
    cmd = {"claude": "claude", "gemini": "gemini", "cursor": "cursor-agent", "codex": "codex"}[m]
    if not shutil.which(cmd):
        return False
    MOTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOTORE_FILE.write_text(json.dumps({"motore": m}), encoding="utf-8")
    return True


# ------------------------------------------------------------------ app
class Orb:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        self.porta = porta()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.title("Jarvis")

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = sw - S - 30, sh - S - 90
        try:
            p = json.loads(POSIZIONE.read_text(encoding="utf-8"))
            x, y = int(p["x"]), int(p["y"])
        except Exception:
            pass
        x = max(-S // 3, min(sw - S * 2 // 3, x))
        y = max(-S // 3, min(sh - S * 2 // 3, y))
        self.root.geometry(f"{S}x{S}+{x}+{y}")
        self.root.update_idletasks()
        self.sup = Superficie(self.root, S, S)
        self.disegno = Disegno()

        self.carta_win = None
        self.carta_sup = None
        self.carta_chiave = None
        self.stato, self.testo, self.livello = "riposo", "", 0.0
        self.liv_liscio = 0.0
        self.cc = False
        self.t0 = time.time()
        self.trascina = None
        self.mosso = False
        self.clic_id = None
        self.bloccato = False

        self.root.bind("<ButtonPress-1>", self.premi)
        self.root.bind("<B1-Motion>", self.muovi)
        self.root.bind("<ButtonRelease-1>", self.rilascia)
        self.root.bind("<Button-3>", self.menu)
        self.root.bind("<Double-Button-1>", self.doppio)

        self.ciclo_dati()
        self.ciclo_cc()
        self.ciclo_frame()
        self.root.mainloop()

    # --- interazione
    def premi(self, e):
        self.trascina = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())
        self.mosso = False

    def muovi(self, e):
        if self.trascina is None or self.bloccato:
            return
        x, y = e.x_root - self.trascina[0], e.y_root - self.trascina[1]
        if abs(x - self.root.winfo_x()) + abs(y - self.root.winfo_y()) > 3:
            self.mosso = True
        self.root.geometry(f"+{x}+{y}")
        self.posiziona_carta()

    def rilascia(self, e):
        if self.mosso:
            self.salva_posizione()
            return
        if self.clic_id is None:  # clic singolo (il doppio lo annulla)
            self.clic_id = self.root.after(260, lambda: (setattr(self, "clic_id", None), self.menu(e)))

    def doppio(self, e):
        if self.clic_id is not None:
            self.root.after_cancel(self.clic_id)
            self.clic_id = None
        apri_app(f"http://127.0.0.1:{self.porta}/#home")

    def salva_posizione(self):
        try:
            POSIZIONE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}), encoding="utf-8")
        except Exception:
            pass

    def menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg="#151a36", fg="#eef0fa", activebackground="#3a4170",
                    activeforeground="#ffffff", bd=0, font=("Segoe UI", 10))
        base = f"http://127.0.0.1:{self.porta}"
        m.add_command(label="Apri Command Center", command=lambda: apri_app(base + "/#home"))
        m.add_command(label="Lavagna agenti", command=lambda: apri_app(base + "/#lavagna"))
        m.add_separator()
        att = leggi_motore()
        for mid, nome in (("claude", "Claude Code"), ("gemini", "Gemini"), ("cursor", "Cursor"), ("codex", "Codex")):
            m.add_command(label=("●  " if mid == att else "○  ") + nome, command=lambda k=mid: scrivi_motore(k))
        m.add_separator()
        m.add_command(label=("Sblocca posizione" if self.bloccato else "Blocca posizione"), command=self.alterna_blocco)
        m.add_command(label="Chiudi Jarvis widget", command=self.root.destroy)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def alterna_blocco(self):
        self.bloccato = not self.bloccato

    # --- carta col testo
    def posiziona_carta(self):
        if self.carta_win is None:
            return
        cw, ch = self.carta_sup.w, self.carta_sup.h
        ox, oy = self.root.winfo_x(), self.root.winfo_y()
        sw = self.root.winfo_screenwidth()
        x = ox - cw + 20 if ox - cw + 20 > 4 else ox + S - 20
        if x + cw > sw:
            x = sw - cw - 4
        y = max(4, oy + S // 2 - ch // 2)
        self.carta_win.geometry(f"+{x}+{y}")

    def aggiorna_carta(self):
        chiave = (self.stato, self.testo) if (self.stato != "riposo" and self.testo) else None
        if chiave == self.carta_chiave:
            return
        self.carta_chiave = chiave
        if self.carta_win is not None:
            self.carta_win.destroy()
            self.carta_win = self.carta_sup = None
        if chiave is None:
            return
        img = carta_testo(self.stato, self.testo)
        self.carta_win = tk.Toplevel(self.root)
        self.carta_win.overrideredirect(True)
        self.carta_win.attributes("-topmost", True)
        self.carta_win.geometry(f"{img.width}x{img.height}+0+0")
        self.carta_win.update_idletasks()
        self.carta_sup = Superficie(self.carta_win, img.width, img.height)
        self.carta_sup.mostra(img)
        self.posiziona_carta()

    # --- cicli
    def ciclo_dati(self):
        self.stato, self.testo, self.livello = leggi_voce()
        if self.stato == "riposo":
            al_lavoro, riga = leggi_lavoro()
            if al_lavoro:
                self.stato, self.testo = "lavoro", riga
        self.aggiorna_carta()
        self.root.after(120, self.ciclo_dati)

    def ciclo_cc(self):
        self.cc = cc_risponde(self.porta)
        self.root.after(4000, self.ciclo_cc)

    def ciclo_frame(self):
        t0 = time.time()
        self.liv_liscio += (self.livello - self.liv_liscio) * 0.35
        img = self.disegno.frame(t0 - self.t0, self.stato, self.liv_liscio, self.cc)
        self.sup.mostra(img)
        attesa = max(1, int(1000 / FPS - (time.time() - t0) * 1000))
        self.root.after(attesa, self.ciclo_frame)


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
        print("L'orb di Jarvis e' gia' acceso.")
        sys.exit(0)
    Orb()


if __name__ == "__main__":
    main()
