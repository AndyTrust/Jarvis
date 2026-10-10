# Contratto: Registro e regole di permesso come dati

*2026-10-03 · cc-registro-opus · si aggiunge a `CONTRATTO-approvazioni.md`, che resta com'è. Aggiornato alle 22:30 con le correzioni della revisione 2 (`vps/cc-ponte/REVISIONE-2-PERMESSI.md`).*

Decisione dell'utente (2026-10-03, idee prese da OpenBot): la politica di permesso del modo «approvazione» sta in un
file di dati, non nel codice. Una pagina «Registro» mostra in un elenco unico cosa Jarvis ha fatto o tentato, con
l'esito e la regola che l'ha deciso.

## 1. Il file delle regole

`~/.locale-onedrive/jarvis-cc/regole-permessi.json`: fuori da git e da OneDrive, permessi 0600. Se manca, si crea
da solo con il contenuto predefinito. Il Command Center lo rilegge a ogni richiesta (cache su mtime, dimensione e inode).

```json
{
  "versione": 1,
  "_commento": "le chiavi che cominciano con _ sono commenti",
  "regole": [
    {"id": "nega-push", "descrizione": "…", "strumento": "Bash",
     "corrispondenza": {"comando_inizia": "git push"}, "azione": "nega", "nota": "il push lo fa l'utente"},
    {"id": "segreti", "strumento": "*", "corrispondenza": {"segreti": true}, "azione": "chiedi"},
    {"id": "strumenti-lettura", "strumento": ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"], "azione": "consenti"},
    {"id": "bash-sola-lettura", "strumento": "Bash",
     "corrispondenza": {"comando_inizia": ["ls", "cat", "git status"]}, "azione": "consenti"}
  ]
}
```

| Campo | Valori |
|---|---|
| `id` | minuscole, cifre, `- _ .`, fino a 48 caratteri, unico; «predefinita» è riservato |
| `strumento` | un nome di Claude Code (`Bash`, `Edit`, `mcp__x__y`…), una lista, oppure `"*"` |
| `corrispondenza` | facoltativa. Più chiavi = tutte devono valere. Una lista = basta un elemento. Dal 2026-10-03 sera niente regex (`comando_regex` e `percorso_regex` rendono il file non valido) |
| ↳ `segreti: true` | la richiesta tocca un file di segreti (percorso, pattern di Glob, una parola del comando) |
| ↳ `comando_inizia` | Bash. Con «consenti»: un comando SINGOLO che comincia con quelle parole (le stesse regole della lista automatica: `~`, `$HOME` e collegamenti risolti). Con «chiedi»/«nega»: basta che UNO dei comandi di una riga composta cominci così (`cd x && git push` è un `git push`) |
| ↳ `percorso_glob` | assoluto o con `~`; `*` e `?` non attraversano le cartelle, `**` (cartella intera, al massimo due) sì; massimo 300 caratteri |
| ↳ `url_dominio` | WebFetch: `esempio.it` o `*.esempio.it`; vale solo con https, porta standard, senza credenziali, mai IP o nomi locali |
| `azione` | `consenti` · `chiedi` · `nega` |
| `rischio` | facoltativo, `basso`/`medio`/`alto`: sostituisce quello calcolato sulla scheda |
| `descrizione`, `nota` | testi brevi; la nota arriva a Claude con un «nega» e compare nella vista «Regole» |

Come si valuta:
0. **Prima i segreti, che nessuna regola scavalca.** «nega» senza scheda per le credenziali che il modello non legge mai
   (`~/.locale-onedrive/cc-ponte/conf.json`, `~/.codex/auth.json`, `~/.gemini/oauth_creds.json`, `~/.claude.json*`,
   `~/.claude/.credentials*`, le history della shell, `/var/lib/cc-ponte`); «chiedi» con rischio ALTO per gli altri segreti
   (`.env*`, chiavi, `.ssh`, `.aws`, `.config/gh|gcloud`, `.kube`, `.docker/config.json`, `.netrc`, `.npmrc`, `.pypirc`, Keychain,
   cookie e password di Chrome, il file delle regole, l'archivio, il registro, `cc-ponte`, i nomi `*secret*`, `*token*`,
   `*credential*`, `auth.json`, `oauth_creds*`, `*.pem`, `*.key`, `id_rsa*`…) e per le cartelle nascoste della home e `~/Library`
   (liberi: `~/.claude`, `~/.ai-memory`, `~/.locale-onedrive`, `~/Library/CloudStorage`). Vale per Read/Write/Edit/Glob/Grep
   (`path`, `pattern`, `glob`, e una ricerca che CONTIENE segreti) e per ogni percorso dentro un Bash (`~`, `$HOME`, `${HOME}`,
   `..`, relativi, collegamenti risolti, jolly, graffe, codice fra virgolette).
1. Le regole si provano in ordine e **la prima che corrisponde decide**. Se nessuna corrisponde: **chiedi** (regola «predefinita»).
2. **consenti**: passa senza scheda. **chiedi**: scheda «Approva / Rifiuta» come prima. **nega**: rifiutata SENZA scheda. Claude riceve «Permesso negato dalla regola «id» … nota … Non riprovare».
3. I paletti che nessuna regola scavalca: una «consenti» non vale mai per un file di segreti, per un Bash composto (`; & | < > \` $ ( ) { } * ? [ ] ! \` a capo), per `--output`/`-o`, per una scrittura sul file delle regole, sull'archivio delle approvazioni o sul registro. In quei casi la regola semplicemente non corrisponde e si passa alla successiva.
4. «consenti» si rifiuta (il file non si carica) se è troppo larga: su `"*"`; su Bash senza `comando_inizia`; un
   `comando_inizia` che comincia con rm, mv, cp, dd, sudo, eval, env, xargs, find, awk, sed, tee, curl, wget, ssh, rsync,
   docker, launchctl, crontab, kill, osascript, una shell, un interprete senza script o con -c/-e, `git`/`gh`/`npm`… da soli
   o con push, reset, clean, config…; su Write/Edit/MultiEdit/NotebookEdit e `mcp__*` senza `percorso_glob` dentro una
   cartella precisa (almeno `~/cartella/sottocartella/…` o `/tmp/…`, mai cartelle nascoste, `~/Library`, `.git`, `.claude`);
   su WebFetch senza `url_dominio`; su WebSearch mai. Il file non si carica neanche se è un collegamento simbolico, non è
   dell'utente o è scrivibile da altri.
5. La validazione è severa: JSON non valido, campo sconosciuto, regex che non compila, id ripetuto, `consenti` su `"*"` senza corrispondenza, `consenti` con `segreti`, glob relativo. Il file allora **non si carica**. Vale l'ultimo file valido (`regole-permessi.ultimo-valido.json`, scritto a ogni caricamento riuscito) o, se manca, il predefinito. L'errore va una volta nel registro (fonte «regola», esito «fallito») e compare nella vista «Regole». Un'eccezione durante la valutazione dà «chiedi», mai «consenti».
6. Read, Glob, Grep, LS, NotebookRead, WebFetch e WebSearch stanno SEMPRE nelle regole «ask» (senza, Claude Code consente da
   solo le letture nella cartella di lavoro). In più gli strumenti nominati in regole «chiedi» o «nega» si aggiungono alle regole «ask» passate a claude con `--settings`. Senza questo, Claude Code li consentirebbe da solo e il gestore non li vedrebbe. Con `"*"` non si può: una «nega» su `"*"` vale solo per gli strumenti che arrivano già al gestore (Bash, scritture, regole «allow» dei settings).

Il lancio in modo «approvazione» usa `--setting-sources user`: i settings di progetto (le «allow» e gli hook del CRM su
OneDrive, le `additionalDirectories`) non si caricano. Il `CLAUDE.md` della cartella arriva con `--add-dir <cartella>` e
`CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`, gli agenti del progetto con `--agents`. Le missioni in lettura o «dal
sito» fanno lo stesso con il SDK.

Il **predefinito** (dal 2026-10-03 sera) è la lista automatica di prima SENZA WebFetch e WebSearch, più la regola
`web-documentazione` (github.com, docs.github.com, anthropic.com, docs.anthropic.com, docs.claude.com, pypi.org, npmjs.com,
*.wikipedia.org, docs.python.org, developer.mozilla.org, developer.apple.com). «docs.*» e «developer.*» generici non ci
sono: docs.attaccante.com sarebbe un canale per mandare fuori i dati. Per il resto il predefinito nasce
dalla lista automatica di prima (`approvazioni_auto` di `configurazione.json`, o il suo default). La prova la confronta
con la funzione viva su più di 3000 casi: le sole differenze sono quelle delle correzioni (segreti, web, git branch, rischio alto). Dopo la creazione del file, `approvazioni_auto` non conta più: la fonte è una sola, il file.

Controllo a mano: `python3 command-center/regole_permessi.py --controlla` (esce con 1 se il file non è valido).
Riscrivere il predefinito (con una copia 0600 del file di prima): `python3 command-center/regole_permessi.py --rigenera`.

La scheda (F3): il comando e le anteprime si mostrano interi fino a 4000 caratteri; oltre, «comando troncato: N caratteri
non mostrati», `troncato: true` e rischio ALTO forzato. Nessuna riga sparisce: si maschera solo il VALORE di un segreto
(`CHIAVE=«valore mascherato»`, `--token «valore mascherato»`, `Authorization: Bearer «valore mascherato»`, `user:«…»@`) e
`valori_mascherati` dice quanti. Il riepilogo arriva a 300 caratteri.

## 2. Approvazioni: due campi

L'oggetto `A` di `CONTRATTO-approvazioni.md` guadagna:
- `regola`: l'id della regola che ha chiesto la scheda, `"predefinita"` se nessuna corrispondeva, `null` per le schede nate prima.
- `deciso_da`: già c'era (`web|mac|telegram|nessuno`).

Il `rischio` della scheda è quello della regola, se la regola lo scrive.

## 3. Il registro

Evento:

```json
{"ts": 1791041537, "fonte": "approvazione|regola|guardia|ponte|schermo",
 "esito": "permesso|rifiutato|fallito|scaduto", "azione": "max 60", "riepilogo": "max 160",
 "regola": "id, «guardia: <motivo>», «ponte: …», o null", "dettagli": {"…": "testi max 300"}}
```

| Fonte | Da dove | Esiti |
|---|---|---|
| approvazione | archivio delle approvazioni (le «attesa» non ci sono) | approvata → permesso, rifiutata → rifiutato, scaduta → scaduto |
| regola | `~/.locale-onedrive/jarvis-cc/registro/regole.jsonl` (lo scrive il gestore dei permessi) | consenti → permesso, nega → rifiutato, file non valido → fallito |
| guardia | `…/registro/guardia.jsonl` (lo scrive la guardia dei comandi, con la patch) | bloccato → rifiutato, confermato con `JARVIS_CONFERMATO=1` → permesso |
| ponte | `/var/lib/cc-ponte/comandi.jsonl` sulla VPS | HTTP 2xx → permesso, 4xx → rifiutato (con la regola del ponte), 5xx → fallito |
| schermo | `/var/lib/cc-ponte/schermo.jsonl` sulla VPS | come il ponte; richieste vicine raggruppate |

La VPS si legge con UNA chiamata `ssh vps-tuo 'tail -n 500 …'`, in sola lettura, con timeout di 10 s e cache di 30 s, in un thread. La prima lettura aspetta al massimo 3 s. Se la VPS non risponde, l'elenco continua senza quelle fonti e `fonti.ponte` lo dice. L'ora della VPS (UTC con la Z) diventa un epoch assoluto.

Niente segreti: ogni testo passa da `approvazioni.pulisci`. Le righe con parole da segreto si nascondono e i token noti si mascherano. Niente anteprime dei file, niente IP, niente variabili d'ambiente.

## 4. Endpoint (stesso schema di accesso degli altri GET: `X-Token`, Host ammesso)

- `GET /api/registro?fonte=&esito=&da=<epoch>&limite=<1-500>&q=<testo, max 100>` → `{"eventi":[…], "totale": N, "fonti": {"approvazione":"ok", "regola":"ok|vuota", "guardia":"ok|vuota", "ponte":"ok|non raggiungibile (…)|in lettura|non chiesta", "schermo":"…"}, "ora": <epoch>}`. `fonte` ed `esito` accettano più valori separati da virgola. Ordine: dal più recente. Parametro non valido → 400 `{"errore": "…"}`.
- `GET /api/registro/regole` → `{"regole":[{id, descrizione, strumento, corrispondenza, azione, rischio, nota}], "origine": "file|ultimo valido|predefinite", "errore": null|"…", "file": "~/…", "proposte": [{"forma", "volte", "ultima", "testo_regola"}], "ora"}`.
- Nessun POST. Le regole si cambiano **solo** modificando il file sul Mac. Le «proposte» sono testi da copiare: forme approvate dall'utente almeno 5 volte (Bash: programma + prima parola; scritture e letture: la cartella con `/*`), escluse quelle che le regole consentono già, i comandi composti e i file di segreti.

Il ponte lascia passare questi GET come gli altri.

## 5. Revisione 3 (2026-10-04)

Il dettaglio è in `registro-dev/LEGGIMI-REVISIONE-3.md`. Cosa cambia nel contratto:
- **I percorsi.**
  - In lettura passano da soli solo dentro le cartelle sicure (lista bianca); il resto della home chiede con rischio alto.
  - I segreti chiedono anche dentro le sicure; le credenziali sono «nega».
  - Ogni confronto avviene sul percorso fisico (`realpath` del percorso scritto) e su quello scritto, senza maiuscole.
  - Una regola `consenti` di sola lettura (Read/Glob/Grep/LS/NotebookRead) con `percorso_glob` può aprire una cartella privata; una di scrittura no.
- **Il web.** `url_dominio` vale solo per URL senza query, frammento, `%`, `..` o `//`, con un percorso fino a 200 caratteri e mai pagine di ricerca, accesso, modifica o API.
- **`POST /api/azione {"tipo":"approva"}`.** Per una scheda di rischio alto, `"decisione":"si"` funziona così:
  - prima va chiamato con `"fase":"prepara"`, che risponde `{"ok":true,"preparato":true,"codice":"<32 esadecimali>","attendi_ms":800,"valido_s":5}`;
  - poi il «sì» con `"codice"`, dopo almeno 800 ms ed entro 5 s;
  - altrimenti risponde 428 `{"errore": …}`;
  - `"no"` e i rischi basso e medio non cambiano.
- **Il gestore.**
  - Rifiuta senza scheda oltre 10 schede in attesa per lavoro o 50 in tutto (regola `troppe-in-attesa` nel registro).
  - Rifiuta sempre lo strumento `mcp__approvazioni__*` chiamato come strumento.
- **Id riservati:** `predefinita`, `segreti-mai`, `troppo-lungo`, `troppe-in-attesa`.
