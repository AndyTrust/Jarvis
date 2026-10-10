# Stato

La scheda con le cose importanti in cima, rifatta il 26/09/2026. Prima si chiamava Home.


## Cosa succede

Il primo riquadro elenca gli ultimi 25 fatti registrati dal pannello: un'azione lanciata, un errore, un cambio di stato. I fatti finiti bene sono in verde, gli errori in rosso, quelli appena partiti hanno un pallino che pulsa. Un bottone chiede a Jarvis «cosa c'è da guardare oggi?», con questo elenco allegato.

## Jarvis

La sfera al centro mostra la voce di Jarvis in questo momento: in attesa, in ascolto, che pensa, che parla. Quando parla le appare intorno una bolla audio e, sotto il nome, un'onda di cinque barre che si muove. Lo stato viene dalla configurazione vera della voce e dal processo che gira davvero, non è un'animazione finta.

## Salute del pannello

Un elenco di ogni raccoglitore del server — i cicli che leggono lo stato di voce, telefono, VPS, memoria e così via — con ogni quanto gira, l'ultima volta che è andato bene, e l'errore se c'è. Il bottone ↻ su una riga rilancia subito solo quel raccoglitore; **↻ tutto** in cima li rilancia tutti (fino a 60 secondi di attesa).

## Sentinella

Aggiunta il 26/09/2026 su richiesta dell'utente. È un giro del server, ogni 60 secondi, che confronta le anomalie di adesso con quelle del giro prima. Guarda:

- la sincronia dei progetti (🟡 o 🔴, o il battito dei 15 minuti fermo);
- i raccoglitori del server in errore;
- i lavori finiti in errore;
- le missioni che attendono una conferma.

- Telegram sul Mac e sulla VPS: se il bot non è agganciato è un'anomalia.

Un'anomalia nuova o rientrata diventa un fatto in «Cosa succede».

**Dalle 17:07 del 26/09/2026 la sentinella agisce** (decisione dell'utente: «se ci sono problemi lo dice a Jarvis, che si attiva con tutti gli agenti per risolvere e ripulire lo stato»). Al massimo una volta ogni 15 minuti, se ci sono anomalie non ancora passate a Jarvis:

1. **La pulizia**, uno script senza modello (`strumenti/sentinella.py --pulisci`): ritira le prese fantasma del registro dei lavori, cancella i recapiti orfani, chiude le sessioni di Claude ferme da più di 4 ore che non sono in ascolto, controlla Telegram Mac e VPS col guardiano (che riavvia se il bot è caduto). Il risultato sta sotto il titolo («ultima pulizia …»).
2. **Jarvis**, solo per quello che resta: un lavoro «Sentinella → Jarvis: N anomalie», `claude -p` in modo lavoro su Sonnet, con l'incarico di risolvere con gli agenti e riferire in dieci righe. La risposta compare sotto «Ultimo rapporto» e il lavoro in Lavori.

Le anomalie già passate a Jarvis non lo fanno ripartire finché restano le stesse; se una sparisce e torna, si segnala di nuovo. Fino alle 17:07 la sentinella chiedeva a Haiku, in sola lettura, cinque righe di parere.

**In ascolto.** Telegram (Mac), il telefono (Remote Control), la voce (backtalk) e la Cloud Chat sono sessioni di Claude che aspettano apposta: ferme è il loro stato normale. Dal 26/09/2026 `strumenti/agenti.py` le riconosce dal comando del processo (non dal pid) e le segna ASCOLTO; il portiere non le chiama più MUTO e le elenca in una riga «in ascolto»; la pulizia non le chiude mai. Se cadono, si riavviano.

**A pannello spento** la fa launchd: `com.jarvis.sentinella15` lancia `sentinella.py --giro` ogni 15 minuti; con il Command Center acceso lo script esce subito e lascia fare al pannello. Il registro sta in `~/.locale-onedrive/log/sentinella.log`.

L'interruttore accanto al titolo accende o spegne il giro della sentinella (si salva in `configurazione.json`, chiave `sentinella`, acceso di default). Il bottone **Giro adesso** lo forza subito, e se c'è qualcosa da passare a Jarvis lo passa senza aspettare i 15 minuti.

## Interruttori

Accendono e spengono processi veri sul Mac, non finti:

- **Voce**: si parla a Jarvis tenendo premuto Comando destro.
- **Jarvis Talk**: il volto di Jarvis. Da acceso appare anche un cerchio flottante sul desktop, sempre sopra le altre finestre, spostabile col mouse.
- **Jarvis Lavagna**: la lavagna comandata con le mani, via webcam (solo in locale).
- **Telefono → PC**: si parla a Jarvis dall'app Claude sul telefono dell'utente.
- **Schermo del telefono**: si vede e si comanda il telefono Android dell'utente dal Mac.
- **Telegram Mac / Telegram VPS**: il bot Jarvis su Telegram, agganciato dal Mac o dalla VPS. Ogni riga ha anche un bottone ↻ («riaggancia subito») oltre all'interruttore.

Un interruttore acceso vuol dire: il server di quel pezzo è vivo e la sua scheda del browser è aperta. Chiudere la scheda spegne anche il server, e viceversa.

## Cosa può fare Jarvis

Due righe di sola lettura, non interruttori: dicono se le conferme sono attive («Conferme») e se Jarvis può usare mouse e tastiera del Mac («Mouse e tastiera»). Si cambiano chiedendolo in chat, non da qui.

## Comandi rapidi

- **Portfolio: carica Daily Confirmation** — legge l'ultima email del broker e aggiorna Odoo.
- **Briefing** — Jarvis riassume in sola lettura cosa è in corso, cosa resta da fare, cosa non torna, in massimo dieci righe.
- **Domande dalle chiamate** — raccoglie le domande lasciate nelle ultime telefonate.
- **Come migliorarti** — Jarvis legge l'autocontrollo, le chiamate recenti e i registri delle ultime missioni, e propone cosa sistemare per primo.

Sotto, i collegamenti rapidi e i **Comandi Claude Code** definiti in `configurazione.json`.

## Chat a voce

Non è un doppione della scheda Chat: è la stessa conversazione che si fa a voce con Jarvis (tenendo Comando destro), letta da `backtalk/chat.jsonl`. L'ultima battuta sta in cima. Da qui si può anche scrivere un messaggio che arriva a Jarvis come se lo avesse sentito parlato.
