---
name: nuovo-progetto
description: "Da usare quando il proprietario nomina un progetto, un'attività o un cliente che non esiste ancora fra i progetti di Jarvis, o fa una richiesta che non rientra in nessuno spazio esistente («apri il progetto X», «iniziamo un progetto per…», «mi segui anche Y», «crea un gruppo per…»), e quando chiede una competenza che nessun agente ha («mi serve qualcuno che faccia Y», «aggiungi un esperto di…»). Crea il progetto con il suo capogruppo, poi gli specialisti uno alla volta. Anche per rinominare, spostare o archiviare un progetto, e per cambiare missione, modello, strumenti o limiti di un agente."
---

# Nuovo progetto e nuovi agenti

Jarvis parte senza progetti. Si programma da solo man mano che il proprietario lavora: ogni progetto nasce
quando serve, con il suo capogruppo; gli specialisti nascono quando serve una competenza.

`R` = la cartella di Jarvis: chiave `repo` di `~/.jarvis/percorsi.json` (di solito `~/Jarvis`).
La fonte unica è `R/command-center/spazi.json` + le schede in `<cartella>/.claude/agents/` + le cartelle.
Il Command Center (lavagna, menu agenti, pagine) si rilegge da lì da solo in 2 secondi: non serve altro.

## 1. Riconoscere il caso

- Il proprietario nomina qualcosa: lancia `python3 R/strumenti/crea_progetto.py --elenco`.
  - C'è già (anche con un nome simile): lavori lì. Leggi `<memoria>/<spazio>/Stato.md`, poi la memoria del progetto.
  - Non c'è: è un progetto nuovo, vai al punto 2.
- Il proprietario chiede una competenza («mi serve qualcuno che…»): se il progetto c'è e nessun agente la copre
  (guarda le `description` in `<cartella>/.claude/agents/`), vai al punto 3. Se non è chiaro il progetto, una sola domanda.

## 2. Creare il progetto

1. Ricava senza domande inutili: nome breve, spazio (predefinito: lo stesso nome; uno spazio esistente se il
   progetto ne fa parte), cartella (predefinita `<progetti>/<nome>`; una cartella esistente se il proprietario la nomina:
   controlla con `ls`), a cosa serve in una riga.
2. **Prima volta** (oppure se `~/.jarvis/risposte-avvio.json` ha `"creazione": "piano"` o non ha la chiave):
   mostra in 4-6 righe cosa crei, con l'uscita di
   `python3 R/strumenti/crea_progetto.py "<nome>" --spazio "<spazio>" --cartella "<cartella>" --descrizione "<riga>" --prova`
   e aspetta il sì. Se `"creazione": "automatica"`: crea subito e dillo dopo.
3. Crea: lo stesso comando senza `--prova`. È idempotente: rilanciarlo non rifà niente.
4. Verifica con un comando: `crea_progetto.py --elenco` e `ls "<cartella>/.claude/agents"`.
5. Dì in due righe cosa esiste ora: spazio, cartella (con `File/` per i file del proprietario), capogruppo `<id>-ceo`,
   `Stato.md` della memoria.

## 3. Creare uno specialista (lo fa il capogruppo, uno alla volta)

Lancia il capogruppo del progetto (agente `general-purpose` con il testo della sua scheda nel compito), oppure, per
una richiesta semplice, crea tu lo specialista:

```
python3 R/strumenti/crea_agente.py "<progetto>" "<ruolo>" --missione "<cosa fa, su quali file, cosa consegna>" \
        --modello sonnet --strumenti "Read, Grep, Glob, Bash" --limiti "<cosa non fa>" --prova
```

Poi senza `--prova`. Regole (lo script le controlla):
- un progetto ha sempre un capogruppo; nessun agente senza missione chiara;
- haiku esegue comandi già scritti, sonnet ricerca, scrive e verifica, opus solo programmazione (`--programma`);
- un agente alla volta, solo quelli che servono davvero.
Ogni agente nasce con il suo diario (`<cartella>/.claude/memoria/agenti/<nome>.md`: FATTO, DA FARE, ERRORI COMMESSI
DA NON RIPETERE) e la scheda gli impone di leggerlo all'avvio e aggiornarlo prima di chiudere.

## 4. Cambiare e togliere

- Agente: `crea_agente.py "<progetto>" <nome> --modifica --missione "…" --modello … --strumenti "…" --limiti "…"`;
  `--togli` lo sposta in `_archivio/` (il capogruppo non si toglie).
- Progetto: `crea_progetto.py --rinomina <progetto> "<nome>"`, `--sposta <progetto> <cartella>`,
  `--archivia <progetto>` (esce dai progetti attivi, i file restano), `--ripristina <progetto>`.
- Le stesse cose si fanno dalla lavagna del Command Center. Ogni file cambiato ha una copia `.bak-…` accanto.

## 5. Dopo

- Lo `Stato.md` dello spazio si aggiorna da solo (ganci e Command Center), con i diari degli agenti e gli errori ripetuti.
- La riunione del gruppo è disponibile subito: `python3 R/strumenti/riunione.py <progetto> prepara`.
- Salva la decisione nella memoria con la skill `aggiorna-memoria`.
