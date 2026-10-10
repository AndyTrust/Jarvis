#!/bin/bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
[ -x backtalk/run.sh ] || { echo "La voce non è installata: rispondi sì alla voce in /inizia (scarica backtalk)."; exit 1; }
./backtalk/run.sh
