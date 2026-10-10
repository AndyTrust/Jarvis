# Modo «approvazione» della chat: come si accende

*2026-10-03 15:51 · cc-backend-approvazioni-opus · contratto: `command-center/CONTRATTO-approvazioni.md`*

Decisione dell'utente del 2026-10-03: niente `--dangerously-skip-permissions`. In modo «approvazione»
claude parte in modalità normale (`--permission-mode default`). Le azioni della lista automatica
passano da sole. Per le altre compare una scheda «Approva / Rifiuta» nel Command Center, e per il
rischio medio o alto arriva anche un avviso su Telegram. La guardia dei comandi resta accesa.

## I pezzi

| File | Cosa fa |
|---|---|
| `command-center/approvazioni.py` | archivio, rischio, testi senza segreti, lista automatica, attività in diretta |
| `command-center/approvazioni_mcp.py` | il gestore dei permessi (server MCP su stdio, strumento `approva`) |
| `command-center/prove/approvazioni-server.patch` | la patch a `server.py`: modo, endpoint, flusso, schermo |
| `command-center/prove/prova_approvazioni.py` | le prove (`--senza-claude` per non spendere token) |

## 1. Applicare la patch

Il Command Center va riavviato dopo la patch. Lo decide l'utente: il pannello sulla 7777 è in uso.

```bash
cd ~/Jarvis/command-center
cp server.py server.py.prima-approvazioni            # copia per tornare indietro
patch -p0 --dry-run -i prove/approvazioni-server.patch   # deve dire solo «patching file server.py»
patch -p0 -i prove/approvazioni-server.patch
python3 -m py_compile server.py
python3 prove/prova_approvazioni.py --senza-claude       # tutto PASS
```

Poi si riavvia il Command Center come al solito (`avvio/Command Center.command`).
Con la patch applicata ma `modo_chat` ancora a «lavoro», la chat lavora come prima. La prova lo
confronta: i comandi di «lavoro» e «lettura» restano identici per i quattro motori. Le novità
sempre attive sono queste:
- gli endpoint `GET /api/approvazioni`, `GET /api/computer/schermo`, `GET /api/computer/stato`;
- il tipo `approva` di `POST /api/azione`;
- il campo `attivita` (vuoto) nei lavori;
- gli eventi con nome sul flusso;
- un giro ogni secondo che scrive il battito nella cartella delle approvazioni.

## 2. Accendere il modo

In `command-center/configurazione.json`:

```json
"modo_chat": "approvazione"
```

Si può anche mandare `POST /api/azione {"tipo":"modo_chat","modo":"approvazione"}` dal pannello.
Il ponte non lo lascia passare da internet (contratto, sez. 5). La voce si legge a ogni domanda,
quindi non serve riavviare.

Facoltativo, la lista automatica (se manca vale questo default):

```json
"approvazioni_auto": {
  "strumenti": ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"],
  "bash": ["ls", "cat", "head", "tail", "pwd", "wc", "date", "whoami", "git status", "git log",
           "git diff", "git show", "git branch", "python3 ~/Jarvis/strumenti/cerca_memoria.py",
           "python3 ~/Jarvis/strumenti/lavori.py chi"]
}
```

Una regola Bash vale solo per un comando singolo che comincia con quelle parole. Non valgono
`;`, `&&`, `|`, `>`, `$( )`, i caratteri jolly, `--output`, né un percorso di segreti (`.env`,
`.ssh`, chiavi). Read, Glob e Grep non passano mai da soli su un file di segreti.

## 3. Tornare indietro

- Solo il modo: `"modo_chat": "lavoro"` (o «lettura») in `configurazione.json`. Vale dalla domanda dopo.
- Tutta la patch: `cp server.py.prima-approvazioni server.py` (oppure `patch -R -p0 -i prove/approvazioni-server.patch`), poi riavvio del Command Center. I file `approvazioni.py` e `approvazioni_mcp.py` possono restare: senza la patch nessuno li usa.

## 4. Dove stanno i dati

`~/.locale-onedrive/jarvis-cc/approvazioni/` sta fuori da git e fuori da OneDrive. La cartella ha
permessi 0700, i file 0600.

| File | Contenuto |
|---|---|
| `approvazioni.jsonl` | una riga per ogni cambio di una richiesta; oltre 2000 righe si compatta da solo |
| `approvazioni.lock` | lock delle scritture (più processi) |
| `battito.json` | il Command Center è vivo (ogni secondo); oltre 30 s il gestore risponde «no» |
| `mcp/<id lavoro>.json` | il `--mcp-config` del lavoro, si cancella a lavoro finito |

Durante un lavoro l'uscita grezza di claude (stream-json) sta in `command-center/lavori/<log>.flusso`.
La pagina non la serve, e a fine lavoro il file si cancella: nel log resta solo la risposta.

## 5. Spegnere

- Il modo: `modo_chat` a «lavoro» o «lettura».
- Una richiesta in corso: «Rifiuta» sulla scheda. Se il Command Center si spegne, il gestore
  risponde «no» entro 30 s. Se nessuno risponde, la richiesta scade dopo 15 minuti con un «no».
- Le richieste di un lavoro finito diventano «scaduta» da sole.

## Note verificate (2026-10-03, Claude Code 2.1.288)

- `--permission-prompt-tool` non compare in `claude --help`, ma funziona. Lo strumento riceve
  `{"tool_name","input","tool_use_id"}` e risponde
  `{"behavior":"allow","updatedInput":…}` oppure `{"behavior":"deny","message":…}`.
- `--permission-mode default` è accettato anche se l'help elenca `manual`. L'evento `init`
  riporta `permissionMode: "default"`. Va scritto esplicito, perché `~/.claude/settings.json`
  ha `defaultMode: bypassPermissions`.
- Le regole «allow» già presenti in `~/.claude/settings*.json` approverebbero senza chiedere
  `Bash(python3 *)`, `Bash(curl *)`, `Bash(ssh *)`, `Bash(git push *)`, l'invio di Gmail e Slack e
  altro. Per questo il modo passa a claude `--settings` con tutte quelle regole in «ask», che vince
  su «allow»: la prova reale ha mandato un `python3 -c` al gestore.
- La guardia dei comandi (hook PreToolUse su Bash) scatta prima del gestore. Nella prova reale
  `rm -rf *` è stato bloccato dalla guardia e non è nata nessuna scheda.
