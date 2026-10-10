#!/usr/bin/env python3
"""Un solo punto d'ingresso per i report e gli avvisi all'utente (2026-10-05, programmatore-notifiche).

Decisione dell'utente del 05/10/2026: «il report deve arrivarmi con notifica su una chat apposita di Jarvis
e del Postino nel CRM e nell'app Jarvis; evitare Telegram se possiamo fare tutto dal CRM; Jarvis e
Postino sono gli unici che mi mandano i report».

    from notifica import notifica
    notifica("jarvis" | "postino", titolo, testo, dati=None, prova=False, chiave="", documento=None)

Dove va:
  1. nel Command Center della VPS (la fonte: funziona col Mac spento), filo «Notifiche Jarvis» o
     «Postino» della chat (#chat del sito e del Mac, app). Sulla VPS con POST /api/notifica su
     127.0.0.1:7777 (il token lo scrive il server in ~/.locale-onedrive/jarvis-cc/token-locale, 0600);
     dal Mac con `ssh vps-tuo python3 /root/jarvis/strumenti/notifica.py --stdin`;
  2. su Telegram SOLO come riserva: se il Command Center della VPS non risponde, oppure se nella
     configurazione del Command Center c'è "notifiche": {"telegram_copia": true} (di default spento).
     In prova (prova=True) Telegram non parte mai.

«chiave» (facoltativa, lettere, cifre, . _ : -): la stessa chiave riscrive lo stesso messaggio invece
di aggiungerne un altro (per esempio «pranzo-2026-10-05»). «dati»: un dizionario JSON che la pagina
mostra come elementi apribili (per il Postino: {"voci": [{numero, da, oggetto, riassunto, codice,
bozza: {destinatario, oggetto, testo}}]}). «documento»: un PDF da allegare solo nella riserva Telegram.

Riga di comando:
  notifica.py manda --chi jarvis --titolo "…" --testo "…" [--testo-file F] [--dati JSON] [--prova] [--chiave K]
                 [--tipo report|avviso] [--routine NOME]
      Dove finisce (l'utente, 2026-10-05 15:05): «report» (report, briefing, rassegna, riunioni, posta, routine con
      «avvisa_postino»: true in command-center/routine-gruppi.json) nella scheda Postino della chat; «avviso»
      (errori, salvataggi, avanzamenti, prove tecniche, permessi) nella chat principale di Jarvis. Senza --tipo
      decide command-center/fili.py (classifica), l'unico punto con la regola.
  notifica.py --stdin            JSON {chi, titolo, testo, dati, prova, chiave} su stdin (lo usa il Mac via ssh)
  notifica.py togli-prove        toglie dai due fili i messaggi di prova
  notifica.py esporta            (sulla VPS) i due fili correnti in JSON: lo specchio del Mac li legge
  notifica.py errore-servizio U  (sulla VPS, da jarvis-errore@U.service) il lavoro U è finito in errore
  notifica.py controlla-launchd  (sul Mac) i com.jarvis.* finiti con uscita diversa da 0
  notifica.py esegui [--nome N] -- <comando…>   per il cron: se il comando fallisce, notifica di Jarvis
Solo libreria standard. Non stampa mai token.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
CC_URL = os.environ.get("JARVIS_CC_URL", "http://127.0.0.1:7777")
CC_HOST = "127.0.0.1:7777"
TOKEN_FILE = HOME / ".locale-onedrive" / "jarvis-cc" / "token-locale"
VPS_SSH = os.environ.get("JARVIS_VPS_SSH", "vps-tuo")
REMOTO = "/root/jarvis/strumenti/notifica.py"
CHAT_UTENTE_RISERVA = ""
MITTENTI = ("jarvis", "postino")
ENV_FILE = [Path(os.environ.get("TELEGRAM_STATE_DIR", "/nonesiste")) / ".env",
            HOME / ".env.jarvis", HOME / "Jarvis" / ".env", HOME / "jarvis" / ".env",
            HOME / ".claude" / "channels" / "telegram-vps" / ".env",
            HOME / ".claude" / "channels" / "telegram-jarviutente" / ".env"]
CHIAVI_BOT = ("TELEGRAM_JARVIUTENTEVPS_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_JARVIUTENTE_TOKEN")


def su_vps():
    return sys.platform.startswith("linux") and Path("/root/jarvis/command-center/server.py").exists()


# ---------------------------------------------------------------- testo
def da_html(testo):
    """Il testo HTML di Telegram (<b>, <i>, <a>) diventa il testo della chat: **grassetto**, link in chiaro."""
    t = str(testo or "")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<a\s+[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", r"\2 (\1)", t, flags=re.I | re.S)
    t = re.sub(r"</?(b|strong)>", "**", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


# ---------------------------------------------------------------- Command Center
def _token():
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def manda_cc(corpo, timeout=15):
    """POST al Command Center locale (sulla VPS). Torna il JSON della risposta, o eccezione."""
    dati = json.dumps(corpo, ensure_ascii=False).encode()
    req = urllib.request.Request(f"{CC_URL}/api/notifica", data=dati, method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": _token(), "Host": CC_HOST})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("errore") or ""
        except ValueError:
            msg = ""
        raise RuntimeError(f"Command Center: {e.code} {msg}".strip()) from None


def manda_ssh(corpo, timeout=40):
    """Dal Mac: lo stesso corpo alla VPS, che fa tutto lei (anche la riserva Telegram)."""
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS_SSH, "python3", REMOTO, "--stdin"],
                       input=json.dumps(corpo, ensure_ascii=False), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError(f"VPS non raggiungibile ({(r.stderr or '').strip()[:160]})")
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- Telegram (solo riserva)
def _env(chiave):
    if os.environ.get(chiave):
        return os.environ[chiave].strip()
    for f in ENV_FILE:
        try:
            for riga in f.read_text(encoding="utf-8").splitlines():
                if riga.startswith(chiave + "="):
                    v = riga.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        except OSError:
            continue
    return ""


def telegram(testo, documento=None):
    """Manda su Telegram (bot Jarvis) il testo, e il PDF se c'è. True se Telegram ha accettato."""
    # l'utente 2026-10-06: Telegram sospeso (reversibile): basta che esista uno dei due file; per riattivare si toglie.
    if (Path.home() / ".jarvis" / "telegram-sospeso").exists():
        return False
    token = next((v for v in (_env(k) for k in CHIAVI_BOT) if v), "")
    chat = _env("TELEGRAM_UTENTE_CHAT_ID") or CHAT_UTENTE_RISERVA
    if not token:
        print("riserva Telegram: nessun token del bot", file=sys.stderr)
        return False
    try:
        if documento and Path(documento).exists():
            r = subprocess.run(["curl", "-4", "-sS", "-m", "60", "-F", f"chat_id={chat}",
                                "-F", f"caption={testo[:1000]}", "-F", f"document=@{documento}",
                                f"https://api.telegram.org/bot{token}/sendDocument"],
                               capture_output=True, text=True, timeout=90)
            return '"ok":true' in r.stdout.replace(" ", "")
        ok = True
        for i in range(0, max(1, len(testo)), 4000):          # Telegram: 4096 caratteri per messaggio
            corpo = json.dumps({"chat_id": chat, "text": testo[i:i + 4000],
                                "disable_web_page_preview": True}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=corpo,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                ok = ok and json.loads(r.read()).get("ok", False)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"riserva Telegram non riuscita: {type(e).__name__}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- il punto d'ingresso
def notifica(chi, titolo, testo, dati=None, prova=False, chiave="", documento=None, tipo="", routine=""):
    """Manda la notifica. Torna {"ok", "dove": "cc"|"telegram"|"nessuno", "classe", ...}. Non solleva mai.
    tipo: «report» | «avviso» | "" (decide fili.classifica); routine: il nome della routine che manda."""
    chi = str(chi or "").strip().lower()
    if chi not in MITTENTI:
        return {"ok": False, "dove": "nessuno", "errore": "mittente: solo jarvis o postino"}
    corpo = {"chi": chi, "titolo": str(titolo or ""), "testo": str(testo or ""), "prova": bool(prova)}
    if dati is not None:
        corpo["dati"] = dati
    if chiave:
        corpo["chiave"] = chiave
    if tipo:
        corpo["tipo"] = str(tipo)
    if routine:
        corpo["routine"] = str(routine)
    try:
        r = manda_cc(corpo) if su_vps() else manda_ssh(corpo)
        if r.get("dove") == "telegram":         # dal Mac: la VPS ha già usato la riserva
            return r
        if not r.get("ok", True) and r.get("errore"):
            raise RuntimeError(r["errore"])
        esito = {"ok": True, "dove": "cc", "sessione": r.get("sessione"), "id": r.get("id"), "classe": r.get("classe")}
        if r.get("telegram_copia") and not prova:
            esito["telegram_copia"] = telegram(f"{titolo}\n\n{testo}".strip(), documento)
        return esito
    except Exception as e:  # noqa: BLE001
        errore = f"{type(e).__name__}: {e}"[:300]
        if prova:
            return {"ok": False, "dove": "nessuno", "errore": errore, "nota": "in prova niente Telegram"}
        tg = telegram(f"[{ 'Postino' if chi == 'postino' else 'Jarvis' }] {titolo}\n\n{testo}".strip(), documento)
        return {"ok": tg, "dove": "telegram" if tg else "nessuno", "errore_cc": errore}


def togli_prove():
    if su_vps():
        return manda_cc({"togli_prove": True})
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", VPS_SSH, "python3", REMOTO, "togli-prove"],
                       capture_output=True, text=True, timeout=40)
    return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"ok": False, "errore": r.stderr[:200]}


def esporta():
    """I due fili correnti letti dall'archivio (solo lettura): lo specchio del Mac."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "command-center"))
    import fili  # noqa: E402
    return {"fili": fili.esporta_speciali()}


# ---------------------------------------------------------------- lavori automatici in errore (l'utente, 05/10/2026)
# «Un lavoro automatico che finisce in errore deve mandare una notifica di Jarvis con la causa breve.»
# VPS: ogni servizio dei timer ha OnFailure=jarvis-errore@%n.service (strumenti/installa_notifiche_vps.sh),
# che lancia «notifica.py errore-servizio <unità>». Mac: il Command Center lancia ogni 5 minuti
# «notifica.py controlla-launchd» (i com.jarvis.* finiti con uscita diversa da 0). Cron: «notifica.py esegui -- <comando>».
# Una notifica per lavoro e per ora al massimo (chiave errore-<nome>-<AAAAMMGGHH>): un lavoro che cade ogni 10
# minuti non riempie il filo.
RIGHE_RUMORE = re.compile(r"^(Started|Starting|Finished|Stopped|Deactivated|Consumed|.*: Main process exited|"
                          r".*: Failed with result|.*: Triggering OnFailure|Failed to start)", re.I)


def causa_breve(righe, tetto=400):
    utili = [r.strip() for r in righe if r.strip() and not RIGHE_RUMORE.match(r.strip())]
    testo = " · ".join(utili[-3:]) or "nessun messaggio nel registro"
    return testo[-tetto:]


def _chiave_errore(nome):
    from datetime import datetime
    return "errore-" + re.sub(r"[^A-Za-z0-9_.:-]", "-", nome)[:50] + datetime.now().strftime("-%Y%m%d%H")


def errore_servizio(unita):
    """Sulla VPS, da jarvis-errore@<unità>.service: causa breve dal registro e notifica di Jarvis."""
    unita = re.sub(r"[^A-Za-z0-9@_.:-]", "", unita)[:120]
    stato = subprocess.run(["systemctl", "show", "-p", "Result", "-p", "ExecMainStatus", "--value", unita],
                           capture_output=True, text=True, timeout=20).stdout.split()
    log = subprocess.run(["journalctl", "-u", unita, "-n", "25", "--no-pager", "-o", "cat", "--since", "-2h"],
                         capture_output=True, text=True, timeout=20).stdout.splitlines()
    nome = unita.removesuffix(".service")
    # 2026-10-05: quando parte jarvis-errore@ il timer può aver già rilanciato l'unità, e systemctl dice «success, 0»
    # del giro nuovo. L'esito vero è l'ultima riga «Failed with result '...'» del registro; senza quella e con
    # success/0 non è un errore e non si notifica (falso allarme «finito in errore (success, uscita 0)»).
    # solo le righe dopo l'ultimo giro finito bene: un «Failed» vecchio di un'ora non è l'errore di adesso
    ultimo_ok = max([i for i, r in enumerate(log) if "Deactivated successfully" in r or r.startswith("Finished ")],
                    default=-1)
    falliti = [re.search(r"Failed with result '([^']+)'", r) for r in log[ultimo_ok + 1:]]
    falliti = [m.group(1) for m in falliti if m]
    if falliti:
        esito = f" ({falliti[-1]}" + (f", uscita {stato[1]})" if len(stato) >= 2 and stato[1] != "0" else ")")
    elif len(stato) >= 2 and stato[0] == "success" and stato[1] == "0":
        return {"ok": True, "saltato": "nessun errore: success, uscita 0"}
    else:
        esito = f" ({stato[0]}, uscita {stato[1]})" if len(stato) >= 2 else ""
    testo = (f"Il lavoro automatico «{nome}» (VPS) è finito in errore"
             + esito + f".\nCausa: {causa_breve(log)}\n"
             f"Registro: journalctl -u {unita} -n 50")
    return notifica("jarvis", f"Errore: {nome}", testo, chiave=_chiave_errore(nome))


def controlla_launchd(stato_file=HOME / ".locale-onedrive" / "jarvis-cc" / "launchd-errori.json"):
    """Sul Mac: i com.jarvis.* fermi con l'ultima uscita diversa da 0. Avvisa una volta per (lavoro, uscita)."""
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20).stdout.splitlines()
    try:
        visti = json.loads(stato_file.read_text())
    except (OSError, ValueError):
        visti = {}
    nuovi, esiti = {}, []
    for riga in out:
        parti = riga.split("\t")
        if len(parti) != 3 or not parti[2].startswith("com.jarvis."):
            continue
        pid, uscita, nome = parti
        if pid != "-" or uscita in ("0", "-"):
            continue
        nuovi[nome] = uscita
        if visti.get(nome) == uscita:
            continue
        log = []
        plist = HOME / "Library" / "LaunchAgents" / f"{nome}.plist"
        try:
            import plistlib
            d = plistlib.loads(plist.read_bytes())
            for chiave in ("StandardErrorPath", "StandardOutPath"):
                f = d.get(chiave)
                if f and Path(f).exists():
                    log = Path(f).read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                    if log:
                        break
        except Exception:  # noqa: BLE001
            pass
        testo = (f"Il lavoro automatico «{nome}» (Mac, launchd) è finito con uscita {uscita}.\n"
                 f"Causa: {causa_breve(log)}")
        esiti.append(notifica("jarvis", f"Errore: {nome}", testo, chiave=_chiave_errore(nome)))
    stato_file.parent.mkdir(parents=True, exist_ok=True)
    stato_file.write_text(json.dumps(nuovi))
    return {"ok": True, "avvisati": len(esiti), "in_errore": nuovi}


def esegui(comando, nome=""):
    """Per il cron: lancia il comando; se esce diverso da 0, notifica di Jarvis con le ultime righe. Torna l'uscita."""
    r = subprocess.run(comando, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        nome = nome or Path(comando[0]).name
        dove = "VPS" if su_vps() else "Mac"
        notifica("jarvis", f"Errore: {nome}", f"Il lavoro automatico «{nome}» ({dove}, cron) è finito con uscita "
                 f"{r.returncode}.\nCausa: {causa_breve((r.stdout + chr(10) + r.stderr).splitlines())}",
                 chiave=_chiave_errore(nome))
    return r.returncode


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        try:
            c = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            print(json.dumps({"ok": False, "errore": "JSON non valido"}))
            return 2
        print(json.dumps(notifica(c.get("chi"), c.get("titolo"), c.get("testo"), c.get("dati"), bool(c.get("prova")),
                                  c.get("chiave") or "", tipo=c.get("tipo") or "", routine=c.get("routine") or ""),
                         ensure_ascii=False))
        return 0
    ap = argparse.ArgumentParser(description="Notifica all'utente nel filo di Jarvis o del Postino (Telegram solo riserva)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manda")
    m.add_argument("--chi", required=True, choices=MITTENTI)
    m.add_argument("--titolo", default="")
    m.add_argument("--testo", default="")
    m.add_argument("--testo-file")
    m.add_argument("--html", action="store_true", help="il testo è HTML di Telegram: si converte")
    m.add_argument("--dati", help="JSON")
    m.add_argument("--chiave", default="")
    m.add_argument("--documento")
    m.add_argument("--prova", action="store_true")
    m.add_argument("--tipo", choices=("report", "avviso"), default="", help="dove va: scheda Postino o chat di Jarvis")
    m.add_argument("--routine", default="", help="la routine che manda (routine-gruppi.json, avvisa_postino)")
    sub.add_parser("togli-prove")
    sub.add_parser("esporta")
    e = sub.add_parser("errore-servizio")
    e.add_argument("unita")
    sub.add_parser("controlla-launchd")
    x = sub.add_parser("esegui")
    x.add_argument("--nome", default="")
    x.add_argument("comando", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "esegui":
        cmd = a.comando[1:] if a.comando[:1] == ["--"] else a.comando
        return esegui(cmd, a.nome) if cmd else 2
    if a.cmd == "errore-servizio":
        print(json.dumps(errore_servizio(a.unita), ensure_ascii=False))
        return 0
    if a.cmd == "controlla-launchd":
        print(json.dumps(controlla_launchd(), ensure_ascii=False))
        return 0
    if a.cmd == "manda":
        testo = Path(a.testo_file).read_text(encoding="utf-8") if a.testo_file else a.testo
        if a.html:
            testo = da_html(testo)
        r = notifica(a.chi, a.titolo, testo, json.loads(a.dati) if a.dati else None, a.prova, a.chiave, a.documento,
                     tipo=a.tipo, routine=a.routine)
    elif a.cmd == "togli-prove":
        r = togli_prove()
    else:
        r = esporta()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
