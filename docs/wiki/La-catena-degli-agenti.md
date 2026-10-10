# La catena degli agenti

Come sono organizzati gli agenti che lavorano per l'utente, e dove si vedono nel Command Center.

## La struttura

```
L'utente
 └─ Chat master = Jarvis, orchestratore   (unica che parla con l'utente e lancia agenti)
     ├─ ricercatore-web (sonnet), esecutore (haiku)       ~/.claude/agents/
     └─ un capogruppo per progetto, con sotto i suoi esperti
         ├─ Azienda Uno        ceo-ai + specialisti · ceo-my140 + specialisti
         ├─ Azienda Due       ceo-Azienda Due + azd-* · ceo-x + x-* (Social)
         └─ Vita personale  ceo-android + specialisti · ceo-risto + specialisti
```

Jarvis è la chat master: capisce la richiesta, la divide, lancia gli agenti, verifica il loro lavoro e risponde all'utente. È l'unica che parla con l'utente e l'unica che lancia agenti. Ogni progetto ha un capogruppo, che risponde a Jarvis e comanda i suoi specialisti. L'elenco degli spazi, dei progetti e dei rispettivi capigruppo è in `command-center/spazi.json` — la stessa fonte che usano il pannello, `sincro/controlla.py` e le missioni.

## I modelli

- **haiku** esegue comandi già scritti: veloce, economico, non decide.
- **sonnet** fa ricerche, analisi, testi, coordinamento e verifica: è il modello dei capigruppo e degli specialisti che devono ragionare.
- **opus** solo per programmare.

## Dove si vede nel pannello

- [Squadra](Squadra), sezione «Agenti per spazio»: una tendina per spazio, una card per progetto, il capogruppo in cima alla sua squadra.
- [Lavagna](Lavagna), bottone «Tutta la catena»: la stessa struttura disegnata come una piramide, dall'utente in giù.
- La scheda di un agente (doppio clic su una riga o su una scheda in lavagna) mostra il suo profilo vero: descrizione, modello, strumenti.

## Come si aggiunge un agente

Il profilo di un agente è un file Markdown con frontmatter in `.claude/agents/<nome>.md`, dentro la cartella del progetto (o in `~/.claude/agents/` per gli agenti di casa di Jarvis, come `esecutore` e `ricercatore-web`). Il frontmatter porta almeno `description`, `model` e `tools`; il corpo del file è l'istruzione vera e propria data all'agente.

Dal pannello, la scheda di un agente (doppio clic) permette di modificare descrizione, modello e strumenti e salvarli: il salvataggio scrive davvero nel file del profilo (`POST /api/agente-profilo`), non solo nell'aspetto grafico della lavagna. Il campo «Dipende da» nella stessa scheda aggiorna invece la sezione «Comunica con» nel profilo, quando si collega un agente a un altro in lavagna.

Un agente nuovo compare in «Agenti per spazio» solo se il suo progetto e il suo capogruppo sono elencati in `spazi.json`.
