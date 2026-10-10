#!/usr/bin/env python3
"""Mac, VPS e app Android sono allineati? (l'utente, 2026-10-04: «devono essere allineati sempre, in automatico»).

Come si allineano da soli (nessun lavoro a mano):
  codice, claude-config, istruzioni   Mac → GitHub (pubblica_auto) → VPS (jarvis-repo-sync, ogni ~10 min, poi sincro_claude.py --verso-casa)
  agenti dei progetti (143 profili)   OneDrive: Mac ↔ copia locale della VPS (jarvis-vault-sync, bisync ogni 5 min)
  app Android: sorgenti               GitHub → /opt/jarvis-android (jarvis-repo-sync, solo avanti veloce)
  app Android: APK sul telefono       build e firma solo sul Mac (pubblica.sh) → /opt/jarvis-agent/releases → il telefono si aggiorna da solo
Questo strumento MISURA se è vero: scrive un'impronta della macchina e, dal Mac, la confronta con quella della VPS.

  allinea_stato.py                 impronta di questa macchina (stampa)
  allinea_stato.py --scrivi        la scrive in ~/.locale-onedrive/allineamento.json (lo fa il giro della VPS)
  allinea_stato.py --confronta     dal Mac: legge l'impronta della VPS via ssh e dice cosa differisce (esito 1 se qualcosa)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
QUI = Path(__file__).resolve().parents[1]
OD = next((p for p in (HOME / "Library/CloudStorage/OneDrive", HOME / "Library/CloudStorage/OneDrive") if p.exists()), None)
FILE = HOME / ".locale-onedrive" / "allineamento.json"


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()[:8]


def impronta_cartella(radice, schema):
    """{file relativo: md5} per i file che rispondono allo schema, e un solo valore riassuntivo."""
    d = {}
    if radice and radice.exists():
        for f in sorted(radice.rglob(schema)):
            if f.is_file() and ".bak" not in f.name and "__pycache__" not in str(f) and ".conflict" not in f.name:
                d[str(f.relative_to(radice))] = md5(f)
    tot = hashlib.md5(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]
    return d, tot


def git(*a, cwd=None):
    try:
        return subprocess.run(["git", *a], cwd=cwd or QUI, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def agenti_progetti():
    d = {}
    for base in ([OD / "Jarvis Brain" / "Progetti", OD / "CRM Azienda Uno"] if OD else []):
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            if f.parent.name == "agents" and f.parent.parent.name == ".claude" and "_archivio" not in str(f) and ".conflict" not in f.name:
                d[str(f.relative_to(OD))] = md5(f)
    return d, hashlib.md5(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]


def app_android():
    r = {}
    src = next((Path(p) for p in ("/opt/jarvis-android", str(HOME / ".locale-onedrive/Jarvis-App-Android")) if Path(p).exists()), None)
    if src:
        g = (src / "app/build.gradle.kts")
        if g.exists():
            m = re.search(r'versionName\s*=\s*"([^"]+)"', g.read_text(encoding="utf-8"))
            r["sorgenti_versione"] = m.group(1) if m else None
        r["sorgenti_commit"] = git("rev-parse", "--short", "HEAD", cwd=src)
        r["sorgenti_dietro_origin"] = git("rev-list", "--count", "HEAD..origin/main", cwd=src)
    rel = Path("/opt/jarvis-agent/releases/version.json")
    if rel.exists():
        try:
            r["apk_pubblicato"] = json.loads(rel.read_text(encoding="utf-8")).get("versionName")
        except ValueError:
            pass
    return r


def impronta():
    git("fetch", "-q", "origin")
    cc, cc_tot = impronta_cartella(QUI / "claude-config", "*.py")
    ag_casa, ag_casa_tot = impronta_cartella(HOME / ".claude" / "agents", "*.md")
    # hook e skill di casa che il repository conosce: devono essere uguali (le guardie incluse)
    diff_hook = [k for k, v in cc.items() if k.startswith("hooks/") and (HOME / ".claude" / k).exists() and md5(HOME / ".claude" / k) != v]
    ag, ag_tot = agenti_progetti()
    return {
        "macchina": os.uname().nodename, "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": {"commit": git("rev-parse", "--short", "HEAD"), "dietro_origin": git("rev-list", "--count", "HEAD..origin/main"),
                 "avanti_origin": git("rev-list", "--count", "origin/main..HEAD"), "modificati": len(git("status", "--short").splitlines())},
        "hook_diversi_dal_repo": diff_hook,
        "agenti_casa": {"n": len(ag_casa), "impronta": ag_casa_tot},
        "agenti_progetti": {"n": len(ag), "impronta": ag_tot},
        "app": app_android(),
    }


def confronta():
    mio = impronta()
    try:
        # dal Mac si interroga la VPS; sulla VPS si interroga il Mac (tunnel inverso, alias «mac»)
        altro = ["mac", "cd ~/my-agent && python3 strumenti/allinea_stato.py"] if sys.platform.startswith("linux") \
            else ["vps-tuo", "python3 /root/jarvis/strumenti/allinea_stato.py"]
        out = subprocess.run(["ssh", "-o", "ConnectTimeout=10", *altro],
                             capture_output=True, text=True, timeout=120).stdout
        vps = json.loads(out)
        if sys.platform.startswith("linux"):  # qui «mio» è la VPS e «vps» il Mac: rimetto le etichette giuste
            mio, vps = vps, mio
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"VPS non raggiungibile o risposta illeggibile ({type(e).__name__})")
        return 1
    problemi = []
    if vps["repo"]["commit"] != mio["repo"]["commit"]:
        problemi.append(f"repository: Mac {mio['repo']['commit']} (avanti {mio['repo']['avanti_origin']}), VPS {vps['repo']['commit']} (dietro {vps['repo']['dietro_origin']}): "
                        "se il Mac è avanti è solo pubblicazione ancora da fare")
    if vps["hook_diversi_dal_repo"]:
        problemi.append(f"VPS: hook diversi dal repository: {', '.join(vps['hook_diversi_dal_repo'])}")
    if vps["agenti_progetti"]["impronta"] != mio["agenti_progetti"]["impronta"]:
        problemi.append(f"agenti dei progetti diversi: Mac {mio['agenti_progetti']['n']} profili, VPS {vps['agenti_progetti']['n']} (la sincronizzazione OneDrive impiega fino a ~20 minuti)")
    a_v, a_m = vps.get("app", {}), mio.get("app", {})
    if a_v.get("sorgenti_versione") and a_v.get("apk_pubblicato") and a_v["sorgenti_versione"] != a_v["apk_pubblicato"]:
        problemi.append(f"app: sorgenti {a_v['sorgenti_versione']} ma APK pubblicato {a_v['apk_pubblicato']} (serve pubblica.sh dal Mac)")
    if a_v.get("sorgenti_dietro_origin") not in (None, "", "0"):
        problemi.append(f"app: i sorgenti sulla VPS sono indietro di {a_v['sorgenti_dietro_origin']} commit")
    print(f"Mac  {mio['repo']['commit']}  agenti {mio['agenti_progetti']['n']}  hook diversi {len(mio['hook_diversi_dal_repo'])}")
    print(f"VPS  {vps['repo']['commit']}  agenti {vps['agenti_progetti']['n']}  hook diversi {len(vps['hook_diversi_dal_repo'])}  app sorgenti {a_v.get('sorgenti_versione')} / APK {a_v.get('apk_pubblicato')}")
    print("ALLINEATI" if not problemi else "DIFFERENZE:\n - " + "\n - ".join(problemi))
    return 1 if problemi else 0


def main(a):
    if "--confronta" in a:
        return confronta()
    d = impronta()
    if "--scrivi" in a:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(d, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
