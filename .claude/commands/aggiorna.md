---
description: Aggiorna Jarvis all'ultima versione senza toccare i tuoi file (dopo git pull)
---

1. Mostra la versione attuale (`cat VERSIONE`) e lo stato di git (`git status --short`, `git log -1 --oneline`).
   Se ci sono modifiche locali a file tracciati, fermati e chiedi cosa farne: non scartarle.
2. `git pull --ff-only`. Se non è un avanzamento veloce, fermati e spiega.
3. `python3 strumenti/installa_guidata.py --prova` e riassumi cosa cambierebbe (i tuoi file restano: profilo, configurazione,
   spazi, memoria sono fuori da git; i file di `~/.claude` diversi dai tuoi vanno accanto come `.nuovo-AAAAMMGG`).
4. Dopo il sì: `python3 strumenti/installa_guidata.py`, poi `python3 strumenti/verifica_installazione.py`.
5. Riferisci versione prima e dopo e l'esito della verifica.
