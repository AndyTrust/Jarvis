---
description: Crea uno specialista in un progetto, con missione, modello, strumenti, limiti e diario
argument-hint: <progetto> <ruolo> [cosa deve fare]
---

Usa la skill `nuovo-progetto`, punto 3, per: $ARGUMENTS

`R` è la chiave `repo` di `~/.jarvis/percorsi.json` (di solito `~/Jarvis`). Se il progetto non esiste, crealo prima
(punto 2). Ricava una missione chiara (cosa fa, su quali file, cosa consegna) e il modello giusto (haiku esegue,
sonnet ricerca/testi/verifica, opus solo programmazione). Lancia
`python3 R/strumenti/crea_agente.py "<progetto>" "<ruolo>" --missione "…" --prova`, poi senza `--prova`, e verifica che
la scheda e il diario esistano.
