#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later  ·  Jarvis, vedi LICENSE e NOTICE.md
"""Ganci git post-commit e pre-push: a ogni commit e a ogni push lo stato del progetto si salva da solo.
In più il gancio pre-commit del Vault: ferma il commit se nello stage c'è un file del Vault o dei segreti (vault.json,
esportazioni, chiavi del dispositivo, vault-sezioni.json, CSV di password, .env.jarvis). Il controllo vero sta in
command-center/vault_cc.py («barriera-git»): legge solo nomi e il campo «formato» dei JSON, mai valori. Questo è
l'UNICO blocco che può fermare git (esce con errore solo se trova un file del Vault).

Il blocco chiama stato_avanzamento.py --giro (Stato.md dello spazio + diario del giorno, muto se non c'è niente di
nuovo) e non ferma mai git: esce sempre bene e sta subito dopo la prima riga, così un gancio già esistente resta
com'era e decide lui l'esito. Un gancio esistente che non è uno script di shell non si tocca (lo si dice).

    python3 strumenti/ganci_git.py <cartella del repo> [--prova]     installa (idempotente)
    python3 strumenti/ganci_git.py <cartella del repo> --togli        toglie solo il blocco di Jarvis

Lo usano crea_progetto.py (nei progetti che sono repo git) e installa_guidata.py (nel repo di Jarvis).
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

INIZIO, FINE = "# jarvis-stato:inizio (strumenti/ganci_git.py)", "# jarvis-stato:fine"
GANCI = ("post-commit", "pre-push")
INIZIO_V, FINE_V = "# jarvis-vault:inizio (strumenti/ganci_git.py)", "# jarvis-vault:fine"
VAULT_CC = Path(__file__).resolve().parent.parent / "command-center" / "vault_cc.py"


def blocco_vault():
    return (f"{INIZIO_V}\n"
            f'_v="{VAULT_CC.as_posix()}"\n'
            f'_p="$(command -v python3 || command -v python)"\n'
            f'if [ -f "$_v" ] && [ -n "$_p" ]; then "$_p" "$_v" barriera-git || exit 1; fi\n'
            f"{FINE_V}\n")


def marcatori(nome):
    """(inizio, fine, testo del blocco) per quel gancio."""
    if nome == "pre-commit":
        return INIZIO_V, FINE_V, blocco_vault()
    return INIZIO, FINE, blocco(nome)


def blocco(evento):
    return (f"{INIZIO}\n"
            f'_j="${{HOME}}/.claude/hooks/stato_avanzamento.py"\n'
            f'_p="$(command -v python3 || command -v python)"\n'
            f'[ -f "$_j" ] && [ -n "$_p" ] && ("$_p" "$_j" --giro --evento {evento} --cwd "$(git rev-parse --show-toplevel)" '
            f">/dev/null 2>&1 &) || true\n"
            f"{FINE}\n")


def cartella_ganci(repo):
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    p = Path(r.stdout.strip())
    return p if p.is_absolute() else Path(repo) / p


def installa(repo, prova=False, togli=False):
    """[(gancio, cosa)]: cosa = «installato», «già a posto», «aggiunto in testa», «tolto», «non è shell: lasciato»."""
    d = cartella_ganci(repo)
    if not d:
        return [("-", "non è un repo git")]
    out = []
    for nome in GANCI + ("pre-commit",):
        f = d / nome
        ini, fin, blk = marcatori(nome)
        testo = f.read_text(encoding="utf-8", errors="ignore") if f.is_file() else ""
        if togli:
            if ini in testo:
                a, b = testo.index(ini), testo.index(fin) + len(fin) + 1
                if not prova:
                    f.write_text(testo[:a] + testo[b:], encoding="utf-8")
                out.append((nome, "tolto"))
            continue
        if ini in testo:
            out.append((nome, "già a posto"))
            continue
        if not testo:
            nuovo, cosa = "#!/bin/sh\n" + blk, "installato"
        else:
            prima, _, resto = testo.partition("\n")
            if not prima.startswith("#!") or not any(s in prima for s in ("sh", "bash", "zsh")):
                out.append((nome, "non è shell: lasciato (aggiungi a mano: " + blk.splitlines()[-2][:60] + "…)"))
                continue
            nuovo, cosa = prima + "\n" + blk + resto, "aggiunto in testa al gancio esistente"
        if not prova:
            d.mkdir(parents=True, exist_ok=True)
            if testo:
                (d / f"{nome}.bak-jarvis").write_text(testo, encoding="utf-8")
            f.write_text(nuovo, encoding="utf-8")
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        out.append((nome, cosa))
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a:
        print(__doc__)
        return 0
    for nome, cosa in installa(Path(a[0]).expanduser(), "--prova" in sys.argv, "--togli" in sys.argv):
        print(f"{nome}: {cosa}" + (" (prova)" if "--prova" in sys.argv else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
