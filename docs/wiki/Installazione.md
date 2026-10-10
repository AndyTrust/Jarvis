# Installazione

*Aggiornata il 2026-10-10 per la versione 0.6.0: installazione guidata da Claude Code, con domande di avvio in modalità piano.*

Jarvis si installa parlando con Claude Code. Claude fa le domande, prepara un piano, te lo mostra, e tocca il Mac solo dopo il tuo sì.
Il Command Center (pannello, lavagna, missioni) è Python puro e parte con il solo Python; voce, orb, mani sul Mac, telefono e VPS si aggiungono a pezzi.

## Strada consigliata: con Claude Code

1. **Installa Claude Code** (fonte ufficiale: [code.claude.com/docs/en/setup](https://code.claude.com/docs/en/setup), letta il 2026-10-10):
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash     # installatore ufficiale, si aggiorna da solo
   # oppure: brew install --cask claude-code         # con Homebrew (si aggiorna con brew upgrade)
   claude --version                                  # in un Terminale nuovo: deve stampare un numero di versione
   ```
   Serve un abbonamento Claude Pro, Max, Team o Enterprise, oppure un account Console. Il piano gratuito non include Claude Code.
2. **Scarica Jarvis**: `git clone https://github.com/AndyTrust/Jarvis ~/Jarvis && cd ~/Jarvis`
3. **Avvia Claude Code** nella cartella: `claude`. La prima volta fai il login nel browser.
4. **Rispondi alle domande di avvio.** Claude legge `CLAUDE.md`, vede che `~/.jarvis/installato.json` non esiste, entra in
   modalità piano e chiede, una cosa alla volta:
   - come vuoi essere chiamato e come vuoi chiamare l'assistente (di solito Jarvis);
   - lingua, tono, fuso orario;
   - che lavoro fai, in una riga, e se partire da zero o creare subito il primo progetto (gli altri nascono dopo,
     quando li nomini: vedi [Progetti e agenti](Progetti-e-agenti)); se il piano va mostrato ogni volta o no;
   - dove tenere la memoria condivisa (`~/Jarvis-Memoria`, oppure un vault Obsidian, iCloud Drive, OneDrive);
   - quali altri programmi di AI usi (Codex, Gemini CLI, Cursor, Grok...), per collegarli alla stessa memoria;
   - se vuoi voce, telefono, VPS facoltativa, posta, Telegram o WhatsApp, lavori automatici;
   - cosa non deve toccare mai.
   Se non parte da solo, scrivi `/inizia`.
5. **Leggi il piano.** Claude scrive le risposte in `~/.jarvis/risposte-avvio.json` (nessun segreto), lancia
   `python3 strumenti/installa_guidata.py --prova` e ti mostra cosa installerà e dove scriverà.
6. **Approva.** Solo allora lancia `python3 strumenti/installa_guidata.py` e poi `python3 strumenti/verifica_installazione.py`.
7. **Accendi il pannello**: `python3 command-center/server.py` e apri http://127.0.0.1:7777.

## Cosa fa l'installazione guidata, passo per passo

| Passo | Cosa | Dove scrive |
|---|---|---|
| 1 | controlla le risposte (campi obbligatori, niente chiavi) | niente |
| 2 | programmi dal `Brewfile`, solo i gruppi che servono: base (python, git, gh, jq, rsync, node), voce (uv, espeak-ng, ffmpeg), mani (cliclick), terminale (tmux, ttyd), telefono (adb, scrcpy) | Homebrew |
| 3 | ambienti Python: orb (`requirements/mac-widget.txt`), missioni (`requirements/missioni.txt`); con la voce scarica backtalk dalla fonte originale | `~/.locale-onedrive/jarvis-widget-venv`, `backtalk/.venv` |
| 4 | il profilo dell'assistente con il tuo nome | `profilo-jarvis.md` (fuori da git) |
| 5 | configurazione del pannello; `spazi.json` vuoto (si parte da zero) | `command-center/configurazione.json`, `spazi.json` (fuori da git) |
| 6 | ganci (anche il salvataggio sulle conferme), agenti, skill `aggiorna-memoria` e `nuovo-progetto`, comandi `/nuovo-progetto` e `/nuovo-agente`, ganci git del repo | `~/.claude/hooks`, `agents`, `skills`, `commands`, `settings.json` (unito, con copia), `.git/hooks` |
| 7 | memoria condivisa e collegamenti | `<memoria>/`, `~/.claude/projects/*/memory`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.jarvis/percorsi.json` |
| 7b | il primo progetto, solo se l'hai chiesto (`crea_progetto.py`) | `spazi.json`, `<memoria>/<spazio>/`, cartella del progetto |
| 8 | lavori automatici, solo se chiesti | `~/Library/LaunchAgents/com.jarvis.*.plist` |
| 9 | segna l'installazione come fatta | `~/.jarvis/installato.json` |

Regole dell'installatore: si può rilanciare (salta quello che è già a posto); ogni file esistente che cambia viene prima
copiato in `<file>.bak-AAAAMMGG`; un tuo file in `~/.claude` diverso da quello di Jarvis non si sostituisce, la versione
nuova va accanto come `.nuovo-AAAAMMGG` (con `--aggiorna` si sostituisce dopo la copia).

## Strada a mano (senza le domande)

```bash
cp docs/risposte-avvio.esempio.json ~/.jarvis/risposte-avvio.json   # poi correggilo
python3 strumenti/installa_guidata.py --prova
python3 strumenti/installa_guidata.py
```

`./installa.sh` resta per chi vuole l'installazione classica senza risposte (configurazione dagli esempi):
`./installa.sh --prova`, poi `./installa.sh`. Opzioni: `--si`, `--senza-brew`, `--senza-voce`, `--senza-widget`, `--launchd`, `--home DIR`.

## Permessi di macOS (a mano, una volta)

Impostazioni di Sistema → Privacy e sicurezza, per **Terminale** (e per Python quando lo chiede):
- **Accessibilità** e **Registrazione schermo**: le mani sul Mac (`strumenti/mac.py`).
- **Microfono**: la voce.

## Le chiavi (`~/.env.jarvis`)

Righe `NOME=valore` in `~/.env.jarvis`, poi `chmod 600 ~/.env.jarvis`. Le scrivi tu: Claude non le chiede in chat e
non le mette nelle risposte di avvio. Il file resta sul Mac: è nel `.gitignore` e nessuno strumento lo copia nella memoria.
Nessuna chiave serve per accendere il pannello. Servono solo per i pezzi facoltativi (Telegram, Gemini, voce cloud, VPS).

## La verifica

`python3 strumenti/verifica_installazione.py` compila il codice Python, controlla il JavaScript, la configurazione,
gli ambienti, i file in `~/.claude`, poi accende un pannello di prova su una porta libera e interroga `/api/spazi`,
`/api/stato`, `/api/catalogo`. Esce con 1 se c'è un errore; gli avvisi sono pezzi facoltativi spenti.

## Con Docker

```bash
docker build -f docker/Dockerfile.template -t jarvis-template .
docker run -d --name jarvis -p 7777:7777 jarvis-template
```

La porta di fuori deve essere uguale a quella di dentro (`CC_PORTA`). Login di Claude Code: `docker exec -it jarvis claude`.
Dettagli in `docker/README.md`.

## Se qualcosa non va

[Problemi](Problemi).
