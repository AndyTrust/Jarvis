#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Il battito dei 15 minuti: controlla la sincronia fra lavoro e memoria.

Perché esiste (l'utente, 20/09/2026 02:10): il Command Center mostrava numeri che
salivano — note, sessioni, sviluppi — e sembravano uno stato. Non lo erano.
Nessuno diceva se la memoria di un progetto fosse davvero aggiornata, e niente
la rimetteva in pari da solo: si aspettava che una sessione di Claude Code
arrivasse alla fine e facesse scattare il gancio Stop. Se la sessione non
arrivava in fondo, il vault restava indietro per ore.

Cosa fa, ogni 15 minuti:

  1. legge lo stato vero di ogni progetto con `sincro/controlla.py --json`
     (la memoria è quella condivisa di ~/.jarvis/percorsi.json);
  2. tiene una copia di sicurezza di ogni vecchio MEMORIA.md che è cambiato;
  3. scrive `sincro/ultimo.json`: quando è passato, cosa ha fatto, e quali
     progetti restano indietro. È questo il file che legge il Command Center.

Fino al 23/09/2026 c'era un passo in più: se una pagina «A che punto siamo»
era più vecchia del suo MEMORIA.md, rilanciava `stato_obsidian.py --conferma`
per riscriverle. Con la memoria unica quelle pagine non si confrontano più, e
il passo è tolto: le chiavi «vault_*» di ultimo.json restano, ferme a «no».

Cosa NON fa, e non deve fare: `brain --salva`.
🔴 Errore già successo: MEMORIA.md scritta dal Mac e
dal PC Windows nello stesso quarto d'ora, via OneDrive, fa sparire un
salvataggio. Un salvataggio automatico ogni 15 minuti ripeterebbe quell'errore
a ciclo continuo. E `--salva` col solo `--stato` ha già cancellato Fatto, Da
fare e tre errori su quattro. Il salvataggio resta a comando: qui si controlla,
si copia e si avvisa.

    ./ogni30.py             un giro, e stampa cosa ha fatto
    ./ogni30.py --zitto     uguale, ma parla solo se c'è un problema
"""
import sys as _s, pathlib as _p; _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "command-center")); import senza_finestre  # noqa: E402,F401  (Windows: niente finestre di terminale)
import argparse
import datetime
try:
    import fcntl
except ImportError:            # Windows: niente fcntl, lucchetto con msvcrt
    fcntl = None
    import msvcrt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

AGENTE = pathlib.Path(__file__).resolve().parent.parent
CONTROLLA = AGENTE / 'sincro' / 'controlla.py'
ULTIMO = AGENTE / 'sincro' / 'ultimo.json'
COPIE = AGENTE / 'sincro' / 'copie'
LUCCHETTO = AGENTE / 'sincro' / '.ogni30.lock'
REGISTRO = AGENTE / 'sincro' / 'ogni30.log'

# 🔴 due processi che scrivono lo stesso file di stato in parallelo: il gancio
# jarvis_status.py ci è già cascato, uno leggeva a metà scrittura. Stesso
# lucchetto, stessa scrittura atomica.
COPIE_DA_TENERE = 48          # un giorno intero di copie per progetto
LAVORI = AGENTE / 'strumenti' / 'lavori.py'   # il registro di chi sta lavorando su cosa
PORTIERE = AGENTE / 'strumenti' / 'portiere.py'  # le chiavi: chi tiene cosa, e se è vero
SALVA_PRIVATO = AGENTE / 'strumenti' / 'salva_privato.sh'  # la copia su Jarvis-Privato
SALVA_TIMEOUT = 600           # dieci minuti: oltre, il battito va avanti lo stesso
ORE_PRIMA_DI_LAMENTARSI = 6   # sotto, un progetto indietro è normale


def adesso():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')


def scrivi_atomico(percorso, testo):
    tmp = percorso.with_suffix(percorso.suffix + '.tmp')
    tmp.write_text(testo, encoding='utf-8')
    tmp.replace(percorso)


def stato_progetti():
    """Lo stato di ogni progetto, da controlla.py: una sola fonte."""
    r = subprocess.run([sys.executable, str(CONTROLLA), '--json'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    # esce 1 quando un progetto è 🔴: il JSON c'è lo stesso, ed è quello che serve
    if r.returncode not in (0, 1) or not r.stdout.strip():
        raise RuntimeError('controlla.py è uscito con %d: %s'
                           % (r.returncode, r.stderr.strip()[-1500:]))
    return json.loads(r.stdout)


def ore_di_ritardo(p):
    """Da quante ore la memoria è indietro rispetto al lavoro vero."""
    mem, lav = p.get('memoria_ora'), p.get('lavoro_ora')
    if not mem or not lav:
        return None
    f = '%Y-%m-%d %H:%M:%S'
    try:
        d = datetime.datetime.strptime(lav, f) - datetime.datetime.strptime(mem, f)
    except ValueError:
        return None
    return round(d.total_seconds() / 3600, 1)


def copia_memoria(progetti):
    """Una copia di ogni MEMORIA.md che è cambiata dall'ultimo giro.

    Non è un backup del progetto: è la rete per quando due computer scrivono
    la stessa memoria su OneDrive e una versione sparisce.
    """
    copiati = []
    for p in progetti:
        cart = pathlib.Path(p.get('cartella') or '')
        mem = cart / '.claude' / 'memoria' / 'MEMORIA.md'
        if not mem.is_file():
            continue
        try:
            testo = mem.read_bytes()
        except OSError as e:          # OneDrive può avere il file non scaricato
            copiati.append({'progetto': p['progetto'], 'errore': str(e)[:120]})
            continue
        impronta = hashlib.sha256(testo).hexdigest()[:16]
        dove = COPIE / p['progetto'].replace('/', '-')
        dove.mkdir(parents=True, exist_ok=True)
        if any(f.name.endswith('-%s.md' % impronta) for f in dove.glob('*.md')):
            continue                  # identica all'ultima: niente da copiare
        nome = '%s-%s.md' % (datetime.datetime.now().strftime('%Y%m%d-%H%M'), impronta)
        (dove / nome).write_bytes(testo)
        copiati.append({'progetto': p['progetto'], 'copia': nome})
        vecchie = sorted(dove.glob('*.md'))[:-COPIE_DA_TENERE]
        for v in vecchie:
            v.unlink()
    return copiati


def rigenera_lavori():
    """Rimette in pari «Lavori in corso»: manda allo storico le prese di chi non
    dà più segno di vita (un terminale chiuso col taglio non fa in tempo a
    scrivere «finito») e riscrive l'indice che leggono tutte le sessioni, sul
    Mac e sul PC dell'amministrazione. Se fallisce non ferma il giro: il resto
    del battito vale lo stesso."""
    try:
        r = subprocess.run([sys.executable, str(LAVORI), 'indice', '--pulisci'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:                        # noqa: BLE001
        return 'registro dei lavori non aggiornato: %s' % e


def giro_portiere():
    """Il giro del portiere delle chiavi: chiavi fantasma, chiavi tenute oltre
    la scadenza, risorse accese che nessuno ha dichiarato, sessioni non
    registrate. Qui si guarda soltanto: il ritiro resta un comando a parte,
    perché togliere una chiave a un agente che sta davvero lavorando
    romperebbe il suo lavoro, e quella decisione la prende Jarvis.

    Il portiere è uno script e non un agente acceso h24 (l'utente, 20/09/2026):
    contare e confrontare chiavi non richiede nessun giudizio."""
    try:
        r = subprocess.run([sys.executable, str(PORTIERE), '--json'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        s = json.loads(r.stdout) if r.stdout.strip() else {}
        note = s.get('note', [])
        return {'chiavi': sum(s.get('chiavi_in_giro', {}).values()),
                'da_guardare': len(note),
                'tipi': sorted({n['tipo'] for n in note}),
                'note': note}
    except Exception as e:                        # noqa: BLE001
        return {'errore': 'portiere non passato: %s' % e}


def salvataggio_privato():
    """La copia di tutto Jarvis nel repository privato Jarvis-Privato.

    Ordine dell'utente del 21/09/2026: memoria, vault, configurazione e dati
    personali devono stare in un posto da cui si ripristina in un click. Lo
    script è deterministico e non chiede niente, quindi può girare qui.

    Parte per ultimo, dopo la sincronia, e non fa mai fallire il battito: se il
    salvataggio si rompe o si blocca, il resto del giro vale lo stesso. I suoi
    controlli sui segreti fanno uscire lo script con 1 e scrivono il motivo in
    ripristino/ALLARME.txt: qui si registra l'esito, non si insiste.
    """
    if sys.platform == 'win32':   # script bash del Mac verso GitHub privato: non si usa su questo PC
        return {'esito': 'non previsto su Windows', 'allarme': False}
    if not SALVA_PRIVATO.is_file():
        return {'esito': 'non c\'è', 'dove': str(SALVA_PRIVATO)}
    try:
        r = subprocess.run(['/bin/bash', str(SALVA_PRIVATO)],
                           capture_output=True, text=True,
                           timeout=SALVA_TIMEOUT, cwd=str(AGENTE))
    except subprocess.TimeoutExpired:
        return {'esito': 'scaduto', 'minuti': SALVA_TIMEOUT // 60}
    except Exception as e:                        # noqa: BLE001
        return {'esito': 'rotto', 'perché': str(e)[:200]}
    righe = [x for x in r.stdout.strip().splitlines() if x.strip()]
    return {'esito': 'fatto' if r.returncode == 0 else 'fallito',
            'uscita': r.returncode,
            'ultima_riga': righe[-1].strip() if righe else '',
            'allarme': (AGENTE / 'ripristino' / 'ALLARME.txt').is_file()}


def manutenzione_claude():
    """~/.claude sempre allineato al repository e ripulito una volta al giorno (l'utente, 29/09/2026).
    Allinea ganci, agenti di casa e skill (verso il repository, il più recente vince) a ogni giro;
    toglie chat, testi PDF e incollati vecchi al massimo una volta ogni 24 ore."""
    fuori = {}
    qui = pathlib.Path(__file__).resolve().parents[1]
    try:
        r = subprocess.run([sys.executable, str(qui / 'strumenti' / 'sincro_claude.py'), '--verso-repo'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        fuori['sincro'] = (r.stdout.strip().splitlines() or [''])[-1]
        marca = qui / 'sincro' / '.ultima-pulizia-claude'
        if not marca.exists() or time.time() - marca.stat().st_mtime > 86400:
            r = subprocess.run([sys.executable, str(qui / 'strumenti' / 'pulisci_claude.py'), '--applica', '--quiet',
                                '--archivia', str(pathlib.Path.home() / '.locale-onedrive' / 'backup-claude-storico')],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
            fuori['pulizia'] = (r.stdout.strip().splitlines() or [''])[-1]
            marca.write_text(fuori['pulizia'] + '\n', encoding='utf-8')
        # Mac, VPS e app Android sono allineati? (l'utente, 04/10/2026): si misura a ogni giro, si dice solo se c'è una differenza
        r = subprocess.run([sys.executable, str(qui / 'strumenti' / 'allinea_stato.py'), '--confronta'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=150)
        righe = r.stdout.strip().splitlines()
        fuori['allineamento'] = 'allineati' if r.returncode == 0 else ' | '.join(l.strip(' -') for l in righe if l.startswith(' - '))[:300] or (righe[-1] if righe else 'sconosciuto')
    except Exception as err:      # noqa: BLE001 — il battito non deve morire
        fuori['errore'] = str(err)
    return fuori


def giro():
    claude = manutenzione_claude()
    dati = stato_progetti()
    progetti = dati.get('progetti', [])
    righe, indietro = [], []
    for p in progetti:
        if p.get('dati'):             # cartelle di soli dati: niente memoria
            continue
        ore = ore_di_ritardo(p)
        riga = {'progetto': p['progetto'], 'semaforo': p.get('semaforo'),
                'esito': p.get('esito'), 'memoria': p.get('memoria_ora'),
                'memoria_file': p.get('memoria_file'),
                'da_fare': p.get('da_fare_aperte'), 'errori': p.get('errori'),
                'lavoro': p.get('lavoro_ora'),
                'lavoro_file': p.get('lavoro_file'), 'ore_indietro': ore,
                'cartella': p.get('cartella')}
        righe.append(riga)
        if ore is not None and ore >= ORE_PRIMA_DI_LAMENTARSI:
            indietro.append(riga)

    # le pagine «A che punto siamo» non si rigenerano più (memoria unica, 24/09/2026)
    serve, rifatto = [], False
    nota = ('non si rigenera più: la memoria sta nella cartella del progetto (.claude/memoria)' if sys.platform == 'win32'
            else 'non si rigenera più: la memoria sta nella memoria condivisa (Stato.md di ogni spazio)')

    copie = copia_memoria(progetti)
    lavori = rigenera_lavori()
    portiere = giro_portiere()
    salvataggio = salvataggio_privato()   # per ultimo: è il più lungo

    esito = {
        'quando': adesso(),
        'lavori': lavori,
        'portiere': portiere,
        'salvataggio_privato': salvataggio,
        'claude': claude,
        'progetti': righe,
        'indietro': [r['progetto'] for r in indietro],
        'vault_rigenerato': rifatto,
        'vault_perche': serve,
        'vault_nota': nota,
        'copie': copie,
        'prossimo_giro_minuti': 15,
    }
    scrivi_atomico(ULTIMO, json.dumps(esito, ensure_ascii=False, indent=1))
    with REGISTRO.open('a', encoding='utf-8') as f:
        f.write('%s · %d progetti · vault %s · %d copie · indietro: %s · '
                'chiavi %s, da guardare %s · salvataggio privato: %s\n'
                % (esito['quando'], len(righe),
                   'rifatto' if rifatto else 'non si rigenera', len(copie),
                   ', '.join(esito['indietro']) or 'nessuno',
                   portiere.get('chiavi', '?'), portiere.get('da_guardare', '?'),
                   salvataggio.get('esito', '?')))
    return esito


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--zitto', action='store_true',
                    help='parla solo se un progetto è indietro o qualcosa è rotto')
    a = ap.parse_args()

    COPIE.mkdir(parents=True, exist_ok=True)
    with LUCCHETTO.open('w') as l:
        try:
            if fcntl:
                fcntl.flock(l, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                msvcrt.locking(l.fileno(), msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, OSError):
            if not a.zitto:
                print('un altro giro è già in corso, salto questo')
            return 0
        try:
            e = giro()
        except Exception as err:      # noqa: BLE001 — il timer non deve morire
            print('il giro è fallito: %s' % err, file=sys.stderr)
            return 1

    if a.zitto and not e['indietro']:
        return 0
    print('%s · %d progetti letti' % (e['quando'], len(e['progetti'])))
    for r in e['progetti']:
        print('  %s %-24s memoria %s%s' % (
            r['semaforo'] or ' ', r['progetto'], r['memoria'] or '—',
            '  (indietro di %s h)' % r['ore_indietro'] if (r['ore_indietro'] or 0) > 0 else ''))
    print('  lavori in corso: %s' % e.get('lavori', '—'))
    pt = e.get('portiere') or {}
    if pt.get('errore'):
        print('  portiere: %s' % pt['errore'])
    else:
        print('  chiavi in giro: %s · da guardare: %s%s'
              % (pt.get('chiavi', '?'), pt.get('da_guardare', '?'),
                 (' (%s)' % ', '.join(pt['tipi'])) if pt.get('tipi') else ''))
    cl = e.get('claude') or {}
    print('  ~/.claude: %s · pulizia: %s' % (cl.get('sincro') or cl.get('errore', '?'), cl.get('pulizia', 'già fatta oggi')))
    print('  Mac/VPS/app: %s' % cl.get('allineamento', '?'))
    sp = e.get('salvataggio_privato') or {}
    print('  salvataggio privato: %s%s'
          % (sp.get('esito', '?'),
             ('  — %s' % sp['ultima_riga']) if sp.get('ultima_riga') else ''))
    if sp.get('allarme'):
        print('  🔴 ripristino/ALLARME.txt: il salvataggio ha trovato un segreto '
              'e non ha spinto niente')
    if e['copie']:
        print('  copie di sicurezza: %s'
              % ', '.join(c.get('progetto', '?') for c in e['copie']))
    if e['indietro']:
        print('  ⚠ da salvare a mano: %s' % ', '.join(e['indietro']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
