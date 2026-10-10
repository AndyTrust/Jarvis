---
name: aggiorna-memoria
description: La memoria di Jarvis, in due modalità. Modalità PROGETTO: all'apertura di una chat su un progetto dice a che punto siamo, quali errori non vanno ripetuti e cosa resta da fare, leggendo .claude/memoria/ della cartella in cui sei; se il progetto è nuovo lo impianta; alla chiusura salva errori, fatto, da fare e aggiorna lo Stato del progetto nella memoria condivisa. Usala come prima cosa aprendo una chat su un progetto, prima di ogni /clear o handoff, e quando l'utente dice «a che punto siamo», «cosa abbiamo fatto», «errori», «impianta», «aggiorna la memoria» (di questo progetto), «handoff». Modalità TRASVERSALE: consolida in un'unica fonte, su tutti gli spazi, quello che è sparso fra memoria condivisa, sessioni di Claude Code e la sua auto-memoria, senza sovrascrivere alla cieca e senza cancellare senza un sì esplicito. Si attiva con «aggiorna memoria» (senza nominare un progetto), «pulizia memoria», «inventario memoria», «consolida la memoria».
---

# aggiorna-memoria

Due modalità che non si mescolano: **progetto** (una cartella per volta) e **trasversale** (tutti gli spazi).

## Dove sta la memoria

Un solo file decide i percorsi: `~/.jarvis/percorsi.json`, scritto all'installazione da `strumenti/collega_memoria.py`.

```json
{"memoria": "~/Jarvis-Memoria", "repo": "~/Jarvis",
 "spazi": [{"nome": "Lavoro", "cartelle": ["~/Progetti/sito"]}]}
```

`python3 ~/.claude/skills/aggiorna-memoria/strumenti/percorsi.py` stampa cosa ha trovato.
Le variabili `JARVIS_MEMORIA` (o `JARVIS_VAULT`) e `JARVIS_REPO` hanno la precedenza.

Struttura della memoria condivisa:

```
<memoria>/
├── Comune/          profilo, regole, come si scrive, agenti
├── <spazio>/        una cartella per spazio; dentro una per progetto
│   ├── Stato.md     FATTO / DA FARE / ERRORI / data-ora (lo aggiornano i ganci)
│   └── <progetto>/A che punto siamo.md
├── Diario/          una nota al giorno
├── Report/
├── Sessioni/        una riga per sessione di Claude Code (la scrivono i ganci)
└── Claude/projects/ la memoria automatica di Claude Code, collegata qui
```

Il nome con cui chiamare l'utente sta in `profilo-jarvis.md` (campo «Come chiamarlo»). Leggilo e usalo; non inventarlo.

## Modalità progetto

### La regola che viene prima: un progetto per volta

Lavori solo nella cartella in cui sei. Note, stato ed errori di un progetto non entrano in un altro.

### Un comando solo

```bash
B=~/.claude/skills/aggiorna-memoria/strumenti/brain.py
python3 $B .            # apre: guarda, decide, riferisce (impianta se il progetto è nuovo)
python3 $B . --salva    # chiude: stato, fatti, date e la pagina «A che punto siamo»
```

### Salvare a fine sessione

```bash
python3 $B . --salva --errore "che cosa è andato storto · perché non si vedeva · come si evita"
python3 $B . --salva --completato "cosa è finito" --dafare "cosa resta"
python3 $B . --salva --tolto "pezzo di testo"      # da fare → fatto
python3 $B . --salva --stato "una riga di contesto"
python3 $B . --salva --fatto slug-breve --descrizione "una riga" --corpo "il fatto" --perche "perché conta"
```

- **Gli errori da non ripetere** sono la sezione che vale di più: stanno in cima e non si accorciano. Scrivi come si evita, non solo cosa è successo. Un errore corretto resta in lista finché esiste il codice che lo rende possibile.
- **Lo stato si sovrascrive**: è uno stato, non un diario. Metti 🔴 davanti a un problema aperto.
- **Data e ora sempre** (`AAAA-MM-GG HH:MM`, dal comando `date`).
- **Prima di dire «fatto»** controlla con un comando o un file.

### Altri strumenti (zero token)

| Comando | A cosa serve |
|---|---|
| `stato.py <cartella>` | a che punto siamo, cosa è cambiato |
| `impianta.py <cartella> [--conferma]` | prepara un progetto nuovo (memoria, CLAUDE.md corto) |
| `handoff.py <cartella>` | il foglio per ripartire in una chat pulita |
| `mappa.py <cartella> -p 3` | albero ASCII di una cartella |
| `pdf_testo.py file.pdf` | testo di un PDF, senza passarlo intero al modello |
| `costo.py` | chi riempie il contesto e quanto costa |
| `stato_obsidian.py [--conferma]` | riscrive «A che punto siamo» di ogni progetto degli spazi |

### Regole di lavoro

- Il `CLAUDE.md` del progetto è un indice corto, non un manuale.
- Prima di tagliare o riscrivere, misura (`costo.py`, `mappa.py`).
- Prima di scrivere interfacce, mostra il layout in ASCII e aspetta l'ok.
- Senza disco (claude.ai, telefono): non fingere di aver letto la memoria; consegna il pezzo di memoria pronto da posare.

## Modalità trasversale

Ogni lancio fa il giro standard, in quest'ordine:

1. **Parte meccanica, prima a secco**: `python3 ~/.claude/skills/aggiorna-memoria/strumenti/giro_memoria.py`, poi `--applica`. Allinea gli indici `MEMORY.md` della memoria di Claude, mette `modified: AAAA-MM-GG HH:MM` dove manca, segnala link rotti e note ferme da oltre 60 giorni.
2. **Cose superate**: `obsoleti.json` elenca i termini che l'utente ha detto di non usare più. Il giro segnala ogni file vivo che li cita. Quando l'utente dice «non lo usiamo più», aggiungi una voce.
3. **Giudizio** (sola lettura): per ogni nota di `~/.claude/projects/*/memory` decidi TIENI · AGGIORNA · UNISCI · TOGLI. La memoria di Claude tiene solo quello che non sta nella memoria condivisa: preferenze, correzioni di comportamento, puntatori.
4. **Esecuzione dopo il sì dell'utente**: le note tolte si spostano in `<memoria>/Comune/_archivio/AAAAMMGG/`, mai `rm`.
5. **Resoconto all'utente**: cosa è fatto, con quale prova, cosa non è verificato, cosa resta.

Strumenti: `inventario.py` (fotografa sessioni, memoria e piani; scrive in `output/`), `estrai_sessione.py <file.jsonl>` (solo il succo di una sessione).

Prima di cancellare una sessione: `ps aux | grep -i claude` e niente file toccati nelle ultime 24 ore.

## Ganci automatici

Se l'installatore li ha messi (`strumenti/installa_claude_config.py`), i ganci di Claude Code `Stop`, `PreCompact` e `SessionEnd` lanciano `~/.claude/hooks/stato_avanzamento.py`, che aggiorna da solo `<memoria>/<spazio>/Stato.md` e `<memoria>/Sessioni/`. Quello che scrivono è meccanico (file toccati, ultimo commit, memoria del progetto): il giudizio resta a questa skill.

## Regole che non decadono

- Mai sovrascrivere una nota alla cieca: bozza prima, unione dopo la verifica.
- Mai cancellare senza un sì esplicito sulla lista proposta.
- Una sola fonte: la memoria condivisa. Le sessioni `.jsonl` e l'auto-memoria di Claude sono materiale grezzo.
- Nessun segreto nella memoria: le chiavi stanno in `~/.env.jarvis`, fuori da ogni repository.
