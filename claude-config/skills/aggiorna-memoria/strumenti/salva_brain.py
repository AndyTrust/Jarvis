#!/usr/bin/env python3
"""salva_brain.py — scrive nel brain: memoria di progetto + indice generale.

Due posti, due scopi. La **memoria di progetto** sta dentro il progetto
(`.claude/memoria/`) e viaggia con lui. L'**indice generale**
(`~/.ai-memory/projects/`) serve a ritrovare i progetti da fuori.

  # dove siamo arrivati (sovrascrive: è uno stato, non un diario)
  ./salva_brain.py <cartella> --stato "Riordino finito."
  ./salva_brain.py <cartella> --completato "sorgenti scompattati" --completato "grafi rifatti"
  ./salva_brain.py <cartella> --dafare "credenziali del database" --dafare "notebooklm login"
  ./salva_brain.py <cartella> --tolto "credenziali del database"     # da fare -> fatto

  # un fatto che non va riscoperto (un file per fatto)
  ./salva_brain.py <cartella> --fatto vault-su-onedrive \
      --descrizione "La memoria sta in ~/Jarvis-Memoria" \
      --tipo progetto \
      --corpo "Testo..." --perche "..." --come "..."

  # una riga di diario, in fondo, mai in mezzo
  ./salva_brain.py <cartella> --log "cancellati 370 file vecchi"

  ./salva_brain.py <cartella> --leggi        # cosa c'è dentro adesso
  ./salva_brain.py <cartella> --wiki "ingerito · cosa è entrato · quali note"
                                             # riga in fondo al log.md del vault
"""
import argparse, re, sys
from datetime import date, datetime
from pathlib import Path

TIPI = ("utente", "feedback", "progetto", "riferimento")
GEN = Path.home() / ".ai-memory" / "projects"

def slug(s):
    """Un solo modo di fare il nome, o si creano due file per lo stesso progetto:
       e' successo con due nomi scritti in modo diverso."""
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip())
    return re.sub(r"-+", "-", s).strip("-")[:60]

TESTA = """# Memoria — {nome}

Un file per fatto. Questo è l'indice: si legge da solo, i file si aprono solo
quando servono. Lo legge `/claude-md` all'apertura di una chat.

## A che punto siamo

{stato}

## Cosa sappiamo già

## Diario
"""

def carica(mem: Path, nome: str) -> str:
    f = mem / "MEMORIA.md"
    if f.is_file():
        return f.read_text(encoding="utf-8")
    return TESTA.format(nome=nome, stato="_(ancora niente)_")

def sezione(t, titolo, nuovo=None):
    """restituisce (prima, contenuto, dopo) di una sezione ##"""
    righe = t.splitlines()
    i = next((k for k, l in enumerate(righe) if l.strip().lower() == titolo.lower()), None)
    if i is None:
        return None
    j = next((k for k in range(i + 1, len(righe)) if righe[k].startswith("## ")), len(righe))
    if nuovo is None:
        return "\n".join(righe[i + 1:j]).strip()
    return "\n".join(righe[:i + 1] + ["", *nuovo.splitlines(), ""] + righe[j:])

def main():
    ap = argparse.ArgumentParser(description="scrive nel brain di progetto")
    ap.add_argument("cartella", nargs="?", default=".")
    ap.add_argument("--stato"); ap.add_argument("--log")
    ap.add_argument("--completato", action="append", default=[],
                    help="una cosa finita (ripetibile)")
    ap.add_argument("--dafare", action="append", default=[],
                    help="una cosa aperta (ripetibile)")
    ap.add_argument("--tolto", action="append", default=[],
                    help="toglie una voce da «Da fare» e la sposta in «Fatto»")
    ap.add_argument("--errore", action="append", default=[],
                    help="un errore da non ripetere: che cosa e' andato storto e come si evita (ripetibile)")
    ap.add_argument("--fatto"); ap.add_argument("--descrizione", default="")
    ap.add_argument("--tipo", choices=TIPI, default="progetto")
    ap.add_argument("--corpo", default=""); ap.add_argument("--perche", default="")
    ap.add_argument("--come", default=""); ap.add_argument("--collega", default="")
    ap.add_argument("--leggi", action="store_true")
    ap.add_argument("--wiki", help="riga da accodare al log.md del vault Obsidian")
    a = ap.parse_args()

    base = Path(a.cartella).expanduser().resolve()
    if not base.is_dir(): sys.exit(f"{base} non è una cartella")
    mem = base / ".claude" / "memoria"; mem.mkdir(parents=True, exist_ok=True)
    oggi = date.today().isoformat()
    adesso = datetime.now().strftime("%Y-%m-%d %H:%M")   # lo stato porta anche l'ora: l'utente, 10/09/2026

    if a.leggi:
        f = mem / "MEMORIA.md"
        print(f.read_text(encoding="utf-8") if f.is_file() else "(memoria vuota)")
        return

    # --- il vault Obsidian: log.md, e SOLO in fondo ---
    if a.wiki:
        w = base / "WIKI"
        if not w.exists():
            sys.exit(f"nessun collegamento WIKI/ in {base}: questo progetto non ha un vault.")
        lg = w / "log.md"
        if not lg.is_file():
            sys.exit(f"{lg} non esiste: il vault non usa il registro.")
        testo = lg.read_text(encoding="utf-8").rstrip()
        riga = a.wiki.strip()
        if not riga.startswith(oggi):
            riga = f"{adesso} · {riga}"
        lg.write_text(testo + "\n\n" + riga + "\n", encoding="utf-8")
        print(f"✅ riga aggiunta in fondo a WIKI/log.md")
        lint = base / "strumenti/lint_wiki.py"
        if lint.is_file():
            import subprocess as sp
            r = sp.run([sys.executable, str(lint)], capture_output=True, text=True, timeout=60)
            rotti = [l for l in r.stdout.splitlines() if l.strip().startswith("[[")]
            print("   collegamenti: " + (f"🔴 {len(rotti)} rotti" if rotti else "tutti buoni"))
        if not (a.stato or a.log or a.fatto or a.completato or a.dafare or a.tolto or a.errore):
            return

    if not (a.stato or a.log or a.fatto or a.completato or a.dafare or a.tolto or a.errore or a.wiki):
        sys.exit("Serve almeno --stato, --completato, --dafare, --tolto, --errore, --fatto o --log.")

    t = carica(mem, base.name)

    # --- un fatto: file suo + riga nell'indice ---
    if a.fatto:
        s = slug(a.fatto)
        corpo = a.corpo.strip() or "_(da scrivere)_"
        if a.perche: corpo += f"\n\n**Perché:** {a.perche.strip()}"
        if a.come:   corpo += f"\n\n**Come si applica:** {a.come.strip()}"
        if a.collega:
            corpo += "\n\nVedi " + " · ".join(f"[[{x.strip()}]]" for x in a.collega.split(",") if x.strip())
        (mem / f"{s}.md").write_text(
            f"---\nnome: {s}\ndescrizione: {a.descrizione or a.fatto}\n"
            f"tipo: {a.tipo}\naggiornato: {adesso}\n---\n\n{corpo}\n", encoding="utf-8")
        riga = f"- [{s}]({s}.md) — {a.descrizione or a.fatto}"
        vecchie = [l for l in (sezione(t, "## Cosa sappiamo già") or "").splitlines()
                   if l.strip() and not l.strip().startswith(f"- [{s}]")]
        t = sezione(t, "## Cosa sappiamo già", "\n".join(vecchie + [riga]))
        print(f"✅ fatto salvato: .claude/memoria/{s}.md")

    # --- fatto / da fare: due elenchi, si spostano da uno all'altro ---
    # anche con il solo --stato si passa di qui: gli elenchi Errori, Fatto e Da fare
    # restano (prima il ramo «elif a.stato» riscriveva la sezione e li cancellava)
    if a.completato or a.dafare or a.tolto or a.errore or a.stato:
        corr = sezione(t, "## A che punto siamo") or ""
        def voci(testo, titolo):
            dentro, out = False, []
            for l in testo.splitlines():
                if l.strip().lower().startswith(f"### {titolo}"): dentro = True; continue
                if dentro and l.strip().startswith("### "): dentro = False
                if dentro and l.strip().startswith("- "): out.append(l.strip()[2:])
            return out
        fatti_l, aperti_l = voci(corr, "fatto"), voci(corr, "da fare")
        errori_l = voci(corr, "errori da non ripetere")
        preambolo = corr.split("###")[0].strip() if "###" in corr else corr.strip()
        for x in a.tolto:
            simili = [v for v in aperti_l if x.lower() in v.lower()]
            if not simili:
                print(f"⚠️  «{x}» non è in «Da fare»: non lo sposto. Aperti: "
                      + (", ".join(aperti_l) or "nessuno"))
                continue
            for v in simili:
                aperti_l.remove(v); fatti_l.append(v)
                print(f"→  «{v}» da fare → fatto")
        for x in a.completato:
            if x not in fatti_l: fatti_l.append(x)
        for x in a.dafare:
            # se e' gia' segnata come fatta, torna aperta: non puo' stare in tutti e due
            fatti_l = [v for v in fatti_l if v != x]
            if x not in aperti_l: aperti_l.append(x)
        for x in a.errore:
            if x not in errori_l: errori_l.append(x)
        doppie = set(fatti_l) & set(aperti_l)
        if doppie:
            aperti_l = [v for v in aperti_l if v not in doppie]
            print("⚠️  erano in tutti e due gli elenchi, le tengo fra le fatte: "
                  + ", ".join(sorted(doppie)))
        blocchi = [f"_{adesso}_"]
        if a.stato: blocchi.append(a.stato.strip())
        elif preambolo and not preambolo.startswith("_"): blocchi.append(preambolo)
        elif preambolo.startswith("_"):
            resto = "\n".join(preambolo.splitlines()[1:]).strip()
            if resto: blocchi.append(resto)
        if errori_l: blocchi.append("### Errori da non ripetere\n"
                                    + "\n".join(f"- {x}" for x in errori_l))
        if fatti_l:  blocchi.append("### Fatto\n" + "\n".join(f"- {x}" for x in fatti_l))
        if aperti_l: blocchi.append("### Da fare\n" + "\n".join(f"- {x}" for x in aperti_l))
        t = sezione(t, "## A che punto siamo", "\n\n".join(blocchi))
        print(f"✅ stato: {len(fatti_l)} fatte · {len(aperti_l)} da fare"
              + (f" · {len(errori_l)} errori da non ripetere" if errori_l else ""))

    # --- il diario: solo in fondo ---
    if a.log:
        d = sezione(t, "## Diario") or ""
        t = sezione(t, "## Diario", (d + f"\n- {adesso} · {a.log.strip()}").strip())
        print("✅ riga di diario aggiunta")

    (mem / "MEMORIA.md").write_text(t.rstrip() + "\n", encoding="utf-8")

    # --- l'indice generale: solo il puntatore, non una copia ---
    if a.stato or a.fatto:
        GEN.mkdir(parents=True, exist_ok=True)
        g = GEN / f"{slug(base.name)}.md"
        stato = sezione(t, "## A che punto siamo") or ""
        n = len(list(mem.glob("*.md"))) - 1
        # 🔴 mai sovrascrivere: qui dentro il gancio Stop scrive da mesi.
        # Si sostituisce SOLO la sezione dello stato, il resto resta.
        testa = (f"---\ntipo: project\nprogetto: {base.name}\naggiornato: {adesso}\n---\n\n"
                 f"# {base.name}\n\n`{base}`\n\nMemoria vera: `{base.name}/.claude/memoria/` "
                 f"({n} fatti). Questo file è solo il puntatore: **non copiarci dentro** "
                 f"il contenuto, si sdoppierebbe. Apri la chat nel progetto e chiama "
                 f"`/claude-md`.\n")
        blocco = f"## A che punto siamo\n\n{stato}\n"
        if g.is_file():
            v = g.read_text(encoding="utf-8")
            corpo = re.sub(r"^---\n.*?\n---\n", "", v, count=1, flags=re.S)
            corpo = re.sub(r"^#[^\n]*\n", "", corpo, count=1).strip()
            corpo = re.sub(r"^`/[^\n]*`\n", "", corpo).strip()
            corpo = re.sub(r"^# [^\n]*\n", "", corpo, flags=re.M).strip()  # via gli H1 doppi (solo H1: 02/10/2026, prima toglieva anche gli H2 e la coda si impilava a ogni salvataggio)
            corpo = re.sub(r"^Memoria vera:.*?`/claude-md`\.\n", "", corpo, flags=re.S).strip()
            if "## A che punto siamo" in corpo:
                corpo = re.sub(r"## A che punto siamo\n.*?(?=\n## |\Z)", "", corpo, flags=re.S).strip()
            # 🔴 Se la coda c'e' gia', si tiene com'e' e NON la si riarchivia:
            # riarchiviare a ogni salvataggio impila una copia dello stato per
            # volta. Il 4/9 questo file era arrivato a 265 righe con quindici
            # copie della stessa sezione.
            m2 = re.search(r"## Da prima di questa memoria\n(.*)", corpo, re.S)
            if m2:
                corpo = m2.group(1).strip()
            coda = f"\n## Da prima di questa memoria\n\n{corpo}\n" if corpo else ""
            g.write_text(testa + "\n" + blocco + coda, encoding="utf-8")
            print(f"✅ indice generale aggiornato (contenuto precedente conservato): "
                  f"~/.ai-memory/projects/{g.name}")
        else:
            g.write_text(testa + "\n" + blocco, encoding="utf-8")
            print(f"✅ indice generale creato: ~/.ai-memory/projects/{g.name}")

if __name__ == "__main__":
    main()
