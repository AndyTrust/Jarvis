# Le cinque skill prese da Superpowers

*Copiate il 2026-09-12 da superpowers 6.3.0 (github.com/obra/superpowers, MIT,
Jesse Vincent). Il plugin resta spento in `~/.claude/settings.json`.*

Il plugin intero costa 840 token a ogni apertura, `/clear` e compattazione: il
suo hook `SessionStart` inietta per intero `using-superpowers`, che impone di
invocare una skill prima di qualunque risposta. Queste cinque copie non hanno
hook: costano zero finché non le chiami.

| Skill | A cosa serve |
|---|---|
| `brainstorming` | il cancello: niente codice prima dell'ok sul disegno |
| `writing-plans` | la specifica diventa task piccoli, con i file e le verifiche |
| `systematic-debugging` | nessuna fix senza causa radice |
| `verification-before-completion` | nessun «fatto» senza il comando che lo prova |
| `writing-skills` | scrivere e correggere le skill (RED-GREEN-REFACTOR) |

## Cosa è stato tolto e perché

- **`brainstorming/scripts/` e `visual-companion.md`.** La companion visuale
  apre un server locale e carica il logo da `primeradiant.com` passando la
  versione di Superpowers: è la telemetria dichiarata nel loro README. Via i
  file, via la sezione che li richiamava. Al suo posto la riga sullo schizzo
  ASCII da approvare, che è già la regola in `~/.claude/CLAUDE.md`.
- **I file di sviluppo di `systematic-debugging`** (`CREATION-LOG.md`,
  `test-pressure-*.md`, `test-academic.md`): servivano a chi l'ha scritta.
- **I rimandi alle nove skill non copiate** (`test-driven-development`,
  `using-git-worktrees`, `subagent-driven-development`, `executing-plans`,
  `finishing-a-development-branch`, `requesting-code-review`,
  `receiving-code-review`, `dispatching-parallel-agents`,
  `using-superpowers`). Chiedono git, una suite di test verde e i worktree.
  Ogni `superpowers:x` è stato riscritto in istruzione autonoma, così nessuna
  delle cinque manda a cercare una skill che non c'è.
- **Le descrizioni sono in italiano** e contengono le frasi con cui le chiami
  davvero («non funziona», «fammi un piano», «è a posto?»). Erano in inglese e
  non si attivavano mai in una conversazione italiana.

## Per aggiornarle

Non c'è aggiornamento automatico: sono copie. Si riscarica il repo, si rifanno
le stesse quattro potature. Le modifiche stanno tutte qui sopra.
