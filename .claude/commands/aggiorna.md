---
description: Aggiorna Jarvis all'ultima versione senza toccare i tuoi file (dopo git pull)
---

1. Mostra la versione attuale (`cat VERSIONE`) e lo stato di git (`git status --short`, `git log -1 --oneline`).
   Se ci sono modifiche locali a file tracciati, fermati e chiedi cosa farne: non scartarle.
2. `git pull --ff-only`. Se non è un avanzamento veloce, fermati e spiega.
3. `python3 strumenti/installa_guidata.py --prova` e riassumi cosa cambierebbe (i tuoi file restano: profilo, configurazione,
   spazi, memoria sono fuori da git; i file di `~/.claude` diversi dai tuoi vanno accanto come `.nuovo-AAAAMMGG`).
4. Dopo il sì: `python3 strumenti/installa_guidata.py`, poi `python3 strumenti/verifica_installazione.py`.
5. Salvataggio automatico dell'aggiornamento: `python3 ~/.claude/hooks/stato_avanzamento.py --giro --evento aggiornamento --cwd "$PWD"`
   e pulizia di quello che Claude Code salva da solo: `python3 strumenti/pulisci_claude.py --applica` (prima `--prova`).
   Poi la skill `aggiorna-memoria` (giro standard) per il giudizio.
6. Riferisci versione prima e dopo, l'esito della verifica e cosa ha fatto la pulizia.
