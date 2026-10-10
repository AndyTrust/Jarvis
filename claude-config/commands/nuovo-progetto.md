---
description: Crea un progetto nuovo con il suo capogruppo (cartella, memoria, Stato.md, voce in spazi.json)
argument-hint: <nome del progetto> [spazio] [cartella]
---

Usa la skill `nuovo-progetto`, punto 2, per il progetto: $ARGUMENTS

`R` è la chiave `repo` di `~/.jarvis/percorsi.json` (di solito `~/Jarvis`). Prima controlla con
`python3 R/strumenti/crea_progetto.py --elenco` che non esista già. Mostra il piano con `--prova` (o crea subito se in
`~/.jarvis/risposte-avvio.json` c'è `"creazione": "automatica"`), poi crea e verifica con `--elenco`.
