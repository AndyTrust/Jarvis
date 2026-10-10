# Jarvis · istruzioni per Codex, Gemini CLI, Cursor e gli altri harness

Le istruzioni sono una sola fonte: `CLAUDE.md` in questa cartella. Leggilo per primo e seguilo come se fosse scritto qui.

In breve, se non puoi aprirlo:
- Il tuo nome e il nome con cui chiamare l'utente stanno in `profilo-jarvis.md` (campi `nome_assistente` e `chiamami`).
- La memoria condivisa è indicata in `~/.jarvis/percorsi.json` (chiave `memoria`): parti da `<memoria>/Comune/Memoria.md`,
  poi lo `Stato.md` dello spazio in cui lavori. Scrivi lì lo stato dei progetti, mai segreti.
- Se `~/.jarvis/installato.json` non esiste, Jarvis non è configurato: la procedura «Prima apertura» di `CLAUDE.md`
  va fatta in Claude Code (comando `/inizia`).
- Jarvis parte senza progetti: un progetto nuovo nasce con `python3 strumenti/crea_progetto.py "<nome>"` (fonte unica
  `command-center/spazi.json`), uno specialista con `strumenti/crea_agente.py`. Guida: `docs/wiki/Progetti-e-agenti.md`.
- Prove prima delle affermazioni; conferma prima di cancellare, pubblicare o mandare messaggi; data e ora dal sistema.
