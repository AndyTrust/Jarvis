# Fili di chat condivisi fra Mac e telefono: analisi e scelta

*2026-10-03 19:27 · cc-fili-opus · problema dell'utente: «la lavagna non fa aggiornare la chat»*

## Com'è oggi (letto nel codice il 2026-10-03)

- **La pagina** (`static/app.js` e `static-nuova/app.js`, righe 3795-4195 della nuova) tiene le chat in
  `THREADS`, un oggetto nel `localStorage` del browser (`cc.fili`). Una chiave per interlocutore:
  `"jarvis"` o `"<progetto>:<nome agente>"`. Per ogni chiave: `sessione` (uuid del filo, creato dalla
  pagina), `avviata`, `messaggi` `[{chi: "io"|"lui", testo, ora, errore?, tipo?, motore?, box?}]` senza
  id, e `attesa` `{id del lavoro, inizio, comando, titolo}` mentre aspetta una risposta.
- `invia()` aggiunge la domanda in locale e manda `POST /api/azione {tipo: "chiedi", testo, sessione, …}`.
  La risposta la va a prendere `seguiRisposte()` ogni 1,5 s con `GET /api/lavoro/<id>`, la aggiunge in
  locale e salva (`salvaFili()`). Il ✕ toglie un messaggio, «svuota» crea una sessione nuova.
- **Il server** (`server.py`, `chiedi()` riga 5122) conosce la sessione e l'interlocutore del lavoro
  (`LAVORI[id]`, solo in memoria), il testo della domanda (`richiesta`) e la risposta (il log in
  `lavori/<data>_<id>.log`, riscritto dal «dopo» con il solo testo). Nessun archivio per filo.
- **`conversazione.py`** tiene per filo solo lo stato di lavoro (in corso, in sospeso, ultime 5 fatte,
  interrotte), con testi corti a 160 caratteri, in `conversazioni.json`: serve all'intestazione della
  domanda dopo, non a ridisegnare una chat.
- Il tipo «filo» che si vede in `server.py` (righe 1595, 2902, 6925) è il filo della **lavagna** (un
  collegamento fra due nodi), non la chat. Il flusso SSE `/api/flusso` non c'entra.

Quindi: una chat aperta sul Mac non esiste sul telefono, e una risposta arrivata a scheda chiusa resta
solo sul dispositivo da cui era partita la domanda.

## La scelta

Il server tiene l'archivio dei fili e la pagina lo unisce alla sua copia. Il server è la fonte.

**Backend, `fili.py`** (solo libreria standard, da copiare in `command-center/`):
- un file JSON per filo, `<uuid>.json`, in `~/.locale-onedrive/jarvis-cc/fili/` (cartella 0700, file
  0600, fuori da git e da OneDrive; `CC_FILI_DIR` la cambia per le prove);
- id stabili: `q-<id lavoro>` la domanda, `a-<id lavoro>` la risposta (anche «Risposta persa»),
  `r-<sessione>` il messaggio del reset. Lo stesso id riscritto aggiorna, non duplica;
- `versione` per filo (+1 a ogni scrittura), `in_attesa` (lavori senza risposta), `titolo`, `interlocutore`;
- lock fra thread e, su Mac e Linux, `flock` fra processi; scrittura atomica (tmp + `os.replace`, fsync);
- limiti: 40.000 caratteri per messaggio (oltre si tronca e si dice in quale `lavori/<log>` sta il testo
  intero), 400 messaggi e 2 MB per filo, 500 fili (escono i meno recenti);
- maschera dei token riconoscibili (`sk-ant-`, `sk-`, `ghp_`, `github_pat_`, `xox?-`, `AKIA`, `AIza`,
  `Bearer …`) e del token della pagina, prima di scrivere;
- nomi file: solo uuid minuscolo (`fullmatch`), id lavoro `[A-Za-z0-9_-]{1,64}`, nome del log controllato.

**Patch a `server.py`** (`fili-server.patch`, 139 righe, applicabile al `server.py` di oggi che ha già
le approvazioni):
- `chiedi(..., filo=True)` solo dall'azione «chiedi» della pagina. Le richieste interne (skill da «/»,
  controllo scadenze) hanno sessioni usa e getta e non entrano: sposterebbero gli altri dispositivi su
  un filo che l'utente non ha mai visto;
- l'id del lavoro si sceglie prima, la domanda entra nell'archivio prima che il lavoro possa finire;
- a lavoro finito (`nuovo_lavoro`, dopo lo stato) la risposta entra con lo stesso testo che la pagina
  legge da `/api/lavoro/<id>` (il log senza la riga «(cartella: …)»);
- «nuova conversazione»: il filo nuovo nasce con il messaggio del server;
- all'avvio `fili.riavvio()`: le attese rimaste diventano «Risposta persa…», lo stesso testo della pagina;
- `GET /api/fili` (riassunti dal più recente) e `GET /api/fili/<uuid>` (il filo), dopo il controllo del
  token come gli altri GET; evento «fili» `{sessione, interlocutore, versione, aggiornato}` sul flusso
  con `emetti_flusso` (lo stesso modo delle approvazioni);
- ogni errore dell'archivio diventa un evento e non ferma la chat. Nessuna scrittura dal client: il
  ponte non apre POST nuovi.

**Front-end, `static-nuova/fili.js`** (nessuna modifica ad `app.js`, una riga in `index.html`):
- all'avvio, a ogni evento «fili», al ritorno sulla scheda, ogni 10 s senza flusso (60 s con il flusso
  vivo) legge `GET /api/fili` e solo i fili cambiati (`versione`);
- per ogni interlocutore vale il filo del server aggiornato più di recente. Stessa sessione della pagina:
  si uniscono i messaggi. Sessione diversa: la pagina ci passa se la sua chat è vuota e mai svuotata qui,
  se la sua sessione è nota al server e più vecchia, o se ha solo messaggi di prima di fili.js e il filo
  del server è più nuovo. Una chat che sta aspettando una risposta non si cambia;
- l'unione segue l'ordine locale: i messaggi locali senza id (domanda non partita, errori di rete, comandi
  «/») restano al loro posto, quelli del server entrano prima del primo messaggio abbinato che li segue o
  in fondo. Abbinamento per id, poi per testo uguale (dal fondo) per i messaggi nati prima;
- avvolge `salvaFili`: prima di salvare mette `fid` = `q-<attesa.id>` alla domanda appena mandata e
  `a-<id>` alla risposta appena arrivata; dopo il salvataggio si accorge dei messaggi tolti con ✕ (non
  tornano dal server su quel dispositivo) e delle sessioni lasciate (svuota, reset: non si riprendono, e
  la chat nuova vuota non riprende fili più vecchi di lei);
- una domanda partita da un altro dispositivo mette «sta lavorando» anche qui (`attesa` con `daFili`),
  e la risposta la prende chi arriva prima, fili.js o `seguiRisposte()`, senza doppioni;
- una chat con messaggi solo locali che viene sostituita si mette da parte in `cc.fili-da-parte` (le
  ultime 5), non si cancella;
- backend vecchio (404): si spegne, la pagina resta com'era.

Perché non un'architettura più semplice: rileggere i log dei lavori non basta (`LAVORI` sta in memoria,
il log non dice sessione né interlocutore e sparisce dalla lista); scrivere i fili dal client vorrebbe
POST nuovi nel ponte, che la consegna esclude. Il server scrive già quando riceve la domanda e quando il
lavoro finisce: è il punto più semplice dove salvare.

## Esito delle prove (2026-10-03 19:26)

`python3 command-center/fili-dev/prova_fili.py --con-claude` → **97 PASS, 0 FAIL, 0 SALTA**:
- a) 40 unitarie su `fili.py`;
- b) 27 sul server con la patch (copia isolata, porta 7799, `CC_PROVA=1`, HOME e archivio temporanei,
  claude finto): dry-run della patch sul `server.py` di oggi, endpoint, 403 senza token o con Host
  estraneo, 404 sui nomi strani, evento «fili» entro 2 s, risposta nel filo uguale a quella che legge la
  pagina, tre domande insieme in fila, troncatura, errore, segreto mascherato, reset, `/lavori` che non
  crea fili, permessi, token assente, riavvio a metà = «Risposta persa»;
- c) 28 con Chrome headless vero: Mac (desktop 1440) e iPhone 14 **attraverso una copia di
  `cc_ponte.py`**, localStorage separati, nessun POST uscito dalle pagine, `pannello.json` della copia e
  quello vero senza cambi di versione. La domanda compare sul telefono in 456 ms; nessun doppione; la
  domanda locale mai partita resta; ✕, ricarica, svuota e filo nuovo si comportano come sopra;
- d) 2 con claude vero (una domanda in «lettura», risposta «pronto»): domanda e risposta nell'archivio.

Schermate: `~/.locale-onedrive/cc-ponte/schermate-fili/` (guardate: le bolle sono nell'ordine giusto).

## Cosa non è provato

- La patch è provata su una copia: il Command Center vero non è stato riavviato né patchato.
- Il ponte vero sulla VPS non è stato toccato: provato con una copia di `cc_ponte.py` in locale.
- Agenti (`<progetto>:<nome>`): la logica è la stessa chiave di `"jarvis"`, ma la prova con un agente
  vero richiede `spazi.json` reali; non fatta.
- Windows: `fcntl` manca, il lock è solo fra thread (il server è un solo processo, basta). Non provato.
- Due dispositivi che scrivono nello stesso secondo in due fili diversi dello stesso interlocutore: vince
  il più recente e l'altro si allinea; non c'è una prova dedicata.

## Rischi

- **Dimensione**: al massimo 500 fili × 2 MB = 1 GB teorico; in pratica una chat da 100 messaggi pesa
  poche centinaia di KB. I limiti si cambiano in testa a `fili.py`. Non c'è pulizia per età.
- **Privacy**: l'archivio contiene il testo intero delle chat in chiaro sul Mac, in una cartella 0700
  fuori da OneDrive e da git. Chi ha l'utente del Mac lo legge (come i log in `lavori/`, che già oggi
  contengono le stesse risposte). La maschera dei segreti prende solo i formati riconoscibili: una
  password scritta in chiaro in chat resta nel file. Dal telefono l'archivio si legge solo dopo password
  + codice del ponte, come il resto della pagina.
- **Fili vecchi nel localStorage**: non si caricano sul server (nessuna scrittura dal client). Restano
  visibili finché quel dispositivo non passa a un filo più nuovo; allora, se avevano messaggi solo loro,
  finiscono in `cc.fili-da-parte` (le ultime 5 chat) e non si vedono più nella pagina. Le sessioni di
  Claude Code restano comunque in `~/.claude/projects`.
- **Regola «vince il più recente»**: se l'utente scrive sul telefono in una chat nuova, il Mac ci passa da
  solo. È voluto («la stessa conversazione ovunque»), ma cambia l'abitudine di avere chat diverse per
  dispositivo con lo stesso interlocutore.
- **Messaggi tolti con ✕**: valgono solo su quel dispositivo (il server non cancella). Togliere il primo
  messaggio di una chat può essere preso per il taglio dei 120 messaggi e tornare.
- **Testo uguale**: un messaggio vecchio senza id identico a una domanda nuova del server viene
  abbinato a quella (la domanda appare una volta sola, al posto del vecchio). Raro, nessuna perdita.
