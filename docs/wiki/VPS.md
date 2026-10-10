# VPS (facoltativa)

Jarvis funziona tutto sul Mac. Una VPS (un piccolo server in affitto, acceso sempre) serve solo se vuoi che alcune cose
girino anche a Mac spento: il pannello raggiungibile da fuori dietro un login, i lavori notturni, il ponte per l'app del telefono.

**Trasparenza:** il link qui sotto è un **link di affiliazione** dell'autore di Jarvis. Se compri da lì, l'autore può
ricevere una commissione; per te il prezzo non cambia. Puoi usare qualunque altro provider: Jarvis non dipende da nessuno.

- Provider consigliato (link di affiliazione): https://www.hostinger.com/it/prezzi?REFERRALCODE=ITALOMARZIANO
- Requisiti indicativi: Ubuntu 24.04, 2 vCPU, 4-8 GB di RAM, 50 GB di disco.

## Collegarla

1. Crea una chiave SSH sul Mac (se non l'hai): `ssh-keygen -t ed25519`.
2. Aggiungila alla VPS dal pannello del provider, poi prova: `ssh root@<indirizzo>`.
3. In `~/.ssh/config` dai un nome alla macchina:
   ```
   Host mia-vps
     HostName <indirizzo>
     User root
     IdentityFile ~/.ssh/id_ed25519
   ```
4. In `command-center/configurazione.json` metti `"vps": "mia-vps"`: la spia VPS del pannello si accende.
5. Installa Claude Code anche lì con lo stesso comando del Mac (`curl -fsSL https://claude.ai/install.sh | bash`) e fai il login.

## Regole

- Le chiavi della VPS stanno in `~/.env.jarvis` e in `~/.ssh`, mai nella memoria né in git.
- Leggere (log, stato, spazio disco) si può fare quando vuoi; riavviare, installare o scrivere nei database va confermato.
- La VPS di solito sta su UTC: per le cose condivise col Mac conta l'ora assoluta, non quella scritta.
