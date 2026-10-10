#!/usr/bin/env python3
"""Prova del registro condiviso delle attività (unione del ramo windows, 2026-10-02):
    python3 command-center/prova_registro_condiviso.py      esce con 1 se qualcosa non torna
Cartelle temporanee, nessun file vero. Simula il PC Windows con JARVIS_ATTIVITA_CONDIVIDI=1:
  1. una richiesta fra agenti va nel registro locale E in attivita-<PC>.jsonl, nel formato comune;
  2. una chat di chi usa il PC («utente»), la sentinella e la memoria restano solo nel locale;
  3. il file condiviso non porta cwd, sessione, missione (percorsi e dati privati);
  4. il Lettore dello stesso PC non conta due volte il proprio file condiviso, ma legge quello di un altro PC.
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

QUI = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="prova-registro-condiviso-"))
os.environ.update(JARVIS_ATTIVITA_DIR=str(TMP / "locale"), JARVIS_ATTIVITA_EXTRA=str(TMP / "condiviso"),
                  JARVIS_ATTIVITA_CONDIVIDI="1", COMPUTERNAME="PC-PROVA")
(TMP / "condiviso").mkdir()
sys.path.insert(0, str(QUI))
import attivita  # noqa: E402
importlib.reload(attivita)

esiti = []


def prova(nome, ok, dettaglio=""):
    esiti.append(bool(ok))
    print(("✅ " if ok else "❌ ") + nome + ("" if ok else f"  [{dettaglio}]"))


attivita.registra("richiesta", "t1", "jarvis", "progetto-a:progetto-a-ceo", "controlla le fatture", fonte="hook", cwd="/segreto", sessione="s1")
attivita.registra("risposta", "t1", "progetto-a:progetto-a-ceo", "jarvis", "fatto", fonte="hook", esito="tutto a posto", durata_s=3.2)
attivita.registra("richiesta", "l:1", "utente", "progetto-a:progetto-a-ceo", "testo privato della chat", fonte="chat")
attivita.registra("richiesta", "s:1", "sentinella", "jarvis", "rapporto", fonte="hook")
attivita.registra("richiesta", "m:1", "jarvis", "memoria", "cerca", fonte="hook")

locale = [json.loads(r) for r in attivita.file_del_giorno().read_text(encoding="utf-8").splitlines()]
cond_f = TMP / "condiviso" / "attivita-PC-PROVA.jsonl"
cond = [json.loads(r) for r in cond_f.read_text(encoding="utf-8").splitlines()] if cond_f.exists() else []
prova("1a il registro locale ha tutte e 5 le righe", len(locale) == 5, len(locale))
prova("1b il file condiviso ha solo le 2 righe fra agenti", [c["id"] for c in cond] == ["t1", "t1"], cond)
prova("1c formato comune: v, ts, ev, id, da, a, testo, fonte, pc",
      all({"v", "ts", "ev", "id", "da", "a", "testo", "fonte", "pc"} <= set(c) for c in cond))
prova("1d nomi brevi negli agenti (progetto-a-ceo, non progetto-a:progetto-a-ceo)", cond and cond[0]["a"] == "progetto-a-ceo", cond[:1])
prova("2  niente chat dell'utente, sentinella o memoria nel condiviso",
      not any(c.get("da") in attivita.PRIVATI or c.get("a") in attivita.PRIVATI for c in cond))
prova("3  niente cwd, sessione, missione nel condiviso", not any({"cwd", "sessione", "missione"} & set(c) for c in cond))

(TMP / "condiviso" / "attivita-ALTRO.jsonl").write_text(json.dumps(
    {"v": 1, "ts": 1.0, "ev": "richiesta", "id": "win:x", "da": "jarvis", "a": "postino", "testo": "posta",
     "fonte": "windows"}) + "\n", encoding="utf-8")
ev = attivita.Lettore(giorni=1).eventi()
prova("4a il Lettore non legge due volte il proprio file condiviso", sum(1 for e in ev if e.get("id") == "t1") == 2,
      [e.get("id") for e in ev])
prova("4b il Lettore legge il file di un altro PC", any(e.get("id") == "win:x" for e in ev))

print(f"\n{sum(esiti)}/{len(esiti)} prove passate · cartella: {TMP}")
sys.exit(0 if all(esiti) else 1)
