# Command Center di Jarvis

Guida d'uso completa, per chi apre il pannello per la prima volta e per chi lo usa ogni giorno. Descrive il codice così com'è il 26 settembre 2026.



## Cos'è

Il Command Center è il pannello di controllo di Jarvis. Gira sul tuo Mac, non su internet. Mostra lo stato di tutti i pezzi — la voce, il telefono,  la VPS, la memoria — accende e spegne gli interruttori, lancia le verifiche, apre le missioni e tiene la chat con Jarvis.

Il codice sta in `~/Jarvis/command-center/`: `server.py` è il server, `static/index.html` e `static/app.js` sono la pagina, `missione.py` lancia le missioni, `spazi.json` elenca gli spazi e i progetti (all'installazione è vuoto: li crea `strumenti/crea_progetto.py`).

## Per chi è

Per l'utente. È l'unico punto dove vedere in un colpo d'occhio cosa sta succedendo su tutte le macchine, senza aprire un terminale per ogni pezzo.

## Come si apre

Due strade:

- Doppio clic su `avvio/Command Center.command` (o l'icona sulla Scrivania).
- Il pannello è già aperto: si va su [http://127.0.0.1:7777](http://127.0.0.1:7777) in un browser qualsiasi del Mac.

Il pannello gira solo su `127.0.0.1`: da fuori dal Mac non si vede. È protetto da un token che cambia a ogni avvio del server — se il server riparte, la pagina se ne accorge da sola e si ricarica (vedi [Domande frequenti e problemi](Domande-frequenti-e-problemi)).

È anche una web app installabile (manifest e service worker): dal telefono dell'utente, sulla stessa rete Wi-Fi, si apre con un QR e si comporta come un'app.

## Le pagine della guida

- [Installazione](Installazione) — da zero al pannello acceso, con Claude Code o con Docker
- [Progetti e agenti](Progetti-e-agenti) — Jarvis parte vuoto e crea progetti e agenti dalle tue richieste
- [Come funziona](Come-funziona) · [Memoria condivisa](Memoria-condivisa) · [Agenti](Agenti) · [Telefono](Telefono) · [VPS facoltativa](VPS)
- [Aggiornare](Aggiornare-Jarvis) · [Disinstallare](Disinstallare) · [Problemi](Problemi)
- [Primi passi](Primi-passi) — dieci minuti per orientarsi
- [La barra e le spie](La-barra-e-le-spie) — cosa vuol dire ogni colore
- [Chat](Chat) — parlare con Jarvis, i comandi rapidi, modo lavoro e lettura
- [Stato](Stato) — cosa succede, la voce di Jarvis, la salute del pannello, la sentinella, gli interruttori
- [Squadra](Squadra) — chi lavora adesso, le chiavi, i lavori, gli agenti per spazio
- [Missioni](Missioni) — affidare un obiettivo a più esperti in parallelo
- [Memoria](Memoria) — i numeri della memoria e la sincronia dei progetti
- [Lavagna](Lavagna) — la mappa degli agenti, trascinabile
- [La catena degli agenti](La-catena-degli-agenti) — chi comanda chi, i modelli
- [La memoria nel vault](La-memoria-nel-vault) — dove sta la memoria vera, come si cerca
- [Domande frequenti e problemi](Domande-frequenti-e-problemi)
- [Sicurezza](Sicurezza)

## Cosa non è

Il Command Center non sostituisce la chat di Claude Code sul Mac o dal telefono: è un pannello. La chat di Jarvis dentro il pannello (`/api/claude-code`) è una chiamata `claude -p` per volta, non una sessione lunga con `--resume`: ogni richiesta riparte, con il modo (lavoro o lettura) deciso dall'interruttore in Chat.
