# Lavagna

La lavagna è la mappa degli agenti, sulla destra del pannello (o a pagina intera sulla scheda **Lavagna**). Ogni scheda è un agente, ogni filo è un collegamento («dipende da», «comunica con»).


## Come si usa

- Si trascina un agente dalla colonna di sinistra sulla lavagna per metterlo come scheda.
- Si tira il pallino a destra di una scheda su un'altra per collegarle.
- Doppio clic sul fondo della lavagna aggiunge una nota libera (o il bottone **＋ Nota**).
- **Ordina**: nella lavagna generale ridisegna «Tutta la catena»; nella lavagna di un gruppo mette una piramide per progetto (capogruppo in cima, squadra sotto). Sposta le schede, non tocca i fili.
- **Centra** riporta la vista al centro.
- **Togli** rimuove la scheda o il collegamento selezionato (disabilitato finché non se ne sceglie uno).

### Togliere un filo (dal 27/09/2026)

Ogni filo ha una presa larga 16 pixel, quindi si prende facilmente anche se la linea è sottile. Un clic lo sceglie e a metà compare una ✕ rossa: un clic sulla ✕ e il collegamento se ne va. Il doppio clic sul filo lo toglie subito; Canc o Backspace come prima. Togliendo un filo fra due agenti si aggiorna il «Comunica con» di tutti e due i profili.


### Allineare le schede: la calamita

Trascinando una scheda, se un bordo o il centro arriva a 10 pixel da quello di un'altra scheda, si aggancia e compare una guida tratteggiata. Con Alt premuto la calamita si spegne.


### Agenti tolti: spariscono anche i loro fili

Quando un agente viene tolto (archiviato) o sparisce dai profili, la sua scheda esce da tutte le lavagne insieme ai suoi fili. Prudenza: se l'elenco degli agenti arriva monco (meno di 10, o sparirebbe più di metà di una lavagna) non si tocca niente.

### Le sinapsi: chi parla con chi

Quando gli agenti lavorano, i fili fra chi si parla si accendono e scorrono, e una bolla mostra il testo vero. La × della bolla la chiude e resta chiusa. A missione finita nessuna comunicazione resta «in corso».


## Più lavagne, per gruppo

Dal 24/09/2026 non c'è più una lavagna sola: ogni gruppo di agenti ha la sua. Cliccare un gruppo nella colonna di sinistra apre solo la sua lavagna, senza mischiare tutti gli agenti insieme. La lavagna **«generale»** è quella di chi arriva dal menu senza passare da un gruppo, e quella di **«Tutta la catena»**.

## Tutta la catena

Il bottone **Tutta la catena** costruisce una piramide dall'alto in basso:

- livello 0: l'utente;
- livello 1: Jarvis, con accanto i suoi agenti di casa (l'esecutore, il ricercatore-web);
- livello 2: i capigruppo, raggruppati per spazio sotto un'etichetta del colore dello spazio;
- sotto ogni capogruppo, la sua squadra in colonna (due colonne affiancate se sono più di sei).

Compaiono solo gli agenti che esistono davvero come file di profilo (letti da `/api/catalogo`); un progetto senza capogruppo ha in testa solo un'etichetta col suo nome. I fili della gerarchia sono ad angolo retto; i collegamenti «comunica con», letti dai profili veri, restano curvi.

## Aggiorna agenti → Jarvis

Manda a Jarvis un incarico: rileggere i profili veri degli agenti, controllare i collegamenti disegnati in lavagna, e aggiornare di conseguenza la mappa (e i profili, se serve). È un lavoro vero, non un salvataggio automatico della sola disposizione grafica.

## La scheda di un agente

Un clic apre la chat con lui; un doppio clic apre la sua scheda, con due parti:

- **Il profilo vero**, quello che legge Claude Code: descrizione, modello (haiku, sonnet, opus), strumenti. Si può modificare e salvare da qui: scrive davvero nel file `.claude/agents/<nome>.md`.
- **Come lo vedi qui**: nome mostrato, nota personale, emoji, colore, gruppo — solo aspetto nella lavagna, non tocca il file dell'agente.

In fondo, «Dipende da» elenca i collegamenti verso altri agenti.

## Modo dimostrazione

Aggiunto il 26/09/2026 per i video dell'utente. Il bottone **Dimostrazione** accende un modo in cui la lavagna non scrive niente fuori dalla pagina, tranne le lavagne il cui nome comincia per `demo-`: tutto il resto (profili veri, Telegram, il file `pannello.json` salvato sul serio) resta come l'ultima volta letto o salvato prima di entrare in dimostrazione.

In questo modo compaiono due bottoni in più:

- **Squadra dimostrativa**: costruisce da zero una lavagna `demo-squadra`, fatta solo di note finte (nessun profilo vero viene toccato) — un capogruppo e una squadra di ruoli generici (analista, ricercatore, programmatore, revisore, verificatore).
- **▶ Fai partire la dimostrazione**: accende in fila, un nodo ogni 900 millisecondi, chi «lavora» e i fili che portano la risposta, per un effetto a scopo di presentazione.

Un'etichetta «DIMOSTRAZIONE · niente viene inviato» resta visibile finché il modo è acceso. Uscendo dalla dimostrazione, quello che era stato cambiato solo in pagina viene scartato e la lavagna torna a essere quella vera.


La squadra dimostrativa in movimento: Umano → Jarvis (harness) → il motore scelto → capogruppo e specialisti che si parlano → il report che risale a Jarvis e all'umano. In modo Dimostrazione niente viene inviato.

