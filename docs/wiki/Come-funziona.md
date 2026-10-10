# Come funziona

Jarvis è una cartella di programmi che lavora intorno a Claude Code, sul tuo Mac.

```
            tu (chat, voce, pannello)
                     │
        ┌────────────▼────────────┐
        │       Claude Code       │  legge CLAUDE.md e profilo-jarvis.md
        │  (Jarvis = orchestratore)│  usa skill, agenti e ganci di ~/.claude
        └──┬─────────┬─────────┬──┘
           │         │         │
   agenti  │   ganci │         │ strumenti (python3 strumenti/...)
           ▼         ▼         ▼
   ┌────────────┐ ┌──────────────────────────────┐ ┌──────────────────┐
   │ esecutore  │ │ Stop / PreCompact / SessionEnd│ │ Command Center   │
   │ ricercatore│ │ → <memoria>/<spazio>/Stato.md │ │ 127.0.0.1:7777   │
   │ capigruppo │ │ → <memoria>/Sessioni/         │ │ chat, lavagna,   │
   └────────────┘ └──────────────┬───────────────┘ │ missioni, stato  │
                                 ▼                 └──────────────────┘
              ┌──────────────────────────────────────┐
              │  memoria condivisa  (~/Jarvis-Memoria)│ ← Codex, Gemini, Cursor
              │  Comune/ · <spazio>/ · Diario/        │   leggono la stessa
              │  Report/ · Sessioni/ · Claude/projects│
              └──────────────────────────────────────┘
```

## I pezzi

| Pezzo | Dove | Cosa fa |
|---|---|---|
| Istruzioni | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` | chi è l'assistente, le regole, la prima apertura |
| Profilo | `profilo-jarvis.md` (tuo, fuori da git) | il tuo nome, quello dell'assistente, tono, lingua |
| Command Center | `command-center/` | il pannello nel browser, solo su `127.0.0.1` |
| Strumenti | `strumenti/` | installazione, memoria, mani sul Mac, verifiche |
| Configurazione per Claude Code | `claude-config/` | ganci, agenti di casa, skill (copiati in `~/.claude`) |
| Lavori automatici | `launchd/` | pannello sempre acceso, sentinella, sincronia (facoltativi) |
| Memoria condivisa | `~/Jarvis-Memoria` o la cartella che scegli | una sola fonte per tutti gli harness |

## Il giro di una richiesta

1. Scrivi in chat (terminale, pannello o voce).
2. Claude Code legge `CLAUDE.md`, il profilo e la porta d'ingresso della memoria.
3. Divide il lavoro, se serve lancia agenti, verifica con comandi.
4. A ogni fine risposta (al massimo ogni 10 minuti), prima della compattazione e a fine sessione, il gancio
   `stato_avanzamento.py` aggiorna lo `Stato.md` dello spazio e il registro delle sessioni.
5. Quando chiudi un lavoro, la skill `aggiorna-memoria` salva il giudizio: errori da non ripetere, fatto, da fare.

## Cosa non esce dal Mac

Il pannello ascolta solo su `127.0.0.1`. Le chiavi stanno in `~/.env.jarvis`. La memoria sta dove scegli tu:
se scegli iCloud Drive o OneDrive, le note viaggiano con quel servizio. I dati vanno ad Anthropic solo come
parte delle conversazioni con Claude, secondo il tuo abbonamento.
