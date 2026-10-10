---
name: riunione-agenti
description: "Da usare quando l'utente chiede la riunione giornaliera degli agenti di un gruppo (Azienda Uno, Azienda Due, Vita personale, Patrimonio), «fate il punto», «cosa dicono gli agenti», «il report della riunione», «a che punto sono le strategie», «chiudi la previsione», oppure quando una strategia di trading o di business va registrata, verificata o giudicata (continuare, correggere, abbandonare). Anche per aggiungere un gruppo nuovo alla riunione."
---

# Riunione degli agenti

## In breve

Un giro al giorno per gruppo, sempre uguale. Lo script fa numeri, controlli, report e
registro; gli agenti danno il giudizio. L'utente riceve una pagina sola, o «niente di nuovo».

```
dati ─► posizioni degli specialisti ─► controlli meccanici + revisore
     ─► verdetto del capogruppo (riunione.json) ─► report per l'utente ─► registro strategie
```

Script: `~/Jarvis/strumenti/riunione.py`. Configurazione dei gruppi (membri, fonti, scadenze,
metriche, cartelle): `~/Jarvis/strumenti/riunione_gruppi.json`. Prove:
`python3 ~/Jarvis/strumenti/prova_riunione.py`.

## Chi fa cosa

```
L'utente
 └─ chat master: lancia prepara, lancia gli agenti, lancia chiudi, parla con l'utente
     └─ capogruppo del gruppo: scrive riunione.json (verdetti)
         ├─ revisore: controlla le posizioni
         └─ specialisti: scrivono una posizione a testa
```

Lo script non lancia agenti. Solo la chat master li lancia, come `general-purpose`, con il
modello scritto nella prima riga del compito e il testo intero del compito.

## Il giro

1. `python3 ~/Jarvis/strumenti/riunione.py <gruppo> prepara`
   Crea `~/Jarvis/riunioni/<gruppo>/<AAAA-MM-GG>/` con `dati.md`, `controlli.md`, i compiti in
   `compiti/` e l'ordine in `LEGGIMI.md`. Se `riunione.json` c'è già, si ferma: la riunione
   di oggi è fatta.
2. Specialisti in parallelo (un messaggio solo). Ognuno scrive `posizioni/<agente>.md` con cinque
   sezioni fisse: Fatti (con fonte e data), Cambiato da ieri, Dubbi, Proposta, Non verificato.
3. Revisore: scrive `posizioni/revisione.md`, esito ok oppure obiezioni.
4. Capogruppo: scrive `riunione.json` (lo schema è nel suo compito).
5. `python3 ~/Jarvis/strumenti/riunione.py <gruppo> chiudi`
   Valida `riunione.json` (se è sbagliato non tocca niente ed elenca gli errori: il lavoro torna
   al capogruppo), scrive `Memoria/<spazio>/Report/AAAA-MM-GG riunione <gruppo>.md`, aggiorna le
   schede delle strategie e rigenera `Strategie.md`. Rilanciato, non riscrive.
6. Alla chat master resta: leggere il report, verificarne almeno un numero, riferire all'utente.

`riunione.py <gruppo> stato` dice a che punto è il giro di oggi. `riunione.py elenco` mostra i gruppi.

Azienda Uno è diverso: la riunione la fa già la routine `com.jarvis.report-direzione` alle 8:00.
`prepara` e `stato` la leggono soltanto; `chiudi` riduce il suo `riunione.json` alla pagina per
L'utente. La routine non si tocca.

## Il report per l'utente

Al massimo una pagina: fino a cinque cose, solo se cambiano una decisione o un rischio; dove
approfondire con il costo del controllo; le decisioni che servono con l'incarico già scritto;
cosa non è verificato. Se non c'è niente di questo: «Niente di nuovo.»

## Il registro delle strategie

Una scheda per strategia in `Memoria/<spazio>/Strategie/<id>.md`, indice `Strategie.md`
rigenerato dallo script (non si corregge a mano). Frontespizio: id, gruppo, versione, stato
(ipotesi, prova, demo, attiva, sospesa, abbandonata), ipotesi, regola, taratura, prova,
previsioni, decisione, versioni.

- `riunione.py <gruppo> strategie`: indice e previsioni scadute da chiudere.
- `riunione.py <gruppo> chiudi-previsione <id> <n> <realizzato> --fonte "<file o comando>"`:
  calcola errore e se il valore cade nell'intervallo.
- Le previsioni si aggiungono e si chiudono, non si cancellano. Una scaduta da più di 30 giorni
  senza esito diventa «scaduta senza dati» alla chiusura successiva.
- Una previsione senza data si scrive «senza data» e non conta come prova.
- Un verdetto «correggere» o «abbandonare» del capogruppo è una proposta: finisce fra le
  decisioni per l'utente e lo stato della scheda non cambia finché l'utente non dice sì.

Per un backtest: `python3 ~/Jarvis/strumenti/backtest_check.py risultati.csv --taratura DA:A --prova DA:A`.
Esce 1 se la prova non viene dopo la taratura; dà errore e copertura a 1, 3 e 12 mesi contro la
media dei 12 mesi prima della prova.

## Regole che non si piegano

- Nessun consiglio finanziario dato come certezza: ogni previsione ha il suo intervallo o la
  scritta «intervallo non dichiarato».
- Ogni numero con fonte e data. Un numero senza fonte va in «Non verificato».
- Niente ordini reali, niente scritture in database o sulla VPS, niente messaggi senza il sì
  dell'utente.
- Mai inventare un numero per riempire una scheda: se la nota non lo dice, il campo resta vuoto.

## Il limite onesto

Le strategie di Patrimonio hanno poche operazioni (20-140 l'anno) e previsioni quasi tutte senza
intervallo o senza data. Con questi dati la copertura non si misura per mesi. Il report lo dice,
invece di presentare un backtest come una prova.

## Aggiungere un gruppo

Un blocco in `riunione_gruppi.json` con nome, spazio, capogruppo, revisore, membri con i temi,
fonti (`percorso` con `max_giorni`, oppure `solo_agenti` per i database), scadenze, metriche
(stesso numero in due file, con `cerca` e `tolleranza`), strategie e report. Un profilo che non
c'è lo segnala `controlli.md`. Poi `python3 ~/Jarvis/strumenti/prova_riunione.py` e
`riunione.py <gruppo> prepara` con `RIUNIONE_RADICE` in una cartella di prova.
