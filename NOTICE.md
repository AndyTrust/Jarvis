# Licenze e avvisi

Jarvis è distribuito con licenza **GNU General Public License v3.0** (file `LICENSE`, testo ufficiale da gnu.org).
Il codice di altri autori resta dei suoi autori, con la sua licenza. Licenze verificate il 2026-10-10 (PyPI, npm, GitHub).

## Dentro questa distribuzione

| Componente | Dove | Autore | Licenza | Compatibile con GPL-3.0 |
|---|---|---|---|---|
| Dots (personaggi della lavagna) e varianti derivate | `command-center/static/dots/` | Atai Barkai (OpenDots / CopilotKit) | MIT, testo in `LICENSE-OpenDots.txt` | sì |
| Cinque skill da Superpowers 6.3.0 (`brainstorming`, `writing-plans`, `systematic-debugging`, `verification-before-completion`, `writing-skills`) | `claude-config/skills/` | Jesse Vincent | MIT, testo in `claude-config/skills/LICENSE-superpowers.txt` | sì |

## Installati sul tuo Mac dall'installatore (non inclusi qui)

| Componente | Come arriva | Licenza | Compatibile con GPL-3.0 |
|---|---|---|---|
| claude-agent-sdk 0.2.x (missioni) | `pip`, `requirements/missioni.txt` | MIT | sì |
| Pillow 12 | `pip`, `requirements/mac-widget.txt` | MIT-CMU (HPND) | sì |
| numpy 2 | `pip` | BSD-3-Clause e altre permissive | sì |
| PyObjC 12 (core, Cocoa, Quartz) | `pip` | MIT | sì |
| cryptography 42+ (il Vault) | `pip`, `requirements/vault.txt`, in `~/.jarvis/vault-venv` | Apache-2.0 o BSD-3-Clause, a scelta | sì (con GPL-3.0 si sceglie Apache-2.0 o BSD) |
| puppeteer 25 (facoltativo) | `npm install`, `package.json` | Apache-2.0 | sì (con GPL-3.0, non con GPL-2.0) |
| backtalk (voce, facoltativo) | `git clone https://github.com/jaredrhod/backtalk` | AGPL-3.0 | combinabile (GPL-3.0 §13); resta AGPL-3.0 |
| sherpa-onnx (parola di attivazione, filtro rumore) | `pip` nell'ambiente della voce | Apache-2.0 | sì |
| Kokoro (voce italiana) | `pip` e modelli scaricati | Apache-2.0 | sì |
| Whisper / mlx-whisper (ascolto) | `pip` | MIT | sì |
| Modello GTCRN (filtro rumore) | scaricato da sherpa-onnx | MIT | sì |
| Modello ERes2Net 3D-Speaker (impronta vocale) | scaricato da sherpa-onnx | Apache-2.0 | sì |
| Programmi del `Brewfile` (python, git, gh, jq, rsync, node, uv, espeak-ng, ffmpeg, cliclick, tmux, ttyd, adb, scrcpy) | Homebrew | ognuno la sua | programmi separati, non collegati al codice: nessun vincolo |

## Da segnalare

- **Claude Code** non è incluso e non è software libero: lo installi tu dal sito di Anthropic e lo usi secondo i termini
  del tuo abbonamento. Jarvis lo lancia come programma esterno.
- **espeak-ng** è GPL-3.0 e **ffmpeg** può essere GPL: si usano come programmi separati, nessun problema.
- **backtalk** è AGPL-3.0: se lo modifichi e lo offri ad altri attraverso una rete, devi dare il codice delle tue modifiche.
  Per questo non è incluso: si scarica dalla fonte originale.
- Nessuna dipendenza incompatibile con GPL-3.0 trovata. L'unico caso che chiede attenzione è AGPL-3.0 (backtalk), che resta
  un pacchetto a parte con la sua licenza.
