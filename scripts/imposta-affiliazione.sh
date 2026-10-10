#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
# imposta-affiliazione.sh — scrive nei documenti i valori di docs/affiliazione.txt al posto dei segnaposto
# {{LINK_AFFILIAZIONE_VPS}} e {{URL_REPOSITORY}}. Si può rilanciare: se un valore cambia, sostituisce anche quello
# scritto la volta prima (lo ricorda in docs/.affiliazione-applicata).
#   bash scripts/imposta-affiliazione.sh            sostituisce
#   bash scripts/imposta-affiliazione.sh --prova    dice quali file cambierebbe
set -euo pipefail
QUI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROVA=0; [ "${1:-}" = "--prova" ] && PROVA=1
CONF="$QUI/docs/affiliazione.txt"; MEMO="$QUI/docs/.affiliazione-applicata"
[ -f "$CONF" ] || { echo "manca $CONF" >&2; exit 2; }
python3 - "$QUI" "$CONF" "$MEMO" "$PROVA" <<'PY'
import sys, json, pathlib
qui, conf, memo, prova = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), sys.argv[4] == "1"
valori = {}
for r in conf.read_text(encoding="utf-8").splitlines():
    r = r.strip()
    if r and not r.startswith("#") and "=" in r:
        k, v = r.split("=", 1)
        valori[k.strip()] = v.strip()
vecchi = json.loads(memo.read_text()) if memo.exists() else {}
cambiati = 0
for f in sorted(qui.rglob("*")):
    if not f.is_file() or ".git" in f.parts or f.suffix not in (".md", ".html", ".txt") or f == conf:
        continue
    try:
        t = f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    n = t
    for k, v in valori.items():
        if not v:
            continue
        n = n.replace("{{" + k + "}}", v)
        if vecchi.get(k) and vecchi[k] != v:
            n = n.replace(vecchi[k], v)
    if n != t:
        cambiati += 1
        print(("[prova] " if prova else "") + "aggiorno " + str(f.relative_to(qui)))
        if not prova:
            f.write_text(n, encoding="utf-8")
if not prova:
    memo.write_text(json.dumps(valori, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
vuoti = [k for k, v in valori.items() if not v]
print(f"{cambiati} file {'da aggiornare' if prova else 'aggiornati'}" + (f"; senza valore: {', '.join(vuoti)}" if vuoti else ""))
PY
