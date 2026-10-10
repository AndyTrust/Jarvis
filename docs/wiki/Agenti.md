# Agenti

Jarvis è l'orchestratore: capisce la richiesta, la divide, lancia gli agenti, verifica e risponde. Gli agenti sono file
Markdown con un'intestazione (nome, descrizione, modello, strumenti) e il testo del compito.

| Dove | Chi |
|---|---|
| `~/.claude/agents/` | gli agenti di casa, validi ovunque: `esecutore` (esegue comandi già decisi, modello haiku), `ricercatore-web` (fonti con link e data) |
| `<progetto>/.claude/agents/` | il capogruppo `<progetto>-ceo` e gli specialisti che crea quando servono (`strumenti/crea_agente.py`, `/nuovo-agente`, o la lavagna). All'installazione non ce n'è nessuno |
| `<progetto>/.claude/memoria/agenti/<nome>.md` | il diario di ogni agente: FATTO, DA FARE, ERRORI COMMESSI DA NON RIPETERE (con data e ora), poi quello che ha imparato (`strumenti/quaderno.py`) |

Regole che valgono per tutti: il nome con cui chiamare l'utente sta in `profilo-jarvis.md` (campo `chiamami`);
prove prima delle affermazioni; nessuna azione irreversibile senza il sì dell'utente; un agente non lancia altri agenti,
lo fa solo l'orchestratore.

Modelli consigliati: haiku per eseguire, sonnet per cercare, analizzare e verificare, opus per programmare.

Come nascono, si cambiano e si archiviano: [Progetti e agenti](Progetti-e-agenti).
Approfondimenti: [La catena degli agenti](La-catena-degli-agenti), [Come parlano gli agenti](Come-parlano-gli-agenti),
[Squadra](Squadra), [Missioni](Missioni).
