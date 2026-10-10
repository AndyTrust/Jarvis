# Domande frequenti e problemi

Le difficoltà più comuni con il Command Center, e come si risolvono. Gli errori nuovi che trovi vanno nello `Stato.md` dello spazio (sezione ERRORI) e nella memoria con la skill `aggiorna-memoria`.

## «Token scaduto: il Command Center è ripartito»

Il token cambia a ogni avvio del server. Se il Command Center è stato riavviato mentre una pagina era già aperta (anche l'app installata sul telefono), quella pagina riceverebbe 403 per sempre con il token vecchio. La pagina se ne accorge da sola e si ricarica, al massimo una volta ogni 15 secondi: non serve fare niente, se dopo un riavvio la pagina resta bianca per qualche secondo è normale.

## Il pannello non risponde, o una scheda resta grigia

- Guarda [La barra e le spie](La-barra-e-le-spie): grigio vuol dire «dato non letto ancora», non necessariamente un guasto.
- Nella scheda [Stato](Stato), il riquadro «Salute del pannello» dice quale raccoglitore è fermo o in errore, e da quanto: il bottone ↻ su quella riga lo rilancia subito senza aspettare il giro dopo.
- Se anche la Salute non si aggiorna, il server stesso potrebbe essere fermo: vedi il punto dopo.

## Fermare il Command Center: `pkill` non lo trova

`pkill -f '^python3 server.py$'` non funziona: macOS mostra il processo con il percorso intero dell'interprete Python, non con il nome breve del comando, quindi il pattern non combacia e il server vecchio resta acceso sulla porta 7777. Il sintomo è che il nuovo avvio muore subito con «Address already in use».

Soluzione: trovare il processo per porta, non per nome:

```
lsof -ti tcp:7777
kill <pid>
```

## Il grafo sinapsi (o un altro iframe) resta rotto dopo un riavvio

Un `<iframe src="...">` scritto una volta sola in HTML non riprova da solo se il servizio dietro non era ancora su, o è stato spento e riacceso. Nel Command Center questo è già risolto per il grafo sinapsi: il caricamento è legato allo stato vero del servizio (`locale.volto`), letto ogni pochi secondi, non al solo attributo `src`. Se capita un problema simile su un `iframe` nuovo, la soluzione è la stessa: legarlo a un segnale di stato che la pagina interroga comunque, non lasciarlo statico.

## Le missioni non rispondono a un'istruzione

Le istruzioni mandate a una missione in corso vengono lette al giro successivo dell'orchestratore, non subito. Una missione che aspetta una conferma senza risposta per 30 minuti la considera un No; una che aspetta un'istruzione senza risposta per un'ora resta bloccata finché non arriva.

## Scadenze risponde 404


## Due sessioni si stanno pestando i piedi


## L'app Android non manda diagnosi


## Il desktop della VPS non si collega

Il collegamento passa da un tunnel SSH e da un processo `websockify` sul Mac: se non parte entro qualche secondo, i log sono in `command-center/lavori/vps-tunnel.log` e `vps-websockify.log`.
