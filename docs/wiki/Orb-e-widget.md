# L'orb di Jarvis (widget sul desktop)

*Scritta il 2026-09-29, portata dall'orb di Windows.* `strumenti/jarvis_widget.py`: il logo di Jarvis dentro l'anello dello stemma, sempre sopra le altre finestre, con trasparenza vera e animazione continua. Parte da solo quando si apre il Command Center (`avvia_orb` in `server.py`) e da `fullstack-agent/start.sh`.

- **Stati:** riposo (respiro turchese), ascolto (verde con barre), penso (archi gialli), parlo (blu con onde), al lavoro (archi lavanda).
- **Puntino:** verde se il Command Center risponde, rosso se è spento.
- **Carta col testo:** quello che hai detto, quello che Jarvis risponde, oppure «AL LAVORO» con il comando in corso e gli agenti attivi (dal bus dei ganci `backtalk/.jarvis_status`).
- **Comandi:** un clic apre il menu (Command Center, Lavagna, motore, blocca, chiudi), doppio clic il Command Center, trascinamento per spostarlo (la posizione si ricorda in `strumenti/orb_posizione.json`).
- **Serve:** l'ambiente `~/.locale-onedrive/jarvis-widget-venv` (Pillow, numpy, PyObjC): `./installa.sh`.
- **Legge:** `.voice_state`, `.voice_waveform`, `chat.jsonl` (la voce) e `.jarvis_status` (i ganci).
