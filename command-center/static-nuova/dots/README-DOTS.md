# Dots: le mascotte degli agenti

*2026-10-04 · cc-dots-opus · richiesta dell'utente: «usa i dots avatar nel nostro Jarvis CRM»*

## Da dove vengono

Le quattro immagini (blue, mint, orange, purple) vengono dal progetto **OpenDots** di CopilotKit
(`github.com/CopilotKit/OpenDots`, cartella `public/dots/`), clonato in
`~/.locale-onedrive/riferimenti/OpenDots/` il 2026-10-03. Gli originali sono PNG 512×512 con
trasparenza, da 320 a 415 KB l'uno.

Licenza: **MIT**, «Copyright (c) Atai Barkai». Il testo intero è in `LICENSE-OpenDots.txt`,
qui accanto, e va tenuto insieme alle immagini.

Anche la scelta del colore viene da OpenDots (`src/client/Mascot.tsx`): per ogni carattere
dell'identità `hash = (hash * 31 + codice del carattere) >>> 0`, poi `hash % 4` nell'ordine
blue, mint, orange, purple. `dots.js` la rifà uguale.

## Cosa c'è qui

| File | Lato | Peso | Uso |
|---|---|---|---|
| `<colore>-64.png` | 64 px | 6-8 KB | avatar fino a 48 px su schermi 1x |
| `<colore>-128.png` | 128 px | 22-26 KB | avatar fino a 48 px su schermi 2x e 3x, avatar da 72-100 px su 1x |
| `<colore>-256.webp` | 256 px | 50-67 KB | avatar grandi (scheda, testa della chat, chiamata), WebP senza perdita |
| `<colore>-256.png` | 256 px | 81-98 KB | solo riserva: si scarica se il browser non apre il WebP |

Ridotte da cc-dots-opus con Pillow (LANCZOS, alfa premoltiplicato). Il WebP a 256 px è
identico pixel per pixel al PNG a 256 px (confronto fatto con ImageChops, nessuna differenza).
Gli originali da 512 px non sono stati copiati.

## Uso

Uso **interno dell'utente**, nel Command Center di Jarvis sul suo Mac e attraverso il suo ponte.
Queste immagini non si distribuiscono e non si vendono, né da sole né dentro altro software.
Se un giorno il Command Center venisse pubblicato o dato ad altri, le immagini vanno tolte
oppure va rispettata la licenza MIT (avviso di copyright e testo della licenza insieme ai file).
