# Memoria

La scheda che dice se la memoria dei progetti è aggiornata davvero, non solo se esiste.


## I tre numeri

- **Note nel vault**: quante note ci sono in totale nella memoria condivisa (`~/Jarvis-Memoria`, o quella scelta all'installazione).
- **Sessioni di Jarvis**: quante sessioni registrate in `<memoria>/Sessioni/`.
- **Diario di oggi**: se la nota del giorno in `01 Diario/` esiste ed è stata toccata.

## Sincronia

La tabella con una riga per progetto viene da `sincro/controlla.py`, che legge l'elenco dei progetti da `command-center/spazi.json` (la stessa fonte usata dal pannello e dalle missioni: un solo elenco, non due). Per ogni progetto controlla:

- **memoria**: data e ora dell'ultima nota modificata nella sua sezione di `Memoria/`;
- **da fare**: quante caselle aperte (`- [ ]`) ci sono nel suo `Da fare.md`;
- **errori**: quante note in «Errori da non ripetere/»;
- **lavoro**: l'ultimo file toccato nella cartella del progetto;
- **agenti**: quanti profili in `.claude/agents/` e se il progetto ha un capogruppo (un file `ceo-*.md`).

Il semaforo per ogni progetto:

- 🔴 memoria o cartella mancante;
- 🟡 c'è lavoro nel progetto più recente dell'ultima nota di memoria, oltre la soglia di tolleranza;
- 🟢 in ordine.

Il bottone **Verifica ora** rilancia subito `controlla.py` invece di aspettare il giro successivo.

## Da fare

Le voci DA FARE lette dallo `Stato.md` di ogni spazio, in un elenco unico.

## Cosa non fa questa pagina

`controlla.py` è di sola lettura, tranne quando gira con `--scrivi` (lo fa da solo a fine di ogni risposta di Jarvis): in quel caso scrive solo `<memoria>/Comune/Report/Stato aggiornamenti.md`, mai dentro una memoria di progetto. Le verifiche e gli agenti dei progetti stanno nella scheda [Squadra](Squadra): sono lavoro, non un dato di sincronia.
