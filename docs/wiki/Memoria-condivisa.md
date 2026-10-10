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
| `~/.claude/projects/*/*.jsonl` (le conversazioni) | no | grandi, scritte mentre lavori, possono contenere quello che incolli; nella memoria va il riassunto (`Sessioni/`, e nel diario quando la chat si archivia) |
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

## Lo stato e il diario si aggiornano da soli

Un solo gancio, `~/.claude/hooks/stato_avanzamento.py`, fa il giro meccanico: per lo spazio della cartella in cui
lavori (dai progetti di `command-center/spazi.json`) riscrive in `<memoria>/<spazio>/Stato.md`, tra i marcatori
`stato-auto`, FATTO / DA FARE / ERRORI di ogni progetto (da `.claude/memoria/MEMORIA.md`), i diari degli agenti, gli
errori ripetuti, i file toccati, l'ultimo commit e la data-ora; poi aggiunge al **diario del giorno**
`<memoria>/Diario/AAAA-MM-GG.md` un blocco «HH:MM · spazio / progetto · evento» con solo le voci nuove di oggi.
Se non c'è niente di nuovo non scrive (idempotente e muto). Le note scritte a mano fuori dai marcatori restano.

Quando parte, senza che tu faccia niente:

| Momento | Chi lo fa partire |
|---|---|
| fine di una risposta (al massimo ogni 10 minuti), compattazione, fine sessione | ganci `Stop`, `PreCompact`, `SessionEnd` di Claude Code |
| scrivi «ok», «perfetto», «va bene», «chiuso», «fatto», «salva» | gancio `UserPromptSubmit` `conferma_salva.py`: lancia il giro e chiede a Claude, nello stesso turno, il salvataggio con giudizio della skill `aggiorna-memoria` |
| ogni commit e ogni push di un progetto (e del repo di Jarvis) | ganci git `post-commit` e `pre-push` (`strumenti/ganci_git.py`, installati da `crea_progetto.py` e dall'installazione, senza toccare i tuoi) |
| aggiornamento del prodotto | comando `/aggiorna` |
| ogni volta che cambiano progetti, schede, diari o file caricati | il Command Center, se è acceso (stessa funzione) |

A mano: `python3 ~/.claude/hooks/stato_avanzamento.py --giro --evento <nome> --cwd <cartella>`.
Il giudizio (cosa è un errore, cosa è finito) lo salva la skill `aggiorna-memoria`:
`python3 ~/.claude/skills/aggiorna-memoria/strumenti/brain.py . --salva --errore "..." --completato "..." --dafare "..."`.

## Pulizia e unione di quello che Claude Code salva da solo

`strumenti/pulisci_claude.py` (ogni giorno alle 6:20 con launchd `com.jarvis.pulizia-claude`, e dentro `/aggiorna`):

| Cartella | Regola |
|---|---|
| `~/.claude/projects/*/memory` | mai cancellata: si unisce alla memoria condivisa (`collega_memoria.py --solo-progetti`, collegamento, i file diversi restano tutti e due) |
| `~/.claude/projects/*/*.jsonl` più vecchie di 30 giorni (`--giorni-chat`) | riassunto nel diario del giorno della chat (sezione «Chat archiviate»: cartella, prima richiesta, ultima risposta), poi archivio compresso in `~/.jarvis/archivio-chat/` controllato, solo dopo esce da `~/.claude`; archivi tenuti 180 giorni |
| `shell-snapshots`, `session-env` (3 giorni), `debug`, `paste-cache` (7), `cache/pdf-testo` (14), `file-history`, `todos` (30) | si svuotano oltre la soglia |
| resto della cache, `settings.json`, `.credentials.json`, `agents/`, `skills/`, `hooks/`, `commands/`, `plugins/` | mai toccati |
| sessioni aperte, file toccati nelle ultime 24 ore | mai toccati |

`python3 strumenti/pulisci_claude.py --prova` dice cosa farebbe (è anche il comportamento senza opzioni);
`--applica` lo fa. I ganci di `settings.json` doppi o che puntano a file che non esistono si segnalano soltanto.

## Togliere i collegamenti

Vedi [Disinstallare](Disinstallare).
