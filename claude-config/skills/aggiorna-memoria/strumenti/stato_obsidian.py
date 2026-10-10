#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""«A che punto siamo»: una pagina per progetto, dentro il progetto.

Perche' esiste: aprendo Obsidian non si vedeva a che punto era niente —
bisognava entrare, aprire `log.md`, e leggere. E la skill prometteva «scrive
nel vault Obsidian» mentre accodava una riga a un registro, solo se qualcuno si
ricordava il flag.

🔴 05/09/2026, l'utente: **«ogni progetto deve essere autonomo, perche' non tutti
i progetti sono collegati; una pagina fuori da ogni progetto crea solo
confusione»**. Percio' NON c'e' una pagina madre in radice: c'e'
`A che punto siamo.md` **dentro la cartella di ogni progetto**, che parla solo
di quel progetto. Chi apre un progetto vede quel progetto, e basta.

`python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva` le riscrive da solo, leggendo il `MEMORIA.md` di ciascuno.
Non si aggiornano a mano: si rilancia.

    ./stato_obsidian.py              che cosa scriverebbe
    ./stato_obsidian.py --conferma   lo scrive
"""
import argparse, datetime, os, pathlib, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from percorsi import memoria as _memoria, progetti as _progetti
VAULT = _memoria()
INDICE = pathlib.Path(os.path.expanduser('~/.ai-memory/global/projects-index.md'))
OGGI = datetime.date.today()
ADESSO = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')   # data e ora, sempre
ADESSO_ISO = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')   # per il frontmatter: data e ORA (l'utente, 19/09/2026)

# I progetti: nome -> (cartella del progetto, cartella nel vault o None)
# Si legge dall'indice globale; questa e' la rete di sicurezza se cambia forma.
# I progetti vengono dagli spazi scelti all'installazione (~/.jarvis/percorsi.json):
# nome -> (cartella del progetto, cartella delle note relativa alla memoria condivisa).
NOTI = _progetti()
# cartelle della memoria che un altro programma rigenera: qui non si scrive dentro
NON_TOCCARE = set()


def cartella_vault(nome, vdir):
    """La cartella delle note di un progetto: relativa a VAULT, o assoluta."""
    v = vdir or nome
    if v.startswith(('~', '/')):
        return pathlib.Path(os.path.expanduser(v))
    return VAULT / v


def quando(p):
    """L'ultima modifica vera dentro una cartella, saltando il rumore.
    Si potano le cartelle di rumore mentre si scende (os.walk), non si
    filtrano dopo: in my-agent un .venv da decine di migliaia di file
    rallenterebbe ogni salvataggio."""
    rumore = {'.git', 'node_modules', '.obsidian', '_to_delete', '.venv-geo',
              '.venv', 'venv', '__pycache__', 'worktrees', '.codegraph', 'graphify-out'}
    ultimo = None
    for radice, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in rumore]
        for nome in files:
            try:
                t = datetime.datetime.fromtimestamp(os.stat(os.path.join(radice, nome)).st_mtime)
            except OSError:
                continue
            if ultimo is None or t > ultimo:
                ultimo = t
    return ultimo


def leggi_memoria(cartella):
    """Fatto, Da fare e diario dal MEMORIA.md del progetto."""
    m = cartella / '.claude' / 'memoria' / 'MEMORIA.md'
    if not m.is_file():
        return None
    t = m.read_text(encoding='utf-8')
    def sezione(titolo):
        i = t.find(titolo)
        if i < 0:
            return []
        j = t.find('\n## ', i)
        k = t.find('\n### ', i + len(titolo))
        fine = min(x for x in (j, k, len(t)) if x > 0)
        return [r[2:].strip() for r in t[i:fine].split('\n') if r.startswith('- ')]
    fatti = sorted((cartella / '.claude' / 'memoria').glob('*.md'))
    # 16/09/2026: prima la pagina non leggeva ne' lo stato ne' gli errori, e in
    # Obsidian non arrivava nessun «errore da non ripetere»: li vedeva solo il
    # terminale all'apertura. Il vault e' il posto dove li leggono l'utente e gli agenti.
    i = t.find('## A che punto siamo')
    stato = []
    if i >= 0:
        # lo stato finisce alla prima sottosezione O alla sezione successiva: una memoria
        # senza sottosezioni (Portfolio) si portava dietro tutto il resto del file
        fine = min(x for x in (t.find('\n### ', i), t.find('\n## ', i + 3), len(t)) if x > 0)
        blocco = t[i + len('## A che punto siamo'):fine]
        stato = [r.strip() for r in blocco.split('\n') if r.strip()]
    return {
        'stato': stato,
        'errori': sezione('### Errori da non ripetere'),
        'fatto': sezione('### Fatto'),
        'dafare': sezione('### Da fare'),
        'diario': sezione('## Diario')[-3:],
        'schede': [f.stem for f in fatti if f.stem != 'MEMORIA'],
        'modificata': datetime.datetime.fromtimestamp(m.stat().st_mtime),
    }


def riga_stato(nome, cartella, memoria, ultima):
    corta = str(cartella).replace(os.path.expanduser('~'), '~')
    if memoria is None:
        return '| **%s** | `%s` | — | — | — | ⚠️ senza memoria: `impianta.py` |' % (nome, corta)
    if not (memoria['fatto'] or memoria['dafare'] or memoria['schede']):
        return '| **%s** | `%s` | — | — | — | impiantato, da riempire |' % (nome, corta)
    rossi = sum(1 for x in memoria['dafare'] if x.startswith('🔴'))
    return '| **%s** | `%s` | %d | %d%s | %d | %s |' % (
        nome, corta,
        len(memoria['fatto']), len(memoria['dafare']),
        (' (%d 🔴)' % rossi) if rossi else '',
        len(memoria['schede']),
        ultima.strftime('%d/%m %H:%M') if ultima else '—')


def pagina_progetto(nome, cartella, memoria, ultima):
    """Quello che serve sapere di UN progetto, e nient'altro."""
    corta = str(cartella).replace(os.path.expanduser('~'), '~')
    r = ["""---
titolo: A che punto siamo
tags:
  - meta
  - stato
aggiornato: %s
tipo: stato
---

# %s — a che punto siamo

> Questa pagina la **riscrive `python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva`**, leggendo
> `%s/.claude/memoria/`. Non si corregge a mano: si rilancia.
""" % (ADESSO_ISO, nome, corta)]

    if memoria is None:
        r.append("⚠️ **Questo progetto non ha memoria.** Aprendo una chat si "
                 "riparte da zero ogni volta.\n")
        r.append("Si impianta una volta sola:\n")
        r.append("```bash\npj impianta %s --conferma\n```\n" % corta)
        return '\n'.join(r)

    r.append("La cartella: `%s` · ultimo file toccato **%s** · memoria del progetto "
             "aggiornata **%s** · pagina riscritta il **%s**\n"
             % (corta, ultima.strftime('%d/%m/%Y %H:%M') if ultima else '—',
                memoria['modificata'].strftime('%d/%m/%Y %H:%M'), ADESSO))

    if memoria.get('stato'):
        r.append("## A che punto siamo\n")
        r += memoria['stato']
        r.append('')

    # Gli errori vengono PRIMA di tutto e non si accorciano mai: rileggerli costa
    # poche centinaia di token, rifarli costa una sessione intera.
    if memoria.get('errori'):
        r.append("## 🔴 Errori da non ripetere — %d voci\n" % len(memoria['errori']))
        r.append("> Si leggono **prima di lavorare**, anche dagli agenti. Ognuno dice che cosa "
                 "e' andato storto, perche' non si vedeva e come si evita. Un errore corretto "
                 "resta qui finche' il codice che lo rendeva possibile esiste.\n")
        r += ['- %s' % x for x in memoria['errori']]
        r.append('')

    rossi = [x for x in memoria['dafare'] if x.startswith('🔴')]
    altri = [x for x in memoria['dafare'] if not x.startswith('🔴')]

    if rossi:
        r.append("## 🔴 Quello che brucia\n")
        r += ['- %s' % x.lstrip('🔴 ') for x in rossi]
        r.append('')
    if altri:
        r.append("## Da fare — %d voci\n" % len(altri))
        r += ['- %s' % x for x in altri]
        r.append('')
    if not memoria['dafare']:
        r.append("## Da fare\n\nNiente in coda.\n")

    if memoria['fatto']:
        r.append("## Fatto — %d voci\n" % len(memoria['fatto']))
        r += ['- %s' % x for x in memoria['fatto'][-15:]]
        if len(memoria['fatto']) > 15:
            r.append('- *…e altre %d, in `.claude/memoria/MEMORIA.md`*'
                     % (len(memoria['fatto']) - 15))
        r.append('')

    if memoria['schede']:
        # si chiamava «Gli errori gia' trovati»: ma sono i file dei FATTI, non gli errori
        r.append("## Fatti da non riscoprire\n")
        r.append("%d schede in `.claude/memoria/`. **Se la richiesta tocca uno "
                 "di questi, apri quel file: non riesplorare la cartella.**\n"
                 % len(memoria['schede']))
        r += ['- `%s`' % x for x in sorted(memoria['schede'])]
        r.append('')

    if memoria['diario']:
        r.append("## Ultime righe di diario\n")
        r += ['- %s' % x for x in memoria['diario']]
        r.append('')

    r.append("## Il ciclo\n")
    r.append("```bash\nbrain.py          # apre: dice a che punto siamo\n"
             "brain.py --salva  # chiude: stato, fatti, date, e questa pagina\n```\n")
    return '\n'.join(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--conferma', action='store_true')
    a = ap.parse_args()

    if not VAULT.is_dir():
        sys.exit('vault non trovato: %s\nla cartella della memoria esiste? (~/.jarvis/percorsi.json)' % VAULT)

    scritte = []
    for nome, (cart, vdir) in NOTI.items():
        p = pathlib.Path(os.path.expanduser(cart))
        if not p.is_dir():
            continue
        mem = leggi_memoria(p)
        dest_dir = cartella_vault(nome, vdir)
        testo = pagina_progetto(nome, p, mem, quando(p))
        dest = dest_dir / 'A che punto siamo.md'
        scritte.append((dest, testo, dest_dir.is_dir()))

    for dest, _, esisteva in scritte:
        print('   %s%s' % (dest.relative_to(VAULT) if dest.is_relative_to(VAULT) else dest,
                           '' if esisteva else '   (cartella nuova)'))

    # 🔴 la pagina madre in radice non si fa piu': confondeva, perche' in
    #    Obsidian un file accanto alle cartelle sembra un progetto fra i altri.
    vecchia = VAULT / 'Brain.md'

    if not a.conferma:
        print('\n(prova a vuoto: rilancia con --conferma per scrivere)')
        if vecchia.is_file():
            print('   e toglie la vecchia %s dalla radice' % vecchia.name)
        return 0

    for dest, testo, _ in scritte:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(testo, encoding='utf-8')
    if vecchia.is_file():
        vecchia.unlink()
        print('   tolta %s dalla radice' % vecchia.name)
    print('\n✅ scritte %d pagine «A che punto siamo», una per progetto'
          % len(scritte))
    return 0


if __name__ == '__main__':
    sys.exit(main())
