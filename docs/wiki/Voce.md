# La voce di Jarvis: filtro rumore, la tua voce, Whisper e Kokoro «Sara»

*Scritta il 2026-09-30, aggiornata il 2026-10-10.*

> **La voce usa programmi di un altro autore.** backtalk (ascolto e parola) è di jaredrhod, licenza AGPL-3.0, e non è dentro questa distribuzione: se nelle domande di avvio scegli la voce, l'installatore lo scarica dalla fonte originale (`git clone https://github.com/jaredrhod/backtalk backtalk`). Le modifiche fatte per l'italiano nella copia dell'autore di Jarvis non sono incluse: la voce parte con le impostazioni di backtalk e si regola come spiegato qui sotto.
 Come far riconoscere a Jarvis che sei tu, togliere il rumore di fondo e regolare quanto è pronto a rispondere. Le chiavi si scrivono in `backtalk/backtalk.json`, un file personale che non va mai su GitHub.

## Cosa fa ogni pezzo

| Pezzo | Compito | Dove si regola |
|---|---|---|
| **Filtro rumore GTCRN** | toglie il rumore di sottofondo (ventola, TV, strada) dall'audio del microfono prima che lo senta Whisper | `mani_libere.filtro_rumore` (acceso di partenza) |
| **Impronta vocale** | riconosce che a parlare sei tu e scarta le frasi degli altri | `mani_libere.soglia_impronta` |
| **Whisper** | trasforma la tua voce in testo | `stt_model`, `stt_language`, `stt_prompt`, `stt_compute` |
| **Kokoro, voce «Sara»** (`if_sara`) | legge le risposte ad alta voce | `voice`, `speed` |
| **«Jarvis»** | la parola che sveglia le mani libere | `mani_libere.parole` |

## 1. Installare il filtro rumore e i modelli

`./installa.sh` lo fa da solo. Da solo, in qualunque momento:

```bash
python3 strumenti/installa_voce.py --controlla   # dice cosa manca
python3 strumenti/installa_voce.py               # scarica e installa quello che manca
```

Scarica il filtro (`gtcrn_simple.onnx`, mezzo mega) e il modello che riconosce le voci (circa 40 MB) in `backtalk/assets/`, controlla i pacchetti Python e imposta la voce Sara. I modelli non vanno su git: si riscaricano.

## 2. Far imparare a Jarvis la tua voce

La voce di Sara non si può clonare: Kokoro ha voci fisse. Il clone F5-TTS è stato tolto il 26/09/2026 perché lento e inutile. Quello che Jarvis impara è **chi sei tu**, e lo impara in due modi:

1. **Registrazione guidata** (una volta, all'inizio): `avvio/Registra la voce dell'utente.command`. Leggi 5 frasi al microfono, in una stanza silenziosa. Crea `impronta-utente.npy`.
2. **Da solo, usandolo**: ogni frase detta col tasto (Cmd destro) affina l'impronta. Dopo 3 frasi con almeno 1,5 secondi di voce è pronta, e le frasi vecchie pesano meno, così segue la voce di oggi. I file audio restano in `backtalk/voce-utente/`.

Se l'impronta si perde: `.venv/bin/python backtalk/strumenti/impronta.py ricalcola` la rifà dalle frasi archiviate.

L'impronta è un dato biometrico: resta sul computer, fuori da git, e non si copia sugli altri PC. Su ogni PC si registra di nuovo.

Provare quanto ti riconosce: `.venv/bin/python backtalk/strumenti/impronta.py verifica frase.wav` dà un numero fra 0 e 1. Sopra `soglia_impronta` (0,55 di partenza) la frase passa.

**Il tono di voce nel testo:** Whisper capisce meglio i tuoi nomi se glieli dici in `stt_prompt` (per esempio i nomi dei tuoi progetti, clienti e luoghi). È il modo per «imparare» come parli: vale per le parole, non per l'intonazione.

## 3. La reattività: Whisper e Kokoro

Il tempo fra quando smetti di parlare e quando Jarvis risponde è la somma di quattro attese. Ognuna si regola.

| Attesa | Cosa la allunga | Chiave | Verso «più pronto» |
|---|---|---|---|
| Silenzio prima di mandare la frase | Jarvis aspetta di essere sicuro che hai finito | `mani_libere.fine_parlato_s` (7 s di partenza; sul Mac dell'utente 3) | abbassala a 2–3 s |
| Trascrizione | il modello di Whisper è grande | `stt_model` | un modello più piccolo (`medium`, `small`): più veloce, sbaglia di più l'italiano. Non misurato: provalo con le tue frasi |
| Eco | il microfono resta chiuso mentre Jarvis parla, più una coda | `mani_libere.coda_eco_ms` (700) | 400–500 con le cuffie, non con le casse |
| Lettura | Sara legge piano | `speed` | 1,15 è più svelta, 0,9 più lenta (utile fra 0,7 e 1,5) |

Altre chiavi utili:
- `mani_libere.vad_aggressivita` (0–3, di partenza 3): 3 è il più severo con il rumore. Se ti taglia le frasi, scendi a 2.
- `mani_libere.attesa_inizio_s` (10): dopo «Jarvis», se non parli entro questi secondi torna in attesa.
- `mani_libere.ignora_iniziali_ms` (300): scarta il «tin» di conferma, che il rilevatore scambierebbe per voce.
- `barge_in` (`true`): se parli mentre Jarvis parla, lui si ferma.
- `mic_mode`: `ptt` (tasto) o mani libere; le mani libere si accendono dicendo «mani libere» e si spengono con «mani legate».

Due configurazioni di partenza (da provare, non sono misure):

```json
"stt_model": "large-v3-turbo",   "mani_libere": {"fine_parlato_s": 3, "coda_eco_ms": 700}      // preciso
"stt_model": "medium",           "mani_libere": {"fine_parlato_s": 2, "coda_eco_ms": 450}, "speed": 1.1   // pronto
```

Dopo ogni modifica riavvia la voce (`avvio/Talk to Jarvis.command`).

## Se qualcosa non va

- **Non ti riconosce mai:** abbassa `soglia_impronta` a 0,45, o rifai `Registra la voce dell'utente`.
- **Risponde a tutti:** alzala a 0,65.
- **Si attiva da solo:** alza `coda_eco_ms`, usa le cuffie.
- **Parla la voce sbagliata:** `voice` deve essere `if_sara` (la `i` iniziale è l'italiano).
- **Controllo generale:** `python3 strumenti/installa_voce.py --controlla`.
