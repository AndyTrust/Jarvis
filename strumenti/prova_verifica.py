#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le prove di `lavori.py verifica`, la serratura delle risorse condivise.

    python3 strumenti/prova_verifica.py

Non tocca il registro vero. Ogni prova lancia `lavori.py` in un processo a
parte con `HOME` dentro una cartella temporanea: `lavori.py` calcola
`~/.ai-memory/global` all'import, quindi con un HOME finto scrive e legge un
registro finto e il vault su OneDrive non se ne accorge.

Le sessioni si fingono con `CLAUDE_SESSION_ID` e la macchina con
`JARVIS_MACCHINA`, che sono gli stessi ganci usati dalle prove a mano scritte
in `.claude/memoria/chiavi-delle-risorse-condivise.md`.

Esce 0 se passano tutte, 1 alla prima che fallisce.
"""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

LAVORI = pathlib.Path(__file__).resolve().parent / 'lavori.py'
FALLITE = []


def lancia(casa, *args, sessione='sessione-a', agente=None, macchina='mac-di-prova'):
    amb = dict(os.environ)
    amb['HOME'] = str(casa)
    amb['CLAUDE_SESSION_ID'] = sessione
    amb['JARVIS_MACCHINA'] = macchina
    amb.pop('JARVIS_AGENTE', None)
    if agente:
        amb['JARVIS_AGENTE'] = agente
    return subprocess.run([sys.executable, str(LAVORI), *args],
                          capture_output=True, text=True, env=amb, timeout=60)


def impronta(casa):
    """Com'è messo il registro adesso: percorso, dimensione e ora di modifica di
    ogni file. Serve a dimostrare che `verifica` non scrive NIENTE — non basta
    guardare le prese, perché `prendo` e `finito` creano cartelle e rigenerano
    l'indice, e una serratura che lo facesse lascerebbe tracce a ogni chiamata."""
    base = casa / '.ai-memory'
    if not base.exists():
        return []
    return sorted((str(p.relative_to(casa)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in base.rglob('*'))


PS1 = pathlib.Path(os.path.expanduser(
    '~/Library/CloudStorage/OneDrive/CRM Azienda Uno/amministrazione/lavori.ps1'))


def prova_gemello_ps1():
    """`lavori.ps1` è lo stesso registro visto dal PC dell'amministrazione, e
    legge e scrive gli stessi file su OneDrive. Se i due si allontanano, le due
    macchine chiamano la stessa risorsa con nomi diversi e non si accorgono di
    litigare — che è esattamente il danno che le chiavi esistono per fermare.

    Il controllo sta QUI, sul Mac, perché su questa macchina PowerShell non c'è
    e quel file non lo esegue nessuno: se la deriva non la trova una prova, non
    la trova nessuno finché non fa danno."""
    if not PS1.is_file():
        print("saltata  lavori.ps1 non è su questa macchina (OneDrive scollegato?)")
        return
    t = PS1.read_text()

    # L'elenco delle risorse: è il nome che viaggia fra le due macchine.
    dentro = re.search(r'\$Risorse140 = @\{(.*?)\n\}', t, re.S)
    prova('ps1: trovo $Risorse140', bool(dentro))
    if dentro:
        sue = set(re.findall(r"^\s*'?([a-z0-9-]+)'?\s*=", dentro.group(1), re.M))
        import importlib.util
        spec = importlib.util.spec_from_file_location('lavori', LAVORI)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mie = set(mod.RISORSE)
        prova('ps1: stesse risorse del gemello Python', sue, mie)

    # I sottocomandi: se uno dei due ne perde uno, chi lo chiama da là si ferma
    # con un errore invece di avere la risposta.
    vs = re.search(r'ValidateSet\(([^)]*)\)', t)
    prova('ps1: trovo il ValidateSet', bool(vs))
    if vs:
        suoi = set(vs.group(1).replace("'", '').replace(' ', '').split(','))
        prova('ps1: conosce verifica', 'verifica' in suoi, True)
        # `indice` sul PC non serve (lo rigenera il battito del Mac): è l'unica
        # differenza voluta, e sta scritta qui perché non sembri una dimenticanza.
        attesi = {'chi', 'prendo', 'battito', 'finito', 'storico', 'chiavi',
                  'libera', 'verifica'}
        prova('ps1: gli stessi comandi, tolto «indice»', suoi, attesi)

    # La logica dell'identità sta in un posto solo anche là.
    prova('ps1: verifica e libera non sono due copie',
          t.count('function TenutaDaAltri'), 1)
    prova('ps1: verifica esce con 0, 2 e 3',
          sorted(set(re.findall(r'exit (\d)',
                 re.search(r"^  'verifica' \{.*?^  \}", t, re.S | re.M).group(0)))),
          ['0', '2', '3'])


def prova(nome, fatto, atteso=None):
    ok = fatto if atteso is None else (fatto == atteso)
    print(('ok      ' if ok else 'FALLITA ') + nome
          + ('' if ok else f'  — atteso {atteso!r}, ottenuto {fatto!r}'))
    if not ok:
        FALLITE.append(nome)


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='prova-verifica-'))
    try:
        casa = tmp / 'casa'
        (casa / '.ai-memory' / 'global').mkdir(parents=True)

        # 1. registro vuoto: una risorsa nota è libera
        r = lancia(casa, 'verifica', 'db-140')
        prova('risorsa libera → 0', r.returncode, 0)
        prova('risorsa libera → dice «libera»', 'libera' in r.stdout, True)

        # 2. un nome che non sta in RISORSE e che nessuno tiene
        r = lancia(casa, 'verifica', 'risorsa-che-non-esiste')
        prova('nome sconosciuto → 2', r.returncode, 2)
        prova('nome sconosciuto → elenca le risorse note',
              'Risorse note:' in r.stdout, True)

        # 3. la sessione A ritira la chiave
        r = lancia(casa, 'prendo', 'Prova', 'un lavoro', '--risorse', 'db-140',
                   '--agente', 'uno', sessione='sessione-a')
        prova('prendo con la chiave riesce', r.returncode, 0)

        # 4. chi l'ha presa la può usare: stessa macchina, sessione, agente
        r = lancia(casa, 'verifica', 'db-140', '--agente', 'uno', sessione='sessione-a')
        prova('chiave mia → 0', r.returncode, 0)

        # 5. stesso agente, sessione diversa: non è la stessa presa
        r = lancia(casa, 'verifica', 'db-140', '--agente', 'uno', sessione='sessione-b')
        prova('stesso nome ma altra sessione → 3', r.returncode, 3)

        # 6. stessa sessione, agente diverso: è il caso del sottoagente, che
        #    gira DENTRO la sessione di chi l'ha lanciato e condivide il
        #    CLAUDE_SESSION_ID. Senza il filtro sull'agente risulterebbe sua.
        r = lancia(casa, 'verifica', 'db-140', '--agente', 'due', sessione='sessione-a')
        prova('sottoagente nella stessa sessione → 3', r.returncode, 3)
        prova('dice chi la tiene', 'uno' in r.stdout, True)
        prova('dice da quanto', 'iniziato' in r.stdout, True)

        # 7. l'altra macchina non può usarla
        r = lancia(casa, 'verifica', 'db-140', '--agente', 'uno',
                   sessione='sessione-a', macchina='altro-pc')
        prova('altra macchina → 3', r.returncode, 3)

        # 8. una chiave presa non blocca le altre
        r = lancia(casa, 'verifica', 'portali-140', sessione='sessione-b')
        prova('un\'altra risorsa resta libera', r.returncode, 0)

        # 9. tenuta da un altro, ma con un nome fuori elenco: vince il 3.
        #    Una serratura non deve mai rispondere «non esiste» mentre
        #    qualcuno ci sta lavorando dentro.
        #    ⚠ progetto diverso da quello della prova 3: `prendo` si ferma se
        #    sul progetto c'è già qualcuno, e la chiave non verrebbe ritirata.
        r = lancia(casa, 'prendo', 'Prova due', 'fuori elenco', '--risorse',
                   'coso-strano', '--agente', 'tre', sessione='sessione-c')
        prova('prendo di un nome fuori elenco riesce', r.returncode, 0)
        r = lancia(casa, 'verifica', 'coso-strano', '--agente', 'quattro',
                   sessione='sessione-d')
        prova('nome ignoto ma tenuto da un altro → 3 (non 2)', r.returncode, 3)

        # 10. verifica NON scrive niente, in nessuno dei tre esiti
        prima = impronta(casa)
        for args in (('verifica', 'db-140'), ('verifica', 'portali-140'),
                     ('verifica', 'risorsa-che-non-esiste')):
            lancia(casa, *args, sessione='sessione-e', agente='curioso')
        prova('verifica non scrive niente nel registro', impronta(casa), prima)

        # 11. `libera` non cambia esito: lo chiama già strumenti/mac.py
        r = lancia(casa, 'libera', 'risorsa-che-non-esiste', sessione='sessione-b')
        prova('libera su nome ignoto e libero resta 0', r.returncode, 0)
        r = lancia(casa, 'libera', 'db-140', '--agente', 'due', sessione='sessione-a')
        prova('libera su chiave di un altro resta 3', r.returncode, 3)

        # 12. restituita la chiave, la risorsa torna libera per tutti
        r = lancia(casa, 'finito', 'provato', '--agente', 'uno', sessione='sessione-a')
        prova('finito riesce', r.returncode, 0)
        r = lancia(casa, 'verifica', 'db-140', '--agente', 'due', sessione='sessione-b')
        prova('dopo finito la chiave è libera', r.returncode, 0)

        # 13. il gemello PowerShell non deve derivare
        prova_gemello_ps1()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FALLITE:
        print(f'\n🔴 {len(FALLITE)} prove fallite: ' + ', '.join(FALLITE))
        return 1
    print('\n✅ tutte le prove passate')
    return 0


if __name__ == '__main__':
    sys.exit(main())
