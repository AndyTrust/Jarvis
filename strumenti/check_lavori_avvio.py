#!/usr/bin/env python3
"""
Controlla all'avvio se Jarvis è libero di lavorare, o se un'altra sessione è dentro.
Se libero, lo prende automaticamente. Se occupato, avvisa e aspetta il rilascio.
"""
import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

# Path al registro dei lavori (su OneDrive, condiviso)
LAVORI_DB = Path.home() / '.ai-memory' / 'global' / 'lavori' / 'registry.json'

def leggi_lavori():
    if not LAVORI_DB.exists():
        return {}
    try:
        with open(LAVORI_DB, 'r') as f:
            return json.load(f)
    except:
        return {}

def prendi_jarvis():
    """Registra che questa sessione sta lavorando su Jarvis."""
    cmd = [
        'python3',
        str(Path.home() / 'Jarvis' / 'strumenti' / 'lavori.py'),
        'prendo',
        'Jarvis',
        'chat-master',
        '--agente', 'jarvis-chat-master'
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=5)
        return True
    except:
        return False

def chi_sta_lavorando():
    """Controlla chi è dentro Jarvis."""
    lavori = leggi_lavori()
    for progetto, info in lavori.items():
        if 'jarvis' in progetto.lower():
            if info.get('stato') == 'working':
                return info
    return None

def main():
    occupato = chi_sta_lavorando()
    if occupato:
        agente = occupato.get('agente', 'sconosciuto')
        inizio = occupato.get('inizio', '?')
        print(f"⏳ Jarvis è occupato da {agente} dal {inizio}", file=sys.stderr)
        print(f"  Attendo il rilascio...", file=sys.stderr)
        # Continua comunque, non blocca
        return 0

    # Libero, me lo prendo
    if prendi_jarvis():
        print(f"✓ Jarvis pronto (registrato)", file=sys.stderr)
        return 0
    else:
        print(f"⚠️  Non ho potuto registrare il lavoro su Jarvis", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
