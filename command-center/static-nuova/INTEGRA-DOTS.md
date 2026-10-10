# Integrare i Dots: le mascotte di OpenDots al posto dei volti

*2026-10-04 02:55 · cc-dots-opus · richiesta dell'utente: «usa i dots avatar nel nostro Jarvis CRM»*

Solo file nuovi, nessun file esistente toccato (`static/`, `server.py`, `app.js`, `index.html` e gli altri
di `static-nuova/` restano come sono):

| File | Cosa |
|---|---|
| `dots.js` (27 KB) | avvolge `window.avatar` di app.js, MutationObserver per il resto, interruttore «Avatar», `window.CCDots` |
| `dots.css` (10 KB) | cosa si vede per ogni scelta, Jarvis con l'anello, stati, movimento, controllo «Avatar» |
| `dots/` | 4 colori × 64/128 px PNG, 256 px WebP senza perdita, 256 px PNG di riserva; `LICENSE-OpenDots.txt` (MIT, Atai Barkai); `README-DOTS.md` |
| `../../vps/cc-ponte/prove-mobile/prova_dots.js` | le prove con Chrome headless |

Immagini e scelta del colore vengono da CopilotKit/OpenDots, licenza MIT. Uso interno dell'utente: non si
distribuiscono né si vendono (dettagli in `dots/README-DOTS.md`).

## 1. Le righe per index.html

Due righe, dopo quelle dei temi (il menu «Avatar» si monta dentro il menu dei temi):

```html
<link rel="stylesheet" href="/static/temi.css">
<link rel="stylesheet" href="/static/dots.css">                  <!-- NUOVA -->
...
<script src="/static/temi.js" defer></script>
<script src="/static/dots.js" defer></script>                    <!-- NUOVA -->
```

`dots.js` deve venire **dopo** `app.js` (che è senza `defer`: va sempre bene) e dopo `temi.js`. Senza `temi.js`
funziona lo stesso: mette un suo pulsante accanto allo stato generale sul desktop.

Copia nei file vivi (quando l'utente dice sì): `dots.js`, `dots.css` e la cartella `dots/` in `static/`, più le due
righe sopra in `static/index.html`. `server.py` non va riavviato: serve qualunque file sotto `static/`,
sottocartelle comprese (`_do_get`, `STATIC in f.parents`). Facoltativo: `dots.js` e `dots.css` nel `GUSCIO` di `sw.js`.

## 2. Come funziona

- **Colore**: lo stesso hash di OpenDots (`Mascot.tsx`: `hash = (hash*31 + codice) >>> 0`, `hash % 4` in ordine
  blue, mint, orange, purple) sulla chiave dell'agente `progetto:nome` (`a.key`, quella che usa tutta la pagina:
  righe `data-agente`, nodi della lavagna, `chatCon`). Nota: il volto «beam» di oggi usa come seme il **ruolo**
  (`ruoloDi(a).cat`), quindi due «seo» hanno la stessa faccia; con quel seme 48 agenti avrebbero dato pochi colori
  e agenti diversi uguali. La chiave è stabile come il ruolo (stessa dopo ricarica, in ogni vista) e distingue
  gli agenti. La catena «Claude adesso» passa `catena:<nome>`: se il nome è di un agente vero prende il suo Dot.
- **Jarvis**: sempre il viola (`purple`), dentro un anello sottile del colore d'accento del tema.
- **Senza toccare app.js**: `function avatar` è una dichiarazione globale di uno script classico, quindi
  `window.avatar = avvolta` cambia anche le chiamate dentro app.js (provato: «window.avatar avvolta» PASS). La
  funzione originale disegna il volto come oggi, poi si aggiungono `<img class="dot-img">` e `<span class="dot-ini">`.
  Quale dei tre si vede lo decide il CSS da `<html data-avatar="dots|volti|iniziali">`: il cambio a caldo è un
  attributo, senza ridisegnare niente. Un MutationObserver (solo `childList`, raccoglie le misure in un solo giro)
  copre quello che app.js e gli altri script disegnano da soli.
- **Immagini**: un solo scaricamento per file. `server.py` manda tutto `/static/` con `Cache-Control: no-store`,
  quindi ogni `<img>` riscaricava il file (misurato: 50 richieste di `blue-64.png` con 50 agenti). `dots.js`
  scarica ogni file una volta con `fetch()` e lo dà a tutti gli `<img>` come `blob:`. La misura la sceglie
  `dots.js` (al posto di `srcset`, che avrebbe riscaricato): avatar fino a 48 px → 64 px su schermi 1x,
  128 px su 2x/3x; da 49 a 100 px → 128/256; oltre → 256. Con Volti e Iniziali non si scarica niente.
  Nessuna richiesta esterna; dietro il ponte passano come il resto, col cookie di sessione.
- **Stati** (solo `transform`, solo dentro `@media (prefers-reduced-motion: no-preference)`, spenti anche
  dall'interruttore «Dots in movimento»):

| Stato | Da dove lo legge | Cosa fa |
|---|---|---|
| riposo | sempre | respiro lentissimo (scala 1 → 1,025 in 7 s); fermo nei messaggi della chat e nel registro |
| lavora | `.al-lavoro`, `[data-agente].attivo`, `.catena li.attivo`, `.nodo.al-lavoro`, `.lav-avatar.in-corso`, voce `thinking`, chiamata `lavora` | oscilla (su e giù di 7%, ±3°, 1,8 s); il pallino verde di app.css resta, l'anello che gira no |
| ascolta | voce `listening`, chiamata `ascolto`/`sente` | respiro più ampio (2,6 s) |
| parla | voce `speaking`, chiamata `parla` | dondola (±3°, 0,9 s) |
| allarme | lavoro dell'agente finito in `errore` negli ultimi 30 minuti (`ultimiLavori`), `.lav-avatar.errore`, chiamata `fermo`, `CCDots.allarme(chi)` | puntino rosso col «!» in alto a destra e `title="in errore"`; uno scuotimento solo, la prima volta per agente |
| fuori servizio | `.agente.spento`, `.nodo.spento`, `.scheda-agente.spento`, `.agente.archiviato`, `a.attivo === false` | `saturate(.4)`, opacità 0,8, fermo |

- **Temi**: ombra morbida sotto (`drop-shadow` 1,5 px), più chiara sui temi chiaro/claude; niente alone.
- **Preferenza**: `localStorage["cc.avatar"]` = `volti` | `iniziali` (Dots = chiave tolta), sempre in try/catch:
  se `localStorage` lancia restano i Dots e il cambio vale per la pagina aperta. `cc.avatar.fermi = "1"` ferma
  il movimento. Un'altra scheda che cambia scelta fa cambiare anche questa (evento `storage`).
- **Controllo «Avatar»**: desktop, in fondo al menu dei temi (pulsante a pallini accanto allo stato), sezione
  «Avatar» con tre `role="radio"` (Dots, Volti, Iniziali, con anteprima) e la casella «Dots in movimento».
  Tastiera: dal gruppo dei temi Tab porta agli avatar (temi.js chiuderebbe il menu: il Tab fra i due gruppi è
  intercettato), frecce e Home/Fine scelgono, Esc chiude. Telefono: riga «Avatar» nel foglio «Altro», sotto «Tema»,
  scelte da 62×44 px.
- `window.CCDots`: `colore(id)`, `modo()`, `elenco()`, `scegli(id)`, `fermi(bool)`, `allarme(chi, bool)`,
  `risolvi(nome|chiave)`, `avvolta()`. Evento `cc-avatar` su `window` a ogni cambio.

## 3. Punto per punto: prima e dopo (con «Dots»)

| Punto | Prima | Dopo |
|---|---|---|
| Lavagna, nodi degli agenti e capogruppo | volto «beam» del ruolo, tondo, 32-40 px | Dot dell'agente nello stesso spazio, senza cerchio; i fili non cambiano (stessa misura dello span) |
| Lavagna, nota «Jarvis — orchestratore» | solo testo | Dot viola da 32 px appoggiato sopra l'angolo in alto a sinistra (assoluto: la nota non cambia misura, non prende i clic) |
| Lavagna, riquadri (note) | invariati | invariati |
| Colonna sinistra «Squadra» | volto 40 px | Dot 40 px; spento = desaturato |
| Testa della chat | volto 72 px (36/30 sul telefono) o «J» | Dot dell'agente; con Jarvis il viola con l'anello |
| Messaggi della chat | volto 26 px o «J» | Dot 26 px (fermo); i comandi «/» restano «/» |
| «sta lavorando» | volto accanto alla bolla | Dot; nella testa e nella colonna oscilla col pallino verde |
| Lavori (Stato), avatarino | lettera nel cerchio che gira | Dot dell'agente (o di Jarvis) che oscilla; «sentinella», giri e verifiche restano lettera (non sono agenti); errore = «!» |
| Scheda di approvazione | «ceo-ai · Bash» solo testo | Dot 24 px dell'agente prima del nome (in chat, nel vassoio e sulla lavagna) |
| Chiamata | «J» nel cerchio 148/180/96 px | Dot viola al 76% del cerchio; onde e anello della fase restano; respira in ascolto, dondola quando parla, oscilla quando lavora, «!» e uno scuotimento se il microfono si ferma |
| Agenti («Claude adesso», catena 48 px) | «J» per Jarvis, volti per gli altri | Jarvis viola con l'anello, Dot per esecutore, postino, ricercatore-web… |
| Scheda agente | volto 72 px | Dot 72 px (256 px su 2x) |
| Scheda nota di casa (jarvis, esecutore…) | iniziale | Dot (Jarvis viola); «memoria» resta lettera |
| Registro | nessun avatar | Dot 22 px prima della fonte quando i dettagli hanno «Agente» (schede) |
| Missioni | nessun avatar oggi | invariato (nessun pixel diverso con Volti) |
| Barra in alto, avatar di Jarvis | «J» nel cerchio 36 px | Dot viola nel cerchio; il cerchio tiene luce e stato della voce; con la voce spenta il Dot resta pieno |
| Badge «Mac acceso» del ponte | accanto all'avatar di Jarvis | invariato: il cerchio ha la stessa misura |
| Foglio «Altro» e barra in basso (telefono) | — | riga «Avatar» in fondo al foglio; la barra in basso non ha avatar e non cambia |
| Archiviati / fantasmi della colonna | ⌫ 👻 📁 | invariati (non sono agenti con un'identità) |

Con «Volti» la pagina è quella di oggi (prova pixel per pixel, sotto). Con «Iniziali» due lettere dal nome dato da
L'utente (`nomeDi`), dentro il cerchio colorato di oggi; Jarvis «J».

## 4. Diff proposti (NON applicati)

Nessuno è necessario per funzionare. Due migliorie, da decidere:

1. `server.py`, `TIPI` (riga ~6572): il WebP oggi esce come `application/octet-stream`. Chrome lo apre lo stesso
   (passa dal blob con il tipo giusto, provato), ma è più pulito dichiararlo:
   ```diff
   -        ".png": "image/png", ".webmanifest": "application/manifest+json"}
   +        ".png": "image/png", ".webp": "image/webp", ".webmanifest": "application/manifest+json"}
   ```
2. `server.py`, `_do_get` (riga ~6761): oggi ogni file di `/static/` è `no-store`, quindi a ogni ricarica i Dots
   (52-155 KB) si riscaricano. Le immagini non hanno segreti: per `/static/dots/` si può mettere una cache di un giorno.
   ```diff
   -                return self._invia(200, f.read_bytes(), TIPI.get(f.suffix, "application/octet-stream"))
   +                cache = [("Cache-Control", "public, max-age=86400")] if "dots" in f.parent.parts else []
   +                return self._invia(200, f.read_bytes(), TIPI.get(f.suffix, "application/octet-stream"), intestazioni=cache)
   ```
   Attenzione: `_invia` scrive sempre `no-store` prima delle intestazioni extra; servirebbe anche lì di non mettere
   il `no-store` quando ne arriva un altro. Va fatto da chi tiene `server.py`, con riavvio deciso dall'utente.

## 5. Esito delle prove (2026-10-04 02:54, `node vps/cc-ponte/prove-mobile/prova_dots.js`)

**Totale: 47/47 PASS** (ultimo giro intero). Schermate (84 + 12 della chiamata grande) in
`~/.locale-onedrive/cc-ponte/schermate/dots/<desktop|iphone>/<tema>/`, guardate a mano: lavagna, chat, squadra,
chiamata, approvazione, registro, agenti, scheda, foglio «Altro», nei temi scuro, chiaro, claude e nero, a
1440×900 e 390×844. Corretto dopo averle guardate: il Dot della nota «Jarvis» copriva la J del testo (spostato
sopra la nota).

- Distribuzione sui **48 agenti veri**: blue 14, mint 11, orange 11, purple 12 (più Jarvis, viola fisso).
- Stesso Dot fra colonna, lavagna, Agenti e testa della chat, e dopo la ricarica: 48 agenti, nessun doppio.
- Richieste e peso per un caricamento con lavagna, Agenti e chat: desktop 1x 5 file, 51,8 KB
  (4 × 64 px + viola 128 della testa); Mac retina 5 file, 155,1 KB (4 × 128 px + viola 256 WebP);
  iPhone 3x 4 file, 92,7 KB. Ogni file scaricato una volta sola.
- Peso aggiunto su disco: `dots.js` 27 KB + `dots.css` 10 KB + immagini 736 KB (di cui 356 KB di PNG 256 di riserva,
  che Chrome non scarica mai).
- Volti = oggi: **0 pixel diversi dentro avatar, nodi della lavagna e schede** in chat, lavagna, Stato, Agenti,
  Missioni e scheda agente. Fuori dagli avatar l'unica differenza è in Agenti, 329 pixel nel testo «attivo da…»
  della catena (fra due caricamenti di oggi: 577). I giri precedenti, senza il doppio confronto, avevano dato
  FAIL per lo stesso motivo (dati vivi cambiati fra un caricamento e l'altro): la prova ora confronta con due
  caricamenti di oggi.
- Lavagna con 57 nodi, 4 giri: da 17,6 → 20,2 ms (+15%) a 22,2 → 21,8 ms (−2%) per disegno: sempre sotto il +20%.
- `prefers-reduced-motion`: 0 animazioni su 155 Dot. Cambio a caldo da mouse e da tastiera, persistenza, ritorno
  a Dots, telefono, `localStorage` bloccato: PASS. Nessuno scorrimento orizzontale, nessun Dot rotto o deformato,
  nessun errore in console, nessuna richiesta esterna, `pannello.json` alla stessa versione (v682).

## 6. Cosa non ho potuto provare

- Safari vero (iPhone): provato solo Chrome con lo user agent di Safari. Il WebP passa da un blob con tipo
  `image/webp` (Safari lo apre dalla 14); se non si apre c'è il PNG da 256 di riserva.
- Il ponte vero sulla VPS: le immagini sono GET normali sotto `/static/`, che il ponte passa dopo il login come
  gli altri file; non l'ho provato da fuori casa.
- Gli stati veri in diretta (un agente che lavora o va in errore davvero): provati forzando le classi e i dati
  nella pagina, non con un lavoro vero.
- Uno screen reader vero: gli avatar restano `aria-hidden` come oggi (il nome è sempre nel testo accanto).

## 7. Rischi

- Il sistema dipende dai nomi globali di app.js (`avatar`, `AGENTI`, `chatCon`, `schedaKey`, `schedaCasaNome`,
  `ultimiLavori`, `nomeDi`) e dalle classi `.avatar`, `.lav-avatar`, `.aj-cerchio`, `.chm-avatar`, `.apv-chi`,
  `.rg-dettagli`. Se uno cambia nome, quel punto torna semplicemente al volto di oggi (tutto è in try/catch);
  `prova_dots.js` lo segnala.
- `static-nuova/app.js` e gli altri file sono in modifica da altri lavori: le prove sono state fatte sui file di
  stanotte (02:23). Da rilanciare dopo che quei lavori sono chiusi.
- Il colore dipende dalla chiave `progetto:nome`: rinominare la cartella di progetto o il profilo cambia il Dot
  (rinominare dal pannello con «Nome da mostrare» no).
- L'allarme si vede solo per i lavori che la pagina conosce (`/api/stato`), entro 30 minuti.
