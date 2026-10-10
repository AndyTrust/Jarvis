#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chi sta lavorando su cosa, adesso. Il registro condiviso fra sessioni e agenti.

Perché esiste (l'utente, 20/09/2026 09:50): sul Mac girano più sessioni di Claude
insieme, e dal PC dell'amministrazione ne gira un'altra sulla stessa cartella
OneDrive. Oggi due di loro si sono sfiorate: una ha rubato il primo piano
mentre l'altra fotografava lo schermo. Fosse capitato sugli stessi file, il
lavoro di una sarebbe sparito sotto quello dell'altra — è già successo con
MEMORIA.md il 9/09/2026, e una versione non è più tornata.

La regola che ne esce: prima di mettere le mani su un progetto si guarda chi
c'è già dentro; se qualcuno ci sta lavorando non si entra, si aspetta e si
verifica dopo; e quello che è stato fatto non si rifà. Così il codice va solo
avanti.

🔴 Perché NON è un file unico condiviso. Un solo .md scritto da tutti, su
OneDrive, è esattamente il modo in cui il 9/09/2026 è sparito il salvataggio
del PC Windows: vince l'ultimo che salva e l'altro non se ne accorge. Qui ogni
sessione scrive SOLO il proprio file in `attivi/`, e nessuno tocca quello di un
altro. L'indice leggibile (`lavori-in-corso.md`) è generato da quei file: si
rigenera, non si scrive a mano.

Dove sta tutto (dal 2026-10-05 sulla VPS, fonte unica; il Mac e il PC Windows
inoltrano i comandi via ssh, vedi REGISTRO_VPS più sotto):

    VPS /root/registro-lavori/attivi/<macchina>__<sessione>__<agente>__<progetto>.json
    VPS /root/registro-lavori/storico/<AAAA-MM>__<macchina>.md
    VPS ~/.ai-memory/global/lavori-in-corso.md   <- l'indice, rigenerato (arriva al Mac via OneDrive)
    Mac ~/.cache/jarvis-lavori/attivi/           <- copia in sola lettura per portiere, badge, lavagna
    (la copia di prima, su OneDrive: ~/.ai-memory/global/lavori/_migrato-sulla-vps-20261005/)

Comandi:

    lavori.py chi                          chi sta lavorando adesso, e su cosa
    lavori.py chi --progetto "<progetto>"   solo quel progetto
    lavori.py prendo "<progetto>" "<cosa>" [--agente X] [--file a,b,c]
                                           [--risorse tunnel-odoo,...] [--max-min 60]
    lavori.py chiavi                       quali risorse sono in mano a qualcuno
    lavori.py verifica <risorsa>            la serratura per gli script: 0 libera
                                           o già mia, 3 di un altro, 2 nome ignoto
    lavori.py battito                      "sono ancora vivo" (ogni tanto)
    lavori.py finito ["<esito>"]           libera e scrive la riga di storico
    lavori.py indice                       rigenera lavori-in-corso.md
    lavori.py storico [--giorni 7]         cosa è stato fatto, e da chi

Uscita: 0 se è tutto libero o l'operazione è riuscita, 3 da `chi` e da `prendo`
quando su quel progetto c'è già qualcun altro al lavoro. 3 vuol dire «fermati e
leggi», non «errore».

LE CHIAVI (l'utente, 20/09/2026 12:55). Un lavoro non occupa solo dei file: occupa
delle *risorse* condivise — il tunnel verso l'Odoo di produzione, il Chrome di
debug, il database, un contenitore. Quelle sono le chiavi. Chi prende un lavoro
dichiara quali chiavi ritira, e le restituisce quando finisce. Due regole:

  1. Una chiave sta in mano a UNO solo. Se è già presa, `prendo` si ferma (3),
     anche se il progetto è diverso: il progetto non c'entra, la risorsa sì.
  2. Ogni chiave ha una scadenza (`--max-min`, default 120). Oltre quella la
     presa è «scaduta» e il portiere la ritira. Nasce dal 20/09/2026: un tunnel
     verso l'Odoo di produzione è rimasto aperto sette ore perché nessuno
     riportava la chiave, e nessuno aveva un modo per accorgersene.

Chi incrocia le chiavi con i processi veri è `strumenti/portiere.py`: una chiave
senza processo dietro è un fantasma, un processo senza chiave è un abusivo.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import processi  # noqa: E402  su Windows os.kill(pid, 0) termina il processo: si usa questo

MEMORIA = pathlib.Path(os.path.expanduser('~/.ai-memory/global'))

# Il registro può stare sulla VPS, fonte unica per più macchine (se configurata); senza VPS è locale
# in ~/.jarvis/registro-lavori. Con la VPS:
#   - sulla VPS questo script lavora in locale, in /root/registro-lavori/
#     (attivi/ e storico/, fuori da OneDrive: nessuna copia in conflitto);
#   - sul Mac (e ovunque non sia la VPS) ogni comando si INOLTRA alla VPS via
#     ssh, con l'identità di chi lo lancia (macchina, sessione, pid): la presa
#     resta sua. Se la VPS non risponde è un errore, mai una presa locale che
#     nessuno vedrebbe;
#   - su un PC Windows lo fa lavori.ps1, con la chiave del PC.
# I moduli che leggono il registro dal Mac (portiere, badge, cruscotto,
# sentinella, lavagna) leggono una copia in sola lettura in ~/.cache/
# jarvis-lavori/, rinfrescata dalla VPS a ogni lettura (al massimo ogni 10 s).
# Distribuzione (2026-10-10): senza una VPS configurata (variabile JARVIS_VPS_SSH) il registro è LOCALE, in
# ~/.jarvis/registro-lavori: chi installa Jarvis su un Mac solo non deve dipendere da un server.
VPS_SSH = os.environ.get('JARVIS_VPS_SSH') or ''
VPS_LAVORI_PY = os.environ.get('JARVIS_VPS_LAVORI_PY') or '/root/jarvis/strumenti/lavori.py'
REGISTRO_VPS = pathlib.Path('/root/registro-lavori')
SU_VPS = (os.environ.get('JARVIS_LAVORI_LOCALE') == '1' or not VPS_SSH
          or str(pathlib.Path(__file__).resolve()).startswith('/root/'))
CLIENTE = not SU_VPS
if SU_VPS:
    LAVORI = pathlib.Path(os.environ.get('JARVIS_LAVORI') or (REGISTRO_VPS if str(pathlib.Path(__file__).resolve()).startswith('/root/')
                                                              else os.path.expanduser('~/.jarvis/registro-lavori')))
else:
    LAVORI = pathlib.Path(os.environ.get('JARVIS_LAVORI_SPECCHIO') or os.path.expanduser('~/.cache/jarvis-lavori'))
ATTIVI = LAVORI / 'attivi'
STORICO = LAVORI / 'storico'
# con JARVIS_LAVORI (prove) anche l'indice va accanto, mai sopra quello vero
INDICE = (LAVORI.parent / 'lavori-in-corso.md') if os.environ.get('JARVIS_LAVORI') else MEMORIA / 'lavori-in-corso.md'

# Le chiavi che una macchina «ospite» (un PC che lavora su un solo progetto) può prendere: vuoto = nessun limite.
CHIAVI_CRM = set()

# Senza battito da più di così, la sessione è considerata morta: un terminale
# chiuso col taglio non fa in tempo a scrivere «finito». 45 minuti perché il
# battito automatico è ogni 30: uno saltato non deve dichiarare morto nessuno.
MORTA_DOPO_MIN = 45

# Quanto dura una chiave se nessuno dice il contrario. Due ore è più di
# qualunque lavoro onesto e molto meno delle sette ore del tunnel dimenticato.
SCADE_DOPO_MIN = 120

# Le risorse condivise che valgono una chiave, con il nome canonico. Non è un
# elenco chiuso — un nome fuori elenco si prende lo stesso, con un avviso — ma
# serve perché due agenti chiamino la stessa cosa allo stesso modo: `tunnel-odoo`
# e `tunnel_odoo_prod` sembrano due risorse diverse e non lo sono.
#
RISORSE = {
    'db-produzione': 'scritture su un database di produzione',
    'shell-remota': 'una sessione ssh sulla VPS che modifica qualcosa',
    'n8n': 'i flussi di n8n',
    'chrome-debug': 'il Chrome dell’utente con la porta di debug 9222',
    'sito-pubblicazione': 'pubblicare su un sito (plugin, pagine, cache): vince sempre l’ultimo',
    'tag-manager': 'un container di Tag Manager',
    'mac-schermo': 'schermo, mouse e tastiera del Mac (strumenti/mac.py)',
    'telefono-adb': 'il telefono Android dell’utente via ADB',
    'memoria-condivisa': 'scritture nella memoria condivisa',
}


def mio_file(progetto, agente=None, risorse=None):
    """🔴 Il nome porta dentro anche l'AGENTE, non solo la sessione.

    Un sottoagente lanciato con lo strumento Agent gira DENTRO la sessione che
    l'ha lanciato: stesso `CLAUDE_SESSION_ID`, stessa macchina. Senza l'agente
    nel nome, `finito` del sottoagente chiudeva anche la presa del suo padre —
    successo davvero il 20/09/2026 alle 13:12, un sottoagente ha chiuso la
    presa di Jarvis mentre stava ancora lavorando."""
    return (ATTIVI / f'{slug(macchina())}__{slug(sessione_id())[:24]}'
                     f'__{slug(chi_sono(agente))[:20]}__{slug(progetto)}.json')


def vivo(d):
    """C'è ancora un processo dietro questa presa? True sì, False no, None non
    si sa (presa di un'altra macchina, o scritta prima che si salvasse il pid:
    lì il PID non vuol dire niente e non si giudica)."""
    if d.get('macchina') != macchina() or not d.get('pid'):
        return None
    if SU_VPS and os.environ.get('JARVIS_PID'):
        return None    # comando inoltrato: i pid sono della macchina di chi chiama, qui non vogliono dire niente
    if processi.WIN:          # su Windows os.kill(pid, 0) termina il processo
        return processi.vivo(d['pid'])
    try:
        os.kill(int(d['pid']), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return None


def leggi_attivi():
    """Tutte le prese in corso. Un file illeggibile non ferma il giro: si
    segnala e si va avanti, se no basta una scrittura a metà da OneDrive per
    rendere cieco il controllo proprio quando serve."""
    fuori = []
    if CLIENTE:
        aggiorna_specchio()
    for f in file_attivi():
        try:
            d = leggi_json(f)
        except OSError as e:
            # 🔴 Su OneDrive un file può esserci ma non essere ancora scaricato:
            # la lettura va in timeout (Errno 60). Non è una presa rimasta a
            # metà, è un file che non è arrivato — contarlo come lavoro in corso
            # riempie il registro di righe che non vogliono dire niente.
            # Succede sul serio quando un'altra macchina scrive nel registro.
            print(f'  (non ancora scaricato da OneDrive, lo salto: {f.name} — {e})',
                  file=sys.stderr)
            continue
        except Exception as e:
            fuori.append({'progetto': '(file illeggibile)', 'cosa': f'{f.name}: {e}',
                          'macchina': '?', 'agente': '?', 'battito': '', 'morta': True,
                          '_file': f})
            continue
        if d.get('chiuso'):
            continue          # chiusa: resta solo dove la cancellazione non è arrivata
        d['_file'] = f
        # 🔴 Il solo battito non basta a dichiarare morto qualcuno. Un
        # sottoagente lavora anche un'ora di fila e non chiama mai `battito`:
        # senza questo controllo, a 45 minuti il battito dei 30 lo manderebbe
        # allo storico e gli libererebbe la chiave mentre sta ancora scrivendo.
        # Se il processo è vivo, il lavoro è vivo, punto.
        d['morta'] = (minuti_di(d, 'battito') > MORTA_DOPO_MIN
                      and vivo(d) is not True)
        # Scaduta è diverso da morta: la sessione può essere vivissima e stare
        # comunque tenendo una chiave da più tempo di quello che aveva chiesto.
        # È il caso del tunnel delle sette ore, che batteva regolarmente.
        d['scaduta'] = minuti_di(d, 'inizio') > max_min(d)
        fuori.append(d)
    return fuori


def chiavi_di(d):
    return [x for x in (d.get('risorse') or []) if x]


def max_min(d):
    """Quanti minuti dura la chiave. Scritto così e non con `or` perché 0 è un
    valore legittimo — «la voglio per il tempo di un comando» — e con `or`
    diventerebbe il default di due ore, cioè l'opposto."""
    v = d.get('max_min')
    return SCADE_DOPO_MIN if v is None else v


def chiavi_in_giro(attivi=None):
    """Quale chiave è in mano a chi, adesso. Solo le prese vive: una presa senza
    battito non tiene più niente, l'ha già lasciata cadere."""
    fuori = {}
    for d in (attivi if attivi is not None else leggi_attivi()):
        if d.get('morta'):
            continue
        for r in chiavi_di(d):
            fuori.setdefault(r, []).append(d)
    return fuori


def minuti_da(quando):
    if not quando:
        return 10 ** 6
    try:
        t = datetime.datetime.strptime(quando, '%Y-%m-%d %H:%M')
    except ValueError:
        return 10 ** 6
    return (_ora_italiana() - t).total_seconds() / 60


def eta_di(d, quale):
    """L'età giusta anche per una presa di un'altra macchina, che può stare su
    un altro fuso: si conta sul tempo assoluto, non sulla data scritta."""
    return _eta(minuti_di(d, quale))


def eta(quando):
    return _eta(minuti_da(quando))


def _eta(m):
    if m >= 10 ** 5:
        return 'da sempre'
    if m < 0:
        return 'appena adesso'
    if m < 60:
        return f'{int(m)} min fa'
    return f'{int(m // 60)} h {int(m % 60)} min fa'


def righe_altri(attivi, progetto=None, escludi=None):
    """Chi c'è, tolto me. Le sessioni morte restano visibili ma marcate: dicono
    che qualcuno era dentro e non ha chiuso, che è un'informazione, non rumore."""
    out = []
    for d in attivi:
        if escludi and d.get('_file') is not None and d['_file'].name == escludi.name:
            continue
        if progetto and slug(d.get('progetto')) != slug(progetto):
            continue
        out.append(d)
    return out


SOLO_CRM = os.environ.get('JARVIS_SOLO_CRM') == '1'   # una macchina ospite vede solo il suo progetto
PAROLE_CRM = re.compile(os.environ.get('JARVIS_SOLO_PROGETTO') or r'(?!)', re.I)   # il nome del progetto della macchina ospite


def del_crm(d):
    return bool(PAROLE_CRM.search(f"{d.get('progetto') or ''} {d.get('cosa') or ''}"))


def stampa(d):
    if SOLO_CRM and not del_crm(d):
        # Il PC dell'amministrazione non vede i progetti dell'utente (2026-10-05): solo che c'è qualcuno e cosa tiene.
        print(f"  {'🔴' if not d.get('morta') else '⚪'} (un lavoro di un altro progetto)")
        if chiavi_di(d):
            print(f"      🔑 {', '.join(chiavi_di(d))}")
        return
    tag = ' ⚠ senza battito, forse chiusa male' if d.get('morta') else ''
    print(f"  {'🔴' if not d.get('morta') else '⚪'} {d.get('progetto')}  —  {d.get('cosa')}")
    print(f"      {d.get('agente') or 'sessione'} su {d.get('macchina')} · "
          f"iniziato {eta_di(d, 'inizio')} · ultimo segno di vita {eta_di(d, 'battito')}{tag}")
    if d.get('file'):
        print(f"      file: {', '.join(d['file'])}")
    if chiavi_di(d):
        print(f"      🔑 {', '.join(chiavi_di(d))}"
              + ('  ⏰ oltre la scadenza' if d.get('scaduta') else ''))


# ---------------------------------------------------------------- comandi



def altri_pc_al_lavoro(ore=3):
    """Le macchine senza vault (PC Windows, VPS) non scrivono in lavori/attivi: lasciano righe in
    <registro condiviso>/<PC>.log (variabile JARVIS_REGISTRO_CONDIVISO) (`AAAA-MM-GG HH:MM | PC | chi | INIZIO <cosa>` e `… | FINE <cosa> | esito`).
    Un INIZIO senza FINE dello stesso «chi» nelle ultime ore vuol dire «sta lavorando» (2/10/2026, l'utente)."""
    import datetime as _dt, re as _re
    from pathlib import Path as _P
    REGISTRO_CONDIVISO = _P(os.environ.get("JARVIS_REGISTRO_CONDIVISO") or (_P.home() / ".jarvis" / "registro-condiviso"))
    fuori = []
    if not REGISTRO_CONDIVISO.is_dir():
        return fuori
    limite = _dt.datetime.now() - _dt.timedelta(hours=ore)
    for f in sorted(REGISTRO_CONDIVISO.glob("*.log")):
        if f.stem.upper() == "MAC":          # il registro di questo Mac: i miei lavori stanno già in lavori/attivi
            continue
        aperti = {}
        for riga in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            parti = [x.strip() for x in riga.split("|")]
            if len(parti) < 4:
                continue
            try:
                t = _dt.datetime.strptime(parti[0], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if t < limite:
                continue
            chi, cosa = parti[2], parti[3]
            if _re.match(r"INIZIO\b", cosa, _re.I):
                aperti[chi] = (parti[0], parti[1], cosa)
            elif _re.match(r"FINE\b", cosa, _re.I):
                aperti.pop(chi, None)
        for chi, (quando, pc, cosa) in aperti.items():
            fuori.append(f"{pc} · {chi} · {cosa} (dalle {quando})")
    return fuori


def cmd_chi(a):
    attivi = leggi_attivi()
    if SOLO_CRM:   # PC Windows: solo il CRM e chi tiene una chiave del CRM
        attivi = [d for d in attivi if del_crm(d) or set(chiavi_di(d)) & CHIAVI_CRM]
    altri = righe_altri(attivi, a.progetto, escludi=None if a.tutti else mio_file(a.progetto or '') if a.progetto else None)
    vivi = [d for d in altri if not d.get('morta')]
    pc_altri = altri_pc_al_lavoro()
    if pc_altri:
        print('Dal registro condiviso (altre macchine):')
        for r in pc_altri:
            print('  🖥 ' + r)
        print('')
        vivi = vivi + [{'pc': 1}]
        if not altri:
            print('Non entrare sugli stessi file: aspetta che finiscano e verifica dopo.')
            return 3
    if not altri:
        print('Nessuno sta lavorando' + (f' su «{a.progetto}»' if a.progetto else '') + '.')
        return 0
    print(f'Al lavoro adesso ({ora()}):')
    for d in altri:
        stampa(d)
    if vivi:
        print('\nNon entrare su quei file: aspetta che finiscano e verifica dopo.')
        return 3
    print('\nTutte senza battito: nessuno è davvero al lavoro, ma qualcosa è '
          'rimasto a metà. Guarda lo storico prima di rifare.')
    return 0


def cmd_prendo(a):
    ATTIVI.mkdir(parents=True, exist_ok=True)
    io = chi_sono(a.agente)
    chiedo = [x.strip() for x in a.risorse.split(',') if x.strip()] if a.risorse else []
    mio = mio_file(a.progetto, io)
    tutti = leggi_attivi()

    # Le chiavi si controllano PRIMA del progetto, e --insisto non le apre: due
    # lavori su progetti diversi possono benissimo litigare sullo stesso tunnel,
    # ed è proprio quel caso che questo controllo esiste per fermare.
    occupate = chiavi_in_giro(tutti)
    scontri = []
    for r in chiedo:
        for d in occupate.get(r, []):
            if d.get('_file') is None or d['_file'].name != mio.name:
                scontri.append((r, d))
    if scontri:
        print('FERMO: queste chiavi sono già in mano a qualcuno.')
        for r, d in scontri:
            print(f'  🔑 {r} — {RISORSE.get(r, "risorsa non in elenco")}')
            stampa(d)
        print('\nNon prendo il lavoro: una chiave sta in mano a uno solo, e '
              '--insisto non vale sulle chiavi. Aspetta che la restituisca.')
        return 3

    altri = righe_altri(tutti, a.progetto, escludi=mio)
    vivi = [d for d in altri if not d.get('morta')]
    if vivi and not a.insisto:
        print(f'FERMO: su «{a.progetto}» c\'è già qualcuno.')
        for d in vivi:
            stampa(d)
        print('\nNon prendo il lavoro. Se sei sicuro che sia un pezzo diverso, '
              'ripeti con --insisto e scrivi nel «cosa» quale pezzo tocchi.')
        return 3

    fuori_elenco = [r for r in chiedo if r not in RISORSE]
    d = {
        'progetto': a.progetto, 'cosa': a.cosa,
        'agente': io,
        'macchina': macchina(), 'sessione': sessione_id(),
        'file': [x.strip() for x in a.file.split(',')] if a.file else [],
        'risorse': chiedo, 'max_min': a.max_min, 'pid': pid_sessione(),
        'inizio': ora(), 'battito': ora(),
        'ts': adesso(), 'ts_battito': adesso(),
    }
    scrivi(mio, d)
    print(f'Preso: {a.progetto} — {a.cosa}')
    if chiedo:
        print(f'Chiavi ritirate ({a.max_min} min): {", ".join(chiedo)}')
        print('Oltre la scadenza le ritira il portiere.')
    # 🔴 Chi usa solo `--file` crede di essersi protetto e non è vero: `--file`
    # dice quali file tocchi, le chiavi si ritirano con `--risorse`. Un agente
    # ha seguito la regola alla lettera e non ha ritirato niente, quindi nessuna
    # serratura l'avrebbe mai fermato (trovato il 20/09/2026). Il promemoria si
    # stampa solo quando serve davvero: chi tocca solo dei file non deve leggere
    # niente in più.
    if not chiedo and a.file:
        print('(nessuna chiave ritirata: --file dice quali file tocchi, non le '
              'risorse. Se apri un database, un browser, lo schermo o il '
              'telefono, aggiungi --risorse — «lavori.py chiavi --libere» le elenca)')

    # Il comando di chiusura già scritto, con l'agente dentro: chi prende con
    # un --agente e chiude con un `finito` nudo chiude la presa di un altro.
    if SOLO_CRM:
        print(f'Per chiudere:  .\\amministrazione\\lavori.ps1 finito "<esito>" -Agente {io}')
    else:
        print(f'Per chiudere:  python3 strumenti/lavori.py finito "<esito>" --agente {io}')
    if fuori_elenco:
        print(f'⚠ nomi fuori elenco: {", ".join(fuori_elenco)} — controlla che '
              'non siano un altro modo di scrivere una risorsa già in RISORSE.')
    if altri:
        print('(c\'erano prese vecchie senza battito, le ho lasciate: '
              'guarda lo storico prima di rifare quel pezzo)')
    return 0


def tenuta_da_altri(risorsa, agente=None):
    """Chi tiene questa risorsa, tolto me. SOLA LETTURA: non scrive niente.

    «Me» è macchina + sessione, e **l'agente conta solo se è dichiarato**.

    Chi dice chi è viene preso in parola: due sottoagenti della stessa sessione
    che dichiarano nomi diversi sono due lavori diversi e si bloccano a vicenda,
    ed è giusto così.

    🔴 Ma chi non dichiara niente eredita la sessione, e non è un dettaglio: uno
    script lanciato dentro un lavoro non riceve `JARVIS_AGENTE`. Col filtro
    sull'agente sempre acceso, chi prendeva una chiave con `--agente giro-dati`
    e poi lanciava uno script si bloccava contro la **propria** chiave: una
    serratura che chiude fuori il padrone non è una serratura, è un guasto."""
    sess, mac = sessione_id(), macchina()
    dichiarato = agente or os.environ.get('JARVIS_AGENTE')
    io = slug(dichiarato) if dichiarato else None
    return [d for d in chiavi_in_giro().get(risorsa, [])
            if not (d.get('macchina') == mac and d.get('sessione') == sess
                    and (io is None or slug(d.get('agente')) == io))]


def cmd_libera(a):
    """«Posso usare questa risorsa?» — la serratura vera, per gli script.

    Serve perché una regola scritta in un profilo è solo un prompt: il modello
    che se la dimentica fa il danno lo stesso. Uno script che tocca una risorsa
    condivisa chiama questo e si ferma da solo:

        python3 lavori.py libera mac-schermo || exit 3

    Esito 0 se è libera o è già mia, 3 se è in mano a un altro. Non blocca chi
    non ha ancora preso niente: il caso da fermare è lo scontro vero, non il
    lavoro di uno solo che non ha voglia di dichiarare.

    `verifica` fa la stessa cosa e in più distingue il nome sbagliato (esito 2).
    Questo resta com'era perché lo chiama già `strumenti/mac.py`: un comando che
    qualcuno usa non cambia esito sotto i piedi."""
    altri = tenuta_da_altri(a.risorsa, a.agente)
    if not altri:
        print(f'{a.risorsa}: libera')
        return 0
    print(f'FERMO: «{a.risorsa}» è in mano a un altro.')
    for d in altri:
        stampa(d)
    return 3


def cmd_verifica(a):
    """La serratura per gli script che aprono una risorsa condivisa.

        python3 lavori.py verifica db-produzione || exit 3

    Tre esiti, e nessuna scrittura — questo comando non crea cartelle, non
    tocca le prese e non rigenera l'indice, così uno script può chiamarlo
    quante volte vuole senza lasciare traccia:

        0   libera, oppure già in mano a chi chiama (stessa macchina, stessa
            sessione, stesso agente: l'identità di `prendo` e `finito`)
        3   in mano a un altro — stampa chi la tiene e da quanto
        2   il nome non è fra le risorse note (RISORSE): quasi sempre un
            refuso nello script che chiama

    🔴 L'ordine conta: prima si guarda chi la tiene, poi se il nome è noto. Un
    nome fuori elenco si può prendere lo stesso (`prendo` lo permette, con un
    avviso), quindi se qualcuno lo tiene davvero la risposta giusta è 3 e non
    «non esiste»: una serratura non deve mai dire «libera» o «boh» mentre uno
    ci sta lavorando dentro."""
    altri = tenuta_da_altri(a.risorsa, a.agente)
    if altri:
        print(f'FERMO: «{a.risorsa}» è in mano a un altro.')
        for d in altri:
            stampa(d)
        return 3
    if a.risorsa not in RISORSE:
        print(f'{a.risorsa}: non è fra le risorse note, e nessuno la tiene.')
        print('Risorse note: ' + ', '.join(sorted(RISORSE)))
        return 2
    print(f'{a.risorsa}: libera')
    return 0


def cmd_chiavi(a):
    attivi = leggi_attivi()
    occupate = chiavi_in_giro(attivi)
    senza = [d for d in attivi if not d.get('morta') and not chiavi_di(d)]
    if not occupate:
        print(f'Nessuna chiave in giro ({ora()}).')
    else:
        print(f'Chiavi in giro ({ora()}): {sum(len(v) for v in occupate.values())} '
              f'su {len(occupate)} risorse')
        for r in sorted(occupate):
            print(f'\n  🔑 {r} — {RISORSE.get(r, "risorsa non in elenco")}')
            for d in occupate[r]:
                tag = ' ⏰ SCADUTA' if d.get('scaduta') else ''
                chi_e = (f'{d.get("agente")} su {d.get("macchina")} · {d.get("progetto")}'
                         if not SOLO_CRM or del_crm(d) else '(un lavoro di un altro progetto)')
                print(f'      {chi_e} · presa {eta_di(d, "inizio")}'
                      f' (max {max_min(d)} min){tag}')
    if senza:
        print(f'\nLavori senza nessuna chiave: {len(senza)} '
              '(toccano solo file, va bene così).')
    if a.libere:
        prese = set(occupate)
        print('\nChiavi libere: ' + (', '.join(sorted(set(RISORSE) - prese)) or 'nessuna'))
    return 3 if any(d.get('scaduta') for v in occupate.values() for d in v) else 0


def scrivi(f, d):
    """Scrittura atomica: su OneDrive un file letto a metà scrittura è un file
    illeggibile per chi sta controllando in quel momento."""
    tmp = f.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, f)


def cmd_battito(a):
    n = 0
    for f in file_attivi():
        try:
            d = leggi_json(f)
        except Exception:
            continue
        if d.get('chiuso'):
            continue
        if d.get('macchina') == macchina() and d.get('sessione') == sessione_id():
            d['battito'] = ora()
            d['ts_battito'] = adesso()
            scrivi(f, d)
            n += 1
    print(f'battito: {n} lavori miei aggiornati')
    return 0


def cmd_finito(a):
    """Chiude le MIE prese, e quando «mie» è ambiguo non chiude niente.

    🔴 Due modi opposti di sbagliare, tutti e due successi davvero il
    20/09/2026. Un sottoagente condivide la sessione col padre: senza filtro,
    il suo `finito` chiudeva il lavoro del padre (13:12). Col filtro
    sull'agente, chi aveva preso con `--agente propaga-chiavi` e chiuso con un
    `finito` nudo ha chiuso la presa di «Jarvis», che era di un altro (13:27).

    La regola che regge tutte e due: senza `--agente`, si chiude solo se nella
    sessione c'è un solo agente con prese aperte. Se ce ne sono di più, non si
    tocca niente e si dice quale comando scrivere."""
    tutte = [d for d in leggi_attivi()
             if d.get('macchina') == macchina() and d.get('sessione') == sessione_id()
             and (not a.progetto or slug(d.get('progetto')) == slug(a.progetto))]
    if a.agente or os.environ.get('JARVIS_AGENTE'):
        io = chi_sono(a.agente)
    else:
        nomi = {slug(d.get('agente')): d.get('agente') for d in tutte}
        if len(nomi) > 1:
            print('FERMO: in questa sessione ci sono prese di più agenti, e non so '
                  'quale sia la tua.')
            for d in tutte:
                stampa(d)
            print('\nDi\' quale chiudere:')
            for n in sorted(nomi.values()):
                print(f'  python3 strumenti/lavori.py finito "<esito>" --agente {n}')
            return 3
        io = list(nomi.values())[0] if nomi else chi_sono(None)
    chiusi = 0
    rese = []
    # Il PC Windows (il registro sulla VPS mette JARVIS_FINITO_LARGO=1): se nella sessione
    # non c'è niente, stessa macchina e stesso agente bastano. Lì ogni comando
    # di PowerShell può nascere in una sessione diversa da quella di `prendo`.
    largo = os.environ.get('JARVIS_FINITO_LARGO') == '1' and not any(
        slug(d.get('agente')) == slug(io) for d in tutte)
    if largo:
        print(f'(nessuna presa di questa sessione: chiudo quelle di {io} su {macchina()})')
    for f in file_attivi():
        try:
            d = leggi_json(f)
        except Exception:
            continue
        if d.get('chiuso'):
            continue
        mio = (d.get('macchina') == macchina()
               and (largo or d.get('sessione') == sessione_id())
               and slug(d.get('agente')) == slug(io))
        if not mio:
            continue
        if a.progetto and slug(d.get('progetto')) != slug(a.progetto):
            continue
        riga_storico(d, a.esito)
        rese.extend(chiavi_di(d))
        # 🔴 Prima si SCRIVE che è chiusa, poi si cancella. OneDrive propaga le
        # modifiche ma non le cancellazioni (verificato sulla VPS il 20/09/2026:
        # l'indice era aggiornato e c'erano ancora 13 prese che sul Mac non
        # esistevano più). Se la fine di un lavoro fosse solo «il file non c'è
        # più», sulle altre macchine quel lavoro resterebbe aperto per sempre.
        d.pop('_file', None)
        d['chiuso'] = adesso()
        d['esito'] = a.esito or ''
        scrivi(f, d)
        f.unlink()
        chiusi += 1
    print(f'chiusi {chiusi} lavori di {io}' + (f' su «{a.progetto}»' if a.progetto else ''))
    if chiusi:
        revoca_badge()
    if rese:
        print(f'chiavi restituite: {", ".join(rese)}')
    cmd_indice(argparse.Namespace(pulisci=False))
    return 0


def chiudi_file(nome, esito):
    """Chiude UNA presa per nome di file: la usa il portiere del Mac (prese
    fantasma, chiavi scadute) che non può più scrivere nel registro da sé."""
    f = ATTIVI / pathlib.Path(nome).name
    try:
        d = leggi_json(f)
    except Exception:
        print(f'{nome}: non c\'è (già chiusa?)')
        return 0
    if d.get('chiuso'):
        return 0
    riga_storico(d, esito)
    d['chiuso'] = adesso()
    d['esito'] = esito or ''
    scrivi(f, d)
    f.unlink(missing_ok=True)
    print(f'chiusa {f.name}' + (f' — chiavi rese: {", ".join(chiavi_di(d))}' if chiavi_di(d) else ''))
    return 0


def cmd_chiudi_file(a):
    for n in a.nomi:
        chiudi_file(n, a.esito)
    cmd_indice(argparse.Namespace(pulisci=False))
    return 0


def cmd_battito_file(a):
    """Battito per nome di file: il Mac lo manda per le prese il cui processo è
    vivo sul Mac (la VPS non può vedere i processi del Mac)."""
    n = 0
    for nome in a.nomi:
        f = ATTIVI / pathlib.Path(nome).name
        try:
            d = leggi_json(f)
        except Exception:
            continue
        if d.get('chiuso'):
            continue
        d['battito'] = ora()
        d['ts_battito'] = adesso()
        scrivi(f, d)
        n += 1
    print(f'battito: {n} prese aggiornate')
    return 0


def battito_vivi():
    """Sul Mac: le prese di questa macchina con il processo ancora vivo ricevono
    un battito sulla VPS. Senza questo un sottoagente che lavora un'ora senza
    chiamare `battito` sembrerebbe morto alla VPS, che non vede i pid del Mac,
    e la sua chiave tornerebbe libera mentre lavora. Lo chiama la sentinella."""
    vive = [d['_file'].name for d in leggi_attivi() if vivo(d) is True]
    if not vive:
        print('battito-vivi: nessuna presa viva di questa macchina')
        return 0
    return inoltra(['battito-file', *vive])


# ---------------------------------------------------------------- VPS
_SPECCHIO_ALLE = [0.0]


def aggiorna_specchio(forza=False):
    """La copia in sola lettura delle prese della VPS, per chi le legge dal Mac.
    Al massimo una volta ogni 10 secondi; se la VPS non risponde resta la copia
    di prima e lo si dice (una copia vecchia è meglio di nessuna, ma va saputo)."""
    if SU_VPS or (not forza and time.time() - _SPECCHIO_ALLE[0] < 10):
        return True
    _SPECCHIO_ALLE[0] = time.time()
    import shutil
    import tarfile
    import tempfile
    try:
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', VPS_SSH,
                            f'tar -C {REGISTRO_VPS} -czf - attivi'], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors='replace').strip()[:200])
        LAVORI.mkdir(parents=True, exist_ok=True)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='.specchio-', dir=LAVORI))
        import io
        with tarfile.open(fileobj=io.BytesIO(r.stdout), mode='r:gz') as tf:
            for m in tf.getmembers():
                if m.isfile() and m.name.startswith('attivi/') and '/' not in m.name[7:] and m.name.endswith('.json'):
                    (tmp / pathlib.Path(m.name).name).write_bytes(tf.extractfile(m).read())
        vecchia = LAVORI / '.attivi-vecchia'
        shutil.rmtree(vecchia, ignore_errors=True)
        if ATTIVI.exists():
            ATTIVI.rename(vecchia)
        tmp.rename(ATTIVI)
        shutil.rmtree(vecchia, ignore_errors=True)
        return True
    except Exception as e:
        print(f'  ⚠ registro sulla VPS non raggiungibile, uso la copia di prima: {e}', file=sys.stderr)
        return False


def inoltra(argv):
    """Esegue il comando sulla VPS, con l'identità di chi chiama. Torna l'esito
    del comando remoto (3 = occupato); 1 se la VPS non risponde."""
    import base64
    env = {'JARVIS_MACCHINA': macchina(), 'JARVIS_SESSIONE': sessione_id(),
           'JARVIS_PID': str(pid_sessione())}
    if os.environ.get('JARVIS_AGENTE'):
        env['JARVIS_AGENTE'] = os.environ['JARVIS_AGENTE']
    carico = base64.b64encode(json.dumps({'argv': list(argv), 'env': env}).encode()).decode()
    try:
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', VPS_SSH,
                            f'python3 {VPS_LAVORI_PY} --remoto {carico}'], timeout=120)
    except Exception as e:
        print(f'ERRORE: il registro dei lavori sta sulla VPS e non la raggiungo ({e}). '
              'Non ho scritto niente: riprova, e non lavorare su risorse condivise finché non risponde.',
              file=sys.stderr)
        return 1
    if r.returncode == 255:
        print(f'ERRORE: ssh {VPS_SSH} non risponde. Il registro dei lavori sta sulla VPS: '
              'non ho scritto niente. Riprova; non lavorare su risorse condivise finché non risponde.',
              file=sys.stderr)
        return 1
    _SPECCHIO_ALLE[0] = 0.0
    return r.returncode


def da_remoto(carico):
    """Sulla VPS: argomenti e identità arrivati da `inoltra` (Mac) o da il registro sulla VPS (Windows)."""
    import base64
    d = json.loads(base64.b64decode(carico).decode())
    argv = d.get('argv') or []
    argv = [argv] if isinstance(argv, str) else [str(x) for x in argv]
    for k, v in (d.get('env') or {}).items():
        if k in ('JARVIS_MACCHINA', 'JARVIS_SESSIONE', 'JARVIS_PID', 'JARVIS_AGENTE'):
            os.environ[k] = str(v)
    return argv


class _Serratura:
    """Un solo comando che scrive alla volta sul registro della VPS: senza, due
    `prendo` nello stesso istante vedono tutti e due la chiave libera."""
    def __enter__(self):
        import fcntl
        LAVORI.mkdir(parents=True, exist_ok=True)
        self.f = open(LAVORI / '.serratura', 'w')
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *x):
        self.f.close()


def revoca_badge():
    """Fine lavoro = si revoca il badge di lavoro della sessione (command-center/badge.py), ma solo se la sessione non
    ha altre prese aperte (un sottoagente che finisce non toglie il badge al padre). Mai un errore verso il chiamante."""
    if SU_VPS and os.environ.get('JARVIS_LAVORI_LOCALE') != '1':
        return    # il badge di lavoro sta sul Mac: lo revoca il Mac dopo l'inoltro
    try:
        import sys as _s
        _s.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'command-center'))
        import badge
        resta = [d for d in leggi_attivi() if d.get('sessione') == sessione_id()]
        if not resta:
            for k in {str(sessione_id() or '').lower(), str(os.environ.get('CC_SESSIONE') or '').lower()} - {''}:
                badge.revoca(k)
    except Exception:
        pass


def riga_storico(d, esito):
    """Una riga per lavoro finito, in un file al mese PER MACCHINA: due macchine
    non scrivono mai lo stesso file, quindi OneDrive non può far sparire niente."""
    STORICO.mkdir(parents=True, exist_ok=True)
    f = STORICO / f"{_ora_italiana().strftime('%Y-%m')}__{slug(macchina())}.md"
    if not f.exists():
        f.write_text(f"# Lavori finiti — {macchina()}, "
                     f"{_ora_italiana().strftime('%B %Y')}\n\n"
                     "Una riga per lavoro. Si aggiunge in fondo, non si riscrive: "
                     "è qui che si guarda prima di rifare qualcosa.\n\n"
                     "| Finito | Progetto | Agente | Cosa | Esito | File |\n"
                     "|---|---|---|---|---|---|\n", encoding='utf-8')
    pulisci = lambda t: (t or '').replace('|', '/').replace('\n', ' ')
    with f.open('a', encoding='utf-8') as fh:
        fh.write(f"| {ora()} | {pulisci(d.get('progetto'))} | {pulisci(d.get('agente'))} "
                 f"| {pulisci(d.get('cosa'))} | {pulisci(esito) or '—'} "
                 f"| {pulisci(', '.join(d.get('file') or [])) or '—'} |\n")


def cmd_indice(a):
    attivi = leggi_attivi()
    if a.pulisci:
        for d in attivi:
            if d.get('morta'):
                riga_storico(d, 'chiusa male: nessun battito, liberata dal battito dei 30 minuti')
                d['_file'].unlink(missing_ok=True)
        attivi = [d for d in attivi if not d.get('morta')]
    r = ['---', 'tipo: global', f'aggiornato: {ora()}', '---', '',
         '# Lavori in corso', '',
         '**Questo file è generato**: si rifà con `python3 ~/my-agent/strumenti/lavori.py indice`, '
         'non si scrive a mano. La fonte sono i file in `lavori/attivi/`, uno per sessione.', '',
         'Prima di lavorare su un progetto si guarda qui. Se qualcuno ci sta già dentro, '
         'non si entra sugli stessi file: si aspetta e si verifica dopo. '
         'Quello che è già stato fatto sta in `lavori/storico/` e non si rifà.', '']
    if not attivi:
        r += ['Adesso non sta lavorando nessuno.', '']
    else:
        r += ['| Progetto | Cosa | Agente | Macchina | Iniziato | Ultimo segno di vita | Chiavi | File |',
              '|---|---|---|---|---|---|---|---|']
        for d in sorted(attivi, key=lambda x: (x.get('progetto') or '', x.get('inizio') or '')):
            v = '⚠ nessun battito' if d.get('morta') else d.get('battito', '')
            k = ', '.join(chiavi_di(d)) or '—'
            if d.get('scaduta') and chiavi_di(d):
                k += ' ⏰'
            r.append(f"| {d.get('progetto')} | {d.get('cosa')} | {d.get('agente')} "
                     f"| {d.get('macchina')} | {d.get('inizio')} | {v} | {k} "
                     f"| {', '.join(d.get('file') or []) or '—'} |")
        r += ['']
    occupate = chiavi_in_giro(attivi)
    r += ['## Le chiavi', '',
          'Una chiave è una risorsa condivisa (un tunnel, un database, il Chrome di '
          'debug, lo schermo del Mac). Sta in mano a uno solo, e si restituisce con '
          '`lavori.py finito`. ⏰ vuol dire che è tenuta oltre la scadenza chiesta.', '']
    if not occupate:
        r += ['Adesso non ne ha in mano nessuno.', '']
    else:
        r += ['| Chiave | In mano a | Da | Scadenza |', '|---|---|---|---|']
        for nome in sorted(occupate):
            for d in occupate[nome]:
                r.append(f"| {nome} | {d.get('agente')} ({d.get('macchina')}) "
                         f"| {d.get('inizio')} | {max_min(d)} min"
                         f"{' ⏰ superata' if d.get('scaduta') else ''} |")
        r += ['']
    r += ['## Dove sta il resto', '',
          '- Cosa è stato fatto e da chi: `lavori/storico/<mese>__<macchina>.md`',
          '- Stato della memoria di ogni progetto: `~/my-agent/sincro/ultimo.json` (battito dei 30 minuti)',
          '- Elenco dei progetti: [[projects-index]]', '']
    INDICE.parent.mkdir(parents=True, exist_ok=True)
    tmp = INDICE.with_suffix('.md.tmp')
    tmp.write_text('\n'.join(r), encoding='utf-8')
    os.replace(tmp, INDICE)
    print(f'{INDICE}: {len(attivi)} lavori in corso')
    return 0


def cmd_storico(a):
    if not STORICO.exists():
        print('Nessuno storico.')
        return 0
    limite = (_ora_italiana() - datetime.timedelta(days=a.giorni)).strftime('%Y-%m-%d')
    righe = []
    for f in sorted(STORICO.glob('*.md')):
        for r in f.read_text(encoding='utf-8', errors='replace').split('\n'):
            if r.startswith('| 20') and r[2:12] >= limite:
                if not SOLO_CRM or PAROLE_CRM.search(r):
                    righe.append(r)
    if not righe:
        print(f'Niente negli ultimi {a.giorni} giorni.')
        return 0
    print(f'Fatto negli ultimi {a.giorni} giorni ({len(righe)} lavori):')
    for r in sorted(righe):
        c = [x.strip() for x in r.strip('|').split('|')]
        print(f'  {c[0]}  {c[1]:<16} {c[2]:<16} {c[3]}')
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest='c', required=True)

    c = s.add_parser('chi', help='chi sta lavorando adesso')
    c.add_argument('--progetto'); c.add_argument('--tutti', action='store_true',
                                                 help='mostra anche i miei lavori')
    c.set_defaults(f=cmd_chi)

    c = s.add_parser('prendo', help='dichiara che stai lavorando su un progetto')
    c.add_argument('progetto'); c.add_argument('cosa')
    c.add_argument('--agente'); c.add_argument('--file')
    c.add_argument('--insisto', action='store_true')
    c.add_argument('--risorse', help='chiavi da ritirare, separate da virgola '
                                     f'(elenco: {", ".join(sorted(RISORSE))})')
    c.add_argument('--max-min', type=int, default=SCADE_DOPO_MIN, dest='max_min',
                   help='per quanti minuti tieni le chiavi (default %(default)s)')
    c.set_defaults(f=cmd_prendo)

    c = s.add_parser('libera', help='«posso usare questa risorsa?» — per gli script')
    c.add_argument('risorsa'); c.add_argument('--agente')
    c.set_defaults(f=cmd_libera)

    c = s.add_parser('verifica', help='la serratura: 0 libera o mia, 3 di un altro, '
                                      '2 nome sconosciuto. Non scrive niente')
    c.add_argument('risorsa'); c.add_argument('--agente')
    c.set_defaults(f=cmd_verifica)

    c = s.add_parser('chiavi', help='quali risorse sono in mano a qualcuno')
    c.add_argument('--libere', action='store_true', help='mostra anche quelle libere')
    c.set_defaults(f=cmd_chiavi)

    c = s.add_parser('battito', help='sono ancora vivo')
    c.set_defaults(f=cmd_battito)

    c = s.add_parser('finito', help='libera e scrive lo storico')
    c.add_argument('esito', nargs='?'); c.add_argument('--progetto')
    c.add_argument('--agente', help='chiude solo le prese di questo agente '
                                    '(default: JARVIS_AGENTE, se no Jarvis)')
    c.set_defaults(f=cmd_finito)

    c = s.add_parser('indice', help='rigenera lavori-in-corso.md')
    c.add_argument('--pulisci', action='store_true',
                   help='manda allo storico le prese senza battito')
    c.set_defaults(f=cmd_indice)

    c = s.add_parser('storico', help='cosa è stato fatto, e da chi')
    c.add_argument('--giorni', type=int, default=7)
    c.set_defaults(f=cmd_storico)

    c = s.add_parser('chiudi-file', help='(portiere) chiude prese per nome di file')
    c.add_argument('esito'); c.add_argument('nomi', nargs='+')
    c.set_defaults(f=cmd_chiudi_file)

    c = s.add_parser('battito-file', help='(Mac) battito per nome di file')
    c.add_argument('nomi', nargs='+')
    c.set_defaults(f=cmd_battito_file)

    c = s.add_parser('battito-vivi', help='(Mac) battito sulla VPS per le prese col processo vivo qui')
    c.set_defaults(f=lambda a: battito_vivi())

    argv = sys.argv[1:]
    if argv[:1] == ['--remoto'] and len(argv) == 2:
        if CLIENTE:
            print('--remoto si usa solo sulla VPS', file=sys.stderr)
            sys.exit(2)
        argv = da_remoto(argv[1])
    if CLIENTE and argv[:1] not in (['battito-vivi'], ['-h'], ['--help'], []):
        esito = inoltra(argv)
        if esito == 0 and argv[:1] == ['finito']:
            revoca_badge()    # il badge di lavoro sta sul Mac
        sys.exit(esito)
    a = p.parse_args(argv)
    if a.c in ('prendo', 'finito', 'battito', 'chiudi-file', 'battito-file', 'indice'):
        with _Serratura():
            sys.exit(a.f(a))
    sys.exit(a.f(a))


if __name__ == '__main__':
    main()
