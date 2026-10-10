# Fili di chat condivisi: come si installa

*2026-10-03 19:30 · cc-fili-opus · perché e come funziona: `command-center/fili-dev/ANALISI.md`*

Niente è installato: il Command Center vivo (7777), `server.py`, `static/` e `app.js` non sono stati
toccati. `app.js` **non** cambia: `fili.js` si aggancia per nome alle sue globali.

## I file

| File | Dove va | Cosa fa |
|---|---|---|
| `command-center/fili-dev/fili.py` | copia in `command-center/fili.py` | archivio dei fili sul Mac |
| `command-center/fili-dev/fili-server.patch` | `patch -p0` in `command-center/` | `server.py`: scrive l'archivio, `GET /api/fili`, evento «fili» |
| `command-center/static-nuova/fili.js` | con il resto di `static-nuova/` in `static/` | unisce l'archivio alla chat della pagina |
| `command-center/fili-dev/prova_fili.py`, `prova_fili_browser.js`, `claude_finto.py` | restano lì | le prove |

`fili.css` non serve: la chat usa i suoi stili.

## 1. Backend (serve il riavvio del Command Center: lo decide l'utente)

```bash
cd ~/Jarvis/command-center
cp server.py server.py.prima-dei-fili
cp fili-dev/fili.py fili.py
patch -p0 --dry-run -i fili-dev/fili-server.patch     # deve dire solo «patching file server.py»
patch -p0 -i fili-dev/fili-server.patch
python3 -m py_compile server.py fili.py
python3 fili-dev/prova_fili.py                        # atteso: FAIL 0 (SALTA 1 = claude vero, facoltativo)
```

Poi il riavvio come al solito (`avvio/Command Center.command`). La cartella
`~/.locale-onedrive/jarvis-cc/fili/` nasce da sola (0700) alla prima domanda.
Patch verificata con `patch -p0 --dry-run` sul `server.py` del 2026-10-03 16:26
(sha256 `8b0d0eb2…c86a`, già con le approvazioni). Se `server.py` cambia prima, rifare il dry-run.

## 2. Front-end: una riga in `index.html`

In fondo al `<body>`, dopo gli altri script `defer` (dopo `app.js`, che deve essere già girato):

```html
<script src="/static/fili.js" defer></script>
```

Diff per `static-nuova/index.html` (NON applicato: quel file è di cc-front-coerenza-opus):

```diff
 <script src="/static/computer.js" defer></script>
+<script src="/static/fili.js" defer></script>
 </body>
```

Se manca il backend (404 su `/api/fili`) `fili.js` si spegne da solo: si può copiare anche prima del
riavvio. Facoltativo: aggiungere `/static/fili.js` a `GUSCIO` in `static/sw.js` alzando `CACHE`.

## 3. Ganci con `app.js` (nessuna modifica)

| Gancio | Come |
|---|---|
| `THREADS`, `chatCon`, `AGENTI`, `FLUSSO`, `seguiInCorso` | lette per nome |
| `salvaFili` | avvolta (`window.salvaFili`): le chiamate di `app.js` passano dall'involucro |
| `disegnaMessaggi`, `aggiornaInvia`, `segnaAttivi` | chiamate dopo un'unione |
| EventSource di `/api/flusso` | stesso involucro di `approvazioni.js` (`window.__ccFlusso`), ascoltatore «fili» |

Se un giorno `app.js` diventa un modulo o rinomina `THREADS`/`salvaFili`, `fili.js` non parte (prima riga)
e la pagina resta come oggi. Va riprovato con `prova_fili.py`.

In `localStorage`, oltre a `cc.fili`: `cc.fili-lasciati`, `cc.fili-tolti`, `cc.fili-visto`,
`cc.fili-ripartiti` (piccoli, con tetto) e `cc.fili-da-parte` (al massimo 5 chat sostituite, 400 KB).
`window.CCFili.stato()` e `window.CCFili.sincronizza()` per chi controlla a mano.

## 4. Ponte

Nessun cambio per i fili: `GET /api/fili*` passa dal filtro come gli altri GET. Le sessioni del ponte
che sopravvivono al riavvio sono un pezzo a parte: `vps/cc-ponte/LEGGIMI.md`, sezione «Sessioni che
sopravvivono al riavvio», da installare sulla VPS con il solito `installa_vps.sh` (con il sì dell'utente).

## Tornare indietro

```bash
cd ~/Jarvis/command-center
cp server.py.prima-dei-fili server.py && rm fili.py      # poi riavvio
# togliere la riga di fili.js da static/index.html e rm static/fili.js
```

L'archivio in `~/.locale-onedrive/jarvis-cc/fili/` si può lasciare o cancellare: la pagina non ne ha bisogno.
