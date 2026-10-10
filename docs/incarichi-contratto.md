# Coda degli incarichi: contratto della Fase 1 (2026-10-04)

Decisione dell'utente: una coda di incarichi sulla VPS fra Jarvis dell'utente, gli agenti del CRM e (Fase 2, dopo il sì di l'amministratore) il suo Jarvis.
Fase 1 = solo VPS e Mac. NIENTE porte nuove su internet, NIENTE modifiche al Caddyfile, NIENTE codice sul PC di l'amministratore.

## Dati (sulla VPS)
Cartella `INCARICHI_DIR` (variabile d'ambiente, default `/var/lib/jarvis-incarichi`), permessi 0700 root. Dentro:
- `incarichi/in_<8 esadecimali>.json`, uno per incarico, scritto in modo atomico (file temporaneo + rename):
  `{"id", "da", "a", "tipo": "domanda|lavoro|messaggio", "testo" (max 4000), "creato" (epoch), "scade" (epoch, default creato+24h),
    "stato": "nuovo|preso|fatto|fallito|annullato|scaduto", "preso_da", "preso_il",
    "risposta": null | {"testo" (max 8000), "esito": "ok|fallito", "da", "il", "token_stimati": int|null}}`
- `battiti/<agente>.json`: `{"agente", "macchina", "il" (epoch), "nota"}`. Un agente è «vivo» se `il` è più recente di 5 minuti.
Nomi di agente: `[a-z0-9-]{1,40}` (es. `ceo-ai`, `commercialista`, `jarvis-utente`, `jarvis-giuseppe`).
Un solo scrittore per file: chi manda scrive solo l'incarico nuovo; chi lavora cambia stato e risposta.

## API Python: `~/Jarvis/strumenti/incarichi.py` (solo libreria standard)
`nuovo(da, a, testo, tipo="domanda", ore=24) -> dict` · `elenco(stato=None, a=None, limite=50) -> list` ·
`leggi(id) -> dict` · `prendi(id, da) -> dict` (solo se «nuovo»; atomico, un solo vincitore) ·
`rispondi(id, da, testo, esito="ok", token_stimati=None) -> dict` (solo da «preso», e solo da chi l'ha preso) ·
`annulla(id, da) -> dict` · `battito(agente, macchina, nota="") -> None` · `stato_pubblico() -> dict`
(`{"incarichi": [...ultimi 50], "battiti": [{"agente","macchina","il","vivo":bool,"nota"}], "contatori": {...}}`) ·
`scadi() -> list` (segna «scaduto» i nuovi/presi oltre `scade`). Errori: `IncaricoNonValido(ValueError)`, `NonTrovato(KeyError)`, `GiaPreso(ValueError)`.
## Riga di comando: stessa cosa
`python3 incarichi.py nuovo --da X --a Y --testo "..." [--tipo lavoro] | elenco [--stato nuovo] [--a Y] | leggi ID | prendi ID --da X | rispondi ID --da X --testo "..." [--esito fallito] | annulla ID --da X | battito AGENTE --macchina M [--nota ".."] | stato | prova`.
Output JSON su stdout (tranne `prova`). Codici di uscita: 0 ok, 1 errore di validazione o non trovato, 2 uso sbagliato.
**Modo remoto:** se gira sul Mac (`sys.platform == "darwin"`) e `INCARICHI_DIR` non è impostata, ogni comando e ogni funzione della libreria esegue
`ssh -o ConnectTimeout=8 vps-tuo python3 /root/jarvis/strumenti/incarichi.py <stessi argomenti>` e ne ritorna il JSON. Sulla VPS lavora in locale.

## Il risveglio degli agenti sulla VPS (`~/Jarvis/strumenti/incarichi_runner.py`)
Un timer systemd ogni 2 minuti: scrive il battito di ogni agente del CRM (`ceo-ai`, `analista-finanziario`, `analista-previsionale`, `cambusa`, `commercialista`,
`commerciale`, `consulente-lavoro`, `cruscotto-bi`, `fiscalista-patrimonio`, `garante-dati`, `legale-societario`, `manutentore-dati`, `revisore-contabile`; i profili
sono i file `.md` in `/mnt/onedrive/CRM Azienda Uno/.claude/agents/`, da leggere dal montaggio rclone) con macchina `vps`; `scadi()`; poi prende gli incarichi «nuovo»
indirizzati a uno di quegli agenti (al massimo 2 per giro) e per ciascuno lancia `claude -p` con il testo del profilo come istruzione di sistema, in SOLA LETTURA
(strumenti consentiti solo Read, Grep, Glob; Bash, Edit, Write vietati; `--max-turns` limitato; timeout 600 s; modello dal frontmatter del profilo,
sonnet se manca), poi `rispondi(...)`. Se fallisce o va in timeout: `rispondi(esito="fallito")`. Mai segreti nella risposta. Un lavoro alla volta per agente.

## Cosa NON fa la Fase 1
Non scrive nel CRM, non manda mail né messaggi, non apre porte, non tocca il PC di l'amministratore, non crea incarichi da sola (solo l'utente e Jarvis).
