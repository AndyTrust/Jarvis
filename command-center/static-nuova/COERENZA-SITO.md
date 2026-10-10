# Coerenza del sito (Command Center da internet) — 2026-10-03

Lavoro di `cc-front-coerenza-opus` sulle copie in `command-center/static-nuova/` (prima versione 18:30,
seconda versione 19:50 dopo la decisione dell'utente «niente in sola lettura dal sito»). I file vivi in
`command-center/static/` non sono stati toccati. Prove: `vps/cc-ponte/prove-mobile/prova_coerenza.js`.
La tabella di cosa passa dal ponte e perché: `vps/cc-ponte/AZIONI-SITO.md` (agente cc-ponte-azioni-opus).

## 1. «modo lettura» al posto di «approvazione»

Causa: `disegnaModoChat()` in `app.js` accettava solo `lavoro` e `lettura`; con `modo_chat = "approvazione"`
(il valore vero in `configurazione.json`) ripiegava su «lettura» in cinque punti: etichetta del ponte,
interruttore sul Mac (con «lavoro» spento e il titolo «il server non conosce ancora il modo»), testa della
chat, nota sotto il campo, benvenuto.

Ora i modi sono tre (`MODI_CHAT`), ognuno con testo e titolo (`titoloModo`):
- lavoro: «lavora davvero: la guardia blocca l'irreversibile»
- lettura: «legge e riferisce, non cambia niente»
- approvazione: «Jarvis chiede il tuo permesso prima di scrivere o lanciare comandi» (con Gemini, Codex,
  Cursor: «non ha il gestore dei permessi: in approvazione lavora in sola lettura», come fa `server.py`).

L'interruttore ha la terza voce «approvazione» (`server.py` la accetta dall'azione `modo_chat`). Dentro il
ponte l'interruttore c'è (il ponte passa `modo_chat` approvazione e lettura) con «lavoro» spento: salta i
permessi, il ponte lo vieta. Con i comandi spenti (comandi-off) al suo posto c'è l'etichetta «modo …» con
lo stesso titolo e «Il modo della chat si cambia dal Mac».

## 2. Cosa funziona dal sito: lo decide il ponte, una sola fonte

- `ponte.js` legge `GET /_ponte/stato` all'avvio e poi ogni 15 s a scheda visibile (e al ritorno sulla
  scheda). Se risponde 200 mette `dentro-ponte` su `<html>` e passa `azioni` ad `app.js`
  (`PONTE.prendiAzioni`): `post_percorsi`, `azione_tipi` («tipo» o «tipo:cosa»), `solo_no`,
  `get_bloccati`, `get_bloccati_parole`, `get_senza_forza`. È la tabella che il ponte usa davvero
  (`elenco_per_pagina()` in `cc_ponte.py`). Quando cambia «comandi» (attivi/spenti) cambia anche l'elenco,
  e la pagina lo prende alla lettura dopo.
- `app.js`, `ponteConsente(chiave)`: una chiamata parte solo se l'elenco la contiene; altrimenti l'errore
  «Disponibile solo dal Mac», senza richiesta. Senza elenco (non ancora arrivato, lettura fallita, ponte
  vecchio) non si blocca niente: decide il ponte e l'errore si vede. Le restrizioni sui valori che l'elenco
  non porta (`v_modo_chat`, `v_missione`, `v_interruttore`, `v_telefono` in `cc_ponte.py`) stanno in
  `PONTE_VALORI_VIETATI`: modo «lavoro», missione «lavoro», specchio del telefono acceso, telefonata.
- Ogni pulsante dice la sua azione: `data-solo-mac="<chiave>"` in `index.html` e `app.js`, oppure
  l'attributo di delega (`data-aggiorna`, `data-apri`, `data-android`, `[data-int] .switch`, `data-cmd`, …:
  `chiaveDi()` in `ponte.js`). `ponte.js` spegne, col titolo «Disponibile solo dal Mac», SOLO i pulsanti la
  cui azione il ponte non passa, e li rimette com'erano quando torna (comandi riaccesi).
- Terminale, VPS e Tecnico restano nascosti nel ponte (menu in alto, foglio «Altro», «>_ Terminale della
  VPS»); `#terminale`, `#vps`, `#tecnico` portano alla chat.
- La lavagna dal sito salva come sul Mac (`/api/pannello/modifica`, riga di stato «salvata · vN», 409 e
  scrittura alla chiusura come sul Mac). Solo con comandi-off la riga dice «NON salvata: dal sito i comandi
  sono spenti, riprovo quando tornano» e le modifiche partono da sole quando l'elenco torna.
- I comandi con «/» (barra e menu) passano (`comando_diretto`).
- Sul Mac (404) `PONTE.dentro` resta falso: nessuna di queste strade si attiva.

## 3. Inventario: cosa resta spento dal sito (misurato col clic su ogni pulsante, 1440)

Solo azioni che il ponte vieta davvero (classe C di AZIONI-SITO.md):

| Pulsante | Azione | Perché |
|---|---|---|
| modo «lavoro» (interruttore della chat) | `modo_chat` lavoro | salta i permessi |
| missione, scelta «lavoro» | `missione` lavoro | agente che agisce senza chiedere |
| Schermo del telefono (accendere) | `interruttore` schermo_telefono | adb; spegnerlo passa |
| Chiama (Telefono) | `telefono:chiama` | telefonata vera a un terzo |
| Android: Associa, Collega, Scollega | `android` | adb |
| Collegamenti (Odoo, n8n, Cruscotto, un'app esterna, Guida) | `apri` | aprono una finestra sul Mac |
| ⌕ Log nel Finder | `mostra_log` | Finder sul Mac |
| cartelle della sincronia, 📄 sulle schede | `apri_percorso_sincronia`, `apri_cartella` | Finder sul Mac |
| Manda (chat a voce) | `chat_voce_manda` | la voce gira in bypass |
| Scegli o crea… (nuovo gruppo) | `GET /api/scegli-cartella` | finestra sul Mac |
| Repository: ↻ Aggiorna | `GET /api/github?forza=1` | rifà git/gh sul Mac a ogni clic |
| Aggiorna ora | `POST /api/aggiorna` | riavvia il Command Center |
| Apri la chat (cartella non fidata) | `chat` | finestra sul Mac |
| Terminale, VPS, Tecnico, assistenza | pagine e riquadri nascosti | GET bloccati |

Tutto il resto è acceso e chiama il ponte: interruttori (voce, volto, mani, telefono, Telegram), sentinella,
↻ aggiorna, verifiche, comandi rapidi, comandi Claude Code, Portfolio, scadenze (chiudi, riapri, aggiungi,
chiudi le selezionate, controllo), missioni in lettura (istruzione, conferma, chiudi), lavori (rilancia,
togli, pulisci, ferma), agenti e gruppi (crea, togli, ripristina, attivo, elimina, crea_squadra, rinomina,
allinea, aggiorna_catena, salva_casa), profili e «Comunica con», motore, lavagna, approvazioni, chat e «/».

Prima della seconda versione (copie della prima versione): 336 pulsanti spenti. Prima di tutto (file di
oggi in `static/`): 309 pulsanti finivano in un rifiuto del ponte, tre GET bloccati a ogni apertura.

## 4. Esito delle prove (2026-10-03 19:55, `node vps/cc-ponte/prove-mobile/prova_coerenza.js`)

Il ponte finto usa il filtro vero: un processo Python carica `cc_ponte.py`, `/_ponte/stato.azioni` è
`elenco_per_pagina()` e ogni POST passa da `regola_di()` (con comandi-off simulato da un file temporaneo).
Nessun POST arriva al Command Center: quelli che il ponte passerebbe hanno una risposta finta.

Totale 96/100 PASS. Non PASS:
- `[ponte]` 3 righe, limiti di `cc_ponte.py` più stretti dei dati veri (il sito qui è corretto):
  1. `v_scadenze`: id ≤ 200 caratteri, ma le «Da ricordare» (task) hanno id fino a 293: chiudere, riaprire,
     chiudere le selezionate di quelle righe dà 400 (6 pulsanti nel giro, più la prova diretta);
  2. `_profilo`: description ≤ 600, ma i profili veri arrivano a 1233 caratteri: «Salva» della scheda agente
     su quei profili dà 400 (la textarea della pagina ne ammette 2000).
- «Mac 1440 agenti»: dati vivi cambiati fra le due schermate (sessioni nuove in «Chiavi e da guardare»).
  Rifatta da sola subito dopo: regressione Mac 15/15 PASS, pannello.json v682 prima e dopo.

Copertura dell'elenco vero (62 voci di /api/azione + 6 percorsi POST): 60/68 chiamate dalla pagina con un
corpo accettato dal filtro vero. Non provate: `agente:elimina` (Elimina definitivo dalla lavagna),
`agente:ripristina`, `agente:elimina_archiviato` (servono agenti archiviati), `aggiorna:agenti` (riga di salute
assente oggi), `portiere:ritira_fantasmi` (nessun fantasma oggi), `pulisci_lavori`, `telefono:centralino_ferma`
(il centralino è spento), `/api/pannello` (nessuna pagina lo usa: la lavagna salva con /api/pannello/modifica).

## 5. Da copiare (sul Mac, con backup)

```bash
cd ~/Jarvis/command-center
S=$(date +%Y%m%d-%H%M)
for f in app.js index.html ponte.js mobile.css; do cp -p static/$f static/$f.bak-$S-prima-coerenza; done
cp static-nuova/app.js static-nuova/ponte.js static-nuova/mobile.css static/
# index.html contiene anche le righe di chiamata.* e computer.* (altro agente): si copia insieme ai loro file
cp static-nuova/index.html static/
shasum static/app.js static-nuova/app.js static/ponte.js static-nuova/ponte.js static/mobile.css static-nuova/mobile.css static/index.html static-nuova/index.html
```

`mobile.js` e `app.css` non cambiano. Il server non va riavviato. Nuovo `app.js` e nuovo `ponte.js` vanno
insieme: `app.js` aspetta la risposta di `ponte.js` (al massimo 4 s) prima delle chiamate.
Tornare indietro: `cp -p static/<file>.bak-$S-prima-coerenza static/<file>`.

## 6. Correzioni di REVISIONE-2-PAGINE.md (2026-10-03 22:30, cc-front-coerenza-opus)

Partite dai file vivi di `static/` (uguali alle copie all'inizio, controllato con shasum). Prova:
`vps/cc-ponte/prove-mobile/prova_revisione2.js` (ogni punto con i file di oggi, «prima», e con le copie, «dopo»).

| Punto | File | Cosa cambia |
|---|---|---|
| 1 F1 permesso nella chiamata | chiamata.js, chiamata.css | comando, percorso e anteprima interi (fino a 4000 caratteri, a capo, riquadro che scorre), «Mostra tutto», avviso se il server ha tagliato («…» a 800) o nascosto righe; Approva spento finché il testo non è stato visto fino in fondo |
| 1 stessa regola nella scheda | approvazioni.js, approvazioni.css | testo fino a 4000, avviso dei tagli, Approva spento finché «Dettagli» non è aperto e letto fino in fondo |
| 2 F2 service worker del Mac | sw.js | in cache solo `/static/…` senza `no-store`; «/», `/vps-fuori/`, `/api/`, `/assistenza`, `/term/` mai; senza rete la paginetta «Jarvis non risponde»; cache `jarvis-cc-v13`, le vecchie cancellate all'attivazione |
| 3 F3 registro | registro.js, registro.css | eventi con data non numerica, negativa, prima del 2000 o oltre un anno nel futuro scartati e contati («N eventi scartati per data non valida»); una scheda che non si disegna non ferma le altre |
| 4 F4 colore | app.js | `coloreSicuro()`: solo #rgb/#rrggbb/#rrggbbaa, rgb()/hsl() con numeri, 30 nomi; il resto diventa il colore dello spazio; la tavolozza dell'avatar solo da #rrggbb |
| 5 R3 tasti e rischio alto | approvazioni.js, chiamata.js | «a»/«r» solo con la scheda a fuoco; «a» disattivato sul rischio alto; secondo tocco valido solo fra 0,8 e 5 s dal primo |
| 6 R4 voce | chiamata.js, chiamata.css | dopo la frase 2 s di conto alla rovescia con «Annulla» e «Invia subito» (letto dagli screen reader); «sì approva», «approvo», «autorizzo»… non partono da sole e non approvano mai: restano testo |
| 7 R6 conversazioni | ponte.js, app.js, fili.js | con 401 su /api/* o /_ponte/stato, rinvio a /_ponte/entra, o clic verso /_ponte/esci: via `cc.fili`, `cc.chatCon`, `cc.fili-da-parte`, `cc.fili-lasciati`, `cc.fili-tolti`, `cc.fili-visto`, `cc.fili-ripartiti` e le cache `jarvis-cc*`; app.js e fili.js non le riscrivono più |
| 8 R7 schermo | computer.js | uscendo da #schermo o con la scheda nascosta: blob revocato, `<img>` vuota, variabile azzerata |
| in più | chiamata.js | `quandoPonte(monta)` stava prima di `let btn`: ReferenceError «Cannot access 'btn' before initialization» (visto in prova_computer su iPhone) |
| in più | mobile.css | interruttore del modo nel ponte sul telefono: bersagli da 40 px (erano 36) |

Controllo statico di innerHTML/insertAdjacentHTML sui file toccati: solo icone SVG fisse (ponte.js, chiamata.js, mobile.js),
`elenco.innerHTML = ""` in app.js e l'avatar SVG costruito con numeri (colori da `hslAHex`). Nessun dato del server.

Prove che cambiano per definizione (aggiornate): `prova_chiamata.js` (frase: 1,5 s + 2 s di conto alla rovescia;
secondo tocco dopo 0,9 s; «sì approva» resta testo; /_ponte/stato chiesto anche da computer.js), `prova_approvazioni.js`
(prima di Approva si leggono i Dettagli; secondo tocco dopo 0,8 s; non raddoppia più le righe già in index.html),
`prova_mobile.js` (/_ponte/stato chiesto anche da computer.js; nel ponte l'interruttore del modo c'è).

Da copiare (con backup, come sopra): `app.js ponte.js mobile.css chiamata.js chiamata.css approvazioni.js approvazioni.css
registro.js registro.css computer.js fili.js sw.js`.

## 7. Ripresa 2026-10-04 00:10: prestazioni, temi, maniglia

- `perf-dev/app-perf.diff` (ETag e avvisi del flusso) e `perf-dev/chiamata-corsa.diff` applicati con `patch -p0`
  sulle copie, DOPO le correzioni della revisione: si applicano puliti; il secondo cambia solo il commento della
  stessa correzione di `btn` già fatta qui.
- Temi: in `index.html` lo snippet di 5 righe nel `<head>` prima di `app.css`, `temi.css` dopo `registro.css`,
  `temi.js` dopo `fili.js` (INTEGRA-TEMI.md). `cc.tema` è una preferenza: alla sessione scaduta resta.
- Server: il nome della VPS («VPS del provider») finiva DENTRO il pulsante della maniglia `⠿` (`firstChild` dopo
  `boxInit`). Ora si cambia il primo nodo di testo del titolo: sul Mac il titolo diventa «⠿ VPS del provider letto
  alle …» al posto di «VPS del provider(in grigio, nella maniglia) Server remoto».
- Ritocchi di colore dello Scuro (`--tenue` .48 → .52, rosso testo `#f0587f`): NON applicati. Cambiano l'aspetto
  di ogni testo secondario dello Scuro di oggi (non è una correzione invisibile) e, secondo INTEGRA-TEMI.md, porterebbero
  sopra 4,5:1 «quasi tutti» i 2.397 casi, non tutti: lo Scuro non diventerebbe comunque conforme AA. Decide l'utente.
- Le prove servono ora TUTTI i file di `static-nuova/` (prima prova_mobile, prova_chiamata, prova_computer,
  prova_approvazioni prendevano dai file vivi chiamata.js, computer.js, registro.js, fili.js…).
  `prova_temi.js --copie` prova i temi sulle copie (pagina e file da static-nuova/).

## 8. Sì in due tempi per il rischio alto (2026-10-04 02:20, revisione 3 dei permessi)

- `registro-dev/approvazioni-js-due-tempi.patch` applicata pulita sulla copia (il risultato è identico a
  `registro-dev/approvazioni.js`): al primo tocco su un rischio alto `{tipo:"approva", id, decisione:"si",
  fase:"prepara"}`, al secondo (dopo 0,8 s, entro 5 s) il «sì» con `codice`; 428 = messaggio e si rifà.
  Restano tutte le protezioni della revisione 2 (testo intero, Approva spento finché non è letto, tasto A
  solo per rischio basso e medio, secondo tocco solo dopo 0,8 s).
- `chiamata.js`: lo stesso protocollo (`preparaSi()`, codice nel «sì», 428 gestito nella scheda della chiamata).
- Prove: il server finto di `prova_approvazioni.js`, `prova_chiamata.js` e `prova_revisione2.js` risponde a
  «prepara» con un codice e rifiuta con 428 il «sì» del rischio alto senza codice giusto o fuori tempo;
  `prova_coerenza.js` usa il filtro vero di `cc_ponte.py` con le regole di `ponte-due-tempi.patch` (fase, codice),
  finché il master non applica la patch al ponte.
- Ponte: con `cc_ponte.py` di oggi (senza `ponte-due-tempi.patch`) il «prepara» dal sito prende 400 «campi non
  ammessi»: va applicata insieme a questi file.

Ultimi file da copiare (tutti, con backup): `index.html app.js ponte.js mobile.css chiamata.js chiamata.css
approvazioni.js approvazioni.css registro.js registro.css computer.js fili.js sw.js temi.css temi.js`.
