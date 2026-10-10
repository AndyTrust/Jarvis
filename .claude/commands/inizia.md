---
description: Domande di avvio e installazione guidata di Jarvis (in modalità piano, niente modifiche prima del sì)
---

Esegui la procedura «Prima apertura» descritta in `CLAUDE.md`, dall'inizio, anche se `~/.jarvis/installato.json` esiste già.

1. Entra in modalità piano (EnterPlanMode) e spiega che non modifichi niente finché l'utente non approva.
2. Se esiste già `~/.jarvis/risposte-avvio.json`, mostralo e chiedi quali risposte cambiare; altrimenti fai le domande di avvio
   una alla volta, nell'ordine di `CLAUDE.md`, proponendo il valore predefinito.
3. Scrivi le risposte in `~/.jarvis/risposte-avvio.json` (forma: `docs/risposte-avvio.esempio.json`), senza segreti.
4. Lancia `python3 strumenti/installa_guidata.py --prova`, presenta il piano (cosa installa, cosa scrive e dove, quali copie
   `.bak` fa) e chiedi l'approvazione con ExitPlanMode.
5. Dopo il sì: `python3 strumenti/installa_guidata.py`, poi `python3 strumenti/verifica_installazione.py`. Riferisci con
   l'uscita dei comandi cosa è fatto e cosa resta a mano.

$ARGUMENTS
