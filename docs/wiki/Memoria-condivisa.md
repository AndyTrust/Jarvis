# Memoria condivisa

Una sola memoria per Claude Code, Jarvis e gli altri programmi di AI che usi. La crea e la collega
`strumenti/collega_memoria.py` (lo lancia l'installazione guidata).

## Dove sta

Il percorso è in `~/.jarvis/percorsi.json` (chiave `memoria`). Predefinito `~/Jarvis-Memoria`; puoi scegliere un vault
Obsidian esistente, una cartella in iCloud Drive o in OneDrive. Una cartella sincronizzata porta le note sugli altri
computer; un disco locale è più veloce e non ha conflitti.

```
<memoria>/
├── Comune/            Memoria.md (porta d'ingresso), Profilo.md, Regole.md, CLAUDE.md (sorgente unica)
├── <spazio>/Stato.md  FATTO / DA FARE / ERRORI / data-ora, scritto dai ganci
├── Diario/  Report/  Sessioni/
└── Claude/
    ├── projects/<progetto>/memory   la memoria automatica di Claude Code
    └── cache/pdf-testo              il testo dei PDF già letti
```

## Cosa viene collegato, e cosa no

| Cartella di Claude Code | Collegata? | Perché |
|---|---|---|
| `~/.claude/projects/*/memory` | sì, collegamento simbolico verso `<memoria>/Claude/projects/<progetto>/memory` | note durature in Markdown: servono a tutti |
| `~/.claude/CLAUDE.md` | sì, diventa un collegamento a `<memoria>/Comune/CLAUDE.md` | una sola fonte di istruzioni globali |
| `~/.claude/cache/pdf-testo` | sì | testo estratto dai PDF dal gancio `pdf_a_testo.py`, riutilizzabile |
| resto di `~/.claude/cache` (changelog, catalogo dei modelli, issue) | no | file interni di Claude Code, li riscrive lui |
| `~/.claude/projects/*/*.jsonl` (le conversazioni) | no | grandi, scritte mentre lavori, possono contenere quello che incolli; nella memoria va il riassunto in `Sessioni/` |
| `paste-cache`, `file-history`, `session-env`, `shell-snapshots`, `debug`, `sessions`, `todos` | no | transitori: su una cartella sincronizzata farebbero conflitti |
| `settings.json`, `.credentials.json`, `.claude.json` | no | impostazioni e accessi del singolo Mac |

## Come unisce senza perdere niente

- Se la cartella di destinazione non c'è: copia i file, sposta l'originale in `memory.bak-AAAAMMGG`, crea il collegamento.
- Se c'è già e ha contenuto: copia solo i file che mancano; quelli uguali li salta; quelli diversi li copia accanto con
  il suffisso `.da-<nome del Mac>-AAAAMMGG` e li elenca. L'originale resta in `.bak`.
- Non cancella mai: ogni passo si può disfare rimettendo la cartella `.bak` al suo posto.
- Provalo prima: `python3 strumenti/collega_memoria.py` (senza `--applica` non scrive niente).

## Gli altri harness

| Programma | File che legge | Cosa scrive l'installatore |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | collegamento alla sorgente unica |
| Codex | `~/.codex/AGENTS.md` | aggiunge un blocco tra marcatori che rimanda alla memoria (copia prima) |
| Gemini CLI | `~/.gemini/GEMINI.md` | come sopra |
| Cursor, Grok, altri | impostazioni dell'app | `<memoria>/Comune/ISTRUZIONI-HARNESS.md` da incollare (Cursor: Settings → Rules) |

## Lo stato dei progetti si aggiorna da solo

Il gancio `~/.claude/hooks/stato_avanzamento.py` scatta su `Stop` (al massimo ogni 10 minuti per sessione), `PreCompact`
e `SessionEnd`. Capisce lo spazio dalla cartella in cui lavori (`spazi` in `percorsi.json`) e riscrive in
`<memoria>/<spazio>/Stato.md`, tra i marcatori `stato-auto`, per ogni progetto: FATTO, DA FARE ed ERRORI presi dalla
memoria del progetto (`.claude/memoria/MEMORIA.md`), i file toccati nella sessione, l'ultimo commit e la data-ora.
Le note scritte a mano fuori dai marcatori restano. Aggiunge una riga in `Sessioni/AAAA-MM.md`. A fine sessione
collega anche le memorie di progetto nuove. Non ferma mai Claude: gli errori vanno in `~/.jarvis/ganci.log`.

Il giudizio (cosa è un errore, cosa è finito) lo salva la skill `aggiorna-memoria`:
`python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva --errore "..." --completato "..." --dafare "..."`.

## Togliere i collegamenti

Vedi [Disinstallare](Disinstallare).
