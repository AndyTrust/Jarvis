# Routine e lavori automatici

*Scritta il 2026-09-29.* Tutto quello che gira da solo sul Mac sono lavori launchd (`launchd/*.plist`, resi da `strumenti/installa_launchd.py`) che chiamano script dentro `routine/` (nella copia dell'utente) o `strumenti/`.

| Lavoro | Quando | Cosa fa |
|---|---|---|
| `com.jarvis.command-center` | sempre | il pannello, riavviato se cade |
| `com.jarvis.sentinella15` | ogni 15 min | pulizia e rapporto in Python |
| `com.jarvis.sincronia30` | ogni 30 min | copia e allinea la memoria |
| `com.jarvis.stai-sveglio` | sempre | `caffeinate -s`: il Mac non dorme se è alimentato |
| `com.jarvis.giro-odoo` | 07:00 | il giro dati di Azienda Uno verso Odoo (`routine/giro-crm.sh`) |
| `com.jarvis.report-direzione` | 08:00 | riunione degli agenti, PDF, email, pubblicazione (`routine/report-direzione.sh`) |
| `com.jarvis.idrata-onedrive` | ogni 20 min | scarica i file di OneDrive rimasti nella nuvola |

**Perché dentro Terminale.** I lavori lanciati da launchd non possono scaricare i file di OneDrive rimasti «solo nella nuvola» (`Operation not permitted` / `Resource deadlock avoided`); Terminale sì. Perciò i tre lavori del CRM partono con `open -g -j -a Terminal routine/job-*.command`: senza conferma, senza finestra in primo piano, e la finestra si chiude da sola.

**Il giro riprova da solo.** `routine/giro-crm.sh`: scarica i file mancanti, lancia il giro, se una parte fallisce rilancia solo quella (al massimo 3 tentativi) e scrive `Reports/Giro/STATO-GIRO.md` (`stato: completo` o `PARZIALE`). Il report delle 08:00 lo legge: se è PARZIALE, il CEO (`ceo-ai` con `manutentore-dati`) rielabora le parti fallite fino a 3 giri. Chi legge `STATO-GIRO.md` con data di oggi e `completo` non deve scaricare di nuovo i dati.

**Verifica.** `launchctl list | grep com.jarvis`; i log stanno in `~/Library/Logs/` (`Azienda Uno_giro.log`, `Azienda Uno_report_direzione.log`, `jarvis_idrata.log`).
