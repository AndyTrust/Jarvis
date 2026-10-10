# Costruire il tuo Jarvis

Questa pagina spiega come è fatto Jarvis e come costruirne una copia per te: la memoria, gli agenti, il pannello con i suoi avatar. Per i comandi di installazione vedi [Installazione](Installazione).

## 1. Le quattro parti

| Parte | Cosa fa | Dove sta |
|---|---|---|
| **Chat master** | L'unico agente che parla con te e lancia gli altri. Capisce la richiesta, la divide, verifica, risponde. | `profilo-jarvis.esempio.md` (copialo in `profilo-jarvis.md`) |
| **Agenti** | Specialisti con un compito preciso (esecutore, ricercatore web, e quelli che aggiungi tu). | `claude-config/agents/` e `.claude/agents/` del progetto |
| **Memoria** | Un vault di note che resta tuo: profilo, regole, spazi di lavoro, diario. | Una cartella sul tuo computer, di tua scelta |
| **Command Center** | Il pannello sul browser: chat, stato, squadra, missioni, lavagna, memoria, avatar. | `command-center/`, su `http://127.0.0.1:7777` |

Tutto gira sul tuo computer. Le tue cartelle, le tue chiavi e la tua memoria non escono da lì, salvo quello che scegli tu di collegare.

## 2. Partire in dieci minuti

```bash
git clone <il tuo repository> ~/jarvis
cd ~/jarvis
./installa.sh --prova      # dice cosa farebbe, non scrive niente
./installa.sh              # installa il necessario
python3 strumenti/verifica_installazione.py   # controlla che sia tutto a posto
python3 command-center/server.py              # poi apri http://127.0.0.1:7777
```

Il pannello parte con il solo Python. Voce, orb sul desktop, Telegram e le routine si aggiungono a pezzi: ognuno ha la sua spia, e se manca non fa cadere il resto.

## 3. Costruire la memoria

La memoria è un vault di note in Markdown. Jarvis la legge all'inizio di ogni lavoro, quindi più è chiara, più gli agenti sbagliano meno.

Struttura consigliata:

```
Memoria/
  00 Comune/            profilo della persona, regole di lavoro, come si scrive, elenco degli agenti
    Memoria.md          la porta d'ingresso: linka tutto il resto
    Diario/             una nota per giorno, con le cose fatte
  <spazio>/             un'area di lavoro (un'attività, un progetto, la vita privata)
    <spazio>.md         stato, da fare, link alle note
    Report/             documenti finiti (PDF)
```

Regole che tengono in piedi la memoria:

- **Una sola fonte per ogni cosa.** Se due note dicono la stessa cosa, ne resta una e l'altra linka a lei.
- **Correggi, non accumulare.** Quando una cosa non è più vera, la riscrivi. Non aggiungi una riga che la smentisce.
- **Data e ora sempre**, in formato `AAAA-MM-GG HH:MM`.
- **Niente segreti nel vault.** Password, token e chiavi stanno in un file `.env` fuori dal vault e fuori da git.

Per cercare nella memoria: `python3 strumenti/cerca_memoria.py "parole"`.

Quando chiudi un lavoro, dì a Jarvis «salva in memoria»: scrive la nota, aggiorna il «da fare» e lascia una riga nel diario.

## 4. Come devono lavorare gli agenti

Ogni agente è un file Markdown in `claude-config/agents/` (o in `.claude/agents/` dentro un progetto). L'intestazione dice chi è; il corpo dice come lavora:

```markdown
---
name: esecutore
description: Cosa fa, e quando usarlo. Così la chat master sa quando chiamarlo.
tools: Bash, Read, Glob, Grep
model: haiku
---

Il testo che guida il lavoro: il compito, i limiti, cosa riportare.
```

Il modello si sceglie per il tipo di lavoro:

- **haiku**: esegue comandi già scritti e riporta l'uscita così com'è.
- **sonnet**: ricerca, analisi, testi, coordinamento e verifica.
- **opus**: programmazione.

Le regole che ogni agente rispetta, qualunque sia il lavoro:

1. **Prove, non ipotesi.** Un fatto è vero solo se l'ha controllato con un file o un comando. Il resoconto dice cosa ha visto, non cosa crede.
2. **Chi è dentro a un lavoro non lo tocca.** Prima di toccare un file controlla se un altro agente ci sta lavorando (`lavori.py chi`, o il registro del tuo progetto).
3. **Conferma prima dell'irreversibile.** Cancellare, pubblicare, fare un deploy, scrivere in produzione, mandare un messaggio: si chiede prima.
4. **Il lavoro non finito torna allo stesso agente**, con il motivo scritto. Non si passa a un altro senza dirlo.
5. **Un agente non approva il proprio lavoro.** Lo verifica un altro, o la chat master con un comando.

Il **quaderno**: ogni agente tiene una memoria sua in `.claude/memoria/agenti/<nome>.md`. Quando trova un errore o una regola utile, la scrive lì con `strumenti/quaderno.py`. Le proposte di modifica al profilo le approva chi coordina il gruppo, mai l'agente da solo.

Un gruppo ha un capogruppo (un agente-coordinatore) che riceve i resoconti dei suoi specialisti, li verifica e manda alla chat master un solo report con le cose che contano.

## 5. Avatar e dots

Il pannello mostra ogni agente con un personaggio, detto dot. I file stanno in `command-center/static/dots/`: un PNG per taglia (64, 128, 256) e, dove c'è, la versione WebP.

Per aggiungere un avatar:

1. metti i PNG in `command-center/static/dots/` con un nome semplice, per esempio `mio-agente-256.png`;
2. associa il nome all'agente nel file di configurazione del pannello (`command-center/configurazione.esempio.json`, copiato in `configurazione.json`);
3. ricarica il pannello.

I dot di base derivano da **OpenDots** di Atai Barkai, licenza MIT. La licenza e l'avviso di copyright stanno in `command-center/static/dots/LICENSE-OpenDots.txt`: tienili insieme alle immagini se le ridistribuisci. Il personaggio di Jarvis (`jarvis-*.png`) è generato con IA, come indicato in `ATTRIBUZIONE-nuovi-dots.txt`.

## 6. Cosa non va mai nel repository

Il file `.gitignore` già esclude queste cose. Se ne aggiungi di tue, tienile fuori da git:

- `.env` e ogni file con segreti (chiavi API, token, password)
- `command-center/configurazione.json`, `spazi.json`, `assistenza.json`: sono la tua configurazione
- `profilo-jarvis.md` (il tuo profilo), `.claude/memoria/` (la tua memoria), `.claude/agents/` (i tuoi agenti, se personali)
- le missioni e i lavori in corso (`command-center/missioni/`, `command-center/lavori/`)
- i backup e le copie con data nel nome

Prima di ogni push, `git status` deve mostrare solo codice. Se compare un file che non riconosci, fermati.

## 7. Dove andare dopo

- [Primi passi](Primi-passi): il primo giro con il pannello acceso.
- [La catena degli agenti](La-catena-degli-agenti): chi comanda chi.
- [La memoria nel vault](La-memoria-nel-vault): come la memoria si collega ai progetti.
- [Routine e lavori automatici](Routine-e-lavori-automatici): cosa far girare da solo.
- [Sicurezza](Sicurezza): i permessi, le conferme e la guardia sui comandi irreversibili.
