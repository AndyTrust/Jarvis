#!/usr/bin/env python3
"""brain.py — un comando solo: guarda cosa c'è e decide. Zero token.

    brain.py              apre: legge, decide, e dice cosa serve
    brain.py --salva ...  chiude: aggiorna stato, fatti, wiki, date

All'apertura non chiede niente: guarda la cartella, la memoria, le date dei
file, e sceglie da sé se il progetto è nuovo (allora lo impianta), se è già a
posto (allora riferisce a che punto siamo), o se qualcosa è scaduto (allora lo
dice, invece di far finta di niente).

Le date: ogni file che dichiara `aggiornato:` viene confrontato con la sua data
di modifica vera. Un documento cambiato tre settimane fa che dice di essere di
oggi mente, e mentire costa più che tacere.
"""
import argparse, os, re, subprocess, sys
from datetime import date, datetime, timedelta
from pathlib import Path

QUI = Path(__file__).resolve().parent
OGGI = date.today()
# tollera **grassetto**, *corsivo* e spazi: il timbro che scriviamo e'
# `*Ultima modifica: 2026-09-04*`, e senza gli asterischi nella regex non si
# riconosceva da solo — cosi' ne aggiungeva uno nuovo a ogni giro.
DATA_RX = re.compile(
    r"^[*_\s]*(aggiornat[ao]|data|ultima modifica)[*_\s]*:\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)",
    re.I | re.M)
DOC = ("CLAUDE.md", "LEGGIMI.md", "MEMORIA.md", "ARCHITETTURA.md", "README.md")
SALTA = {".git", "node_modules", "__pycache__", ".venv", ".codegraph", "graphify-out",
         "dist", "build", "vendor",
         # 19/09/2026: codice altrui. Timbrarlo aggiunge righe a file che non sono
         # nostri (sorgenti di Asterisk, worktree di prova).
         "worktrees", "sorgenti", "third-party", "third_party"}

def di_altri(p: Path, base: Path) -> bool:
    """Vero se p sta dentro una sottocartella che è un repository git suo
       (backtalk, barehands...): lo aggiorna update.sh, una riga in più
       diventerebbe una modifica locale in conflitto."""
    base, d = base.resolve(), p.resolve().parent
    while d != base and base in d.parents:
        if (d/".git").exists():
            return True
        d = d.parent
    return False

def py(script, *args):
    return subprocess.run([sys.executable, str(QUI/script), *map(str, args)],
                          capture_output=True, text=True)

def scadute(base: Path, giorni=14):
    """documenti il cui contenuto è cambiato dopo la data che dichiarano"""
    out = []
    for p in base.rglob("*.md"):
        if any(s in p.parts for s in SALTA) or p.name not in DOC or di_altri(p, base):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
            mod = date.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        m = DATA_RX.search(t)
        if not m:
            out.append((p.relative_to(base), None, mod, "senza"))
            continue
        dich = date.fromisoformat(m.group(2)[:10])
        if (mod - dich).days > 1:
            out.append((p.relative_to(base), dich, mod, "scaduta"))
    return out

def timbra(p: Path, quando=None):
    """Aggiorna la data dichiarata. Se il file non ne aveva mai avuta una, mette
       la sua data di MODIFICA vera, non oggi: scrivere oggi su un documento
       fermo da tre settimane e' una bugia in piu', non una in meno."""
    try:
        t = p.read_text(encoding="utf-8")
        reale = datetime.fromtimestamp(p.stat().st_mtime).replace(second=0, microsecond=0)
    except OSError:
        return False
    mod = reale.strftime("%Y-%m-%d %H:%M")
    m0 = DATA_RX.search(t)
    aveva = bool(m0)
    # 19/09/2026, l'utente: «oltre la data ci vuole l'orario, voglio sapere se
    # realmente sono stati aggiornati». L'ora si scrive SOLO se il file è
    # cambiato dopo l'ultimo timbro: altrimenti ogni salvataggio riscriverebbe
    # l'ora e la «freschezza» sarebbe finta.
    if aveva and not quando:
        dichiarato = datetime.fromisoformat(m0.group(2).replace("T", " ")[:16])
        # 19/09/2026: un'ora dichiarata NEL FUTURO (16:34 scritto alle 10:15 nel
        # CLAUDE.md del CRM, 17:06 nella memoria) bloccava ogni timbro successivo,
        # perché il file sembrava sempre «già aggiornato». Il futuro non vale.
        if reale <= dichiarato <= datetime.now():
            return False
    q = quando or (datetime.now().strftime("%Y-%m-%d %H:%M") if aveva else mod)
    if aveva:
        n = DATA_RX.sub(lambda m: m.group(0).replace(m.group(2), str(q)), t, count=1)
    elif t.startswith("---"):
        n = re.sub(r"^---\n", f"---\naggiornato: {q}\n", t, count=1)
    elif t.lstrip().startswith("#"):
        righe = t.splitlines()
        i = next(k for k, l in enumerate(righe) if l.lstrip().startswith("#"))
        righe.insert(i + 1, f"\n*Ultima modifica: {q}*")
        n = "\n".join(righe) + "\n"
    else:
        return False
    if n != t:
        p.write_text(n, encoding="utf-8")
        return True
    return False

def main():
    ap = argparse.ArgumentParser(description="il brain del progetto, in un comando")
    ap.add_argument("--salva", action="store_true", help="modo chiusura")
    ap.add_argument("--timbra", action="store_true", help="porta a oggi le date scadute")
    ap.add_argument("--hook", action="store_true", help="corto e silenzioso se non c'è nulla")
    # La cartella si cerca a mano, PRIMA di argparse: un posizionale qui
    # ruberebbe il valore delle opzioni che appartengono a salva_brain.py
    # (--completato, --dafare, --fatto...), e ricostruirlo dopo e' fragile.
    argv = sys.argv[1:]
    base, tolti = Path.cwd().resolve(), []
    for i, x in enumerate(argv):
        if x.startswith("-"):
            continue
        if i > 0 and argv[i - 1].startswith("--") and argv[i - 1] not in (
                "--salva", "--timbra", "--hook"):
            continue                      # e' il valore di un'opzione, non la cartella
        q = Path(x).expanduser()
        if q.is_dir():
            base, tolti = q.resolve(), [i]
            break
    argv = [x for i, x in enumerate(argv) if i not in tolti]
    a, resto = ap.parse_known_args(argv)

    mem = base/".claude"/"memoria"/"MEMORIA.md"
    cm = base/"CLAUDE.md"
    nuovo = not mem.is_file() and not cm.is_file()

    # ---------- CHIUSURA ----------
    if a.salva:
        r = py("salva_brain.py", base, *resto)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode:
            sys.exit(r.returncode)
        n = sum(1 for p in (mem, cm) if p.is_file() and timbra(p))

        # --- la pagina madre del vault ---
        # 05/09/2026, l'utente: «Obsidian deve essere il nostro cervello di ogni
        # progetto nel tempo». Prima la skill PROMETTEVA di scrivere nel vault e
        # accodava una riga a un registro, solo se qualcuno passava --wiki.
        # Adesso la pagina «Brain» — tutti i progetti, a che punto sono, ultima
        # modifica — si riscrive da sola a ogni salvataggio. Non e' un flag da
        # ricordare: e' parte della chiusura.
        so = py("stato_obsidian.py", "--conferma")
        for riga in (so.stdout or "").split("\n"):
            if riga.startswith("✅") or riga.startswith("vault non"):
                print(riga)
        if so.returncode:
            print("⚠️  la pagina Brain del vault non e' stata riscritta:",
                  (so.stderr or "").strip().split("\n")[-1][:120])

        vecchie = scadute(base)
        if vecchie:
            print(f"\n⚠️  {len(vecchie)} documenti con la data scaduta:")
            for p, d, m, perche in vecchie[:8]:
                print(f"   {str(p):<44} {perche}")
            print("   `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --timbra` li porta a oggi — ma prima guarda se il")
            print("   contenuto è ancora vero: timbrare una bugia la rende peggiore.")
        return

    # ---------- TIMBRO ----------
    # --- il vault: c'e' una pagina madre, ed e' fresca? ---
    # Si dice in UNA riga: serve a sapere se il cervello e' allineato, non a
    # ricopiarlo. Chi vuole il dettaglio apre Brain.md.
    sys.path.insert(0, str(Path(__file__).parent))
    from percorsi import memoria as _memoria
    vault = _memoria()
    # la pagina di QUESTO progetto, non una pagina globale.
    # ⚠️ La cartella nel vault NON si chiama sempre come la cartella sul disco
    # (il nome nella memoria può essere diverso): la mappa autorevole è NOTI dentro
    # stato_obsidian.py, la stessa che usa --salva per scrivere. Indovinare dal
    # nome faceva dire «manca» a ogni apertura, anche appena salvato.
    def _dir_vault():
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from stato_obsidian import NOTI, cartella_vault
            mio = base.resolve()
            for nome, (cart, vdir) in NOTI.items():
                if Path(os.path.expanduser(cart)).resolve() == mio:
                    return cartella_vault(nome, vdir)
        except Exception:
            pass
        for d in (base.name, base.name.replace("_", " ")):
            if (vault / d).is_dir():
                return vault / d
        return None

    _d = _dir_vault()
    madre = (_d / "A che punto siamo.md") if _d else None
    if not a.salva and not a.timbra:
        if not vault.is_dir():
            print("\n⚠️  cartella della memoria condivisa non trovata: la pagina Brain non si legge.")
        elif madre is None or not madre.is_file():
            print("\n⚠️  il vault non ha «A che punto siamo» per questo progetto:"
                  " `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva` la scrive.")
        else:
            # 16/09/2026: «allineata» voleva dire «file modificato da meno di un giorno».
            # Su una cartella sincronizzata la data di modifica mente, e una pagina riscritta oggi puo'
            # non contenere cio' che c'e' in memoria (gli errori non ci arrivavano mai).
            # Si confronta il CONTENUTO: numero di errori, ultime voci, stato.
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from stato_obsidian import leggi_memoria
                mem_ = leggi_memoria(base) or {}
                pag = madre.read_text(encoding="utf-8")
                mancano = []
                err = mem_.get("errori") or []
                if err and ("Errori da non ripetere — %d voci" % len(err)) not in pag:
                    mancano.append("errori (%d in memoria)" % len(err))
                for chiave, nome in (("errori", "ultimo errore"),
                                     ("dafare", "ultima voce da fare"),
                                     ("fatto", "ultima voce fatta")):
                    v = mem_.get(chiave) or []
                    if v and v[-1].lstrip("🔴 ")[:60] not in pag:
                        mancano.append(nome)
                st = mem_.get("stato") or []
                if st and st[-1][:60] not in pag:
                    mancano.append("stato")
                if mancano:
                    print("\n🧠 vault: «A che punto siamo» ⚠️ NON allineata — manca: %s."
                          " Rilancia `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva`." % ", ".join(mancano))
                else:
                    print("\n🧠 vault: «A che punto siamo» allineata alla memoria"
                          " (stato, %d errori, Fatto, Da fare)" % len(err))
            except Exception as e:
                print("\n🧠 vault: controllo del contenuto non riuscito: %s" % str(e)[:100])

    if a.timbra:
        v = scadute(base)
        if not v:
            print("✅ nessuna data scaduta"); return
        for p, d, m, tipo in v:
            f = base/p
            if timbra(f):
                nuova = OGGI if tipo == "scaduta" else m
                print(f"→ {str(p):<46} {d or '(nessuna)'} → {nuova}")
        return

    # ---------- APERTURA ----------
    if nuovo:
        if a.hook:
            # In una cartella qualunque tace. Ma se sembra un progetto vero,
            # una riga la dice: il silenzio sembra un guasto.
            # «piu' di 15 file» era troppo largo: ~/Downloads lo passava.
            # Serve un segno vero — un marcatore di progetto, o l'essere gia'
            # elencato fra i progetti in AI-Memory.
            segni = [".git", "package.json", "pyproject.toml", "Cargo.toml",
                     "composer.json", "go.mod", "Makefile"]
            pare = any((base/s).exists() for s in segni)
            if not pare:
                idx = Path.home()/".ai-memory/global/projects-index.md"
                try:
                    pare = base.name.lower() in idx.read_text(
                        encoding="utf-8", errors="ignore").lower()
                except OSError:
                    pass
            if pare and base != Path.home():
                print(f"📁 {base.name} — non impiantato (niente CLAUDE.md, niente "
                      f"memoria).\n↑ Dillo all'utente in una riga e offri "
                      f"`python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py .` per prepararlo. Poi rispondi alla sua richiesta.")
            return
        print(f"\n╭─ {base.name}")
        print( "│  🆕 PROGETTO NUOVO — niente memoria, niente CLAUDE.md")
        print( "╰─\n")
        print(py("impianta.py", base).stdout.rstrip())
        print("\n→ Impianta con:  python3 ~/.claude/skills/aggiorna-memoria/strumenti/impianta.py . --conferma")
        print("  Poi riempi le caselle «DA SCRIVERE» del CLAUDE.md: quello è giudizio.")
        return

    r = py("stato.py", base, *(["--hook"] if a.hook else []))
    testo = r.stdout.rstrip()
    if testo:
        print(testo)
        if a.hook:
            # Il referto entra nel contesto del modello, non sullo schermo
            # dell'utente: senza questa riga lui apre una chat e "non succede
            # niente". Va detto ad alta voce, in due righe, non incollato.
            print("\n↑ Riferisci all'utente in DUE RIGHE dove siamo e cosa resta "
                  "aperto, prima di rispondere alla sua richiesta. Non incollargli "
                  "questo referto. Non riscoprire quello che e' gia' in memoria: "
                  "apri il file del fatto in .claude/memoria/.")

    v = scadute(base)
    vec = [x for x in v if x[3] == "scaduta"]
    sen = [x for x in v if x[3] == "senza"]
    if a.hook:
        if vec:
            print(f"\n🔴 {len(vec)} documenti dicono una data e ne hanno un'altra: "
                  + ", ".join(str(p) for p, *_ in vec[:3])
                  + (" …" if len(vec) > 3 else "") + "  (brain.py --timbra)")
    else:
        if vec:
            print(f"\n🔴 {len(vec)} documenti cambiati DOPO la data che dichiarano:")
            for p, d, m, _ in vec:
                print(f"   {str(p):<46} dice {d}, toccato {m}")
            print("   Guarda se il contenuto è ancora vero, POI `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --timbra`.")
        if sen:
            print(f"\n·  {len(sen)} documenti non dichiarano nessuna data"
                  f" — `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --timbra` ci mette quella di modifica vera")
            for p, *_ in sen[:5]:
                print(f"   {p}")
            if len(sen) > 5:
                print(f"   … e altri {len(sen)-5}")

    if not a.hook and not mem.is_file():
        print("\n⚠️  C'è il CLAUDE.md ma non la memoria. A fine sessione:")
        print("   brain.py --salva --completato \"...\" --dafare \"...\"")

if __name__ == "__main__":
    main()
