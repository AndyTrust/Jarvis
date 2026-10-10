#!/usr/bin/env python3
"""Grafici SVG per i report in PDF. Solo libreria standard.

Si usano da Python:
    from grafici import barre, linea_del_tempo
    barre("uscita.svg", "Titolo", [("Etichetta", 12), ("Altra", 5)], colori=None)
    linea_del_tempo("uscita.svg", "Titolo", "11:30", "16:45",
                    [("11:53", "12:01", "lavoro", "#16a34a"), ...],
                    segni=[("12:31", "scade")])

Nel report markdown si richiamano con ![Titolo](grafici/uscita.svg): Obsidian li
mostra così, e report_pdf.py li porta dentro il PDF.
"""
from html import escape

FONT = "font-family='-apple-system,Helvetica,Arial,sans-serif'"
PALETTE = ["#0e7490", "#f59e0b", "#16a34a", "#dc2626", "#7c3aed", "#475569"]


def _min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def barre(percorso, titolo, voci, colori=None, larghezza=720, unita=""):
    """Barre orizzontali. voci = [(etichetta, numero), ...]."""
    riga, sinistra, destra = 30, 210, 60
    alto = 46 + riga * len(voci)
    massimo = max(v for _, v in voci) or 1
    utile = larghezza - sinistra - destra
    s = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{larghezza}' height='{alto}' viewBox='0 0 {larghezza} {alto}'>",
         f"<rect width='100%' height='100%' fill='white'/>",
         f"<text x='0' y='20' {FONT} font-size='15' font-weight='700' fill='#0b3b4a'>{escape(titolo)}</text>"]
    for i, (et, n) in enumerate(voci):
        y = 40 + i * riga
        col = (colori or PALETTE)[i % len(colori or PALETTE)]
        w = max(2, utile * n / massimo)
        s.append(f"<text x='{sinistra - 10}' y='{y + 15}' text-anchor='end' {FONT} font-size='12' fill='#1a1f2b'>{escape(et)}</text>")
        s.append(f"<rect x='{sinistra}' y='{y}' width='{w:.1f}' height='20' rx='3' fill='{col}'/>")
        s.append(f"<text x='{sinistra + w + 8:.1f}' y='{y + 15}' {FONT} font-size='12' font-weight='700' fill='#1a1f2b'>{n}{escape(unita)}</text>")
    s.append("</svg>")
    _scrivi(percorso, s)


def linea_del_tempo(percorso, titolo, inizio, fine, tratti, segni=None, larghezza=720):
    """Una barra del tempo. tratti = [(da, a, etichetta, colore)], segni = [(ora, etichetta)]."""
    t0, t1 = _min(inizio), _min(fine)
    sinistra, destra, y, h = 20, 20, 62, 34
    utile = larghezza - sinistra - destra
    x = lambda hhmm: sinistra + utile * (_min(hhmm) - t0) / (t1 - t0)
    alto = 190
    s = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{larghezza}' height='{alto}' viewBox='0 0 {larghezza} {alto}'>",
         "<rect width='100%' height='100%' fill='white'/>",
         f"<text x='0' y='20' {FONT} font-size='15' font-weight='700' fill='#0b3b4a'>{escape(titolo)}</text>"]
    ora = (t0 // 60 + 1) * 60
    while ora < t1:                                                   # tacche ogni ora
        xx = sinistra + utile * (ora - t0) / (t1 - t0)
        s.append(f"<line x1='{xx:.1f}' y1='{y + h + 4}' x2='{xx:.1f}' y2='{y + h + 12}' stroke='#94a3b8'/>")
        s.append(f"<text x='{xx:.1f}' y='{y + h + 26}' text-anchor='middle' {FONT} font-size='11' fill='#64748b'>{ora // 60}:00</text>")
        ora += 60
    for da, a, et, col in tratti:
        x0, x1 = x(da), x(a)
        s.append(f"<rect x='{x0:.1f}' y='{y}' width='{max(x1 - x0, 3):.1f}' height='{h}' fill='{col}'/>")
        s.append(f"<text x='{(x0 + x1) / 2:.1f}' y='{y + h + 48}' text-anchor='middle' {FONT} font-size='12' font-weight='700' fill='{col}'>{escape(et)}</text>")
    for ora_s, et in segni or []:
        xx = x(ora_s)
        s.append(f"<line x1='{xx:.1f}' y1='{y - 8}' x2='{xx:.1f}' y2='{y + h}' stroke='#1a1f2b' stroke-width='1.5'/>")
        s.append(f"<text x='{xx:.1f}' y='{y - 12}' text-anchor='middle' {FONT} font-size='10' fill='#1a1f2b'>{escape(et)}</text>")
    s.append("</svg>")
    _scrivi(percorso, s)


def _scrivi(percorso, righe):
    from pathlib import Path
    p = Path(percorso)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(righe), encoding="utf-8")
