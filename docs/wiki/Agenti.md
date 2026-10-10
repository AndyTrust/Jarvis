# Agenti

Jarvis è l'orchestratore: capisce la richiesta, la divide, lancia gli agenti, verifica e risponde. Gli agenti sono file
Markdown con un'intestazione (nome, descrizione, modello, strumenti) e il testo del compito.

| Dove | Chi |
|---|---|
| `~/.claude/agents/` | gli agenti di casa, validi ovunque: `esecutore` (esegue comandi già decisi, modello haiku), `ricercatore-web` (fonti con link e data) |
| `<progetto>/.claude/agents/` | il capogruppo di un progetto e i suoi esperti (li crei dalla lavagna con «Nuovo agente») |
| `<progetto>/.claude/memoria/agenti/<nome>.md` | il quaderno di ogni agente: quello che ha imparato (`strumenti/quaderno.py`) |

Regole che valgono per tutti: il nome con cui chiamare l'utente sta in `profilo-jarvis.md` (campo `chiamami`);
prove prima delle affermazioni; nessuna azione irreversibile senza il sì dell'utente; un agente non lancia altri agenti,
lo fa solo l'orchestratore.

Modelli consigliati: haiku per eseguire, sonnet per cercare, analizzare e verificare, opus per programmare.

Approfondimenti: [La catena degli agenti](La-catena-degli-agenti), [Come parlano gli agenti](Come-parlano-gli-agenti),
[Squadra](Squadra), [Missioni](Missioni).
