# Problemi

| Cosa vedi | Cosa fare |
|---|---|
| `claude: command not found` | apri un Terminale nuovo; se non basta, la cartella `~/.local/bin` non è nel PATH: [guida ufficiale](https://code.claude.com/docs/en/troubleshoot-install) |
| Claude non fa le domande di avvio | scrivi `/inizia`; controlla che sei nella cartella di Jarvis (`pwd`) |
| Le domande ripartono ogni volta | `~/.jarvis/installato.json` non c'è: l'installazione non è arrivata in fondo. Rilancia `python3 strumenti/installa_guidata.py` e leggi l'errore |
| «nelle risposte c'è qualcosa che sembra una chiave» | hai scritto una chiave in `risposte-avvio.json`: toglila e mettila in `~/.env.jarvis` |
| `brew: command not found` | installa Homebrew da https://brew.sh, oppure `--senza-brew` |
| Il pannello non si apre | `python3 command-center/server.py` e leggi l'errore; porta occupata: `CC_PORTA=7778 python3 command-center/server.py` |
| La pagina dice «token scaduto» | il server è ripartito: ricarica |
| `403 host non ammesso` | usa `127.0.0.1` o `localhost` con la stessa porta di `CC_PORTA` |
| Lo `Stato.md` di uno spazio non si aggiorna | la cartella in cui lavori non è in nessuno spazio di `~/.jarvis/percorsi.json`; guarda `~/.jarvis/ganci.log` |
| Un file `.nuovo-AAAAMMGG` in `~/.claude` | avevi già un tuo file con quel nome: confrontali; `python3 strumenti/installa_claude_config.py --aggiorna` sostituisce (con copia) |
| File `.da-<Mac>-AAAAMMGG` nella memoria | due versioni diverse della stessa nota: uniscile a mano e togli quella in più |
| Le mani sul Mac non cliccano | Impostazioni di Sistema → Privacy e sicurezza → Accessibilità e Registrazione schermo per Terminale |

Altre domande: [Domande frequenti e problemi](Domande-frequenti-e-problemi). La verifica completa:
`python3 strumenti/verifica_installazione.py`.
