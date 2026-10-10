#!/usr/bin/env python3
"""Il giro notturno dell'apprendimento (l'utente, 2026-10-04): porta i quaderni degli agenti nel vault.

Per ogni spazio di spazi.json (più i progetti di Vita personale che non ci stanno):
  1. rigenera `Memoria/<spazio>/Quaderni degli agenti.md`: un indice di tutti i quaderni dello spazio con le ultime
     righe di ogni sezione e il link al file (così Obsidian e cerca_memoria.py li vedono);
  2. scrive `Memoria/<spazio>/Report/<data> Apprendimento.md` solo se c'è qualcosa di nuovo rispetto all'ultimo giro
     (righe nuove nei quaderni, errori ripetuti, proposte al profilo in attesa);
  3. stampa il riassunto; esce con 3 se c'è almeno un errore ripetuto (lo stesso errore in due giorni diversi).
Lo stato dell'ultimo giro sta in ~/.locale-onedrive/giro-apprendimento.json (quante righe aveva ogni quaderno).

  python3 ~/Jarvis/strumenti/giro_apprendimento.py            # il giro
  python3 ~/Jarvis/strumenti/giro_apprendimento.py --secco    # dice cosa farebbe, non scrive
Lo lancia launchd ogni mattina (com.jarvis.giro-apprendimento), o Jarvis prima della riunione.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quaderno  # noqa: E402

OD, JARVIS = quaderno.OD, quaderno.JARVIS
STATO = Path.home() / ".locale-onedrive" / "giro-apprendimento.json"
ORA = datetime.now()
SECCO = "--secco" in sys.argv
TITOLARE = OD / "Jarvis Brain/Memoria/Vita personale"


def spazi():
    """[(nome dello spazio, cartella di memoria dello spazio, cartella Report, [cartelle dei progetti])]"""
    try:
        d = json.loads(quaderno.SPAZI_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = []
    out, viste = [], set()
    for s in (d if isinstance(d, list) else d.get("spazi", [])):
        mem = quaderno._percorso(s.get("memoria") or "")
        cart_mem = mem.parent if mem.suffix == ".md" else mem
        rep = quaderno._percorso(s["report"]) if s.get("report") else cart_mem / "Report"
        progetti = [quaderno._percorso(p["cartella"]) for p in s.get("progetti", [])]
        out.append((s.get("nome") or s["id"], cart_mem, rep, progetti))
        viste.update(progetti)
    extra = [c for c in quaderno.EXTRA_CARTELLE if c not in viste]
    for nome, cm, rep, pr in out:
        if cm == TITOLARE:
            pr.extend(extra)
            break
    else:
        out.append(("Vita personale", TITOLARE, TITOLARE / "Report", extra))
    return out


def quaderni_di(cartelle):
    """(cartella del progetto, file del quaderno) per ogni agente del progetto, anche se il quaderno non esiste ancora."""
    coppie = dict(quaderno.cartelle_progetti())
    coppie[quaderno.CASA.parent] = quaderno.MEMORIA_CASA
    for c in cartelle:
        m = coppie.get(c, c / ".claude" / "memoria")
        agenti = quaderno.CASA if c == quaderno.CASA.parent else c / ".claude" / "agents"
        for prof in sorted(agenti.glob("*.md")) if agenti.is_dir() else []:
            if prof.name.startswith(("LEGGIMI", "_")):
                continue
            yield c, m / "agenti" / f"{prof.stem}.md"


def main():
    stato = {}
    try:
        stato = json.loads(STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    nuovo_stato = dict(stato)
    totale_nuove, totale_rip, totale_prop = 0, 0, 0
    for nome_spazio, cart_mem, rep, progetti in spazi():
        if not cart_mem.is_dir():
            continue
        righe_indice = [f"# Quaderni degli agenti · {nome_spazio}", "",
                        f"*Rigenerato da `strumenti/giro_apprendimento.py` il {ORA:%Y-%m-%d %H:%M}: non modificare a mano. "
                        "Ogni quaderno lo scrive l'agente stesso (`strumenti/quaderno.py`).*", ""]
        nuove_spazio, prop_spazio, rip_spazio, dettaglio = 0, [], [], []
        trovati = False
        for c, f in quaderni_di(progetti):
            trovati = True
            sez = quaderno.leggi_quaderno(f)
            n = sum(len(v) for v in sez.values())
            prima = stato.get(str(f), 0)
            nuove = max(0, n - prima)
            nuove_spazio += nuove
            nuovo_stato[str(f)] = n
            righe_indice.append(f"## {f.stem} · {c.name} · {n} righe" + (f" · {nuove} nuove" if nuove else ""))
            righe_indice.append(f"[file]({f.as_uri()}) · profilo: [{f.stem}.md]({(c / '.claude' / 'agents' / (f.stem + '.md')).as_uri()})")
            for k, t in quaderno.SEZIONI:
                if sez[k]:
                    righe_indice.append(f"- **{t}:** " + " · ".join(f"{d} {x}" for d, x in sez[k][-5:]))
            righe_indice.append("")
            if nuove:
                dettaglio.append(f"- **{f.stem}** ({c.name}): {nuove} righe nuove")
            prop_spazio += [(f.stem, d, x) for d, x in sez["proposta"]]
        if not trovati:
            continue
        for a_nome, cart, giorni, testo in quaderno.errori_ripetuti():
            if Path(cart) in progetti:
                rip_spazio.append((a_nome, giorni, testo))
        totale_nuove += nuove_spazio
        totale_rip += len(rip_spazio)
        totale_prop += len(prop_spazio)
        indice = cart_mem / "Quaderni degli agenti.md"
        if not SECCO:
            indice.write_text("\n".join(righe_indice).rstrip("\n") + "\n", encoding="utf-8")
        if nuove_spazio or rip_spazio:
            r = [f"# Apprendimento · {nome_spazio} · {ORA:%Y-%m-%d}", "",
                 f"*Giro delle {ORA:%H:%M}. Indice completo: [[Quaderni degli agenti]].*", "",
                 f"## Righe nuove nei quaderni: {nuove_spazio}"] + (dettaglio or ["- nessuna"]) + [""]
            r.append(f"## Errori ripetuti (lo stesso errore in due giorni diversi = fallimento): {len(rip_spazio)}")
            r += [f"- 🔴 **{a}**: {len(g)} giorni ({g[0]} → {g[-1]}) · {t}" for a, g, t in rip_spazio] or ["- nessuno"]
            r.append("")
            r.append(f"## Proposte al profilo in attesa del capogruppo: {len(prop_spazio)}")
            r += [f"- {a} · {d} · {x}" for a, d, x in prop_spazio[-30:]] or ["- nessuna"]
            if not SECCO:
                rep.mkdir(parents=True, exist_ok=True)
                (rep / f"{ORA:%Y-%m-%d %H%M} Apprendimento.md").write_text("\n".join(r) + "\n", encoding="utf-8")
        print(f"{nome_spazio:28} righe nuove {nuove_spazio:3} · errori ripetuti {len(rip_spazio)} · proposte {len(prop_spazio)}"
              + ("" if SECCO else f" → {indice.name}"))
    if not SECCO:
        STATO.parent.mkdir(parents=True, exist_ok=True)
        STATO.write_text(json.dumps(nuovo_stato, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"totale: {totale_nuove} righe nuove, {totale_rip} errori ripetuti, {totale_prop} proposte")
    sys.exit(3 if totale_rip else 0)


if __name__ == "__main__":
    main()
