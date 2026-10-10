# Integrare il Registro e le regole di permesso come dati

*2026-10-03 19:40 · cc-registro-opus · contratto: `command-center/CONTRATTO-registro.md`*

Nessun file vivo è stato toccato. Il master installa nell'ordine qui sotto: prima il backend, poi la pagina.

## 1. Backend (Mac)

File nuovi, già al loro posto e usati da nessuno finché non si applica la patch:
`command-center/regole_permessi.py`, `command-center/registro.py`, `command-center/CONTRATTO-registro.md`.

```bash
cd ~/Jarvis/command-center
cp server.py server.py.prima-registro; cp approvazioni.py approvazioni.py.prima-registro; cp approvazioni_mcp.py approvazioni_mcp.py.prima-registro
python3 registro-dev/rifai_patch.py                   # rifà la patch sul server.py di adesso (cambia spesso) e fa il --dry-run
patch -p0 --dry-run -i registro-dev/registro.patch    # tre «patching file», niente FAILED
patch -p0 -i registro-dev/registro.patch
python3 -m py_compile server.py approvazioni.py approvazioni_mcp.py regole_permessi.py registro.py
python3 registro-dev/prova_registro.py                 # tutto PASS (aggiungere --con-claude per la prova reale)
python3 regole_permessi.py --controlla                 # crea il file delle regole col predefinito e dice se è valido
```

- `approvazioni_mcp.py` e `approvazioni.py` valgono dal **prossimo lavoro** della chat: il gestore dei permessi riparte a ogni lavoro. Il server non serve riavviarlo.
- `server.py` (il nuovo `/api/registro` e il passaggio di `CC_REGOLE_FILE`/`CC_REGISTRO_DIR` alle prove) vale dopo il riavvio del Command Center. Lo decide l'utente.
- La guardia dei comandi (facoltativo, consigliato: senza, la fonte «guardia» resta vuota):
  ```bash
  cd ~/.claude/hooks && cp guardia_comandi.py guardia_comandi.py.prima-registro
  patch -p0 --dry-run -i ~/Jarvis/command-center/registro-dev/guardia-registro.patch && patch -p0 -i ~/Jarvis/command-center/registro-dev/guardia-registro.patch
  python3 guardia_comandi.py --prova
  ```
  Vale subito per ogni sessione (è un hook). Le decisioni non cambiano: la prova confronta l'uscita con l'originale.
- Tornare indietro: `patch -R -p0 -i registro-dev/registro.patch` (o le copie `.prima-registro`). Il file delle regole può restare: senza la patch nessuno lo legge.

## 2. Le righe da aggiungere a `index.html`

Nel `<head>`, con gli altri fogli di stile (prima di `<script>window.CC_TOKEN = "__TOKEN__";</script>`):

```html
<link rel="stylesheet" href="/static/registro.css">
```

In fondo, dopo le altre `<script … defer>` (dopo `computer.js`):

```html
<script src="/static/registro.js" defer></script>
```

Non serve altro: `registro.js` da solo
- chiede `GET /api/registro?limite=1`. Se risponde 404 (server senza la patch) non crea niente e non fa altre richieste;
- aggiunge la voce «Registro» (`#registro`) al menu in alto, prima di «Memoria», e al foglio «Altro» del telefono (icona «≡»);
- aggiunge `registro: "Registro"` a `TITOLI` di app.js;
- crea `<section class="vista vista-registro" data-vista="registro">` dentro `<main>`.

Vale sul Mac e dentro il ponte, dove i due GET passano come gli altri.

Facoltativo, più pulito quando app.js e mobile.js tornano liberi: `registro: "Registro"` in `TITOLI`, `registro: "≡"` in
`ICONE_FOGLIO` di mobile.js, i due file in `GUSCIO` di `static/sw.js`. La voce si può anche scrivere in `index.html`
(`<a href="#registro" data-vista="registro"><i class="spia grigia"></i>Registro</a>`): registro.js non la duplica.

## 3. Disposizione

```
telefono (390 px)                          desktop (1440 px)
┌ Registro [Registro|Regole] ──┐           ┌ Registro [Registro|Regole]        aggiornato 3 s fa ┐
│ aggiornato adesso            │           │ ┌ Cerca [__________________] ─────┐ ┌ Proposte (1) ───┐
│ Cerca [____________________] │           │ │ Esito  (Tutti)(✓)(✕)(!)(⏱)       │ │ proponi regola: │
│ Esito (Tutti)(✓ Permesso)(✕… │ ← scorre  │ │ Fonte  (Tutte)(Scheda)(Regola)… │ │ consenti Bash   │
│ Fonte (Tutte)(Scheda)(Regol… │   di lato │ │ ! Ponte (VPS): non raggiungibile │ │ npm test        │
│ ! Ponte (VPS): non raggiung. │           │ │ 10 eventi                        │ │ ▸ Testo regola  │
│ 10 eventi                    │           │ │ ┃✕ Rifiutato [Regola] Bash  19:16│ └─────────────────┘
│ ┃✕ Rifiutato [Regola] Bash   │           │ │ ┃Lanciare: whoami                │
│ ┃Lanciare: whoami      19:16 │           │ │ ┃Regola che l'ha deciso: nega-…  │
│ ┃Regola che l'ha deciso: …   │           │ │ ┃▸ Dettagli                      │
│ ┃▸ Dettagli                  │           │ └──────────────────────────────────┘
│ … schede …                   │
│ ┌ Proposte ────────────────┐ │           «Regole»: elenco numerato in sola lettura (id, Consenti/Chiedi/Nega,
│ └──────────────────────────┘ │           strumento, quando, nota) + «∞ predefinita: chiedi», il percorso del
└──────────────────────────────┘           file, e l'avviso rosso se il file non è valido.
```

## 4. Comportamento

- Elenco a schede: esito in colore e in parola (✓ Permesso, ✕ Rifiutato, ! Fallito, ⏱ Scaduto), fonte (Scheda, Regola, Guardia, Sito, Schermo), ora (con la data se non è oggi), riepilogo, la regola («Regola che l'ha deciso» in rosso per i rifiuti di regola, guardia e ponte; «Regola che ha chiesto la scheda» per le schede, dove decide l'utente) e «Dettagli» ripiegabili.
- Filtri per esito e per fonte (più di uno insieme), ricerca per testo (300 ms dopo l'ultimo tasto). Tutto si chiede al server: `GET /api/registro?limite=200&esito=…&fonte=…&q=…`.
- Dall'indirizzo: `#registro?esito=rifiutato`, `&fonte=guardia,regola`, `&q=push`, `&vista=regole`. La pagina legge i filtri e riporta l'indirizzo a `#registro`, perché `mostraVista()` di app.js conosce solo i nomi delle viste.
- Aggiornamento ogni 10 s solo a vista aperta e scheda del browser visibile. Le regole e le proposte ogni 60 s. Un solo fetch in volo.
- Se la VPS non risponde compare un avviso giallo e l'elenco mostra le altre fonti. Con rete giù, 401 o token scaduto compare un messaggio, e gli eventi già letti restano.
- Proposte: solo testo da copiare («Copia il testo» usa gli appunti; senza permesso seleziona il testo). Nessun POST, nessun campo modificabile.
- Accessibilità: schede `role=tablist` con le frecce, filtri `aria-pressed` in gruppi con nome, conteggio in una regione `aria-live` che cambia solo quando cambia il numero, tocchi da 44 px sul telefono, `<time datetime>`. Tutti i testi passano da `textContent`.
- Tema: le variabili di app.css (`--rialzo`, `--testo`, `--verde`, `--rosso`…) con valori di riserva.
- Per le prove: `window.CCRegistro.stato()`, `window.CCRegistro.rileggi()`.

## 5. Prove

```
python3 command-center/registro-dev/prova_registro.py [--con-claude]
node command-center/registro-dev/prova_registro_vista.js [--solo iphone14,desktop]
```

La seconda apre la pagina viva in sola lettura. Risponde lei a `/api/registro*`, abortisce tutti i POST e controlla alla fine che la versione di `pannello.json` non sia cambiata. Schermate in `~/.locale-onedrive/cc-ponte/schermate-registro/`.
