# Come parlano gli agenti: serietà e umorismo

*Scritta il 2026-09-29.* Ogni agente, e Jarvis, ha tre campi nel profilo (`.claude/agents/<nome>.md`): `tono`, `serieta` e `umorismo`. Le due manopole vanno da 0 a 3 e sono indipendenti: un agente può essere rigoroso e con una battuta ogni tanto.

| Valore | Serietà | Umorismo |
|---|---|---|
| 0 | leggero | nessuno |
| 1 | pacato | misurato |
| 2 | professionale | vivace |
| 3 | rigoroso | sfacciato |

Si cambiano dalla scheda dell'agente sulla lavagna (tasto destro), da «Nuovo agente» e «Nuovo gruppo», e per Jarvis dalla scheda della nota «Jarvis — orchestratore» (profilo in `profilo-jarvis.md`, letto dal gancio di apertura `sessioni.py`). Il Command Center scrive in ogni profilo il blocco `<!-- come-parla:inizio -->` con il testo che l'agente legge davvero. `strumenti/imposta_come_parla.py --applica` riempie i valori mancanti per ruolo.
