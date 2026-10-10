#!/usr/bin/env python3
"""Genera lo «Stato» di ogni progetto e lo Stato generale dalle note di Memoria (l'utente, 2026-10-02).

Un file generato per progetto (`Memoria/<spazio>/<progetto>/Stato.md`) e uno generale
(`Memoria/00 Comune/Stato generale.md`): contatori per tipo e variante, cose aperte, ultime decisioni, fatti ed
errori, agenti e report. Non si scrivono a mano: ogni giro li rifà. Le note restano la fonte.

    python3 stato_vault.py            # rifà tutto
    python3 stato_vault.py --prova    # dice cosa scriverebbe, senza scrivere
Schedulato da launchd (com.jarvis.stato-vault, ogni 30 minuti).
"""
import json, re, sys
from datetime import datetime, timedelta
from pathlib import Path

MEM = Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain/Memoria"
SPAZI_JSON = Path(__file__).resolve().parents[1] / "command-center/spazi.json"
PROGETTI = [("Azienda Uno", "CRM"), ("Azienda Uno", "Sito"), ("Azienda Due", "AZD"), ("Azienda Due", "AZD"), ("Azienda Due", "Social"),
            ("Azienda Due", "Comune"), ("Vita personale", "Jarvis"), ("Vita personale", "App Android"),
            ("Vita personale", "prodotto-uno"), ("Vita personale", "Progetto B"), ("Vita personale", "L'utente Business"),
            ("Vita personale", "Hobby"), ("Vita personale", "Demo"), ("Vita personale", "Metatrader"),
            ("Patrimonio", "Progetto B"), ("Patrimonio", "Strategie")]
def progetti_dinamici():
    """Progetti nati dalla lavagna: sezioni_memoria «Spazio/Progetto» di spazi.json non ancora nella lista fissa."""
    try:
        d = json.loads(SPAZI_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    extra = []
    for s in d.get("spazi", []):
        for p in s.get("progetti", []):
            for sez in p.get("sezioni_memoria") or []:
                if sez.count("/") == 1:
                    a, b = sez.split("/")
                    if (a, b) not in PROGETTI and (a, b) not in extra and (MEM / a / b).is_dir():
                        extra.append((a, b))
    return extra


VARIANTI = ["mac", "windows", "test", "business", "comune"]
INIZIO, FINE = "<!-- stato-generato:inizio -->", "<!-- stato-generato:fine -->"


def leggi(p):
    t = p.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"---\n(.*?)\n---\n?", t, re.S)
    c = dict(re.findall(r"^([A-Za-zàèéìòù_]+):\s*(.*)$", m.group(1), re.M)) if m else {}
    return {k: v.strip().strip("\"'") for k, v in c.items()}, t[m.end():] if m else t


def note_di(cartella):
    out = []
    for p in cartella.rglob("*.md"):
        if p.name in ("Stato.md",) or "_archivio" in p.parts or "Report" in p.parts or ".claude" in p.parts:
            continue
        c, corpo = leggi(p)
        c["_p"], c["_corpo"], c["_stem"] = p, corpo, p.stem
        out.append(c)
    return out


def quando(c):
    try:
        return datetime.strptime(c.get("aggiornato", "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.fromtimestamp(c["_p"].stat().st_mtime)


def var_riga(testo):
    """La variante di una riga di «Da fare» di Jarvis, dalle parole che usa."""
    sys.path.insert(0, str(Path(__file__).parent))
    from vault_cartellini import variante
    return variante(testo, "")


def aperti(note):
    voci = []
    for c in note:
        if c.get("tipo") == "da-fare" or c["_p"].name == "Da fare.md":
            for riga in c["_corpo"].splitlines():
                m = re.match(r"\s*- \[ \]\s*(.+)", riga)
                if m:
                    voci.append((c["_stem"], m.group(1).strip()[:200], c.get("progetto", "")))
    return voci


def ultime(note, tipo, n=6):
    s = sorted((c for c in note if c.get("tipo") == tipo), key=quando, reverse=True)[:n]
    return [f"- {quando(c):%Y-%m-%d} · [[{c['_stem']}]]" + (f" · {c['variante']}" if c.get("variante") else "") for c in s]


def agenti_di(spazio, progetto):
    try:
        d = json.loads(SPAZI_JSON.read_text(encoding="utf-8"))
        sys.path.insert(0, str(SPAZI_JSON.parent))
        import spazi
    except Exception:
        return []
    righe = []
    for s in spazi.carica():
        for p in s["progetti"]:
            if any(x == f"{spazio}/{progetto}" for x in p.get("sezioni_memoria") or []) and p["esiste"]:
                for a in spazi.profili(p["cartella"], p.get("capogruppo")):
                    righe.append(f"| {a['nome']} | {a['modello']} | {'sì' if a.get('attivo', True) else 'spento'} | "
                                 f"{a.get('riporta_a') or ('CEO' if a.get('capogruppo') else '—')} |")
    return righe


def blocco(spazio, progetto, note):
    ora = datetime.now()
    per_tipo = {}
    for c in note:
        per_tipo[c.get("tipo", "nota")] = per_tipo.get(c.get("tipo", "nota"), 0) + 1
    ap = aperti(note)
    ap = [a for a in ap]
    ultimo = max((quando(c) for c in note), default=None)
    L = [INIZIO, "", f"> Generato da `strumenti/stato_vault.py` il {ora:%Y-%m-%d %H:%M}. Non modificare qui: si cambiano le note, lo Stato si rifà da solo.", "",
         f"**Ultima nota aggiornata:** {ultimo:%Y-%m-%d %H:%M}" if ultimo else "**Nessuna nota ancora.**",
         f"**Note:** {len(note)} · " + ", ".join(f"{k} {v}" for k, v in sorted(per_tipo.items(), key=lambda x: -x[1])), ""]
    if progetto == "Jarvis":
        L += ["## Per variante", "", "| Variante | Note | Aperte | Ultimo aggiornamento |", "|---|---|---|---|"]
        for v in VARIANTI:
            nv = [c for c in note if c.get("variante") == v]
            if nv:
                av = [a for a in ap if var_riga(a[1]) == v]
                L.append(f"| {v} | {len(nv)} | {len(av)} | {max(quando(c) for c in nv):%Y-%m-%d} |")
        L.append("")
    L += [f"## Da fare ({len(ap)} aperte)", ""] + ([f"- [[{s}]]" + (f" · **{var_riga(t)}**" if progetto == "Jarvis" else "") + f" — {t}" for s, t, _ in ap[:25]] or ["- niente di aperto"]) + (["- … e altre " + str(len(ap) - 25)] if len(ap) > 25 else []) + [""]
    for tipo, titolo in (("decisione", "Ultime decisioni"), ("fatto", "Ultimi fatti"), ("errore", "Errori da non ripetere (più recenti)")):
        u = ultime(note, tipo)
        if u:
            L += [f"## {titolo}", ""] + u + [""]
    ag = agenti_di(spazio, progetto)
    if ag:
        L += ["## Agenti di questo progetto", "", "| Agente | Modello | Attivo | Risponde a |", "|---|---|---|---|"] + ag + [""]
    rep = MEM / spazio / "Report" / progetto
    if rep.is_dir():
        L += ["## Report", "", *[f"- [[{f.stem}]]" for f in sorted(rep.glob("Stato *.md"))], ""]
    L.append(FINE)
    return "\n".join(L), len(ap), ultimo, len(note)


def cartella_codice(spazio, progetto):
    try:
        sys.path.insert(0, str(SPAZI_JSON.parent))
        import spazi
        for s in spazi.carica():
            for p in s["progetti"]:
                if f"{spazio}/{progetto}" in (p.get("sezioni_memoria") or []):
                    return p["cartella"], p.get("capogruppo")
    except Exception:
        pass
    return None, None


def guida(spazio, progetto):
    """Guida agenti.md: creata una volta sola (poi si scrive a mano); lo Stato invece si rifà."""
    cod, capo = cartella_codice(spazio, progetto)
    var = ("\n## Varianti di Jarvis\n\n- **mac**: Jarvis sul Mac dell'utente (Command Center, lavagna, voce, launchd, VPS).\n- **windows**: installazione e uso su un PC Windows (PowerShell, `lavori.ps1`).\n"
           "- **test**: ambiente di prova (Jarvis-Privato-Test, installazioni pulite).\n- **business**: il prodotto venduto (licenza, Sponsors, Patreon, assistenza).\n"
           "- **comune**: vale per tutte.\nUna nota di una variante non si usa per decidere su un'altra senza dirlo.\n") if progetto == "Jarvis" else ""
    return (f"---\ntitolo: Guida agenti · {progetto}\ntipo: guida\nspazio: {spazio}\nprogetto: {progetto}\nstato: vivo\n"
            f"aggiornato: {datetime.now():%Y-%m-%d %H:%M}\n---\n\n# Guida agenti · {progetto}\n\n"
            f"Per ogni agente di questo progetto e per l'utente. Lo stato si legge in [[Stato]] (generato); qui c'è come si lavora. Collegato a [[{spazio}]] · [[LEGGIMI]].\n\n"
            f"## Prima di lavorare\n\n1. Leggi [[Stato]]: cosa è aperto, ultime decisioni ed errori.\n2. Cerca prima di riscoprire: `python3 ~/Jarvis/strumenti/cerca_memoria.py --spazio \"{spazio}\" \"parole\"`.\n"
            "3. Badge: `python3 ~/Jarvis/strumenti/lavori.py chi`, poi `prendo` con `--agente <tuo nome>`; alla fine `finito`.\n\n"
            f"## Dove sta cosa\n\n- Codice: `{cod or 'vedi Progetti/'}`\n- Capogruppo: {capo or 'nessuno: la chat master (Jarvis) coordina'}\n"
            f"- Memoria: `Memoria/{spazio}/{progetto}/` (Fatti, Decisioni, Errori da non ripetere, Wiki, Da fare)\n- Report: `Memoria/{spazio}/Report/{progetto}/Stato {progetto}.md` (uno solo, vivo)\n{var}\n"
            "## Dopo aver lavorato\n\n- Scrivi una nota con il cartellino (spazio, progetto, tipo, stato, aggiornato; variante per Jarvis). Prima aggiungi a una nota esistente.\n"
            "- Aggiorna il `Da fare.md` del progetto: spunta ciò che è chiuso.\n- Aggiorna il report vivo; il vecchio va in `Report/.../_archivio/AAAA-MM/`.\n"
            "- Niente segreti nelle note. Niente cancellazioni senza il sì dell'utente.\n\n"
            "## Quando non sei sicuro\n\nDillo. Prove, non ipotesi: dai per fatto solo ciò che hai controllato con un file o un comando.\n")


def scrivi(p, blocco_txt, intestazione):
    if p.exists():
        t = p.read_text(encoding="utf-8")
        if INIZIO in t and FINE in t:
            nuovo = re.sub(re.escape(INIZIO) + r".*?" + re.escape(FINE), lambda m: blocco_txt, t, flags=re.S)
        else:
            nuovo = t.rstrip() + "\n\n" + blocco_txt + "\n"
    else:
        nuovo = intestazione + "\n" + blocco_txt + "\n"
    if not p.exists() or p.read_text(encoding="utf-8") != nuovo:
        p.write_text(nuovo, encoding="utf-8")
        return True
    return False


def main(prova):
    tab, cambiati = [], 0
    for spazio, progetto in PROGETTI + progetti_dinamici():
        cart = MEM / spazio / progetto
        if not cart.is_dir():
            continue
        note = note_di(cart)
        testo, n_ap, ultimo, n = blocco(spazio, progetto, note)
        intest = (f"---\ntitolo: Stato · {progetto}\ntipo: stato\nspazio: {spazio}\nprogetto: {progetto}\nstato: vivo\n"
                  f"aggiornato: {datetime.now():%Y-%m-%d %H:%M}\n---\n\n# Stato · {progetto}\n\nCollegato a [[{spazio}]] · [[Stato generale]] · "
                  f"guida per gli agenti: [[Guida agenti]]\n")
        if not prova:
            cambiati += scrivi(cart / "Stato.md", testo, intest)
            if not (cart / "Guida agenti.md").exists():
                (cart / "Guida agenti.md").write_text(guida(spazio, progetto), encoding="utf-8"); cambiati += 1
        fermo = ultimo and (datetime.now() - ultimo > timedelta(days=7)) and n_ap > 0
        tab.append((spazio, progetto, n, n_ap, ultimo, fermo))
    # generale
    L = [INIZIO, "", f"> Generato il {datetime.now():%Y-%m-%d %H:%M} da `strumenti/stato_vault.py`.", "",
         "| Spazio | Progetto | Note | Aperte | Ultimo aggiornamento | Segnale |", "|---|---|---|---|---|---|"]
    for spazio, progetto, n, ap, ultimo, fermo in tab:
        L.append(f"| {spazio} | [[{spazio}/{progetto}/Stato\\|{progetto}]] | {n} | {ap} | {ultimo:%Y-%m-%d} | " +
                 ("🟡 fermo da oltre 7 giorni con cose aperte" if fermo else "🟢") + " |" if ultimo else
                 f"| {spazio} | {progetto} | 0 | 0 | — | ⚪ vuoto |")
    L += ["", "Le cose aperte di ogni progetto sono nel suo Stato. Il quadro di chi lavora adesso è in `00 Cruscotto`.", "", FINE]
    intest = ("---\ntitolo: Stato generale\ntipo: stato\nspazio: Comune\nprogetto: Comune\nstato: vivo\n"
              f"aggiornato: {datetime.now():%Y-%m-%d %H:%M}\n---\n\n# Stato generale\n\nUna riga per progetto. Collegato a [[Memoria]].\n")
    if not prova:
        cambiati += scrivi(MEM / "00 Comune/Stato generale.md", "\n".join(L), intest)
    print(("scritti/aggiornati" if not prova else "prova:"), cambiati, "file;", len(tab), "progetti")
    for r in tab:
        print(f"  {r[0]:18} {r[1]:18} note {r[2]:4} aperte {r[3]:3} {'FERMO' if r[5] else ''}")


if __name__ == "__main__":
    main("--prova" in sys.argv)
