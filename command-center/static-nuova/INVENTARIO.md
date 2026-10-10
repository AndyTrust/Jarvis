# Inventario delle pagine del Command Center (telefono)

*2026-10-03, cc-ponte-mobile-opus. Misure di `vps/cc-ponte/prove-mobile/prova_mobile.js` con Chrome
headless: «prima» = file di oggi in `static/` (iPhone 14, 390×844), «dopo» = `static-nuova/` sullo
stesso iPhone 14. «Bersagli piccoli» = elementi toccabili con un lato sotto i 40 px, sul totale
visibile. Le schermate stanno in `~/.locale-onedrive/cc-ponte/schermate/<dispositivo>/<pagina>.png`
(quelle «prima» in `schermate/vecchi/`).*

## Come è fatta la pagina

Una sola pagina (`index.html`) in tre colonne: a sinistra gli agenti (`aside.lato`), al centro le
viste (`section.vista[data-vista]`), a destra lavagna, terminale e VPS (`aside.destra`, pannelli
`.pannello-destra[data-pannello]`). La vista la sceglie l'indirizzo: `mostraVista()` in `app.js`
legge `location.hash`, `TITOLI` dà il nome, `PANNELLI = ["lavagna","vps","terminale"]` sono le
pagine intere (`paginaIntera()`), `pannelloAttivo()` = l'hash senza «#». Sul desktop si naviga con
il menu in alto (`nav.schede.menu`); sul telefono, da oggi, con la barra in basso
(Chat · Lavagna · Stato · Altro) e il foglio «Altro», costruiti da `mobile.js` con le stesse voci.

## Pagine e finestre

| # | Pagina (nome nel codice) | Come si apre | Prima sul telefono | Dopo sul telefono |
|---|---|---|---|---|
| 1 | Chat (`chat`) | `#chat`, scheda «Chat» in basso, clic su un agente | usabile a fatica: interruttore lettura/lavoro tagliato, avatar da 72 px, campo a 14 px (zoom di iOS), 25/34 bersagli piccoli, pagina alta metà schermo (la colonna destra prendeva una riga) | 0/33 bersagli piccoli; campo a 16 px sopra la tastiera; comandi «/» su una riga che scorre; azioni del messaggio con un tocco; nel ponte: microfono, altoparlante, Stop, etichetta del modo |
| 2 | Chat a schermo pieno con microfono (`#chat-voce`) | scorciatoia «Parla a Jarvis» dell'app installata | non esisteva (apriva la chat) | sul Mac apre la chat; nel ponte un microfono grande: un tocco e si detta |
| 3 | Stato (`home`) | `#home`, scheda «Stato», avatar di Jarvis in alto | 77/87 bersagli piccoli, 116 testi sotto 12 px | 0/86, testo ≥ 12 px; riquadri in una colonna; repository su due colonne |
| 4 | Squadra (`agenti`, era «Catena · Lavori»; `#lavori` porta qui) | foglio «Altro» › Squadra | 27/85 piccoli, 169 testi sotto 12 px, azioni delle righe solo al passaggio del mouse | 0/30; azioni sempre visibili; lavori e dettaglio uno sotto l'altro |
| 5 | Missioni (`missioni`) | «Altro» › Missioni | 16/18 piccoli | 0/17; «Affida» a tutta larghezza; albero senza colonne fisse |
| 6 | Scadenze (`scadenze`) | «Altro» › Scadenze | 399/400 piccoli (caselle da 13 px) | 0/399; caselle da 44 px col segno da 22 |
| 7 | Memoria (`memoria`) | «Altro» › Memoria | 9/10 piccoli, tabella della sincronia tagliata a destra (20 celle fuori) | 0/9; la tabella scorre dentro il suo riquadro |
| 8 | Server (`server`) | «Altro» › Server | 11/12 piccoli | 0/11 |
| 9 | Telefono (`telefono`) | «Altro» › Telefono | 24/26 piccoli, interruttori da 22 px | 0/25; interruttori da 44 px |
| 10 | Tecnico (`tecnico`, banco arancione) | «Altro» › Tecnico | 12/13 piccoli | 0/12; nel ponte «solo sul Mac» (il ponte blocca `/api/tecnico`) |
| 11 | Lavagna (`lavagna`, pagina intera) | `#lavagna`, scheda «Lavagna» | inutilizzabile: schiacciata in 142 px a destra (partiva dopo la colonna degli agenti), barra in alto sparita | a tutta larghezza fra le due barre; pulsanti su una riga che scorre; un dito sposta schede e foglio, due dita fanno zoom; il pallino dei fili si prende col dito |
| 12 | VPS (`vps`, pagina intera, noVNC) | «Altro» › VPS | schiacciata come la lavagna | a tutta larghezza; nel ponte «solo sul Mac» (bloccata dal ponte) |
| 13 | Terminale (`terminale`, pagina intera, ttyd) | «Altro» › Terminale, «>_» in chat | schiacciata, segmenti Mac/VPS da 22 px | a tutta larghezza; nel ponte «solo sul Mac» (bloccato dal ponte) |
| 14 | Colonna degli agenti (`aside.lato`: motore, nuova chat, gruppi) | ☰ in alto, «Altro» › Agenti | cassetto solo sotto 760 px; 17/18 piccoli; 5 icone per gruppo che coprivano il nome | cassetto fino a 820 px (e telefono girato); 0/34; per gruppo restano «scheda» e «lavagna», il resto è nella scheda del gruppo |
| 15 | Foglio «Altro» | scheda «Altro» in basso | non esisteva | tutte le altre pagine con spie e contatori del menu |
| 16 | Scheda agente (`dialog#scheda-agente`) | doppio tocco o tocco lungo su un agente, ⓘ in Squadra | finestra da 440 px, 47/49 piccoli | schermo pieno, testata fissa con ✕, 0/48 |
| 17 | Scheda gruppo (`dialog#scheda-gruppo`) | ⓘ sul gruppo | 10/12 piccoli | schermo pieno, 0/12 |
| 18 | Scheda casa (`dialog#scheda-casa`: esecutore, ricercatore-web) | clic destro su una nota «di casa» in lavagna (`apriNotaDiCasa`); col dito: tocco lungo su Android, su iPhone non si apre | 7/8 piccoli | schermo pieno, 0/8 |
| 19 | Nuovo agente (`dialog#nuovo-agente`) | «＋ Nuovo agente» | 9/10 piccoli | schermo pieno, 0/10 |
| 20 | Nuovo gruppo (`dialog#nuovo-gruppo`) | «＋ Nuovo gruppo» | 15/16 piccoli, caselle nascoste visibili | schermo pieno, `hidden` rispettato, 0/14 |
| 21 | Profili e lavagna (`dialog#allineamento`) | «Profili: …» in lavagna | 3/3 piccoli | schermo pieno, 0/3 |
| 22 | Guida della lavagna (`dialog#guida-lavagna`) | «Guida» in lavagna | 2/2 piccoli | schermo pieno, 0/2 |
| 23 | Togli dalla lavagna (`dialog#togli-scelta`) | «Togli» su una scheda | 5/5 piccoli | schermo pieno, 0/5 |
| 24 | Sinapsi (`details#lav-sinapsi`) | sotto la barra della lavagna | righe a 4 colonne tagliate | righe su due livelli, lista alta al massimo 30% |
| 25 | Assistenza (riquadri in Stato, `#assistenza-tecnico` e `#box-assistenza`, banner) | `#assistenza-tecnico` porta in Stato | due colonne strette | una colonna; nel ponte i dati non arrivano (bloccati dal ponte) |

Le finestre di conferma del browser (`confirm()`, per esempio «Chiudi sessione» del terminale) sono
quelle del sistema: sul telefono sono già a misura.

## Cosa si fa male col dito (lasciato così, non rotto)

- Trascinare un agente dalla colonna alla lavagna usa il drag and drop HTML: col dito non va. Dal
  telefono si usa «Metti in lavagna» nella scheda dell'agente o «Tutta la catena».
- Selezione multipla in lavagna (Ctrl/Cmd/Maiusc): solo con la tastiera.
- Spostare i riquadri con la maniglia ⠿: funziona (pointer events), ma sul telefono le colonne sono una sola.
- La scheda casa si apre solo col clic destro (tocco lungo su Android): su iPhone Safari non c'è
  il «contextmenu», quindi da iPhone non si apre. Non l'ho cambiato: servirebbe toccare `app.js`.
- Doppio tocco per la scheda di un agente: Chrome Android lo riconosce; su iPhone è più sicuro ⓘ
  (Squadra) o il tocco lungo (Android).

Le misure complete per ogni dispositivo sono nel resoconto e in
`~/.locale-onedrive/cc-ponte/schermate/giro.json` (dopo) e `schermate/vecchi/giro.json` (prima).
