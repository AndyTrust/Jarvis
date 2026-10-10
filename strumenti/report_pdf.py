#!/usr/bin/env python3
"""Trasforma un report in markdown in un PDF e in una pagina HTML, leggibili ovunque.

Uso:  python3 strumenti/report_pdf.py <file.md> [<file.pdf>] [--solo-mancanti]
Senza il secondo argomento PDF e HTML nascono accanto al markdown, stesso nome (l'utente, 07/10/2026:
ogni report deve avere sia l'HTML sia il PDF da scaricare). L'HTML è un file solo: stile dentro e
immagini incorporate. Con --solo-mancanti rifà soltanto quello dei due che non c'è ancora.

Solo libreria standard: il markdown diventa HTML con un convertitore piccolo
(titoli, elenchi, tabelle, grassetto, corsivo, codice, citazioni, linee), e
Chrome senza finestra lo stampa in PDF. Niente da installare.
"""
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font: 12.5px/1.55 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1a1f2b; }
h1 { font-size: 24px; margin: 0 0 6px; padding-bottom: 8px; border-bottom: 3px solid #0e7490; color: #0b3b4a; }
h2 { font-size: 17px; margin: 22px 0 6px; color: #0e7490; border-bottom: 1px solid #d5dde3; padding-bottom: 3px; }
h3 { font-size: 14px; margin: 16px 0 4px; color: #0b3b4a; }
h2, h3 { break-after: avoid; }
p { margin: 6px 0; }
ul, ol { margin: 6px 0 6px 20px; padding: 0; }
li { margin: 2px 0; }
code { font: 11px ui-monospace, Menlo, monospace; background: #eef2f5; padding: 1px 4px; border-radius: 3px; }
pre { background: #eef2f5; padding: 8px 10px; border-radius: 5px; font: 10.5px/1.4 ui-monospace, Menlo, monospace; white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 8px 0; padding: 4px 12px; border-left: 4px solid #f59e0b; background: #fff8e6; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 11px; break-inside: auto; }
tr { break-inside: avoid; }
th { background: #0e7490; color: #fff; text-align: left; padding: 5px 7px; }
td { border: 1px solid #d5dde3; padding: 4px 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f5f8fa; }
hr { border: none; border-top: 1px solid #d5dde3; margin: 14px 0; }
figure { margin: 10px 0; break-inside: avoid; }
img { max-width: 100%; height: auto; }
a { color: #0e7490; }
"""


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def celle(riga):
    riga = riga.strip()
    if riga.startswith("|"):
        riga = riga[1:]
    if riga.endswith("|"):
        riga = riga[:-1]
    return [c.strip() for c in riga.split("|")]


def markdown_a_html(md, base=None):
    righe = md.splitlines()
    if righe and righe[0].strip() == "---":            # frontmatter
        for i in range(1, len(righe)):
            if righe[i].strip() == "---":
                righe = righe[i + 1:]
                break
    out, i = [], 0
    while i < len(righe):
        r = righe[i]
        s = r.strip()
        if s.startswith("```"):
            blocco = []
            i += 1
            while i < len(righe) and not righe[i].strip().startswith("```"):
                blocco.append(righe[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(blocco)) + "</code></pre>")
            i += 1
        elif not s:
            i += 1
        elif base and re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", s):
            m = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", s)
            src = (base / m.group(2)).resolve().as_uri()
            out.append(f'<figure><img src="{src}" alt="{html.escape(m.group(1))}"></figure>')
            i += 1
        elif re.fullmatch(r"-{3,}|\*{3,}", s):
            out.append("<hr>")
            i += 1
        elif s.startswith("#"):
            liv = min(len(s) - len(s.lstrip("#")), 3)
            out.append(f"<h{liv}>{inline(s.lstrip('#').strip())}</h{liv}>")
            i += 1
        elif s.startswith("|") and i + 1 < len(righe) and re.fullmatch(r"\|?[\s:|-]+\|?", righe[i + 1].strip()):
            testa = celle(s)
            i += 2
            corpo = []
            while i < len(righe) and righe[i].strip().startswith("|"):
                corpo.append(celle(righe[i]))
                i += 1
            t = "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in testa) + "</tr></thead><tbody>"
            for c in corpo:
                t += "<tr>" + "".join(f"<td>{inline(x)}</td>" for x in c) + "</tr>"
            out.append(t + "</tbody></table>")
        elif s.startswith(">"):
            citazione = []
            while i < len(righe) and righe[i].strip().startswith(">"):
                citazione.append(righe[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(citazione)) + "</blockquote>")
        elif re.match(r"([-*+]|\d+[.)])\s", s):
            ordinato = s[0].isdigit()
            voci = []
            inizio_blocco = r"\s*(#|```|\||>|-{3,}$)"
            while i < len(righe):
                if re.match(r"\s*([-*+]|\d+[.)])\s", righe[i]):
                    voce = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", righe[i])
                    voce = re.sub(r"^\[( |x)\]\s*", lambda m: "☐ " if m.group(1) == " " else "☑ ", voce)
                    voci.append(voce)
                    i += 1
                elif righe[i].strip() and not re.match(inizio_blocco, righe[i]):
                    voci[-1] += " " + righe[i].strip()         # riga che continua la voce sopra
                    i += 1
                elif (not righe[i].strip() and i + 1 < len(righe)
                      and re.match(r"\s{2,}\S", righe[i + 1])
                      and not re.match(r"\s*([-*+]|\d+[.)])\s", righe[i + 1])):
                    i += 1                                       # vuoto poi rientrata: stessa voce
                else:
                    break
            tag = "ol" if ordinato else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(v)}</li>" for v in voci) + f"</{tag}>")
        else:
            par = []
            while i < len(righe) and righe[i].strip() and not re.match(
                    r"\s*(#|```|\||>|([-*+]|\d+[.)])\s|-{3,}$)", righe[i]):
                par.append(righe[i].strip())
                i += 1
            if not par:                                   # riga che non capisco: la tengo com'è
                par.append(righe[i].strip())
                i += 1
            out.append("<p>" + inline(" ".join(par)) + "</p>")
    return "\n".join(out)


def incorpora_immagini(corpo):
    """Le immagini file:// diventano data URI: la pagina HTML resta un file solo, apribile ovunque."""
    import base64, mimetypes
    from urllib.parse import unquote, urlparse

    def sostituisci(m):
        p = Path(unquote(urlparse(m.group(1)).path))
        if not p.is_file():
            return m.group(0)
        tipo = mimetypes.guess_type(p.name)[0] or "image/png"
        return 'src="data:%s;base64,%s"' % (tipo, base64.b64encode(p.read_bytes()).decode())
    return re.sub(r'src="(file://[^"]+)"', sostituisci, corpo)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    solo_mancanti = "--solo-mancanti" in sys.argv
    if not args:
        sys.exit(__doc__)
    sorgente = Path(args[0]).expanduser().resolve()
    pdf = Path(args[1]).expanduser().resolve() if len(args) > 1 else sorgente.with_suffix(".pdf")
    html_file = pdf.with_suffix(".html")
    corpo = markdown_a_html(sorgente.read_text(encoding="utf-8"), sorgente.parent)
    pagina = f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(sorgente.stem)}</title><style>{CSS}</style></head><body>{corpo}</body></html>'
    if not (solo_mancanti and html_file.exists()):
        html_file.parent.mkdir(parents=True, exist_ok=True)
        html_file.write_text(incorpora_immagini(pagina), encoding="utf-8")
        print(f"HTML: {html_file} ({html_file.stat().st_size // 1024} KB)")
    if solo_mancanti and pdf.exists() and pdf.stat().st_size >= 1000:
        return
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "report.html"
        f.write_text(pagina, encoding="utf-8")
        pdf.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", f.as_uri()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
    if not pdf.exists() or pdf.stat().st_size < 1000:
        sys.exit(f"PDF non creato: {pdf}")
    print(f"PDF: {pdf} ({pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
