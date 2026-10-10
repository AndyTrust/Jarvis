# Aggiornare Jarvis

## Il modo semplice (2026-10-10)

```bash
cd ~/Jarvis
git pull --ff-only
claude          # poi scrivi /aggiorna
```

`/aggiorna` controlla che non ci siano tue modifiche ai file del repository, mostra cosa cambierebbe con
`python3 strumenti/installa_guidata.py --prova` e, dopo il tuo sì, rilancia l'installazione guidata (che salta quello che c'è già)
e la verifica. I tuoi file (profilo, configurazione, spazi, memoria, chiavi) non sono nel repository e non si toccano.
Se un file in `~/.claude` è diverso dal tuo, la versione nuova va accanto come `.nuovo-AAAAMMGG`.

## Lo strumento completo

*Scritta il 2026-09-29.* Jarvis si aggiorna come un normale programma: arrivano codice nuovo, grafica e documentazione; le tue impostazioni, i tuoi agenti, la memoria e i documenti non si toccano mai.

```bash
python3 strumenti/aggiorna_jarvis.py            # dice cosa cambierebbe (nessuna scrittura)
python3 strumenti/aggiorna_jarvis.py --applica  # aggiorna, poi ./installa.sh e la verifica
python3 strumenti/aggiorna_jarvis.py --torna-indietro   # rimette la versione di prima
```

**Non si tocca mai:** `command-center/configurazione.json`, `spazi.json`, `pannello.json`, `assistenza.json`, le missioni e i lavori, `.env*`, `.claude/` (agenti, memoria, impostazioni), `profilo-jarvis.md`, e tutto ciò che git ignora. Sono file tuoi: non sono nel repository.

**Se avevi modificato un file di codice** che l'aggiornamento cambia, ne tiene una copia in `.aggiornamenti/` e mette la versione nuova. Se un file nuovo dovesse cadere dove hai già un file tuo, si ferma e non lo sovrascrive.

**Dopo l'aggiornamento** parte `installa.sh` (che salta quello che c'è già) e la verifica; se trova un errore lo dice e con `--torna-indietro` si ritorna com'era. Su Windows: `AGGIORNA.ps1`.

## Pulizia e allineamento di `~/.claude` (ogni giorno, in automatico)

- `strumenti/pulisci_claude.py`: toglie le chat più vecchie di 7 giorni (mai `memory/`, mai le ultime 24 ore, mai le sessioni aperte), i testi PDF vecchi (14 giorni) e i testi incollati (3 giorni). Senza `--applica` mostra soltanto.
- `strumenti/sincro_claude.py`: allinea ganci, agenti di casa e skill «aggiorna-memoria» tra `~/.claude` e `claude-config/` (vince il file più recente, con copia di sicurezza).
- Il battito dei 30 minuti (`sincro/ogni30.py`) li chiama: allineamento a ogni giro, pulizia una volta ogni 24 ore.

## Regola del contesto

Al 95% del contesto Jarvis fa l'ultimo aggiornamento (la soglia del 50% non c'è più dal 02/10/2026) e chiude con un piccolo report. La chat nuova riparte da quel riassunto («riprendi l'ultima chat»), senza ricaricare l'intera sessione.
