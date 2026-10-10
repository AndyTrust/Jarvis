# Progetti e agenti

Jarvis parte vuoto: dopo l'installazione non c'è nessun progetto, nessuno spazio, nessun capogruppo e nessuno
specialista. Ci sono solo l'assistente, i due agenti di casa (`esecutore`, `ricercatore-web`), i ganci, le skill
e il Command Center con le pagine vuote («Nessun progetto ancora: di' a Jarvis di crearne uno»).
Progetti e agenti nascono dalle tue richieste, uno alla volta.

## Una sola fonte

| Cosa | Dove |
|---|---|
| Elenco di spazi e progetti | `~/Jarvis/command-center/spazi.json` |
| Schede degli agenti | `<cartella del progetto>/.claude/agents/<nome>.md` |
| Diari degli agenti | `<cartella del progetto>/.claude/memoria/agenti/<nome>.md` |
| File che carichi | `<cartella del progetto>/File/`, elencati in `<cartella del progetto>/Indice-file.md` |
| Stato del progetto | `<memoria>/<spazio>/Stato.md` (con `<spazio>.md`, `Decisioni.md`, `Report/`) |
| Diario del giorno | `<memoria>/Diario/AAAA-MM-GG.md` |

Tutto il resto (lavagna, menu agenti, pagine del Command Center, riunioni, giro notturno, `Stato.md`) si rilegge da
qui. Il Command Center guarda questi file ogni 2 secondi: un progetto o un agente creato dalla riga di comando o dalla
chat compare sulla lavagna e nel menu da solo, senza ricaricare (nella prova: tra 0,3 e 2 secondi).

`<memoria>` è la chiave `memoria` di `~/.jarvis/percorsi.json` (predefinita `~/Jarvis-Memoria`). La cartella dei
progetti nuovi è la chiave `progetti` (predefinita `~/Progetti`).

## Come nasce un progetto

Lo dici a parole («apri il progetto Sito Vetrina», «mi segui anche il ricettario?») o con `/nuovo-progetto <nome>`.
L'assistente controlla che non esista (`crea_progetto.py --elenco`), la prima volta ti mostra il piano e poi lo crea:

```bash
python3 strumenti/crea_progetto.py "Sito Vetrina" --descrizione "sito di presentazione" --prova   # cosa farebbe
python3 strumenti/crea_progetto.py "Sito Vetrina" --descrizione "sito di presentazione"
python3 strumenti/crea_progetto.py "Ricettario" --spazio "Cucina" --cartella ~/Lavori/Ricette     # cartella che c'è già
```

Cosa crea, solo se manca (rilanciarlo non rifà niente; ogni file cambiato ha una copia `.bak-AAAAMMGG-HHMMSS`):
- la voce in `spazi.json` (spazio nuovo col nome del progetto, se non dici `--spazio`);
- `<memoria>/<spazio>/` con `<spazio>.md`, `Stato.md` (FATTO / DA FARE / ERRORI, data e ora), `Decisioni.md`, `Report/`;
- la cartella del progetto con `File/`, `Indice-file.md`, `.claude/memoria/MEMORIA.md`, `.claude/memoria/agenti/`;
- il capogruppo `.claude/agents/<id>-ceo.md`, dal modello unico, con il suo diario;
- se la cartella è un repo git, i ganci `post-commit` e `pre-push` che salvano lo stato (un gancio tuo resta: il
  blocco di Jarvis va in testa e non cambia l'esito).

Se in `~/.jarvis/risposte-avvio.json` c'è `"creazione": "automatica"`, l'assistente crea senza mostrare il piano.
Lo stesso si fa dalla lavagna con «＋ Nuovo gruppo»: usa lo stesso codice.

## Come nasce un agente

Ogni progetto ha sempre un capogruppo. Gli specialisti li crea lui, uno alla volta, quando serve una competenza
(o tu: «mi serve qualcuno che scriva i testi», `/nuovo-agente "Sito Vetrina" copywriter`):

```bash
python3 strumenti/crea_agente.py "Sito Vetrina" copywriter \
        --missione "scrive i testi delle pagine partendo dai file in File/" \
        --modello sonnet --strumenti "Read, Grep, Glob" --limiti "non pubblica niente" --prova
```

Regole controllate dallo script: nessun agente senza una missione chiara (almeno 25 caratteri, diversa dal ruolo);
haiku esegue comandi già scritti, sonnet ricerca, scrive e verifica (predefinito), opus solo per programmare
(serve `--programma` o una missione che parla di codice); un progetto senza capogruppo si rifiuta.

La scheda ha missione, modello, strumenti, limiti, memoria e il diario obbligatorio: l'agente lo legge all'avvio
(`quaderno.py leggi <nome>`) e prima di chiudere scrive FATTO, DA FARE ed ERRORI COMMESSI DA NON RIPETERE
(`quaderno.py scrivi <nome> --fatto "…" --da_fare "…" --errore "…"`). I diari finiscono da soli nello `Stato.md`
dello spazio; un errore scritto in due giorni diversi compare come «⚠ ERRORI RIPETUTI (da segnalare al proprietario)».

## I file del progetto

Carichi i file dalla card del progetto («📎 Progetto e file» nella pagina Squadra) oppure li copi a mano in
`<cartella>/File/`. `Indice-file.md` si riscrive da solo (nome, data di arrivo, cosa è, peso) e il capogruppo lo legge
all'inizio di ogni lavoro.

## Cambiare, togliere, archiviare

| Cosa | Dalla riga di comando | Dal Command Center |
|---|---|---|
| Missione, modello, strumenti, limiti di un agente | `crea_agente.py "<progetto>" <nome> --modifica --missione "…"` | scheda dell'agente (doppio clic) |
| Diario di un agente | `quaderno.py scrivi <nome> …` | scheda dell'agente, «Modifica il diario» |
| Togliere uno specialista | `crea_agente.py "<progetto>" <nome> --togli` (va in `.claude/agents/_archivio/`) | scheda, «Togli (archivia)» |
| Nome e descrizione del progetto | `crea_progetto.py --rinomina <id> "<nome>"` | «📎 Progetto e file» |
| Spostare la cartella | `crea_progetto.py --sposta <id> <cartella nuova>` | — |
| Archiviare il progetto | `crea_progetto.py --archivia <id>` (esce da `spazi.json`, i file restano) | «📎 Progetto e file», «Archivia» |
| Riprenderlo | `crea_progetto.py --ripristina <id>` | — |

Il capogruppo non si toglie: si archivia il progetto. Cancellare davvero una cartella resta una scelta tua, a mano.

## Riunioni e giro notturno

Ogni progetto con capogruppo è un gruppo della riunione giornaliera (`python3 strumenti/riunione.py <id> prepara`),
con capogruppo, specialisti, `Stato.md` e indice dei file come fonti. Il giro notturno dei diari
(`strumenti/giro_apprendimento.py`) lavora sugli stessi progetti. Senza progetti non fanno niente e non danno errori.
