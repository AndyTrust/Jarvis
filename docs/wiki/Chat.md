# Chat

La scheda che si apre per prima. È la conversazione con Jarvis (o con un altro agente, scelto dalla colonna di sinistra) dentro il pannello.



## Come funziona

Ogni messaggio va al server (`POST /api/azione`, tipo «chiedi») e diventa un lavoro del pannello (si vede anche in Lavori). Il server lancia il motore scelto (vedi «Motori» qui sotto) nella cartella di Jarvis, o in quella del progetto se chatti con un agente. Una conversazione è un filo: la prima domanda apre la sessione, le altre la riprendono, così il motore ricorda quello che vi siete detti. La pagina legge la risposta finché il lavoro non è chiuso.

## Motori

*Dal 26/09/2026 sera: prima il selettore c'era, ma rispondeva sempre Claude Code.*

Nella colonna di sinistra, sotto «Motore», scegli chi risponde: **Claude Code**, **Gemini**, **Codex** o **Cursor**. La scelta sta in un solo file (`~/.claude/skills/aggiorna-memoria/motore_attivo.json`), lo stesso che usa la bolla del widget sul desktop. La testa della chat dice quale motore risponderà; sotto le risposte di un motore diverso da Claude c'è «via Gemini», «via Codex»…

Jarvis resta lo stesso: cambia il motore, non la memoria. Ogni motore legge il suo file di istruzioni nella cartella `~/Jarvis`, e tutti rimandano alle stesse regole e allo stesso vault:

| Motore | Legge | Comando lanciato | Modo lavoro | Modo lettura |
|---|---|---|---|---|
| Claude Code | `CLAUDE.md` | `claude -p … --output-format json` | `--dangerously-skip-permissions`, con la guardia dei comandi | `--permission-mode plan` |
| Gemini | `GEMINI.md` (importa `AGENTS.md`) | `gemini -p … --output-format json` | `--approval-mode yolo --sandbox` | `--approval-mode plan` |
| Codex | `AGENTS.md` | `codex exec --json …` | sandbox `workspace-write` | sandbox `read-only` |
| Cursor | `AGENTS.md` | `cursor-agent -p … --output-format json` | `--force --sandbox enabled` | `--mode plan` |

Da sapere:

- **La guardia dei comandi vale solo per Claude Code** (è un suo hook). Gli altri motori in modo lavoro stanno nel sandbox del loro programma: scrivono solo nella cartella di lavoro. `AGENTS.md` dice loro di non fare niente di irreversibile senza il tuo sì.
- **Gli agenti sono gli stessi profili.** Con Claude il profilo parte con `--agent`; con gli altri il testo comincia con «Agisci come l'agente X: segui il profilo in …».
- **Cambiare motore a metà di un filo** apre una sessione nuova per quel motore: la memoria del vault c'è, la conversazione di prima no. Se torni al motore di prima, riprende la sua.
- **Un motore senza login è spento** nel selettore (passaci sopra: il motivo è nel suggerimento) e una domanda mandata a lui torna con l'errore, senza cambiare motore. Per collegarlo: Claude `claude` poi `/login`; Codex `codex login`; Cursor `cursor-agent login`.
- **Gemini**: il login Google del programma non è più accettato da Google per gli account personali. Il pannello usa la chiave di Google AI Studio che sta in `~/.env.jarvis` (`GEMINI_API_KEY`, o `GOOGLE_AI_STUDIO_KEY`), senza toccare le impostazioni di Gemini sul Mac.

## Modo lavoro o modo lettura

In alto alla chat c'è l'interruttore **lavoro / lettura**:

- **lavoro** (l'impostazione di partenza, decisione dell'utente del 26/09/2026): Claude Code parte con `--dangerously-skip-permissions`, cioè lavora davvero — scrive file, lancia comandi — senza fermarsi a ogni passo a chiedere il permesso di sistema. La guardia dei comandi (`~/.claude/hooks/guardia_comandi.py`) resta accesa comunque: blocca da sola `rm -rf` pericolosi, push forzati, `reset --hard`, DROP e simili, anche in questo modo.
- **lettura**: Claude Code parte con `--permission-mode plan`, cioè legge e propone, non scrive niente.

Il modo si cambia con un clic e si salva in `command-center/configurazione.json` (`modo_chat`): vale per tutte le richieste della chat finché non lo si cambia di nuovo. Le missioni hanno una loro modalità separata (vedi [Missioni](Missioni)); gli agenti del CRM e i comandi rapidi restano sempre in sola lettura, qualunque sia l'interruttore della chat. La sentinella non usa più nessun modello (dal 26/09/2026 17:35): pulisce e scrive il rapporto in Python.

## I comandi rapidi

Sopra la casella di testo ci sono quattro bottoni con una domanda già scritta:

- **/memoria** — cerca nella memoria del vault
- **/brain** — a che punto è il progetto
- **/lavori** — chi sta lavorando adesso
- **/verifica** — quadro di sincronia di tutti i progetti

Un clic li manda così come sono; si può anche scrivere `/` nella casella per vedere i suggerimenti: sotto i quattro diretti compare l'elenco delle skill e dei comandi di Claude Code disponibili (nell'esempio di questa guida, venti), ognuno con una riga di descrizione.

## Il contesto del box

Molti riquadri delle altre pagine (Stato, Squadra, Scadenze, Server, Telefono, Tecnico…) hanno un bottone **«Chiedi a Jarvis: …»**. Cliccandolo, il pannello allega automaticamente in coda al messaggio l'ultimo dato che quel riquadro sta mostrando: un blocco con il nome del box, la data e l'ora del Mac, e i dati in JSON compatto (fino a 4000 caratteri). Così non serve copiare a mano numeri o righe di log: Jarvis li ha già.

## Terminale accanto alla chat


## Ricominciare

**Ricomincia** svuota la conversazione visualizzata con lo stesso interlocutore (Jarvis o un agente), senza toccare i lavori già registrati in [Squadra](Squadra).

## Chattare con un agente invece che con Jarvis

Dalla colonna di sinistra (l'elenco degli agenti per spazio) un clic su un agente apre la chat con lui: il nome e la cartella in testa alla chat cambiano di conseguenza. Un doppio clic apre invece la sua scheda (descrizione, modello, strumenti — vedi [La catena degli agenti](La-catena-degli-agenti)).
