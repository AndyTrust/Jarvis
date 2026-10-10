# La barra e le spie

La barra in alto porta a undici sezioni. Ogni voce del menu ha un pallino colorato (la spia) prima del nome. Il calcolo delle spie sta tutto nella pagina (`spieSchede()` in `static/app.js`): il server non manda colori già pronti, manda solo i dati.

## I colori

- **Grigia**: il dato non c'è ancora (il server è appena partito, o è un server vecchio che non manda ancora quella informazione).
- **Verde**: tutto in ordine.
- **Gialla**: qualcosa chiede attenzione, non è grave.
- **Rossa**: qualcosa è fermo o rotto.
- **Un pallino che pulsa** (sulla scheda Chat): Jarvis sta rispondendo in quel momento.

## Le regole, scheda per scheda

- **Squadra**: pulsa se Jarvis sta lavorando (`claude_ora.lavorando`) o c'è un lavoro «in corso» o un agente attivo di una missione. Gialla se il portiere segnala una chiave MUTA o SCADUTA. Rossa se segnala una chiave FANTASMA o ABUSIVA. Verde altrimenti.
- **Missioni**: gialla se una missione è «in corso» o «in avvio». Gialla anche se una missione «attende conferma» o «attende istruzioni». Verde altrimenti.
- **Memoria**: rossa se un progetto è 🔴 nella sincronia (cartella o memoria mancante). Gialla se un progetto è 🟡 (c'è lavoro più recente dell'ultima nota di memoria) o il battito dei 15 minuti è fermo. Verde altrimenti.
- **Server**: rossa se un sito o un contenitore della VPS è giù. Gialla se disco o RAM superano l'85%. Verde altrimenti. Grigia se la VPS non è ancora stata letta.
- **Chat**: pulsa mentre Jarvis sta scrivendo una risposta.
- **Stato**: rossa se un raccoglitore del server (uno dei cicli che leggono i dati) è in errore. Verde altrimenti.

## «● live» e «○ sondaggio»

Accanto alla barra, prima del cerchietto di Jarvis, c'è una scritta piccola:

- **● live**: la pagina è collegata al flusso in tempo reale (`GET /api/flusso`, Server-Sent Events). Ogni volta che qualcosa cambia sul server, la pagina lo sa entro un istante, senza ricaricare.
- **○ sondaggio**: il flusso non è collegato (per esempio appena aperta la pagina, o dopo una caduta della connessione). La pagina allora richiede lo stato da sola ogni 15 secondi, finché il flusso non si riaggancia.

Il flusso manda un messaggio quando la versione dei dati sale, con l'elenco di quali dati sono cambiati (per esempio `["locale","lavori"]`), così la pagina aggiorna solo quello che serve. Ogni 15 secondi, anche senza niente di nuovo, il server manda un battito per tenere viva la connessione.

## Il cerchietto di Jarvis

Accanto all'orologio, il cerchietto con la «J» prende lo stesso colore e la stessa scritta della voce di Jarvis in Stato (spento, in ascolto, pensa, parla). È visibile da ogni pagina del pannello, non solo da Stato: un clic ci porta dritti in Stato.

## Dati vecchi

Se un riquadro non riesce a leggere i suoi dati da un po' (più di tre giri del suo intervallo normale, o dopo un errore), la pagina lo segna in grigio invece di mostrarlo come fresco. Serve a non far credere buono un numero che in realtà non si aggiorna più da tempo.
