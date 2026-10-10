# Disinstallare

Niente di quello che segue cancella la tua memoria: la cartella della memoria resta finché non la cancelli tu.

1. **Lavori automatici** (se li avevi accesi):
   ```bash
   for f in ~/Library/LaunchAgents/com.jarvis.*.plist; do launchctl bootout gui/$(id -u) "$f" 2>/dev/null; mv "$f" "$f.disattivato"; done
   ```
2. **Collegamenti della memoria**: per ogni `~/.claude/projects/*/memory` che è un collegamento, togli il collegamento e
   rimetti la copia `.bak` (oppure copia lì la cartella dalla memoria):
   ```bash
   for m in ~/.claude/projects/*/memory; do [ -L "$m" ] && { t="$(readlink "$m")"; rm "$m"; cp -R "$t" "$m"; }; done
   [ -L ~/.claude/CLAUDE.md ] && { t="$(readlink ~/.claude/CLAUDE.md)"; rm ~/.claude/CLAUDE.md; cp "$t" ~/.claude/CLAUDE.md; }
   ```
3. **Ganci di Jarvis** in `~/.claude/settings.json`: rimetti la copia `settings.json.bak-AAAAMMGG-HHMM` fatta
   all'installazione, oppure togli a mano le voci che citano `stato_avanzamento.py`, `sessioni.py`, `jarvis_status.py`,
   `guardia_comandi.py`.
4. **Agenti e skill** copiati: `~/.claude/agents/esecutore.md`, `ricercatore-web.md`, `~/.claude/skills/aggiorna-memoria` e le
   altre skill di `claude-config/skills/`. Spostali nel Cestino dal Finder se non li vuoi.
5. **Blocchi negli altri harness**: in `~/.codex/AGENTS.md` e `~/.gemini/GEMINI.md` togli il testo tra
   `<!-- jarvis-memoria:inizio -->` e `<!-- jarvis-memoria:fine -->` (c'è anche la copia `.bak`).
6. **Ambienti Python**: `~/.locale-onedrive/jarvis-widget-venv` e `backtalk/.venv`.
7. **Stato di Jarvis**: `~/.jarvis/` (risposte, percorsi, stato dei ganci). Le chiavi in `~/.env.jarvis` le togli tu.
8. **La cartella di Jarvis** (`~/Jarvis`): spostala nel Cestino.

Claude Code resta installato: per toglierlo segui [la guida ufficiale](https://code.claude.com/docs/en/setup#uninstall-claude-code).
