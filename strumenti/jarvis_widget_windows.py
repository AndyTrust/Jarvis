#!/usr/bin/env python3
"""Il widget di Jarvis per Windows: un piccolo pallino sempre sopra le altre
finestre, in basso a destra dello schermo, che mostra se il Command Center e'
acceso o spento. Un clic apre/chiude la bolla del motore (stesso file di stato
letto dalla sidebar del Command Center e dal widget del Mac, strumenti/jarvis_widget.py:
non si duplica lo stato in due posti). Doppio clic: apre il Command Center nel browser.
Click destro: chiude il widget. Trascinamento (tasto centrale): sposta il widget.

Mentre parli con Jarvis (strumenti/talk_to_jarvis_windows.py, Shift destro), l'orb
cambia colore (ascolto/penso/parlo) e sopra appare da sola una bolla col testo
vero — quello che hai detto, quello che Jarvis risponde. Stesso file di stato
scritto da talk_to_jarvis_windows.py (strumenti/stato_voce.json), stessa idea
del "volto" sul Mac (state/state), qui in una versione fatta apposta per Windows.

Non dipende da ai-visualizer ne' da backtalk (Mac-only, non presenti su
Windows): legge solo se qualcosa risponde su http://127.0.0.1:<porta>/.

Uso:
  python3 strumenti/jarvis_widget_windows.py
"""
import json
import random
import shutil
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path

QUI = Path(__file__).resolve().parent
CARTELLA_CC = QUI.parent / "command-center"
CONFIG = CARTELLA_CC / "configurazione.json"
STATO_VOCE_FILE = QUI / "stato_voce.json"
LATO = 30
MARGINE = 24
INTERVALLO_MS = 3000
INTERVALLO_VOCE_MS = 120  # veloce: la forma d'onda deve sembrare viva, non a scatti
DOPPIO_CLIC_MS = 350
VOCE_SCADUTA_S = 40  # un file di stato più vecchio di così è di una sessione morta
N_BARRE = 5

VERDE = "#3ddc84"    # parli tu (ascolto)
ROSSO = "#e05252"
GRIGIO = "#555555"
BLU = "#4a9eff"      # parla Jarvis
GIALLO = "#f5c542"   # penso
# richiesto: verde mentre parla l'utente (ascolto), blu mentre parla Jarvis (parlo)
COLORE_STATO_VOCE = {"ascolto": VERDE, "penso": GIALLO, "parlo": BLU}
ETICHETTA_STATO_VOCE = {"ascolto": "ti ascolto…", "penso": "sto pensando…", "parlo": "Jarvis dice:"}

# Stessa fonte del selettore "Motore" nella sidebar del Command Center e della
# bolla del widget Mac: un solo file di stato, non duplicato.
MOTORE_FILE = Path.home() / ".claude" / "skills" / "aggiorna-memoria" / "motore_attivo.json"
MOTORI = ("claude", "gemini", "cursor", "codex")
MOTORI_NOME = {"claude": "Claude Code", "gemini": "Gemini", "cursor": "Cursor", "codex": "Codex"}
MOTORI_COMANDO = {"claude": "claude", "gemini": "gemini", "cursor": "cursor-agent", "codex": "codex"}
ALTEZZA_RIGA = 28
MARGINE_BOLLA = 6


def _leggi_stato_voce():
    try:
        d = json.loads(STATO_VOCE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return "inattivo", "", 0.0
    if time.time() - d.get("ts", 0) > VOCE_SCADUTA_S:
        return "inattivo", "", 0.0
    stato = d.get("stato", "inattivo")
    if stato not in COLORE_STATO_VOCE:
        return "inattivo", "", 0.0
    return stato, d.get("testo", ""), float(d.get("livello", 0.0) or 0.0)


def porta():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("porta", 7777)
    except Exception:
        return 7777


def acceso(p):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/", timeout=1.0):
            return True
    except Exception:
        return False


def _motore_disponibile(id_motore):
    return shutil.which(MOTORI_COMANDO[id_motore]) is not None


def _leggi_motore_attivo():
    try:
        m = json.loads(MOTORE_FILE.read_text(encoding="utf-8")).get("motore", "claude")
        return m if m in MOTORI and _motore_disponibile(m) else "claude"
    except Exception:
        return "claude"


def _scrivi_motore_attivo(id_motore):
    if id_motore not in MOTORI or not _motore_disponibile(id_motore):
        return False
    MOTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MOTORE_FILE.write_text(json.dumps({"motore": id_motore}), encoding="utf-8")
    return True


class Widget:
    def __init__(self):
        self.porta = porta()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg="black")

        schermo_w = self.root.winfo_screenwidth()
        schermo_h = self.root.winfo_screenheight()
        x = schermo_w - LATO - MARGINE
        y = schermo_h - LATO - MARGINE - 40  # sopra la barra delle applicazioni
        self.root.geometry(f"{LATO}x{LATO}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=LATO, height=LATO, bg="black", highlightthickness=0)
        self.canvas.pack()
        self.pallino = self.canvas.create_oval(2, 2, LATO - 2, LATO - 2, fill=GRIGIO, outline="")
        # il "logo": una J bianca al centro dell'orb, come l'avatar di Jarvis nel pannello
        self.logo = self.canvas.create_text(LATO / 2, LATO / 2, text="J", fill="white",
                                             font=("Segoe UI", int(LATO * 0.5), "bold"))

        self.bolla = None
        self.bolla_voce = None
        self._barre_voce = []
        self._ultimo_stato_voce = "inattivo"
        self._clic_precedente_id = None
        self.canvas.bind("<Button-1>", self._clic_sinistro)
        self.canvas.bind("<Button-3>", lambda e: self.root.destroy())
        self._trascina = None
        self.canvas.bind("<ButtonPress-2>", self._inizio_trascina)
        self.canvas.bind("<B2-Motion>", self._trascina_finestra)

        self.aggiorna()
        self.aggiorna_voce()
        self.root.mainloop()

    def _inizio_trascina(self, evento):
        self._trascina = (evento.x, evento.y)

    def _trascina_finestra(self, evento):
        if self._trascina is None:
            return
        dx, dy = evento.x - self._trascina[0], evento.y - self._trascina[1]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._chiudi_bolla()

    def _clic_sinistro(self, evento):
        # un doppio clic (entro DOPPIO_CLIC_MS) apre il Command Center; un clic solo alterna la bolla
        if self._clic_precedente_id is not None:
            self.root.after_cancel(self._clic_precedente_id)
            self._clic_precedente_id = None
            webbrowser.open(f"http://127.0.0.1:{self.porta}/")
            self._chiudi_bolla()
            return
        self._clic_precedente_id = self.root.after(DOPPIO_CLIC_MS, self._alterna_bolla)

    def _alterna_bolla(self):
        self._clic_precedente_id = None
        if self.bolla is not None:
            self._chiudi_bolla()
        else:
            self._apri_bolla()

    def _chiudi_bolla(self):
        if self.bolla is not None:
            self.bolla.destroy()
            self.bolla = None

    def _apri_bolla(self):
        attivo = _leggi_motore_attivo()
        altezza = ALTEZZA_RIGA * len(MOTORI) + 8
        x = self.root.winfo_x()
        y = self.root.winfo_y() - altezza - MARGINE_BOLLA  # sopra l'orb, in basso a destra

        self.bolla = tk.Toplevel(self.root)
        self.bolla.overrideredirect(True)
        self.bolla.attributes("-topmost", True)
        self.bolla.configure(bg="#151515")
        self.bolla.geometry(f"{LATO * 6}x{altezza}+{x - LATO * 5}+{y}")

        for i, id_motore in enumerate(MOTORI):
            pronto = _motore_disponibile(id_motore)
            segno = "●  " if id_motore == attivo else "○  "
            titolo = segno + MOTORI_NOME[id_motore] + ("" if pronto else "  ·  da installare")
            b = tk.Button(
                self.bolla, text=titolo, anchor="w", bg="#151515", fg=("#f0f0f0" if pronto else "#666666"),
                activebackground="#2a2a2a", activeforeground="#f0f0f0", bd=0, font=("Segoe UI", 9),
                state=("normal" if pronto else "disabled"),
                command=lambda m=id_motore: self._scegli_motore(m),
            )
            b.place(x=4, y=i * ALTEZZA_RIGA + 4, width=LATO * 6 - 8, height=ALTEZZA_RIGA - 2)

    def _scegli_motore(self, id_motore):
        if _scrivi_motore_attivo(id_motore):
            self._chiudi_bolla()

    def aggiorna(self):
        # il colore di voce (ascolto/penso/parlo) ha la precedenza su quello del server:
        # lo aggiorna aggiorna_voce(), più veloce; qui solo se la voce è inattiva.
        if self._ultimo_stato_voce == "inattivo":
            colore = VERDE if acceso(self.porta) else ROSSO
            self.canvas.itemconfig(self.pallino, fill=colore)
        self.root.after(INTERVALLO_MS, self.aggiorna)

    def aggiorna_voce(self):
        stato, testo, livello = _leggi_stato_voce()
        cambiato = stato != self._ultimo_stato_voce or (self.bolla_voce is not None
                    and getattr(self, "_ultimo_testo_voce", None) != testo)
        if cambiato:
            self._disegna_stato_voce(stato, testo)
            self._ultimo_testo_voce = testo
        if stato != "inattivo":
            self.canvas.itemconfig(self.pallino, fill=COLORE_STATO_VOCE[stato])
            self._aggiorna_barre(stato, livello)
        self._ultimo_stato_voce = stato
        self.root.after(INTERVALLO_VOCE_MS, self.aggiorna_voce)

    def _disegna_stato_voce(self, stato, testo):
        if stato == "inattivo":
            self.canvas.itemconfig(self.pallino, fill=(VERDE if acceso(self.porta) else ROSSO))
            self._chiudi_bolla_voce()
            return
        self._apri_bolla_voce(stato, testo)

    def _chiudi_bolla_voce(self):
        if self.bolla_voce is not None:
            self.bolla_voce.destroy()
            self.bolla_voce = None
            self._barre_voce = []

    def _apri_bolla_voce(self, stato, testo):
        # non si sovrappone alla bolla del motore, aperta a mano
        self._chiudi_bolla()
        self._chiudi_bolla_voce()
        larghezza = LATO * 8
        etichetta = ETICHETTA_STATO_VOCE.get(stato, stato)
        corpo = testo[:220] if testo else ""
        righe = 2 if corpo else 1
        altezza_barre = 22
        altezza = 20 + righe * 16 + altezza_barre
        x = self.root.winfo_x()
        y = self.root.winfo_y() - altezza - MARGINE_BOLLA

        self.bolla_voce = tk.Toplevel(self.root)
        self.bolla_voce.overrideredirect(True)
        self.bolla_voce.attributes("-topmost", True)
        self.bolla_voce.configure(bg="#151515")
        self.bolla_voce.geometry(f"{larghezza}x{altezza}+{x - larghezza + LATO}+{y}")

        tk.Label(self.bolla_voce, text=etichetta, fg=COLORE_STATO_VOCE[stato], bg="#151515",
                 font=("Segoe UI", 9, "bold"), anchor="w").place(x=8, y=4, width=larghezza - 16, height=16)

        # la forma d'onda: N_BARRE rettangoli, altezza aggiornata a ogni giro dal livello vero
        self.canvas_barre = tk.Canvas(self.bolla_voce, width=larghezza - 16, height=altezza_barre,
                                       bg="#151515", highlightthickness=0)
        self.canvas_barre.place(x=8, y=20)
        self._barre_voce = []
        larghezza_barra = (larghezza - 16) / N_BARRE
        for i in range(N_BARRE):
            cx = i * larghezza_barra + larghezza_barra / 2
            barra = self.canvas_barre.create_rectangle(
                cx - 3, altezza_barre / 2, cx + 3, altezza_barre / 2,
                fill=COLORE_STATO_VOCE[stato], outline="")
            self._barre_voce.append((barra, cx))

        if corpo:
            tk.Label(self.bolla_voce, text=corpo, fg="#f0f0f0", bg="#151515", font=("Segoe UI", 9),
                     anchor="w", justify="left", wraplength=larghezza - 16).place(
                x=8, y=20 + altezza_barre, width=larghezza - 16, height=altezza - 24 - altezza_barre)

    def _aggiorna_barre(self, stato, livello):
        if not self._barre_voce or self.bolla_voce is None:
            return
        altezza_barre = 22
        meta = altezza_barre / 2
        for barra, cx in self._barre_voce:
            # un po' di variazione per barra, cosi' non salgono e scendono tutte uguali
            h = max(2, min(meta, livello * meta * (0.6 + random.random() * 0.8)))
            self.canvas_barre.coords(barra, cx - 3, meta - h, cx + 3, meta + h)
            self.canvas_barre.itemconfig(barra, fill=COLORE_STATO_VOCE[stato])


def main():
    Widget()


if __name__ == "__main__":
    main()
