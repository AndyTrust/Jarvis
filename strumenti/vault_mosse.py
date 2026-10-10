#!/usr/bin/env python3
"""Sposta file e cartelle del vault tenendo un log per annullare (riordino del 2026-10-02).

    from vault_mosse import muovi, salva_log
    python3 vault_mosse.py --annulla <log.json>
Niente si cancella: quello che esce di scena va in «_da_cancellare_20261002/».
"""
import json, shutil, sys, time
from pathlib import Path

BRAIN = Path.home() / "Library/CloudStorage/OneDrive/Jarvis Brain"
CESTINO = BRAIN / "_da_cancellare_20261002"
LOG = Path.home() / "Jarvis/log/riordino_vault-20261002.json"
_mosse = json.loads(LOG.read_text()) if LOG.exists() else []


def muovi(src, dst, motivo=""):
    src, dst = Path(src), Path(dst)
    if not src.exists():
        return None
    if dst.exists():                                     # mai sovrascrivere: il doppio va accanto
        dst = dst.with_name(f"{dst.stem} (doppio {int(time.time())}){dst.suffix}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _mosse.append({"da": str(src), "a": str(dst), "motivo": motivo})
    salva_log()
    return dst


def cestino(src, motivo="vecchio, già riportato altrove"):
    src = Path(src)
    return muovi(src, CESTINO / src.relative_to(BRAIN) if str(src).startswith(str(BRAIN)) else CESTINO / src.name, motivo)


def salva_log():
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(_mosse, ensure_ascii=False, indent=1))


if __name__ == "__main__" and "--annulla" in sys.argv:
    for m in reversed(json.loads(Path(sys.argv[sys.argv.index("--annulla") + 1]).read_text())):
        if Path(m["a"]).exists():
            Path(m["da"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(m["a"], m["da"])
    print("annullato")
