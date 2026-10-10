# La memoria nel vault

Dove sta davvero la memoria di Jarvis e dei progetti, e come si cerca senza riscoprire quello che è già scritto.

## Una sola memoria


Ogni nota ha link `[[...]]` verso le note collegate e link `file:///` verso la cartella e il file vero.

## Come si cerca

Prima di scrivere qualcosa di nuovo, si cerca se esiste già:

```
python3 ~/Jarvis/strumenti/cerca_memoria.py "parole"
python3 ~/Jarvis/strumenti/cerca_memoria.py "token n8n" --spazio "<spazio>" -n 5
python3 ~/Jarvis/strumenti/cerca_memoria.py "saldo unicredit" --tipo errore
python3 ~/Jarvis/strumenti/cerca_memoria.py --rifai        # rifà l'indice da zero
```

L'indice è SQLite con ricerca full-text (FTS5), tenuto sul Mac fuori da OneDrive, e si rifà da solo guardando solo i file cambiati (data e misura) prima di ogni ricerca. La ricerca ignora maiuscole e accenti; le parole si cercano tutte insieme (AND), a meno di usare `--o` (basta una); una frase esatta va fra virgolette doppie dentro l'argomento.

## La sincronia: `controlla.py`

`python3 ~/Jarvis/sincro/controlla.py` guarda, per ogni progetto elencato in `command-center/spazi.json`, se la sua sezione di memoria è aggiornata rispetto al lavoro fatto davvero nella sua cartella. Il dettaglio del semaforo (🔴🟡🟢) e dei numeri che produce è nella pagina [Memoria](Memoria) del pannello.

## Le caselle dell'utente: `task.py`

Ogni richiesta dell'utente diventa una casella nel diario del giorno:

```
python3 ~/Jarvis/strumenti/task.py add "testo"        aggiunge una casella aperta
python3 ~/Jarvis/strumenti/task.py fatto "testo"      spunta la casella che contiene questo testo
python3 ~/Jarvis/strumenti/task.py lista              le aperte di oggi e dei 3 giorni prima
```


## «Salva in memoria»

Quando un lavoro si chiude (anche con un semplice «perfetto» o «va bene» dell'utente): si scrive o si aggiorna la nota in `Memoria/<spazio>/`, correggendo quello che non è più vero senza aggiungere doppioni; si aggiorna il «Da fare» della sezione; si aggiorna la memoria del progetto con lo strumento della skill `aggiorna-memoria`; si aggiunge una riga nel diario del giorno e si spunta la casella; si verifica che `Memoria/00 Comune/Report/Stato aggiornamenti.md` non abbia righe 🟡 o 🔴 rimaste aperte.

## Niente doppioni

Una sola fonte per ogni cosa: gli spazi e i progetti sono in `spazi.json`, non ripetuti altrove; la memoria vera è nel vault, non nelle vecchie `<progetto>/.claude/memoria/MEMORIA.md` (superate dal 23/09/2026); gli agenti sono file di profilo veri, non descrizioni sparse in più note.
