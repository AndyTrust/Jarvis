# Il Vault

Il Vault è la cassaforte delle password dentro il Command Center: accessi ai siti, carte, PIN, variabili (le chiavi
dei programmi) e note sicure. Tutto resta cifrato sul tuo computer. Parte **vuoto**: lo crei tu, la prima volta.

Si apre dalla voce **Vault** del menu del Command Center (sul Mac può stare sotto «Altro»), indirizzo
`http://127.0.0.1:7777/#vault`.

## Dove stanno i dati

| Sistema | Cartella del Vault | Chiave del dispositivo |
|---|---|---|
| macOS | `~/Library/Application Support/Jarvis/vault/` | Portachiavi di macOS (servizio «jarvis-vault») |
| Windows | `%APPDATA%\Jarvis\vault\` | file protetto con DPAPI, legato al tuo account di Windows |

Il Vault rifiuta di vivere in un repository git, in OneDrive, iCloud, Dropbox, Google Drive o in un vault di Obsidian.
Dentro la cartella ci sono `vault.json` (cifrato), `backup/` (copie cifrate), `usi.jsonl` (registro degli usi, senza
valori) e, se lo scrivi tu, `config.json`.

## Come si crea

1. Apri **Vault** nel Command Center. Vedi «Vault non ancora creato».
2. Scrivi la tua email e una password di almeno 12 caratteri (due volte).
3. Il Vault ti mostra **24 parole di recupero**. Scrivile su carta, in ordine, e tienile in un posto sicuro. Non le
   rivedrai più.
4. Spunta «Le ho scritte su carta» e premi **Continua**. Il Vault è aperto e vuoto, con le sezioni Lavoro, Personale,
   Famiglia, Casa, Soldi, Altro.

Per aggiungere una voce: **+ Nuova**, scegli il tipo (Accesso web, Carta, PIN, Variabile, Nota sicura), compila, **Salva**.
Il Vault si blocca da solo dopo 5 minuti senza tocchi, o dopo 1 minuto con la scheda nascosta. Puoi impostare un PIN
(menu **⋯**) per sbloccarlo più in fretta: dopo 5 errori il PIN si spegne.

Le sezioni di partenza e le regole per l'importazione stanno in `command-center/vault-sezioni.esempio.json`. Per
cambiarle copialo in `command-center/vault-sezioni.json`: quel file è tuo, resta fuori da git e l'aggiornamento non lo
tocca.

## Come si importa da Chrome

1. In Chrome: **Impostazioni → Compilazione automatica → Gestore delle password → Impostazioni → Esporta password**.
   Salva il file `.csv` in **Download**, **Scrivania** o **Documenti**.
2. Nel Vault: menu **⋯ → Da Chrome (CSV)**, scegli il file, premi **Prepara il piano**. Vedi solo dei conteggi:
   quante voci, quanti doppioni, quante password riusate.
3. Premi **Importa ora**. Prima dell'importazione il Vault fa un backup cifrato di sé stesso.
4. Alla fine il Vault ti propone di **eliminare il file CSV**, che contiene tutte le password in chiaro. Servono due
   conferme. Poi svuota il Cestino e cancella le altre copie del file (mail, cloud).

Regole: stesso sito e stesso utente diventano una voce sola; password uguali su siti diversi non si uniscono, ma la voce
porta l'avviso «password riusata». Una voce che hai modificato a mano non viene sovrascritta da un'importazione dopo.

Da `~/.env.jarvis` (le chiavi dei programmi): menu **⋯ → Importa le chiavi di .env.jarvis**. Il file si legge e basta,
non viene mai modificato. Due nomi con lo stesso valore diventano una voce con un alias.

## Esportare, importare, backup

- **Esporta (file cifrato)**: un file `vault-esportazione-AAAAMMGG-HHMM.json` cifrato con una frase che scegli
  (almeno 12 caratteri). Serve per spostare il Vault su un altro computer. Senza la frase non si apre.
- **Importa un'esportazione del Vault**: lo stesso file, con la stessa frase, in un Vault già creato. Le voci che ci
  sono già si saltano.
- **Backup ora**: una copia cifrata di `vault.json` in `backup/`. In più il Vault ne fa una al giorno da solo (tiene le
  ultime 30). Per un backup completo copia la cartella del Vault su un disco esterno: è cifrata, ma da sola non basta
  per aprirla (servono la password e la chiave del dispositivo, oppure le 24 parole).

## Recupero con le 24 parole

Se hai perso la password, o sei su un computer nuovo (la chiave del dispositivo non c'è più), nella pagina di sblocco
premi **Ho perso l'accesso**, scrivi le 24 parole e una password nuova. Il Vault crea una chiave del dispositivo nuova
e ti fa entrare. Il PIN va reimpostato. Senza le 24 parole e senza la password **nessuno** può aprire il Vault, nemmeno
l'assistente: non esiste una porta di servizio.

## Accesso con Google (facoltativo)

All'inizio il pulsante «Accedi con Google» è spento e dice perché: ogni proprietario deve creare il **suo** client OAuth.
Il repository non contiene nessun ID client.

1. Vai su <https://console.cloud.google.com/>, crea un progetto (o scegline uno tuo).
2. **API e servizi → Schermata di consenso OAuth**: tipo «Esterno», nome a piacere, la tua email. Ambiti: solo `openid`
   e `email`. Aggiungi la tua email fra gli utenti di test.
3. **API e servizi → Credenziali → Crea credenziali → ID client OAuth**, tipo **Applicazione web**.
   URI di reindirizzamento autorizzato: `http://127.0.0.1:7777/api/vault/google/callback` (se usi un'altra porta,
   metti quella).
4. Copia ID client e segreto client in `~/.env.jarvis` (su Windows `%USERPROFILE%\.env.jarvis`), mai nel repository:

   ```
   VAULT__GOOGLE_CLIENT_ID=il-tuo-id.apps.googleusercontent.com
   VAULT__GOOGLE_CLIENT_SECRET=il-tuo-segreto
   ```

   In alternativa scrivili in `google-client.json` dentro la cartella del Vault:
   `{"client_id": "...", "client_secret": "..."}`.
5. Ricarica la pagina del Vault: il pulsante si accende. Puoi creare il Vault con Google, oppure collegare Google a un
   Vault creato con email e password (menu **⋯ → Collega l'account Google**).

Google conferma **chi sei**, non cifra i dati. Con Google attivo la chiave resta quella del dispositivo. Se vuoi che
serva anche la password: menu **⋯ → Con Google chiedi anche la password**.

## Sicurezza, in parole semplici

- Ogni voce è cifrata con AES-256-GCM. Le chiavi si aprono con la password (PBKDF2-SHA256, 600 000 giri) **insieme**
  alla chiave del dispositivo. Chi ruba solo il file del Vault non può provare le password a tappeto.
- La pagina vede i valori solo quando premi **Mostra** o **Copia**; dopo 20 secondi tornano mascherati, gli appunti si
  svuotano dopo 30 secondi. CVV, PIN della carta e codici di recupero chiedono di nuovo password o PIN ogni volta.
- Nessun valore finisce nei log, nel registro degli usi o nelle risposte di errore. L'assistente vede solo nomi e stato.
- Il Vault si apre solo da questo computer (`127.0.0.1`). Una richiesta da un'altra macchina, o arrivata da internet
  attraverso un ponte, riceve 403.
- Ogni voce ha uno storico di 20 versioni e si può annullare; anche l'eliminazione si annulla.
- Un gancio git (installato da `strumenti/ganci_git.py`) ferma il commit se nello stage c'è un file del Vault, una
  esportazione, `vault-sezioni.json`, un CSV di password o `.env.jarvis`. Lo stesso controllo si lancia a mano con
  `python3 command-center/vault_cc.py barriera-git`.

## Limiti onesti

- **Ripiego senza portachiavi.** Se il portachiavi del sistema non è disponibile (Windows senza DPAPI, o
  `JARVIS_VAULT_PORTACHIAVI=file`), la chiave del dispositivo sta in un file con i permessi del solo tuo utente, nella
  cartella del Vault. Il Vault resta cifrato con la tua password, ma chi copia tutta la cartella può provare a
  indovinarla: in quel caso la pagina lo dice, e conviene una password lunga.
- **Chi controlla il tuo account** (un programma maligno che gira come te, mentre il Vault è aperto) può leggere quello
  che leggi tu. Il Vault protegge i dati a riposo, non un computer già compromesso.
- **Cancellare il CSV** sovrascrive il file prima di toglierlo, ma su un disco SSD questo non garantisce che i blocchi
  vecchi spariscano. Per questo il Vault ricorda di svuotare il Cestino e cancellare le altre copie.
- **Windows**: il codice DPAPI usa le funzioni di sistema `CryptProtectData`/`CryptUnprotectData` con `ctypes`, senza
  librerie in più. Le prove automatiche di questa versione sono state fatte su macOS; su Windows vero vanno ripetute
  (vedi «Prove» sotto).

## Cosa non fa

- **Non usa mai le carte.** Una carta si salva e si mostra a te, ma l'assistente e gli agenti non la usano: un
  pagamento passa da un servizio di pagamento, con la tua conferma.
- **Non sincronizza** il Vault fra computer: per spostarlo usi esporta/importa.
- **Non compila i siti da solo su Windows.** L'uso da parte degli agenti (`strumenti/vault.py usa` e `codice`, che
  scrivono un valore nel campo di Chrome senza mostrarlo a nessuno) esiste solo su macOS e nel modo VPS (Linux). Su
  macOS è spento finché non scrivi nel `config.json` del Vault `"uso_agenti": true` e il browser da usare, per esempio
  `"browser": {"principale": 9222}` (Chrome avviato con `--remote-debugging-port=9222`). Ogni uso chiede il tuo
  **Consenti** nella pagina, una volta. Il valore va solo nel sito scritto nella voce (campi Domini o Link).
- **Non legge la posta** per i codici di verifica se non hai installato tu uno strumento `strumenti/posta.py` con le tue
  caselle.

## Modo VPS (avanzato, facoltativo)

Chi ha un server Linux con il Command Center dietro un login può far vivere lì il Vault: si accende con
`JARVIS_VAULT_MODO=vps` nel servizio, più `JARVIS_VAULT_URL_PUBBLICO=https://il-tuo-sito` (per il ritorno di Google)
e, se servono agli agenti, `JARVIS_VAULT_BROWSER_PORTE='{"nome": porta}'`. La chiave del dispositivo sta in un file 0400
in una cartella separata dai dati. Sul computer locale, `"remoto": "https://il-tuo-sito/#vault"` nel `config.json` del
Vault trasforma la pagina in un rimando. È una configurazione per chi sa amministrare un server: senza queste variabili
il Vault resta solo locale.

## Se il Vault dice «spento»

Manca la libreria di cifratura `cryptography` nel Python del Command Center.

- **macOS**: `python3 -m venv ~/.jarvis/vault-venv && ~/.jarvis/vault-venv/bin/pip install -r requirements/vault.txt`
  (lo fa `installa.sh`), poi riavvia il Command Center. Il Vault trova da solo quell'ambiente se la versione di Python è
  la stessa del `python3` che avvia il pannello.
- **Windows**: rilancia `INSTALLA.ps1` (mette `cryptography` nell'ambiente `.venv`), poi riavvia il Command Center.

## Prove

Le prove lavorano in una casa finta completa (HOME, USERPROFILE, APPDATA, XDG_*) e con dati finti:

```
python3 command-center/prova_vault.py            # cifratura, sblocco, voci, storico, recupero, Google finto, barriera
python3 command-center/prova_vault_chrome.py     # importazione da CSV
python3 command-center/prova_vault_server.py     # il Command Center vero su una porta libera (--resta per il browser)
```

Su Windows si lanciano con `python` dalla cartella `app` del repository (o da `%USERPROFILE%\jarvis`).
