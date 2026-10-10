# Command Center sul telefono: come si installa

*Preparato il 2026-10-03 da cc-ponte-mobile-opus. Niente è ancora installato: i file vivi in `static/` non sono stati toccati.*

## Cosa entra

| File | Stato | Cosa fa |
|---|---|---|
| `index.html` | modificato (3 punti) | viewport con `interactive-widget=resizes-content`; carica `mobile.css` dopo `app.css`; carica `mobile.js` e `ponte.js` (defer) dopo `app.js` |
| `manifest.webmanifest` | modificato | scorciatoie «Parla a Jarvis» (`/#chat-voce`) e «Chat» (`/#chat`) in testa, «Agenti» e «Missioni» restano |
| `mobile.css` | nuovo | telefono (fino a 820 px, o telefono girato), dito sul tablet (821-1100 px con `pointer: coarse`), stili del ponte |
| `mobile.js` | nuovo | barra di schede in basso, foglio «Altro», altezza con la tastiera (visualViewport), zoom a due dita sulla lavagna, azioni dei messaggi con un tocco |
| `ponte.js` | nuovo | solo se `/_ponte/stato` risponde 200: badge Mac, microfono, altoparlante, Stop, avviso comandi spenti |

`app.js`, `app.css` e `sw.js` **non cambiano** e non si copiano. Gli altri file che stanno in
`static-nuova/` (`approvazioni.*`, `attivita.*`) sono di un altro lavoro (cc-front-approvazioni-opus):
non fanno parte di questa consegna.

`server.py` non va riavviato: rilegge `index.html` a ogni richiesta e serve qualunque file dentro
`static/` (nessuna lista di file ammessi, controllato in `_do_get`, righe 6254-6284 del 2026-10-03).

## 0. Controllo prima di copiare

I file vivi devono essere ancora quelli da cui è partita la copia (2026-10-03 15:25):

```bash
cd ~/.locale-onedrive/Jarvis/command-center
shasum -a 256 static/index.html static/manifest.webmanifest
# atteso:
# 1582b853f712b0633e21ee20dabcf1c111fa4a286eb22d4bb5ed0e5633ce81a6  static/index.html
# 53b49c28058188d9ebdcc2dc9b013973d065dcaf299375ada1e47bd323e976ef  static/manifest.webmanifest
```

Se uno dei due è diverso, qualcuno ha cambiato il file vivo dopo: **non copiare sopra**. Si
rifanno a mano le tre modifiche di `index.html` (`diff static/index.html static-nuova/index.html`
le mostra) o le scorciatoie del manifest sul file nuovo.

## 1. Copia con backup datato

```bash
cd ~/.locale-onedrive/Jarvis/command-center
D=$(date +%Y%m%d-%H%M)
mkdir -p "static-backup-$D"
cp -p static/index.html static/manifest.webmanifest "static-backup-$D/"
cp -p static-nuova/index.html static-nuova/manifest.webmanifest \
      static-nuova/mobile.css static-nuova/mobile.js static-nuova/ponte.js static/
echo "backup in static-backup-$D"
```

## 2. Verifica

```bash
cd ~/.locale-onedrive/Jarvis
for f in / /static/mobile.css /static/mobile.js /static/ponte.js /manifest.webmanifest; do
  printf '%s ' "$f"; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:7777$f"; done   # tutti 200
node vps/cc-ponte/prove-mobile/prova_mobile.js --niente-regressione   # giro e funzioni: atteso «Totale: N/N PASS»
```

Poi una ricarica della pagina sul Mac (desktop identico) e una dal telefono attraverso il ponte.
Il service worker del Mac è «rete prima di tutto»: i file nuovi arrivano alla prima ricarica.

## Tornare indietro

```bash
cd ~/.locale-onedrive/Jarvis/command-center
D=AAAAMMGG-HHMM          # la cartella static-backup-… creata al punto 1
cp -p "static-backup-$D/index.html" "static-backup-$D/manifest.webmanifest" static/
rm static/mobile.css static/mobile.js static/ponte.js
```

Senza `mobile.css`, `mobile.js` e `ponte.js` la pagina vecchia non li chiede: si torna esattamente a prima.

## Da sapere per il ponte

Letto in `vps/cc-ponte/cc_ponte.py` il 2026-10-03 alle 16:01 (sola lettura, il file è di cc-ponte-comandi-opus):

- `GET /_ponte/stato` c'è e risponde `{"ponte":true,"mac":…,"comandi":"attivi"|"spenti"}`: è lo
  stesso contratto che usa `ponte.js`. Funziona davvero solo quando quella versione del ponte gira sulla VPS.
- Passa un solo POST, `/api/azione` con `tipo` «chiedi», «ferma» o «approva». Quindi da fuori casa
  funzionano: invio della chat, «Chiedi a Jarvis: …» dei riquadri, lo Stop (`{tipo:"ferma", id}`, id
  `[A-Za-z0-9_-]{1,64}`). **Non** funzionano (403 «non disponibile da qui»): i comandi con «/»
  (`comando_diretto`), verifiche e comandi rapidi, interruttori, missioni, modo lettura/lavoro
  (per questo `ponte.js` lo mostra solo come etichetta), salvataggi della lavagna (`/api/pannello/modifica`).
- Con l'interruttore di emergenza acceso il ponte risponde 503 a «chiedi» e «ferma»: la chat mostra
  l'avviso «Comandi spenti dall'interruttore di emergenza».
- Terminale, VPS e Tecnico sono bloccati dal ponte: nel foglio «Altro» sono segnati «solo sul Mac».
