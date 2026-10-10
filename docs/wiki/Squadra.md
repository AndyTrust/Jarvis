# Squadra

Prima si chiamava «Catena · Lavori». Rifatta il 26/09/2026: tutto quello che dice chi lavora sta qui, in un ordine solo.


## Claude adesso

Dice se una sessione di Claude Code sta lavorando in questo momento (letto da `backtalk/.jarvis_status`, scritto dagli hook `jarvis_status.py`), su cosa, e mostra la catena degli agenti coinvolti. In fondo, una riga sola porta alla sincronia (il dettaglio intero sta in [Memoria](Memoria), unica fonte).

Due bottoni: «chi lavora e su cosa?» e «verifica la sincronia».

## Chiavi e da guardare


## Lavori

La lista dei lavori lanciati dal pannello — chat, verifiche, agenti, missioni — con filtri («Tutti», «In corso», «Finiti», «Errori») e una casella di ricerca su titolo, agente, richiesta. Un clic su un lavoro apre il suo dettaglio a destra:

- la richiesta intera (dentro un riquadro a comparsa, per non occupare spazio);
- il risultato, con «a capo» spuntabile;
- chi l'ha fatto e quanto ci ha messo;
- le azioni: copiare il risultato, rilanciare lo stesso lavoro, riaprirlo in Chat nello stesso filo, toglierlo dalla lista.

**Riaprire in Chat** riprende la stessa sessione (con `--resume`) mettendo in pagina la richiesta e la risposta già scambiate, per continuare da lì — è l'unico punto del pannello dove la chat non riparte da zero.

**Pulisci i chiusi** toglie dalla lista i lavori già finiti: il file di log resta comunque in `command-center/lavori/`, si pulisce solo la vista.

## Agenti per spazio

Una tendina per spazio, una card per progetto dentro, con il capogruppo in cima alla sua squadra. Se uno spazio ha un solo progetto con lo stesso nome il titolo compare una volta sola, non due. Con zero progetti la sezione dice «Nessun progetto ancora: di' a Jarvis di crearne uno». Ogni card ha «📎 Progetto e file»: nome, descrizione, file caricati in `File/`, indice e archivio del progetto.

Un clic su un agente apre la chat con lui; un doppio clic apre la sua scheda (descrizione, modello, strumenti, con chi comunica). La casella di ricerca filtra per nome o compito. «Apri tutti» / «Chiudi tutti» aprono o chiudono tutte le tendine insieme.

## Verifiche e agenti dei progetti

Gli script di controllo pronti (per esempio l'autocontrollo di Jarvis, che scrive `prove/RAPPORTO.md`) e un modulo per lanciare un agente di progetto con una richiesta a piacere, o vuota per la sua verifica di routine. Questi agenti lavorano sempre in sola lettura, qualunque sia il modo scelto in Chat.

## Sessioni Claude aperte adesso

L'elenco dei processi `claude` in esecuzione sul Mac in questo momento, con pid, se lavorano davvero o sono ferme, da quando, il processore consumato, in quale progetto girano. Stessa fonte di `strumenti/agenti.py`.
