# Routine e lavori automatici

*Scritta il 2026-09-29.* Tutto quello che gira da solo sul Mac sono lavori launchd (`launchd/*.plist`, resi da `strumenti/installa_launchd.py`) che chiamano script dentro `routine/` (nella copia dell'utente) o `strumenti/`.

| Lavoro | Quando | Cosa fa |
|---|---|---|
| `com.jarvis.command-center` | sempre | il pannello, riavviato se cade |
| `com.jarvis.sentinella15` | ogni 15 min | pulizia e rapporto in Python |
| `com.jarvis.sincronia30` | ogni 30 min | copia e allinea la memoria |
| `com.jarvis.stai-sveglio` | sempre | `caffeinate -s`: il Mac non dorme se è alimentato |
| `com.jarvis.pulizia-claude` | 06:20 | pulizia e unione di `~/.claude` nella memoria condivisa (`strumenti/pulisci_claude.py`) |
| `com.jarvis.giro-apprendimento` | 06:40 | i diari degli agenti dei progetti nella memoria (nessun progetto = niente da fare) |

I lavori tuoi (un giro dati, un report del mattino) si aggiungono con un modello in `launchd/` e una riga in
`DI_TITOLARE` di `strumenti/installa_launchd.py`.

**Perché dentro Terminale.** I lavori lanciati da launchd non possono scaricare i file di OneDrive rimasti «solo nella nuvola» (`Operation not permitted` / `Resource deadlock avoided`); Terminale sì. Un lavoro tuo che legge da OneDrive può partire con `open -g -j -a Terminal <script>.command`.

**Verifica.** `launchctl list | grep com.jarvis`; i log stanno in `~/.jarvis/log/`.
