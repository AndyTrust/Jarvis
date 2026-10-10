# Integrare i temi: Scuro, Nero, Chiaro, Claude, Automatico

*2026-10-03 · cc-temi-opus · richiesta dell'utente: «inserisci anche i temi nero, chiaro e Claude»*

Tre file nuovi in `command-center/static-nuova/`: `temi.css`, `temi.js` e questo. Nessun file vivo toccato
(`static/`, `server.py`, `cc_ponte.py` restano come sono). Prova: `vps/cc-ponte/prove-mobile/prova_temi.js`.

| Tema | Per chi | Fondo · testo · accento |
|---|---|---|
| Scuro (predefinito) | quello di oggi, identico ai pixel | `#141414`/`#181818` · `#f0f0f0` · `#599ce7` |
| Nero | schermi OLED, notte | `#000` · `#fff` · `#6aaefc`, bordi bianchi al 15-38% |
| Chiaro | sole sul telefono | `#eceef2`/`#f7f8fa`, riquadri bianchi · `#111418` · `#1a52a8` |
| Claude | aspetto caldo di Claude | crema `#faf9f5`/`#f0eee6`, avorio `#fff` · `#1f1e1b` · terracotta `#b4532f` (pulsanti), `#a64f2d` (testo), `#c6613f` (bordi, logo); titoli e risposte di Jarvis con le grazie di sistema (`ui-serif`, New York, Iowan, Charter, Georgia) |
| Automatico | chi vuole seguire il sistema | Chiaro di giorno, Scuro di sera; cambia a pagina aperta |

## 1. Le righe da aggiungere a `index.html`

**a) Nel `<head>`, subito PRIMA di `<link rel="stylesheet" href="/static/app.css">`** (5 righe). Applica il tema
prima che il browser legga i fogli di stile: niente lampo del tema sbagliato. Legge `cc.tema` dentro try/catch
(se `localStorage` lancia resta Scuro), accetta solo i cinque valori, con «auto» mette anche `data-auto`.
Lo stesso blocco lo usa la prova (lo legge da qui fra i due commenti `temi`).

```html
<!-- temi: snippet -->
<script>/* tema prima dei fogli di stile: niente lampo del tema sbagliato (temi.js, INTEGRA-TEMI.md) */
(function(){var d=document.documentElement,t="scuro";try{t=localStorage.getItem("cc.tema")||"scuro"}catch(e){}
if(!/^(scuro|nero|chiaro|claude|auto)$/.test(t))t="scuro";d.setAttribute("data-tema",t);
if(t==="auto"){var c=false;try{c=matchMedia("(prefers-color-scheme: light)").matches}catch(e){}d.setAttribute("data-auto",c?"chiaro":"scuro")}})();
</script>
<!-- /temi -->
```

La pagina ha già uno script in linea (`window.CC_TOKEN`) e né `server.py` né il ponte mettono una CSP sulla
pagina del pannello: lo snippet non chiede altro. Se un giorno arriva una CSP, serve il suo hash.

**b) Nel `<head>`, DOPO l'ultimo foglio** (`registro.css`), così vince sugli altri:

```html
<link rel="stylesheet" href="/static/temi.css">
```

**c) In fondo, dopo `<script src="/static/fili.js" defer></script>`:**

```html
<script src="/static/temi.js" defer></script>
```

Facoltativo: `temi.css` e `temi.js` in `GUSCIO` di `static/sw.js` (alzando `CACHE`), come per gli altri file nuovi.
Il `<meta name="theme-color" content="#141414">` resta: lo aggiorna `temi.js`.

## 2. Come funziona

- **Un solo interruttore**: `<html data-tema="scuro|nero|chiaro|claude|auto">`. Con `auto` c'è anche
  `data-auto="chiaro|scuro"`, che `temi.js` aggiorna con `matchMedia('(prefers-color-scheme: light)')`.
  `data-auto` evita di copiare due volte la palette Chiara (una per «chiaro», una per «auto» di giorno): i
  selettori sono `:root:is([data-tema="chiaro"], [data-tema="auto"][data-auto="chiaro"])`.
- **Scuro non cambia di un pixel**: ogni regola di `temi.css` sta sotto `:root[data-tema=…]` di un tema diverso
  da Scuro. Le uniche regole senza tema sono quelle del selettore (`.tema-*`), elementi che prima non c'erano.
- **Palette**: ogni tema ridefinisce le variabili di `app.css` (`--chrome --fondo --rialzo --rialzo-2 --testo
  --testo-2 --tenue --linea* --hover --attivo --accento* --verde --giallo --rosso --viola --arancio --grigio`)
  e `color-scheme` (light o dark: barre di scorrimento, `select`, `meter`, caselle native).
- **Colori scritti a mano**: passano da variabili nuove `--t-*` con un override per componente (tabella qui sotto).
- **Preferenza**: `localStorage["cc.tema"]`, sempre in try/catch. Scuro cancella la chiave (torna al predefinito).
  Un'altra scheda che cambia tema fa cambiare anche questa (evento `storage`).
- **`<meta name="theme-color">`**: `#141414`, `#000000`, `#eceef2`, `#f0eee6` (Automatico: quello del tema effettivo).
- **Selettore**: sul desktop un pulsante a pallini nella barra in alto, subito prima dello stato generale
  (sopra 1700 px mostra anche il nome). Apre un menu `role="radiogroup"` con cinque `role="radio"` e l'anteprima a
  tre pallini (fondo, testo, accento). Tastiera: Invio o Spazio apre, frecce e Home/Fine scelgono (e applicano),
  Esc chiude e torna al pulsante, Tab chiude. `aria-label` in italiano («Tema dei colori: Claude. Cambia tema»).
  Sul telefono (≤ 820 px) il pulsante in alto non c'è: c'è la riga «Tema» in fondo al foglio «Altro»
  (stesso radiogroup, cinque scelte da 44 px). Il foglio resta aperto: si vede subito il risultato.
- `window.CCTemi`: `tema()`, `effettivo()`, `elenco()`, `scegli(id)`, `apriMenu(bool)`. Evento `cc-tema` su
  `window` a ogni cambio. Nessuna dipendenza, nessuna richiesta di rete, nessun font da internet.

## 3. Inventario dei colori e come li copro

### Variabili di `app.css` (`:root`)
Coperte tutte dalle palette. I file aggiunti (`approvazioni.css`, `attivita.css`, `chiamata.css`, `computer.css`,
`registro.css`) usano `var(--x, ripiego)`: seguono il tema senza override, salvo le righe sotto.

### Colori scritti a mano (CSS)

| Dove | Colore fisso | Problema sul chiaro / sul nero | Override in `temi.css` |
|---|---|---|---|
| `app.css` `::selection` | `rgba(89,156,231,.4)` | tinta sbagliata | `--t-sel` |
| `button.primario`, `.invia`, `approvazioni.css .apv-si`, `computer.css .pc-primario` | fondo `var(--testo)`, testo `#111`, hover `#fff` | sul chiaro testo nero su fondo nero | `--t-primario`, `--t-su-primario`, `--t-primario-hover` (Claude: terracotta col bianco) |
| `.logo-nome::first-letter`, `mobile.css .m-marca b::first-letter` | `#8fa8f0` | 2:1 sul chiaro | `--t-logo-j` |
| `.avatar-j` e `style="--c:#f0f0f0"` scritto da `app.js` (avatar «J» nei messaggi) | `#f0f0f0` | cerchio invisibile sul chiaro | `--c: var(--t-j) !important` (batte lo stile in linea) |
| `body::before` (aurora) | due `radial-gradient` blu/viola | Nero non è più nero | `--t-aurora` (Nero: niente; chiari: leggerissima) |
| `.centro` `.lato` `.avatar-jarvis` | `rgba(24,24,24,.72)`, `rgba(20,20,20,.82)`, `rgba(20,20,20,.6)` | fondo scuro fisso | `--t-centro`, `--t-lato`, `--t-vetro` |
| `.aj-cerchio`, `.cuore` (sfera di Stato), `mobile.css .ponte-mic-grande` | `radial-gradient(#2c3440,#111418)`, `(#2c2c2c,#151515)` | palla scura sul chiaro | `--t-aj`, `--t-cuore` |
| `.modo-chat [data-modo=lavoro].attivo` | testo `#bff0d0` | 1,3:1 sul chiaro | `--t-verde-testo` |
| `.bolla-scrive` e puntini | `#121418`, `#7fb3ee` | bolla nera | `--t-bolla`, `--t-puntini` |
| ombre `rgba(0,0,0,.35–.6)` (suggerimenti, toast, finestre, vassoio, schede della lavagna, foglio, cassetto) | nere pesanti | sporcano il chiaro | `--t-ombra`, `--t-ombra-forte`; velo delle finestre `rgba(17,20,24,.38)` |
| `.switch` (binario `#101010`, pomello `#d8d8d8`, `--luce` 89,156,231) e `mobile.css .switch::before` | binario nero | sul chiaro sembra acceso; luce a 2,9:1 | `--t-switch`, `--t-switch-bordo` (≥ 3:1), `--t-pomello`; `--luce` più scura (anche telefono, tecnico, `#sa-attivo`) |
| `mobile.css` caselle e pallini (SVG in `data:` con `#141414`, `#888`, `#599ce7`) | fissi nell'SVG | casella nera sul chiaro | SVG per Nero, Chiaro (blu) e Claude (terracotta) |
| `mobile.css .lato` `#141414`, `.m-schede` `rgba(18,18,18,.96)`, veli `rgba(0,0,0,.5)` | scuri | barra in basso nera | `var(--chrome)`, `--t-barra-sotto`, velo più leggero |
| `.lavagna` puntini `rgba(240,240,240,.09)`, `.lavagna.sopra` `#1b1f26` | chiari | puntini invisibili | `--t-griglia`, `--t-lavagna-sopra` |
| `.lav-fili path` `var(--linea-3)`, frecce | fili deboli | sotto 3:1 sul chiaro | `--t-filo` (`#858b95` su `#f7f8fa`); `.sinapsi.risposta` `#3fa266` → `var(--verde)` |
| `.nodo.nota` `#2a2618`, `.nodo.nota.colorata .testo-nota` `color-mix(--c 55%, #fff)` | nota marrone, testo quasi bianco | illeggibile sul chiaro | `--t-nota`; testo `color-mix(--c 45%, #000)` |
| `#lav-demo.attivo`, `.lav-demo-badge`, `.lav-mod-badge` (`#1a1206` su giallo), `.demo-via` (`#0d1520` su accento), `computer.css .pc-avviso-ico`/`.pc-nascondi` (`#1a1405` su giallo) | testo scuro su giallo/blu | il giallo e il blu del chiaro sono scuri | `--t-su-giallo`, `--t-su-accento` (bianco) |
| `.sinapsi-bolla` `#121418`, `.lav-barra` `rgba(240,240,240,.08)`, `.lav-avatar.in-corso::before` (interno scuro) | scuri | — | `--t-bolla`, `var(--linea)`, `--t-dentro-lavoro` |
| `.lista-eventi .ev-finito` `#9fdcb6`, `.ev-errore` `#f3a3b9` | pastello | 1,5:1 sul chiaro | `--t-verde-testo`, `--t-rosso-testo` |
| `.repo-badge.public` `#e5b454`, `.repo-stato.ok` `#3fa266`, `.attenzione` `#e5b454` | fissi | 1,8:1 sul chiaro | `var(--giallo)`, `var(--verde)` |
| `.schede a.tecnico` `color-mix(arancio 70%, transparent)` | trasparente | 3,6:1 sul chiaro | `var(--arancio)` |
| `.maniglia-box` opacità .45 | — | in Server il titolo «VPS del provider» finisce DENTRO la maniglia (vedi rischi) e scende a 2,5:1 | opacità 1 nei temi nuovi |
| `mobile.css .ponte-badge.spento` `#f3a3b9`, `.ponte-modo.lavoro` `#bff0d0`, `.approvazione` `#f5d9a8`, `.ponte-nota.errore`, `.ponte-avviso` `#f6c0cf`, `.ponte-velo-voce` `rgba(14,14,14,.97)` | pastello e scuri | illeggibili sul chiaro | `--t-*-testo`, `--t-rosso-chiaro`, `--t-velo-voce` |
| `approvazioni.css .apv-lav-box` `rgba(20,20,20,.94)` | scuro | — | `--t-vassoio-lav` |
| `chiamata.css .chm-avatar` (40% del colore di fase), `.chiamata-pillola.chm-pil-permesso` (`#111` su giallo scurito), `.chm-p-si` | — | centro marrone, testo nero su marrone | gradiente al 14%, testo bianco, `var(--verde)` |
| Nero: pulsanti pieni rossi e verdi col bianco (`.assist-stop`, `.ponte-stop`, `.ponte-mic.ascolta`, `.chm-chiudi`, `.lav-x-filo`, `.apv-conferma`, `.chm-p-si`, `.chiamata-pillola`) | `var(--rosso)`/`var(--verde)` | il rosso e il verde del Nero sono chiari (per il testo): bianco sopra a 2,3–3:1 | fondo `#c81e50` / `#1a7f45` (5,6 e 5:1) |
| Claude | — | — | titoli (`h2`, chat, schede, foglio, registro, approvazioni, chiamata) e risposte di Jarvis in `--t-serif`; codice resta monospazio; campo di scrittura più morbido |

### Colori negli script e nel DOM
| Dove | Cosa | Come |
|---|---|---|
| `app.js` `COLORE_SPAZIO`, `DEMO.colori`, avatar «beam» (SVG con `fill` in linea, `contrastoDi()`) | colori degli spazi e dei volti | restano: sono identità, con il loro contrasto interno (bianco o nero calcolato); su fondo chiaro reggono |
| `app.js` `style="--c:#f0f0f0"` / `--c:#5a5a5a` sugli avatar in chat | J chiara, «/» grigio | J: override sopra; grigio va bene ovunque |
| `app.js` stili in linea della chat a voce in Stato, `style:"cursor:default"`, `--liv`, larghezze | usano già `var(--…)` | niente da fare |
| `index.html` marker SVG delle frecce `fill="#599ce7"`/`#3fa266"` | coperti da `.lav-fili marker path { fill }` di `app.css` e da `--t-filo` | — |
| `mobile.js`, `chiamata.js`, `ponte.js` icone SVG | `currentColor` | seguono il testo |
| grafici | nel pannello non c'è canvas: barre `meter` (native, seguono `color-scheme`), `.lav-barra`, spie | coperti |
| terminale (`ttyd`), desktop VPS (noVNC), schermo del Mac (`computer.js`) | iframe e immagini | restano scuri: sono il contenuto di un'altra macchina; la cornice segue il tema |
| suggerimenti (`title`) | tooltip del sistema | li disegna il browser |

## 4. Pagine del ponte (accesso, «Mac non raggiungibile», emergenza del service worker)

Oggi `STILE` di `cc_ponte.py` segue solo `prefers-color-scheme`. Il diff qui sotto fa leggere alle tre pagine la
stessa `cc.tema` (stesso sito del pannello) con le stesse palette. Scelta di sicurezza: uno **script fisso** di una
riga, ammesso dalla CSP **solo con il suo hash SHA-256** (`script-src 'sha256-…'`, calcolato da Python all'avvio
dal testo stesso: se qualcuno lo cambia, l'hash cambia con lui). Niente `'unsafe-inline'`, niente nonce da
generare a ogni risposta; ogni altro script in linea e ogni attributo `on…` resta bloccato. Lo script accetta solo
`scuro|nero|chiaro|claude`: con «auto» o senza scelta resta il comportamento di oggi (`prefers-color-scheme`).
Imposta anche `theme-color`. La pagina di emergenza esce dal service worker senza CSP e ha già il suo script: lo
script del tema viaggia con lei. **Va applicato da chi ha in mano `cc_ponte.py`**; il diff è fatto sul file di
oggi (21:15) e la prova controlla ogni volta che si applichi ancora.

```bash
cd ~/Jarvis/vps/cc-ponte && cp cc_ponte.py cc_ponte.py.prima-temi
# il blocco qui sotto, salvato in /tmp/temi-ponte.patch
patch -p0 --dry-run -i /tmp/temi-ponte.patch && patch -p0 -i /tmp/temi-ponte.patch
python3 prova_cc_ponte.py      # sulla copia: tutto PASS (vedi esiti)
```
Il service worker del ponte cambia contenuto (la pagina di emergenza è dentro `SW_PONTE_JS`): se si vuole che i
telefoni lo riprendano subito, alzare anche `SW_VERSIONE`.

<!-- temi: ponte.patch -->
```diff
--- cc_ponte.py
+++ cc_ponte.py
@@ -184,7 +184,16 @@
              # «Origin: null» sul POST del form di accesso e il controllo dell'origine lo rifiutava.
              # same-origin manda l'Origin vero allo stesso sito e niente agli altri.
              ("Referrer-Policy", "same-origin"))
+# Tema delle pagine del ponte (2026-10-03): lo stesso «cc.tema» che il pannello salva nel localStorage
+# (stesso sito). Uno script fisso, ammesso dalla CSP solo col suo hash SHA-256: niente 'unsafe-inline',
+# nessun altro script può partire. Senza scelta, o con «auto», resta prefers-color-scheme come prima.
+SCRIPT_TEMA = ("(function(){try{var t=localStorage.getItem(\"cc.tema\"),m={scuro:\"#141414\",nero:\"#000000\","
+               "chiaro:\"#eceef2\",claude:\"#f0eee6\"};if(!m.hasOwnProperty(t))return;"
+               "document.documentElement.setAttribute(\"data-tema\",t);"
+               "var e=document.querySelector('meta[name=\"theme-color\"]');if(e)e.setAttribute(\"content\",m[t])}catch(e){}})();")
+HASH_TEMA = base64.b64encode(hashlib.sha256(SCRIPT_TEMA.encode("utf-8")).digest()).decode("ascii")
 CSP_PAGINE = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; manifest-src 'self'; "
+              f"script-src 'sha256-{HASH_TEMA}'; "
               "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
 
 # ---------------------------------------------------------------- web app installabile (2026-10-03)
@@ -542,6 +551,15 @@
 --bordo:#d4d4d8;--accento:#1d4ed8;--accento-testo:#fff;--errore:#b91c1c}
 @media (prefers-color-scheme:dark){:root{--sfondo:#121214;--carta:#1c1c1f;--testo:#f4f4f5;--tenue:#a1a1aa;
 --bordo:#3f3f46;--accento:#60a5fa;--accento-testo:#0b1220;--errore:#f87171}}
+:root[data-tema=scuro]{color-scheme:dark;--sfondo:#141414;--carta:#1f1f1f;--testo:#f0f0f0;--tenue:#b5b5b5;
+--bordo:#6e6e6e;--accento:#599ce7;--accento-testo:#0d1520;--errore:#f28aa5}
+:root[data-tema=nero]{color-scheme:dark;--sfondo:#000;--carta:#0b0b0b;--testo:#fff;--tenue:#b0b0b0;
+--bordo:#707070;--accento:#6aaefc;--accento-testo:#04101f;--errore:#ff8fab}
+:root[data-tema=chiaro]{color-scheme:light;--sfondo:#eceef2;--carta:#fff;--testo:#111418;--tenue:#575c65;
+--bordo:#7d838d;--accento:#1f5fbf;--accento-testo:#fff;--errore:#c0254f}
+:root[data-tema=claude]{color-scheme:light;--sfondo:#f0eee6;--carta:#faf9f5;--testo:#1f1e1b;--tenue:#5c584c;
+--bordo:#857f71;--accento:#b4532f;--accento-testo:#fff;--errore:#b3261e}
+:root[data-tema=claude] h1{font-family:ui-serif,"New York","Iowan Old Style",Charter,Georgia,serif;font-weight:600}
 *{box-sizing:border-box}
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;
 background:var(--sfondo);color:var(--testo);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@@ -567,7 +585,7 @@
             "<link rel=\"manifest\" href=\"/manifest.webmanifest\">"
             "<link rel=\"icon\" type=\"image/png\" sizes=\"32x32\" href=\"/static/icona-32.png\">"
             "<link rel=\"apple-touch-icon\" sizes=\"180x180\" href=\"/static/icona-180.png\">"
-            f"<title>{html.escape(titolo)}</title><style>{STILE}</style></head>"
+            f"<title>{html.escape(titolo)}</title><script>{SCRIPT_TEMA}</script><style>{STILE}</style></head>"
             f"<body><main>{corpo}</main></body></html>").encode("utf-8")
 
 
--- prova_cc_ponte.py
+++ prova_cc_ponte.py
@@ -371,7 +371,9 @@
         esito("pagina di accesso: 200, viewport, campo numerico one-time-code, un pulsante «Entra»",
               r.status == 200 and 'name="viewport"' in testo and 'inputmode="numeric"' in testo
               and 'autocomplete="one-time-code"' in testo and testo.count("<form") == 1 and ">Entra<" in testo
-              and "<script" not in testo and "prefers-color-scheme" in testo)
+              # un solo script: quello fisso del tema (cc.tema), ammesso dalla CSP col suo hash (temi, 2026-10-03)
+              and testo.count("<script") == 1 and f"<script>{cc_ponte.SCRIPT_TEMA}</script>" in testo
+              and f"script-src 'sha256-{cc_ponte.HASH_TEMA}'" in cc_ponte.CSP_PAGINE and "prefers-color-scheme" in testo)
         esito("pagina di accesso: no-store e intestazioni di sicurezza",
               "no-store" in intestazione(r, "Cache-Control") and "max-age" in intestazione(r, "Strict-Transport-Security")
               and intestazione(r, "X-Content-Type-Options") == "nosniff" and intestazione(r, "X-Frame-Options") == "DENY"
```
<!-- /temi -->

## 5. Esiti delle prove (2026-10-03, ultima corsa completa 22:07-22:20)

`node vps/cc-ponte/prove-mobile/prova_temi.js` → **33/33 PASS**, uscita 0. Chrome headless vero (puppeteer-core),
pagina viva in sola lettura, tutti i POST abortiti, versione di `pannello.json` uguale prima e dopo (v682).
Schermate: `~/.locale-onedrive/cc-ponte/schermate-temi/<tema>/<iphone14|desktop>/<pagina>.png`, misure in `giro.json`,
identità in `identita-scuro/`, ponte in `ponte/` (con l'uscita intera di `prova_cc_ponte.py` sulla copia).

| Gruppo | Esito |
|---|---|
| Giro: 4 temi × 31 pagine e finestre × 2 dispositivi (390×844 e 1440×900), 236 viste | Nero, Chiaro, Claude: 0 testi sotto soglia su ~6.600 per tema; nessuno scorrimento orizzontale; nessun errore in console |
| Scuro identico a 1440 (13 pagine e finestre, vecchia e nuova aperte insieme) | 0 px diversi tolto il pulsante del selettore; col pulsante le differenze stanno solo nella barra in alto (x 1074-1271, y 10-46) |
| Cambio al volo, persistenza, primo disegno | PASS: sfondo, `theme-color`, `color-scheme` cambiano senza ricaricare; dopo la ricarica Claude è già applicato quando la pagina finisce di leggersi |
| Automatico (preferenza emulata con CDP) | PASS: giorno Chiaro, sera Scuro, e ritorno, a pagina aperta |
| `localStorage` che lancia | PASS: parte Scuro, 0 errori; il cambio vale per la pagina aperta |
| Selettore da tastiera e ARIA | PASS: radiogroup da 5, Invio apre sulla voce scelta, frecce cambiano, Esc torna al pulsante |
| Foglio «Altro» | PASS: 5 scelte da 53×110 px, un tocco cambia tema, foglio aperto |
| Ponte (copia di `cc_ponte.py` + diff) | PASS: il diff si applica al file di oggi; CSP senza violazioni; il tema vale su accesso, «non raggiungibile» ed emergenza; contrasto AA; `prova_cc_ponte.py` 192/192 sulla copia |

Pagine del giro: le 25 di `INVENTARIO.md` (le 12 viste, chat-voce, Altro, cassetto degli agenti, le 9 finestre,
Sinapsi, Assistenza) più Registro, Schermo, chat con messaggi e codice, chat con le schede di approvazione dei tre
rischi, la chiamata e il menu dei temi. «—» = non esiste su quel dispositivo (Altro e cassetto solo sul telefono,
menu dei temi solo sul desktop). Ogni cella: testi sotto soglia / testi controllati.

| Pagina | scuro tel | scuro 1440 | nero tel | nero 1440 | chiaro tel | chiaro 1440 | claude tel | claude 1440 |
|---|---|---|---|---|---|---|---|---|
| chat | nota 4/53 | nota 18/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 |
| home | nota 108/305 | nota 140/328 | PASS 0/305 | PASS 0/328 | PASS 0/305 | PASS 0/328 | PASS 0/305 | PASS 0/328 |
| agenti | nota 104/245 | nota 116/300 | PASS 0/244 | PASS 0/300 | PASS 0/244 | PASS 0/300 | PASS 0/244 | PASS 0/308 |
| missioni | nota 4/54 | nota 16/57 | PASS 0/54 | PASS 0/57 | PASS 0/54 | PASS 0/57 | PASS 0/54 | PASS 0/57 |
| scadenze | nota 449/792 | nota 461/795 | PASS 0/792 | PASS 0/795 | PASS 0/792 | PASS 0/795 | PASS 0/792 | PASS 0/795 |
| memoria | nota 6/94 | nota 18/97 | PASS 0/94 | PASS 0/97 | PASS 0/94 | PASS 0/97 | PASS 0/94 | PASS 0/97 |
| server | nota 7/91 | nota 19/94 | PASS 0/91 | PASS 0/94 | PASS 0/91 | PASS 0/94 | PASS 0/91 | PASS 0/94 |
| telefono | nota 25/102 | nota 37/105 | PASS 0/102 | PASS 0/105 | PASS 0/102 | PASS 0/105 | PASS 0/102 | PASS 0/105 |
| tecnico | nota 4/53 | nota 18/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 |
| lavagna | nota 34/125 | nota 48/130 | PASS 0/125 | PASS 0/130 | PASS 0/125 | PASS 0/130 | PASS 0/125 | PASS 0/130 |
| vps | nota 4/53 | nota 18/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 |
| terminale | nota 4/53 | nota 18/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 | PASS 0/53 | PASS 0/58 |
| registro | nota 26/125 | nota 38/128 | PASS 0/125 | PASS 0/128 | PASS 0/125 | PASS 0/128 | PASS 0/125 | PASS 0/128 |
| schermo | nota 7/65 | nota 19/68 | PASS 0/65 | PASS 0/68 | PASS 0/65 | PASS 0/68 | PASS 0/65 | PASS 0/68 |
| chat-messaggi | nota 7/62 | nota 21/67 | PASS 0/62 | PASS 0/67 | PASS 0/62 | PASS 0/67 | PASS 0/62 | PASS 0/67 |
| approvazioni | nota 16/108 | nota 30/114 | PASS 0/108 | PASS 0/114 | PASS 0/108 | PASS 0/114 | PASS 0/105 | PASS 0/114 |
| chat-voce | nota 10/72 | nota 24/77 | PASS 0/72 | PASS 0/76 | PASS 0/72 | PASS 0/76 | PASS 0/73 | PASS 0/77 |
| altro | nota 10/85 | — | PASS 0/85 | — | PASS 0/85 | — | PASS 0/86 | — |
| lato | nota 10/68 | — | PASS 0/68 | — | PASS 0/68 | — | PASS 0/69 | — |
| tema-menu | — | nota 30/83 | — | PASS 0/83 | — | PASS 0/83 | — | PASS 0/83 |
| scheda-agente | nota 9/67 | nota 10/69 | PASS 0/67 | PASS 0/69 | PASS 0/67 | PASS 0/69 | PASS 0/67 | PASS 0/69 |
| scheda-gruppo | nota 46/78 | nota 46/78 | PASS 0/78 | PASS 0/78 | PASS 0/78 | PASS 0/78 | PASS 0/78 | PASS 0/78 |
| scheda-casa | nota 1/10 | nota 1/10 | PASS 0/10 | PASS 0/10 | PASS 0/10 | PASS 0/10 | PASS 0/10 | PASS 0/10 |
| nuovo-agente | nota 1/13 | nota 1/13 | PASS 0/13 | PASS 0/13 | PASS 0/13 | PASS 0/13 | PASS 0/13 | PASS 0/13 |
| nuovo-gruppo | nota 3/19 | nota 3/21 | PASS 0/19 | PASS 0/21 | PASS 0/19 | PASS 0/21 | PASS 0/19 | PASS 0/21 |
| allineamento | nota 1/4 | nota 1/4 | PASS 0/4 | PASS 0/4 | PASS 0/4 | PASS 0/4 | PASS 0/4 | PASS 0/4 |
| guida-lavagna | nota 1/3 | nota 1/3 | PASS 0/3 | PASS 0/3 | PASS 0/3 | PASS 0/3 | PASS 0/3 | PASS 0/3 |
| togli-scelta | nota 0/5 | nota 0/5 | PASS 0/5 | PASS 0/5 | PASS 0/5 | PASS 0/5 | PASS 0/5 | PASS 0/5 |
| sinapsi | nota 40/140 | nota 54/144 | PASS 0/140 | PASS 0/147 | PASS 0/140 | PASS 0/147 | PASS 0/141 | PASS 0/144 |
| assistenza | nota 108/305 | nota 140/328 | PASS 0/305 | PASS 0/328 | PASS 0/305 | PASS 0/328 | PASS 0/305 | PASS 0/328 |
| chiamata | nota 1/9 | nota 1/9 | PASS 0/9 | PASS 0/9 | PASS 0/9 | PASS 0/9 | PASS 0/9 | PASS 0/9 |

### Casi di contrasto trovati dal controllo e corretti
Il controllo gira sul DOM in Chrome: per ogni testo visibile prende il colore e lo sfondo effettivo risalendo gli
antenati (colori semitrasparenti composti, opacità dei gruppi). Soglia 4,5:1, testo grande 3:1. Esenti e contati a
parte: controlli disabilitati, stati attenuati apposta (`.dato-vecchio`, `.spento`, `.archiviato`, schede decise),
testo di soli simboli o emoji, testo su gradiente o immagine.

| Tema | Dove | Prima | Correzione |
|---|---|---|---|
| Nero, Chiaro, Claude | Server, titolo «VPS del provider» (finisce dentro la maniglia `.maniglia-box` a opacità .45) | 2,5:1 (Nero), 3,3:1 (Chiaro) | maniglia piena nei temi nuovi |
| Chiaro | contatore nella scheda attiva (`#conta-catena`) | 4,13:1 | accento da `#1f5fbf` a `#1a52a8` |
| Claude | badge «capogruppo» e contatore della scheda attiva | 4,4:1 e 3,89:1 | accento testo da `#a64f2d` a `#8f3f1d` |
| Nero | pulsanti pieni rossi e verdi col bianco (Stop, Chiudi chiamata, Approva confermato, Sì della chiamata, pillola) | 2,3–3:1 (calcolato) | fondi `#c81e50` e `#1a7f45` |
| Chiaro, Claude | cerchio della chiamata (fase «lavora»: centro marrone) | brutto, non un errore di contrasto | gradiente al 14% |

### Scuro: il contrasto di oggi (non toccato)
Scuro deve restare identico ai pixel, quindi i suoi casi sotto soglia restano: **2.397 testi su 6.617**, quasi tutti
di un soffio. `--tenue` (`rgba(240,240,240,.48)`) dà 4,37:1 sui riquadri `#1f1f1f`, 4,48-4,49:1 sul fondo;
`--rosso` `#e34671` come testo sui riquadri 4,22:1; bianco su `--rosso` 3,9:1, su `--verde` 3,2:1. Basterebbe
`--tenue: rgba(240,240,240,.52)` e un rosso testo `#f0587f` per portarli quasi tutti sopra 4,5:1, ma è una decisione
dell'utente: cambierebbe lo Scuro di oggi. Il tema Nero ha già questi valori corretti.

## 6. Cosa non ho potuto provare
- Safari vero su iPhone e Chrome su Android: solo Chrome headless con viewport e user agent da telefono. Il
  `theme-color` dinamico sulla barra di Safari/Chrome Android e la scelta «Automatico» al cambio di sistema su un
  telefono vero non li ho visti.
- I font con le grazie di Claude: sul Mac Chrome usa New York (`ui-serif`); su Android, senza New York, Iowan e
  Charter, cade su Georgia o sul serif di sistema (Noto Serif). Non l'ho visto su Android.
- Il ponte vero su internet: le tre pagine le ho servite in locale con la CSP del diff; Caddy davanti no
  (`CC_PONTE_PROVA_CADDY` non impostata, come nella prova del ponte).
- Le schede della lavagna su desktop: in alcune corse il pannello vivo era lento (giri della sentinella) e la
  colonna degli agenti è rimasta «lettura…»; le schede le ho viste e misurate sul telefono (Chiaro).
- Contenuti dentro gli iframe (terminale, desktop VPS) e lo schermo del Mac: restano scuri per scelta.
- Il controllo del contrasto copre il testo; per i componenti (≥ 3:1) ho controllato a mano bordi di campi,
  binari degli interruttori, caselle e fili della lavagna dei temi nuovi, non con uno strumento automatico.

## 7. Rischi
- **`app.css` cambia ogni giorno**: un colore nuovo scritto a mano non passa dai temi. La prova lo trova (contrasto
  o schermata); conviene scrivere i colori nuovi con le variabili.
- **Specificità**: gli override usano `:root:is([data-tema=…])` (0,3,0 e più). Una regola nuova con `!important` o
  con un id li può battere.
- **Il pulsante del selettore** sta nella barra: sopra 1700 px mostra anche il nome. Se la barra si riempie ancora
  (più schede), il nome è la prima cosa da togliere.
- **Diff del ponte**: tocca `cc_ponte.py` (CSP e `STILE`) e una riga di `prova_cc_ponte.py`, che oggi pretende
  «nessuno script nella pagina di accesso»: con il diff pretende «un solo script, quello del tema, col suo hash».
  Va bene a chi tiene la revisione di sicurezza? Se no, l'alternativa senza script: tenere solo
  `prefers-color-scheme` e cambiare le due palette di `STILE` con quelle di Chiaro e Scuro. Il file cambia spesso
  (un altro agente ci lavora): il diff va rifatto se non si applica più (la prova lo dice).
- **Bug di `app.js` trovato strada facendo** (non corretto, non è mio): in Server il titolo del box «VPS del provider»
  finisce dentro il pulsante della maniglia `⠿` (riscritto dopo `boxInit`), quindi a opacità .45 e dentro un
  `<button>` con un altro `aria-label`.
- Il Command Center vivo è stato riavviato alle 21:20:54 durante una corsa (non da me): il token è cambiato e quella
  corsa si è fermata; l'ultima corsa completa è dopo.
