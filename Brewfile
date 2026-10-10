# Programmi di sistema che Jarvis usa sul Mac. Tutti insieme:  brew bundle --file=Brewfile
# strumenti/installa_guidata.py installa solo i gruppi che servono alle tue risposte di avvio:
# l'etichetta tra parentesi quadre in fondo alla riga dice il gruppo. Il Command Center da solo parte con il solo Python.

# --- essenziali
brew "python@3.12"     # [base] 3.10 o più nuovo per il Command Center; la voce vuole 3.11-3.12
brew "git"             # [base]
brew "gh"              # [base] GitHub da riga di comando
brew "jq"              # [base]
brew "rsync"           # [base]
brew "node"            # [base] npm: puppeteer facoltativo e strumenti web

# --- voce: ascolto (Whisper), parola (Kokoro), «Hey Jarvis»
brew "uv"              # [voce] gestore dell'ambiente Python di backtalk
brew "espeak-ng"       # [voce] fonemi per la voce italiana (Kokoro)
brew "ffmpeg"          # [voce] audio dei vocali

# --- mani sul Mac (strumenti/mac.py): clic, tastiera, schermo
brew "cliclick"        # [mani]

# --- terminale nel pannello e Telegram con Claude Code
brew "tmux"            # [terminale]
brew "ttyd"            # [terminale]

# --- telefono Android (facoltativo)
cask "android-platform-tools"   # [telefono] adb
brew "scrcpy"                   # [telefono] schermo del telefono
