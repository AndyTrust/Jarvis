# Missioni

Una missione è un obiettivo affidato a uno spazio (Azienda Uno, Azienda Due, Vita personale…) e a uno o più dei suoi progetti. Dal 23/09/2026 una missione è un solo processo: dentro gira un orchestratore che lancia gli esperti dei progetti scelti come sottoagenti dello stesso processo, in parallelo fino a un tetto scelto, e poi il capogruppo verifica il lavoro fatto.


## Prima era diverso

Fino al 23/09/2026 ogni progetto apriva un proprio processo, con il capogruppo in cima: con più lavori insieme si aprivano tante finestre e non reggeva. Ora è un processo solo (`missione.py`), lanciato dal Mac con il Python di `backtalk` (serve `claude_agent_sdk`).

## Come si affida una missione

1. Si sceglie lo **spazio** da un menu; i progetti di quello spazio compaiono di fianco (vengono da `spazi.json`).
2. Si scrive l'**obiettivo** in poche righe, per esempio «controlla che settembre sia tutto caricato e dimmi cosa manca».
3. Si sceglie quanti **esperti in parallelo** al massimo (da 1 a 10, 5 di default).
4. Si sceglie la **modalità**:
   - **lettura**: nessuno modifica niente, si scrive solo il report finale.
   - **lavoro**: le modifiche ai file partono davvero, ma tutto quello che `conferme.py` giudica irreversibile — cancellare, spostare, pubblicare, fare deploy, scrivere sulla VPS o in un database, mandare messaggi, installare qualcosa, toccare segreti o regole, scrivere fuori dal progetto — si ferma e aspetta il Sì dell'utente nel pannello.
5. Si clicca **Affida**.

Il server crea una cartella per la missione (`command-center/missioni/<data>_<ora>/`), scrive `missione.json` e lancia il processo. Ogni cosa che l'orchestratore o gli esperti dicono e fanno finisce in `registro.log`; l'albero degli agenti, con lo stato e l'esito di ognuno, sta in `agenti.json`.

## Cosa succede durante

- Ogni sottoagente passa da un controllo (`can_use_tool`) prima di ogni strumento: in lettura si nega senza chiedere tutto quello che scriverebbe (tranne il report della missione e la cartella della missione stessa); in lavoro si chiede solo l'irreversibile.
- Il tetto al parallelo è vero: se ci sono già N esperti al lavoro, un nuovo lancio aspetta che uno finisca.
- Le **conferme** aperte compaiono nella scheda della missione, con il comando esatto sotto gli occhi: un Sì o un No scrive la risposta e l'orchestratore riprende. **Nessuna risposta entro 30 minuti vale come un No.**
- Si può mandare un'**istruzione** nuova a missione in corso, senza fermarla: va in `messaggi/`, e l'orchestratore la legge al giro dopo.
- **Nessuna richiesta dell'utente per un'ora** su una missione che aspetta istruzioni la lascia bloccata finché non arriva.

## Chiudere una missione

Il bottone di chiusura scrive un file `chiudi` vuoto nella cartella: la missione si ferma da sola al controllo successivo. Una missione chiusa (o finita in errore, o interrotta) resta visibile nel pannello, a tendina chiusa, per 24 ore, poi viene spostata in `missioni_archivio` (recuperabile, non cancellata). Da lì si può anche toglierla subito dal pannello.

## Agenti delle missioni

Sotto l'elenco delle missioni, la lista di tutti i sottoagenti attivi in questo momento, in qualunque missione — letta dai registri delle missioni stesse, non da un contatore a parte.

## Il report finale

Alla chiusura normale, il capogruppo scrive un report in `Memoria/<spazio>/Report/<data> <titolo>.md`. Se la stessa missione viene rifatta nello stesso giorno, il file nuovo prende anche l'ora nel nome, per non sovrascrivere quello di prima.

## Conferme e chiusura sicura (dal 27/09/2026)

Quando un agente vuole fare una cosa che non si disfa (cancellare, pubblicare, mandare un messaggio, scrivere fuori dal progetto) la missione si ferma e mostra la richiesta con **Sì** e **No**. Si risponde una volta sola: dopo, i pulsanti si spengono e dicono cosa hai risposto. Scrivere il testo di un file non chiede più conferma: il controllo guarda il comando, non le parole dentro il file. Un `python3 << EOF` o un `ssh` con dentro un push chiedono ancora.


Una richiesta a cui nessuno risponde scade dopo 30 minuti e sparisce dal pannello. «Chiudi missione» chiude davvero: se dopo 60 secondi il processo è ancora vivo, il pannello lo ferma. A missione chiusa nessun agente resta «al lavoro» e un capogruppo mai partito è scritto «non partito». Le missioni chiuse, in errore o interrotte vanno in archivio da sole dopo 24 ore; «Togli dal pannello» le archivia subito, e da `missioni_archivio/` si recuperano.

