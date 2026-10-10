# Inizia qui

1. Apri il Terminale (Applicazioni → Utility → Terminale).
2. Installa Claude Code: `curl -fsSL https://claude.ai/install.sh | bash` (fonte: code.claude.com/docs/en/setup, letta il 2026-10-10; in alternativa `brew install --cask claude-code`).
3. Chiudi e riapri il Terminale, poi controlla: `claude --version`.
4. Serve un abbonamento Claude Pro, Max, Team o Enterprise (o un account Console): il piano gratuito non include Claude Code.
5. Scarica Jarvis: `git clone https://github.com/AndyTrust/Jarvis ~/Jarvis` (se `git` manca, macOS propone di installare gli Strumenti da riga di comando: accetta).
6. Entra nella cartella: `cd ~/Jarvis`
7. Avvia Claude Code: `claude`. La prima volta si apre il browser per il login: segui le istruzioni.
8. Claude legge `CLAUDE.md`, entra in modalità piano e ti fa le domande di avvio, una alla volta: come ti chiami, la lingua, la memoria, e se partire da zero o creare subito il primo progetto. Se non parte da solo, scrivi `/inizia`.
9. Prima di toccare il Mac ti mostra il piano (cosa installa, cosa scrive, dove fa le copie). Niente cambia finché non dici sì.
10. Dopo: per un progetto nuovo basta dirlo («apri il progetto Sito») o scrivere `/nuovo-progetto Sito`; per un aiutante, `/nuovo-agente Sito copywriter`. Guida: `docs/wiki/Progetti-e-agenti.md`.
11. Password, carte e PIN: il **Vault** del pannello (voce «Vault», parte vuoto, lo crei con email e password). Guida: `docs/wiki/Vault.md`.
12. Guida completa: `docs/wiki/Installazione.md`. Problemi: `docs/wiki/Problemi.md`.
