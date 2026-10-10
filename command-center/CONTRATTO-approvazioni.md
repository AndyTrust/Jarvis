# Contratto API: approvazioni, attività in diretta, schermo del Mac

*2026-10-03 · scritto dal master. Tre agenti lavorano in parallelo su questo contratto (backend, front-end, ponte). Non si cambia senza passare dal master.*

Decisione dell'utente (2026-10-03): **niente bypass dei permessi**. Il motore (claude) parte in modalità normale; le azioni sicure passano da sole, le altre chiedono il permesso all'utente con una scheda «Approva / Rifiuta» (sul web, sulla lavagna e con notifica Telegram). La guardia dei comandi (hook PreToolUse) resta accesa sopra a tutto.

Tutti gli endpoint stanno nel Command Center (`server.py`, 127.0.0.1:7777) e usano lo stesso schema di accesso degli altri: GET liberi dopo la pagina, POST con `X-Token` e `Origin` ammesso.

## 1. Approvazioni

Oggetto `A`:

```json
{
  "id": "ap_1a2b3c4d",
  "creata": 1790000000,
  "scade": 1790000900,
  "lavoro_id": "ab12cd34",
  "sessione": "uuid-del-filo-o-null",
  "agente": "Jarvis",
  "strumento": "Edit",
  "riepilogo": "Scrivere in ~/Jarvis/strumenti/posta.py",
  "dettagli": {"comando": "…", "percorso": "…", "righe_aggiunte": 12, "righe_tolte": 3, "anteprima": "max 800 caratteri"},
  "rischio": "basso|medio|alto",
  "stato": "attesa|approvata|rifiutata|scaduta",
  "deciso_da": "web|mac|telegram|nessuno",
  "deciso": 1790000100
}
```

(`dettagli` ha solo i campi pertinenti; testi sempre troncati e senza segreti: niente variabili d'ambiente, niente contenuto di file `.env`.)

- `GET /api/approvazioni` → `{"in_attesa":[A…], "recenti":[A…ultime 20 decise], "ora": <epoch>}`
- `POST /api/azione` con `{"tipo":"approva","id":"ap_…","decisione":"si"|"no","motivo":"opzionale, max 300"}` → `{"ok":true,"stato":"approvata|rifiutata"}`; è idempotente: se l'approvazione è già decisa risponde 200 con lo stato attuale e `"gia_deciso":true`; se non esiste 404; se è scaduta 409.
- `/api/flusso` (SSE esistente) emette un evento `approvazione` con `A` ogni volta che ne nasce una o cambia stato.
- Scadenza: 15 minuti senza risposta = `scaduta` e il motore riceve un rifiuto. Una richiesta alla volta per strumento uguale non si accumula: se Claude ne chiede due uguali di fila si mostra una sola scheda.
- Notifica Telegram: alla nascita di una approvazione con rischio medio o alto, riuso del meccanismo già presente in `server.py` (`notifica-utente` / `TELEGRAM_JARVIUTENTE_TOKEN`), con testo breve e senza il contenuto dei comandi lunghi.

## 2. Attività in diretta

Ogni lavoro (`/api/lavoro/<id>`, forma già esistente) guadagna un campo `attivita`: lista delle ultime 50 voci

```json
{"ts": 1790000000, "tipo": "leggo|scrivo|lancio|cerco|web|agente|penso", "testo": "leggo posta.py", "esito": "in corso|ok|errore"}
```

e `/api/flusso` emette l'evento `attivita` con `{"lavoro_id": "...", "voce": {…}}`. I testi sono brevi (max 120 caratteri), già in italiano, senza segreti. La pagina li mostra in chat al posto dello spinner.

## 3. Schermo del Mac (occhi)

- `GET /api/computer/schermo?w=<larghezza px, 320-1600, default 800>` → `image/jpeg` dello schermo principale del Mac, con cache di 1 secondo (più richieste nello stesso secondo ricevono lo stesso frame). Se il Mac è bloccato o la registrazione schermo non è permessa: 503 `{"errore": "..."}`.
- `GET /api/computer/stato` → `{"schermo": true|false, "ultimo_lavoro": "id|null", "ultimi_file": ["percorso", …max 10]}`.
- Solo lettura: niente clic né tasti in questa fase.

## 4. Il ponte (VPS)

Il ponte lascia passare, in più, un solo tipo nuovo di POST `/api/azione`: `approva` con `id` che rispetta `ap_[0-9a-f]{8}`, `decisione` in `si`/`no`, `motivo` opzionale fino a 300 caratteri. Con l'interruttore `comandi-off` acceso passa solo `decisione:"no"` (la direzione sicura). I GET nuovi (`/api/approvazioni`, `/api/computer/*`) passano come tutti gli altri GET.

## 5. Che cosa NON c'è

Nessun clic o tasto remoto sul Mac, nessun cambio del modo da internet, nessuna approvazione automatica «per sempre».
