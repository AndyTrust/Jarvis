# Integrare approvazioni e attività nella pagina

*2026-10-03 16:00 · cc-front-approvazioni-opus · contratto: `command-center/CONTRATTO-approvazioni.md` (sezioni 1 e 2)*

Quattro file nuovi in `command-center/static-nuova/`. Nessun file esistente è stato toccato.

| File | Cosa fa |
|---|---|
| `approvazioni.js` / `.css` | Schede «Rifiuta / Approva» (in chat, nel riquadro in basso, sulla lavagna), badge nell'intestazione, «(N)» nel titolo, segnalazioni della sentinella sulla lavagna |
| `attivita.js` / `.css` | Nella bolla «sta lavorando» l'elenco vivo di cosa fa Jarvis, al posto dei tre puntini |

## 1. Le righe da aggiungere a `index.html`

Nel `<head>`, subito prima di `<script>window.CC_TOKEN = "__TOKEN__";</script>` (dopo `mobile.css`):

```html
<link rel="stylesheet" href="/static/approvazioni.css">
<link rel="stylesheet" href="/static/attivita.css">
```

In fondo al `<body>`, dopo `<script src="/static/ponte.js" defer></script>` e prima di `</body>`:

```html
<script src="/static/approvazioni.js" defer></script>
<script src="/static/attivita.js" defer></script>
```

Devono stare **dopo** `app.js`: leggono le sue globali. Con `defer` partono a pagina letta, quando `app.js` ha già girato.
La prova `vps/cc-ponte/prove-mobile/prova_approvazioni.js` aggiunge proprio queste quattro righe alla copia in memoria di `index.html`.

Facoltativo: aggiungere i quattro file a `GUSCIO` in `static/sw.js` (alzando `CACHE`), così a server spento la pagina in cache li ha. Il service worker è «rete prima», quindi senza questa riga funziona lo stesso.

## 2. Ganci con `app.js` (nessuna modifica ad `app.js`)

I file nuovi non chiedono cambi ad `app.js`. Si agganciano così:

| Gancio | Come | Se manca |
|---|---|---|
| `FLUSSO.es` (EventSource di `/api/flusso`) | `const` globale letta per nome; ascoltatori `approvazione` e `attivita` | `approvazioni.js` apre un EventSource suo con `?token=` |
| Costruttore `EventSource` | Avvolto una volta sola (`window.__ccFlusso`): ogni EventSource verso `/api/flusso`, compresi i ricollegamenti di `app.js`, riceve gli ascoltatori **prima** del primo evento. Resta un EventSource vero | Si usa solo `FLUSSO.es` |
| `window.api` | Avvolto in modo passivo: le risposte di `GET /api/lavoro/<id>` (quelle di `seguiRisposte`, ogni 1,5 s) passano intatte e se c'è il campo `attivita` lo leggo. Zero richieste in più | `attivita.js` legge da solo `/api/lavoro/<id>` ogni 2 s, solo per la chat aperta |
| `THREADS`, `chatCon` | Lette per nome: `THREADS[chatCon].attesa.id` è il lavoro della chat aperta | Niente scheda in chat: tutte vanno nel riquadro in basso |
| `ultimoStato` | Letta ogni 3 s: `sentinella.anomalie` e `salute.raccoglitori[].errore` diventano segnalazioni | Nessuna segnalazione |
| `#messaggi` | `MutationObserver`: dopo ogni `disegnaMessaggi()` rimetto scheda ed elenco sotto la bolla (`.msg` che contiene `#durata-attesa`) | — |
| `<title>` | `MutationObserver`: `mostraVista()` riscrive il titolo, io rimetto «(N) » davanti | — |
| `header.barra`, `#lavagna`, `.vista-chat .compositore` | Il badge va prima di `.stato-generale`; il riquadro della lavagna è figlio di `#lavagna` (fuori da `#lav-mondo`, quindi `disegnaLavagna()` non lo tocca); in Chat il riquadro in basso si mette prima di `.compositore` | Badge in fondo al body |

Per le decisioni uso un `fetch` mio verso `POST /api/azione` (stesse intestazioni di `api()`: `X-Token`, JSON) e non `azione()`, perché `azione()` perde il codice di risposta e serve distinguere 404, 409, 403 e rete giù.

Se un giorno `app.js` diventa un modulo, o rinomina `FLUSSO`/`THREADS`/`chatCon`/`ultimoStato`/`api`, i file nuovi non si rompono: ripiegano come scritto sopra. Va solo riprovato.

Per chi scrive altri script: `window.CCApprovazioni.rileggi()` forza una lettura, `window.CCApprovazioni.stato()` dice se il backend c'è e quali id aspettano; `window.CCAttivita.voci(id)` dà le voci di un lavoro.

## 3. Cosa serve dal backend (per l'agente del backend)

1. **SSE con eventi col nome.** Oggi `_flusso()` in `server.py` manda solo `data: {versione, chiavi}` (evento `message`). Per le approvazioni servono:
   ```
   event: approvazione
   data: {oggetto A del contratto}

   event: attivita
   data: {"lavoro_id": "...", "voce": {"ts":…, "tipo":"leggo", "testo":"leggo posta.py", "esito":"in corso"}}
   ```
   L'`onmessage` di `app.js` non vede gli eventi col nome, quindi non li confonde con i suoi. Accetto anche, in alternativa, un evento normale con `{"tipo":"approvazione","approvazione":A}` oppure con `chiavi` che contiene `"approvazioni"` (in quel caso rileggo `GET /api/approvazioni`).
2. **Attenzione al nome «attivita».** Nel flusso di oggi la chiave `attivita` dentro `chiavi` vuol dire «riga nuova nel registro delle attività» (`caricaSommarioAttivita`). L'evento col nome `attivita` del contratto è un'altra cosa. Funzionano insieme, ma se il backend preferisce si può chiamare l'evento `attivita_lavoro`: basta cambiare una stringa in `attivita.js`.
3. **`GET /api/approvazioni` deve tenere le scadute fra le `recenti`** con `stato:"scaduta"`. Una richiesta in attesa che sparisce dall'elenco senza passare per `recenti` la tolgo in silenzio (dopo 15 s se era arrivata dal flusso).
4. **Una voce `in corso` che finisce** va mandata con gli **stessi** `ts`, `tipo` e `testo` e l'`esito` nuovo: la riconosco così e aggiorno la riga invece di aggiungerne una.
5. **Risposte di `POST /api/azione` tipo `approva`**, come da contratto: 200 `{ok, stato, gia_deciso?}`, 404, 409. Se il 403 di token scaduto arriva con `token_scaduto:true` dico di ricaricare la pagina; ogni altro errore mostra `errore` del corpo.
6. **Segnalazioni.** Oggi la sorgente leggibile è `/api/stato` → `sentinella.anomalie[] {tipo, chiave, testo, da_ts}` e `salute.raccoglitori[].errore`. «Ok, visto» resta in questo browser (`localStorage["apv.visti"]`, chiave = `chiave` + `da_ts`), perché il backend non ha un endpoint per segnare un'anomalia come vista e non ne ho inventati. **Manca nel backend**: (a) un «visto» condiviso fra PC e telefono; (b) una sorgente per gli errori dei lavori e delle missioni finite male (oggi stanno solo nella lista dei lavori), se l'utente li vuole come schede.

## 4. Comportamento, in breve

- **Dove compare la scheda.** Se `lavoro_id` è il lavoro della chat aperta e la Chat è visibile: sotto la bolla «sta lavorando». Altrimenti nel riquadro in basso: in Chat è in fila sopra il campo di scrittura (non copre l'ultima risposta), nelle altre viste è fisso in basso sopra la barra di schede del telefono. Si può ridurre a una riga («Riduci»). Sulla lavagna compare sempre anche il riquadro sovrapposto (sola visualizzazione, niente in `pannello.json`); con la lavagna a pagina intera il riquadro in basso si nasconde per non fare doppione.
- **Scheda.** Rischio in colore e in parola («Rischio basso/medio/alto» con ● ▲ ■), agente e strumento, conto alla rovescia, «Dettagli» ripiegabili (comando, percorso, righe +/−, anteprima), pulsanti da 48 px (52 px sul telefono). Con rischio alto «Approva» chiede un secondo tocco entro 5 s.
- **Dopo la decisione** la scheda dice «Approvata/Rifiutata alle HH:MM» (o «Scaduta», o «Era già approvata da Telegram») e si chiude dopo 4 s. Errori in italiano: rete giù (i pulsanti tornano usabili), 15 s senza risposta, 404 «non esiste più», 409 «troppo tardi, scaduta».
- **Accessibilità.** Annunci in una regione `aria-live` sola (nuova richiesta, esito); le schede sono `role="group"` con titolo; A e R funzionano solo con il fuoco sulla scheda (mai scorciatoie globali, mai dentro un campo di testo); dopo una decisione il fuoco passa alla richiesta seguente. Le schede dentro `#messaggi` hanno `aria-live="off"` per non essere lette due volte.
- **Sondaggio.** `GET /api/approvazioni` ogni 5 s senza flusso, ogni 30 s con il flusso vivo o a scheda nascosta, e a ogni riapertura del flusso. Al primo 404 smette (backend vecchio): niente schede, niente badge, niente richieste a vuoto.
- **Attività.** Ultime 3 voci, l'ultima evidenziata, «mostra tutte (N)»; al massimo una voce nuova ogni 250 ms (se il ritardo supera 10 voci salta avanti); «in corso» con un anello che gira, fermo con `prefers-reduced-motion`; testi sempre con `textContent`.
- **Tema.** La pagina è solo scura (`color-scheme: dark`); i file usano le sue variabili (`--testo`, `--rialzo`, `--verde`…), quindi seguono un eventuale tema chiaro che usi le stesse variabili.

## 5. Prove

```
node vps/cc-ponte/prove-mobile/prova_approvazioni.js            # iPhone 14, Pixel 7, tablet, desktop
node vps/cc-ponte/prove-mobile/prova_approvazioni.js --solo iphone14
```

Pagina viva in sola lettura, tutti i POST abortiti tranne `approva` (a cui risponde la prova). `app.js` e `app.css` vengono da `static/` (static-nuova non li ha più). Schermate in `~/.locale-onedrive/cc-ponte/schermate-approvazioni/`.

Esito del 2026-10-03 16:05: 144/144 sui quattro dispositivi (casi di decisione su iPhone 14 e desktop), più 92/92 con `--solo pixel7,tablet --tutti`.

Non provato: backend vero (il contratto è realizzato in parallelo), SSE vero con eventi col nome dal server, telefono vero (solo Chrome con emulazione), il ponte con `comandi-off` (il messaggio mostrato è il campo `errore` della risposta).
