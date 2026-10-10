# Sicurezza

Le regole di sicurezza che valgono per il Command Center e per tutto quello che Jarvis fa intorno.

## Il pannello resta sul Mac

Il Command Center gira solo su `127.0.0.1:7777`: da fuori dal Mac non è raggiungibile. Ogni richiesta all'API vuole il token della pagina (`X-Token`), che cambia a ogni avvio del server. Il flusso in tempo reale (`/api/flusso`) accetta il token anche in query string, perché `EventSource` non manda intestazioni personalizzate, ma solo su quell'indirizzo.

## La guardia dei comandi

`~/.claude/hooks/guardia_comandi.py` è un hook che si attiva prima di ogni comando Bash (`PreToolUse`) e blocca, prima che partano, i comandi irreversibili: `rm -rf` su home o su cartelle principali, push forzati, `reset --hard`, riscrittura della storia git, `DROP`, `TRUNCATE`, `DELETE` senza `WHERE`, `docker prune`, i volumi. Vale anche quando la chat gira in modo «lavoro» con `--dangerously-skip-permissions` (vedi [Chat](Chat)): il bypass dei permessi di Claude Code non spegne questo hook. Se blocca qualcosa, si chiede all'utente; solo dopo il suo sì si rilancia lo stesso comando con `JARVIS_CONFERMATO=1` davanti. Le prove dell'hook si vedono con `python3 ~/.claude/hooks/guardia_comandi.py --prova`.

## Le missioni: cosa chiede conferma

`command-center/conferme.py` decide, comando per comando, cosa una missione in modalità «lavoro» può fare da sola e cosa deve fermarsi a chiedere all'utente. Passano da sole le letture, le ricerche, i lanci di agenti e le modifiche ai file dentro il progetto e i vault. Chiedono sempre conferma: cancellare, spostare, comandi di sistema (`sudo`, `kill`, `crontab`…), installare pacchetti, pubblicare o fare deploy, scrivere sulla VPS o in un database, mandare messaggi, toccare file delicati (`.env*`, `.ssh/`, `settings.local.json`, `CLAUDE.md`, `.git/`, chiavi e certificati), scrivere fuori dalle cartelle del progetto. In modalità «lettura» tutto questo si nega senza nemmeno chiedere, insieme a ogni comando che scriverebbe qualcosa in locale.

## Un segreto non esce mai dal Mac


## Non si vende e non si distribuisce codice di altri

Vale anche per codice nostro che lo importa. Il repository `Jarvis-Privato` — quello di cui questa guida è la wiki — è privato e contiene i dati veri dell'utente: macchine, numeri, chiavi di configurazione (mai i segreti veri, che restano fuori). Il prodotto da vendere, Jarvis Business, vive in un repository separato, senza nessun dato dell'utente.

## Conferma prima dell'irreversibile

Cancellare, pubblicare, fare deploy, scrivere in produzione o sulla VPS, mandare messaggi: si dice cosa si sta per fare e si aspetta il sì dell'utente, in chat o nel pannello (le richieste di conferma di una missione, in [Missioni](Missioni)). Tutto il resto si esegue senza chiedere.

## VPS: tempo assoluto

