# La chiamata con Jarvis: come si integra

*2026-10-03 18:00 · agente cc-front-chiamata-opus · file nuovi: `chiamata.js`, `chiamata.css`, prova `vps/cc-ponte/prove-mobile/prova_chiamata.js`*

Conversazione a voce a schermo pieno, solo nel ponte (https://vps.esempio.it).
Sul Mac (porta 7777) non compare niente e non parte nessuna richiesta.

## Righe da aggiungere a `index.html`

Nel `<head>`, dopo le altre `<link rel="stylesheet">` (dopo `attivita.css`):

```html
<link rel="stylesheet" href="/static/chiamata.css">
```

In fondo al `<body>`, dopo `<script src="/static/attivita.js" defer></script>`:

```html
<script src="/static/chiamata.js" defer></script>
```

Nient'altro: nessuna modifica a `app.js`, `ponte.js`, `approvazioni.js`, `attivita.js`, `server.py`, `cc_ponte.py`.
Per la messa in produzione i due file vanno copiati in `static/` insieme a `index.html`, come gli altri di `static-nuova/`.

## Come si accende

- `chiamata.js` non chiede `/_ponte/stato`. Guarda la classe `ponte` sul `<body>`, che `ponte.js` mette solo quando `/_ponte/stato` risponde 200. Senza quella classe il file resta inerte: zero elementi, zero richieste.
- Il pulsante «Chiama» (telefono verde, 48 px) va subito dopo il microfono di `ponte.js` (`.ponte-mic`). Se il microfono non c'è ancora, il file lo aspetta con un MutationObserver sul form. Nei browser senza riconoscimento vocale va prima di «invio».
- Anche `#chiamata` nell'indirizzo apre la chiamata. L'indirizzo torna subito su `#chat`.

## I ganci

| Con chi | Cosa usa | Come |
|---|---|---|
| `app.js` | `THREADS`, `chatCon`, `filo()` | lettura per nome (const/let di uno script classico), come `approvazioni.js` |
| `app.js` | `invia()` | la frase va nel campo `#chiedi-testo`, poi parte `invia()`. Quello che l'utente aveva scritto a mano torna nel campo subito dopo. Corpo inviato: `{tipo:"chiedi", testo, sessione, continua, agente, progetto, motore}`, lo stesso della chat scritta, quindi il messaggio compare in chat e nello storico |
| `app.js` | `seguiRisposte` | non la chiama: legge `THREADS[chat].attesa` e l'ultimo messaggio ogni 250 ms. La risposta arriva quando app.js la mette nel filo |
| `app.js` | `azione({tipo:"ferma", id})` | pulsante Stop, lo stesso dello Stop di ponte.js |
| `attivita.js` | `window.CCAttivita.voci(id)` | l'ultima attività diventa il sottotitolo «lancio docker ps…». Senza attivita.js, durante la chiamata il file legge `/api/lavoro/<id>` ogni 2 s |
| `approvazioni.js` | `window.CCApprovazioni.stato()` / `rileggi()` | un id nuovo in attesa fa partire subito la lettura. Dopo una decisione chiede la rilettura, così le schede della chat si aggiornano |
| server | `GET /api/approvazioni` | ogni 2 s, solo a chiamata aperta e pagina visibile. Su 404 smette |
| server | `POST /api/azione {tipo:"approva", id, decisione:"si"\|"no"}` | solo da un tocco su Approva o Rifiuta. Rischio alto: secondo tocco entro 5 s |
| `ponte.js` | `speechSynthesis` | a chiamata aperta `speak` e `cancel` di altri script vengono ignorati, così l'altoparlante di ponte.js non legge la stessa risposta due volte e il suo «taci» non tronca la lettura. Alla chiusura tornano gli originali |

Per le prove e per altri script: `window.CCChiamata = { attiva, stato, apri, chiudi, perVoce }`.
`window.__CHIAMATA_TEMPI` (impostato prima del caricamento o durante) accorcia i tempi: `silenzio` 1500, `coda` 700, `inattivita` 300000, `avviso` 240000, `sfondo` 60000, `sonda` 2000, `rapido` 2000, `tettoRiavvii` 5, `conferma` 5000.

## Comportamento

- Fasi mostrate: «Ascolto», «Ti sento…», «Jarvis sta lavorando», «Jarvis parla», «Muto», più «Microfono fermo» quando il microfono è bloccato o continua a chiudersi.
- La frase parte dopo 1,5 s di silenzio. Il microfono resta chiuso mentre Jarvis lavora e mentre parla, e riapre 700 ms dopo la fine della voce.
- Testo letto: niente markdown, codice, indirizzi o emoji. Un percorso diventa il nome del file. Un blocco di codice diventa «Ti ho scritto il codice in chat». Si leggono al massimo 3 frasi (circa 320 caratteri), poi «Il resto è in chat».
- Interrompere Jarvis: tocco sul cerchio, oppure Stop mentre parla. Interrompere parlando non è fatto: con la voce di Jarvis nel microfono il riconoscimento si sentirebbe da solo.
- Riavvio del riconoscimento: dopo una sessione normale riparte sempre. Se si chiude subito (meno di 2 s senza risultati), riprova con attese crescenti (250 ms → 4 s). Dopo 5 riavvii di fila si ferma e dice «tocca il cerchio per riprovare».
- Permesso: riquadro grande con il rischio scritto, il riepilogo, il comando o il percorso, e i pulsanti Rifiuta/Approva (60 px). A voce dice solo «Jarvis chiede un permesso: <riepilogo breve>», senza percorsi né comandi. Nessuna parola detta approva: la decisione è sempre un tocco. Il fuoco va su «Rifiuta».
- Inattività: avviso a 4 minuti (scritto e detto), chiusura a 5 minuti senza parlato, risposte o tocchi. Un lavoro in corso conta come attività.
- Pagina in secondo piano per più di 60 s: la chiamata si chiude. Se la pagina torna visibile prima, il microfono riparte.
- Wake Lock: chiesto all'apertura se il browser lo ha, richiesto di nuovo quando la pagina torna visibile, rilasciato alla chiusura.
- Esc riduce la chiamata. «Riduci» torna alla chat: la pillola con timer e stato galleggia sopra i messaggi, e un tocco la riapre. Con un permesso da decidere la pillola diventa gialla.

## Privacy

Nel browser non si registra e non si salva audio. **Chrome però manda l'audio del microfono ai server di Google per il riconoscimento** (Web Speech API): vale per tutta la durata dell'ascolto, ed è lo stesso del dettato di ponte.js. Al Command Center arriva solo il testo riconosciuto, come un messaggio scritto. La voce di Jarvis è la sintesi del telefono (`speechSynthesis`, voce it-IT se c'è). Chi non vuole mandare audio a Google usa il microfono della tastiera.

## Limiti noti

- iPhone/Safari: spesso non c'è `SpeechRecognition`. Il pulsante dice «La chiamata vocale non è disponibile in questo browser: usa il microfono della tastiera» e non apre niente.
- Il primo `speechSynthesis.speak` richiede un gesto. Con il pulsante Chiama il gesto c'è. Con `#chiamata` aperto da un collegamento, la prima lettura potrebbe restare muta finché l'utente non tocca la pagina.
- Se durante la chiamata l'utente usa anche il microfono di ponte.js, i due riconoscimenti si contendono il microfono.
