# Pagina «Schermo» (gli occhi di Jarvis): come agganciarla

*2026-10-03 · file nuovi `computer.js` e `computer.css` · contratto: `command-center/CONTRATTO-approvazioni.md`, sezione 3*

Lo schermo del Mac visto dal telefono, in **sola visione** (niente clic né tasti). Esiste solo dentro
il ponte: sul Mac locale `/_ponte/stato` risponde 404 e `computer.js` non crea niente e non fa altre
richieste. Il ponte lascia passare `/api/computer/*` solo con l'interruttore `/etc/cc-ponte/schermo-on`
acceso (vedi `vps/cc-ponte/LEGGIMI.md`, «Schermo del Mac»).

## Le righe da aggiungere a `index.html` (il minimo, basta questo)

Nel `<head>`, con gli altri fogli di stile (prima della riga `<script>window.CC_TOKEN …`):

```html
<link rel="stylesheet" href="/static/computer.css">
```

In fondo, dopo le altre `<script … defer>` (dopo `attivita.js`):

```html
<script src="/static/computer.js" defer></script>
```

Niente altro è obbligatorio. Dentro il ponte `computer.js` da solo:
- aggiunge la voce «Schermo» (`#schermo`) al menu in alto, prima di «Lavagna», e al foglio «Altro»
  del telefono (mobile.js costruisce il foglio all'avvio, prima che la voce esista);
- aggiunge `schermo: "Schermo"` a `TITOLI` di app.js (`mostraVista()` mostra solo le viste che conosce);
- crea `<section class="vista vista-schermo" data-vista="schermo">` dentro `<main>`.

## Facoltativo, più pulito (quando app.js e mobile.js tornano liberi)

- `app.js`, `const TITOLI = { … }`: aggiungere `schermo: "Schermo"` (computer.js lo aggiunge solo se manca).
- `mobile.js`, `ICONE_FOGLIO`: `schermo: "▣"`. Serve solo se un giorno la voce sta scritta in index.html.
  **Non** mettere la voce nel menu di index.html: comparirebbe anche sul Mac, dove la pagina non esiste.
- `app.js`, `spieSchede()`: oggi rimette grigia la spia di ogni voce che non conosce, quindi la spia di
  «Schermo» resta grigia. Se si vuole: `st.schermo = …` (per esempio verde quando lo schermo è acceso).

## Disposizione

```
telefono (390 px)                         desktop (1440 px)
┌ Schermo del Mac ─────────────┐          ┌ Schermo del Mac ───────────────┐ ┌ Cosa sta facendo Jarvis ┐
│ ! Questo è il tuo schermo    │          │ ! avviso ............ [Nascondi]│ │ titolo · in corso       │
│   reale … Sola visione       │          │ ● in diretta · 1 s  [Pausa][Q][⛶]│ │ ▶ voce  ✓ … ultime 6   │
│ [        Nascondi         ]  │          │ ┌─────────────────────────────┐ │ └─────────────────────────┘
│ ● in diretta · aggiornato 1 s│          │ │      immagine schermo       │ │ ┌ Ultimi file toccati ────┐
│ [ Pausa ][ Schermo intero ]  │          │ └─────────────────────────────┘ │ │ ~/Jarvis/…/posta.py     │
│ Qualità [ Media (960 px) ▾ ] │          │ [−][100%][+]       sola visione │ └─────────────────────────┘
│ ┌──────────────────────────┐ │          └─────────────────────────────────┘
│ │   immagine dello schermo │ │
│ └──────────────────────────┘ │
│ [−][100%][+]  sola visione   │
├ Cosa sta facendo Jarvis ─────┤
├ Ultimi file toccati ─────────┤
```

Spento, 503 senza permesso, nascosto, sessione scaduta: al posto dell'immagine una spiegazione
(senza i comandi dello schermo, che lì non servono).

## Cosa fa la pagina (in breve)

- immagine con `fetch("/api/computer/schermo?w=…", {headers: {"X-Token": …}})` → `URL.createObjectURL`,
  l'URL precedente revocato; una richiesta ogni 2 s, **un solo fetch in volo**; il ponte rifiuta `?token=`;
- si ferma con la scheda del browser nascosta, fuori da `#schermo`, in «Pausa», dopo «Nascondi»
  (che interrompe anche il fetch in corso e toglie l'immagine) e dopo un 503 «permesso» (riparte con «Riprova»);
- qualità piccola/media/grande = 640/960/1280 px (`localStorage` «cc.schermo.qualita», con try/catch);
- zoom: due dita, doppio tocco (doppio clic col mouse), trascinamento, Ctrl+rotella, tasti + − 0 e frecce;
- schermo intero: Fullscreen API, su iPhone la pagina coperta;
- sotto: `GET /api/computer/stato` ogni 5 s → `ultimo_lavoro` → `GET /api/lavoro/<id>` (titolo, stato,
  ultime 6 attività) e `ultimi_file` (solo testo, `~` al posto della home, mai aperti);
- `/_ponte/stato` riletto ogni 15 s a pagina aperta: quando l'utente accende o spegne lo schermo la pagina lo vede da sola.
- tutto con `textContent`. Per le prove: `window.CCComputer.stato()`.

## Prove

`node vps/cc-ponte/prove-mobile/prova_computer.js` (Chrome headless, iPhone 14, Pixel 7, tablet, desktop
1440; schermate in `~/.locale-onedrive/cc-ponte/schermate-computer/`).
