#!/usr/bin/env python3
"""Prove della pagina Routine (routine.py, 2026-10-05). Uso:

    python3 command-center/prove/prova_routine.py            # tutto
    python3 command-center/prove/prova_routine.py --senza-server

Parti:
  a) parser con dati finti: timer systemd (systemctl show + list-timers -o json), crontab, plist di launchd
  b) gruppi e tipi (routine-gruppi.json finto), gruppi nuovi della lavagna
  c) validazione: nomi, orari (cron, systemd con systemd-analyze finto, Mac), comandi e descrizioni
  d) prepara → conferma: il comando si scrive ma NON parte senza il codice, troppo presto o dopo l'annullamento
  e) server.py su una COPIA in una cartella temporanea (porta 7798, CC_PROVA=1, HOME temporanea, VPS inesistente,
     LaunchAgents finti): elenco, rifiuto della conferma senza «conferma: true» e senza codice, plist intatto

Non tocca la VPS, launchd né il Command Center vero: l'esecuzione è finta (ESEGUI) e la copia del server lavora su
file temporanei. Ogni riga è PASS o FAIL; in fondo i totali, esito 1 se qualcosa non passa.
"""
import json
import os
import re
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CC = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="prova-routine-"))
os.environ["CC_ROUTINE_DIR"] = str(TMP / "registro")
os.environ["CC_ROUTINE_GRUPPI"] = str(TMP / "routine-gruppi.json")
os.environ["CC_ROUTINE_LAUNCHAGENTS"] = str(TMP / "LaunchAgents")
os.environ["CC_ROUTINE_VPS"] = "vps-finta"
os.environ["CC_ROUTINE_COMPITI"] = str(TMP / "compiti")
os.environ["JARVIS_ATTIVITA_DIR"] = str(TMP / "attivita")
sys.path.insert(0, str(CC))
shutil.copy(CC / "routine-gruppi.json", TMP / "routine-gruppi.json")
import routine as R  # noqa: E402

RISULTATI = {"PASS": 0, "FAIL": 0}
NON_PASS = []


def esito(nome, ok, dettaglio=""):
    tipo = "PASS" if ok else "FAIL"
    RISULTATI[tipo] += 1
    riga = f"{tipo}  {nome}" + (f"  — {str(dettaglio)[:300]}" if dettaglio and not ok else "")
    if not ok:
        NON_PASS.append(riga)
    print(riga, flush=True)
    return ok


def rifiuta(f, *a, parola="", **kw):
    try:
        f(*a, **kw)
    except (R.RoutineNonValida, R.NonTrovata) as e:
        return parola.lower() in str(e).lower()
    return False


# ---------------------------------------------------------------- dati finti
TIMERS = """Unit=jarvis-giro-odoo.service
TimersCalendar={ OnCalendar=*-*-* 07:00:00 Europe/Rome ; next_elapse=Tue 2026-10-06 05:00:00 UTC }
LastTriggerUSec=Mon 2026-10-05 05:00:00 UTC
Id=jarvis-giro-odoo.timer
Description=Giro dati Azienda Uno → Odoo (07:00)
ActiveState=active
UnitFileState=enabled

Unit=jarvis-sincronia30.service
TimersMonotonic={ OnUnitActiveUSec=15min ; next_elapse=2month }
TimersMonotonic={ OnBootUSec=3min ; next_elapse=3min }
Id=jarvis-sincronia30.timer
Description=Sincronia (ogni 15 minuti)
ActiveState=inactive
UnitFileState=disabled

Unit=apt-daily.service
Id=apt-daily.timer
Description=non nostro
ActiveState=active
UnitFileState=enabled
"""
SERVIZI = """Result=success
ExecMainStartTimestamp=@1791181200
ExecMainExitTimestamp=@1791181260
ExecMainStatus=0
ExecStart={ path=/bin/bash ; argv[]=/bin/bash -c /root/jarvis/routine/giro-crm.sh >> /var/log/jarvis-giro-odoo.log 2>&1 ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
Id=jarvis-giro-odoo.service
Description=Giro dati
ActiveState=inactive
SubState=dead
FragmentPath=/etc/systemd/system/jarvis-giro-odoo.service

Result=exit-code
ExecMainStartTimestamp=@1791195803
ExecMainExitTimestamp=@1791195810
ExecMainStatus=2
ExecStart={ path=/bin/bash ; argv[]=/bin/bash -c python3 /root/jarvis/sincro/ogni30.py --zitto ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
Id=jarvis-sincronia30.service
ActiveState=failed
SubState=failed
"""
ELENCO = json.dumps([{"next": 1791262800000000, "left": 0, "last": 1791176400000000, "passed": 0,
                      "unit": "jarvis-giro-odoo.timer", "activates": "jarvis-giro-odoo.service"}])
CRONTAB = """# Progetto B — la vigilanza.
# Ogni dieci minuti guarda che tutto stia davvero funzionando
3,13,23,33,43,53 * * * * /root/Desktop/Progetto B/scripts/vigilanza.sh >> /root/Desktop/Progetto B/analisi/vigilanza_cron.log 2>&1
40 20 * * * /root/Desktop/Progetto B/scripts/leggi_spread.sh Test3 40 >> /root/x/spread.log 2>&1
40 9 * * * /root/Desktop/Progetto B/scripts/leggi_spread.sh Test3 30 >> /root/x/spread.log 2>&1
40 3 * * * /root/crm1-crm/scripts/backup.sh >> /root/crm1-crm/etl/log/backup.log 2>&1
MAILTO=""
*/5 * * * * /usr/bin/python3 /opt/jarvis-portiere/sync-jarvis-onedrive.py >> /tmp/sync-jarvis.log 2>&1
30 3 * * * /opt/passbolt/backup.sh >/dev/null 2>>/opt/passbolt/backup/errori.log  # Passbolt, copia notturna
#ROUTINE-PAUSA */10 * * * * /root/backup/guardiano.sh
riga rotta senza campi
# routine prova-nome: una descrizione data dalla pagina
0 8 * * 1-5 /bin/true
"""
LAUNCHCTL = "PID\tStatus\tLabel\n-\t0\tcom.jarvis.giro-apprendimento\n4321\t0\tcom.jarvis.tunnel-vps\n-\t78\tcom.azd.controllo-giornaliero\n-\t0\tcom.google.altro\n"


def scrivi_plist(nome, d):
    cart = TMP / "LaunchAgents"
    cart.mkdir(exist_ok=True)
    (cart / nome).write_bytes(plistlib.dumps(d))


scrivi_plist("com.jarvis.giro-apprendimento.plist", {"Label": "com.jarvis.giro-apprendimento",
             "ProgramArguments": ["/opt/homebrew/bin/python3", "/Users/x/Jarvis/strumenti/giro_apprendimento.py"],
             "StartCalendarInterval": {"Hour": 6, "Minute": 40}, "StandardOutPath": str(TMP / "giro.log")})
scrivi_plist("com.jarvis.tunnel-vps.plist", {"Label": "com.jarvis.tunnel-vps", "ProgramArguments": ["/x/tunnel.sh"], "KeepAlive": True})
scrivi_plist("com.azd.controllo-giornaliero.plist", {"Label": "com.azd.controllo-giornaliero", "ProgramArguments": ["/bin/bash", "-lc", "cd AZD-AZD && ./c.sh"],
             "StartCalendarInterval": [{"Hour": 8, "Minute": 0}, {"Hour": 20, "Minute": 0}]})
scrivi_plist("com.jarvis.sentinella15.plist.disabled", {"Label": "com.jarvis.sentinella15", "ProgramArguments": ["/x/s.py"], "StartInterval": 900})
scrivi_plist("com.google.keystone.agent.plist", {"Label": "com.google.keystone.agent", "ProgramArguments": ["/x"]})


def parte_a():
    print("\n== a) parser con dati finti")
    rr = R.routine_systemd(TIMERS, SERVIZI, ELENCO)
    ids = [r["id"] for r in rr]
    esito("systemd: solo i timer nostri (apt-daily fuori)", ids == ["vps:jarvis-giro-odoo", "vps:jarvis-sincronia30"], ids)
    g = rr[0]
    esito("systemd: OnCalendar con il fuso, «ogni giorno 07:00»", g["calendario"] == ["*-*-* 07:00:00 Europe/Rome"] and g["orario"] == "ogni giorno 07:00", g)
    esito("systemd: attivo, esito ok, codice 0", g["attivo"] and g["esito"] == "ok" and g["codice"] == 0, g)
    esito("systemd: ultimo e prossimo da list-timers (µs → s)", g["ultimo"] == 1791176400 and g["prossimo"] == 1791262800, (g["ultimo"], g["prossimo"]))
    esito("systemd: comando da argv[] e file di log", g["comando"].startswith("/bin/bash -c /root/jarvis/routine/giro-crm.sh") and g["log_file"] == "/var/log/jarvis-giro-odoo.log", g["comando"])
    s = rr[1]
    esito("systemd: intervallo monotono «ogni 15 min», in pausa, senza prossimo", s["orario"] == "ogni 15 min" and not s["attivo"] and s["prossimo"] is None, s)
    esito("systemd: errore con codice 2 e risultato exit-code", s["esito"] == "errore" and s["codice"] == 2 and s["risultato"] == "exit-code", s)

    utc = timezone.utc
    adesso = datetime(2026, 10, 5, 10, 35, tzinfo=utc).timestamp()
    cc = R.routine_cron(CRONTAB, "1791195000 /root/x/spread.log\n", utc, adesso)
    nomi = [r["nome"] for r in cc]
    esito("cron: nomi dagli script, doppione con -2, etichetta «routine nome:»",
          nomi == ["progetto-b-vigilanza", "progetto-b-leggi-spread", "progetto-b-leggi-spread-2", "crm1-crm-backup",
                   "jarvis-portiere-sync-jarvis-onedrive", "passbolt-backup", "backup-guardiano", "prova-nome"], nomi)
    v = cc[0]
    esito("cron: descrizione dal commento sopra", v["descrizione"].startswith("Ogni dieci minuti") or v["descrizione"].startswith("Progetto B"), v["descrizione"])
    esito("cron: prossima 10:43 e ultima 10:33 (UTC)", v["prossimo"] == datetime(2026, 10, 5, 10, 43, tzinfo=utc).timestamp()
          and v["ultimo"] == datetime(2026, 10, 5, 10, 33, tzinfo=utc).timestamp(), (v["prossimo"], v["ultimo"]))
    esito("cron: «ogni ora ai minuti 3, 13…»", v["orario"].startswith("ogni ora ai minuti 3, 13"), v["orario"])
    b = cc[3]
    esito("cron: 40 3 * * * UTC = ogni giorno 05:40 di Roma (ora legale)", b["orario"] == "ogni giorno 05:40", b["orario"])
    esito("cron: */5 = «ogni 5 min»", cc[4]["orario"] == "ogni 5 min", cc[4]["orario"])
    esito("cron: commento in coda come descrizione", cc[5]["descrizione"] == "Passbolt, copia notturna", cc[5]["descrizione"])
    esito("cron: «#ROUTINE-PAUSA» = in pausa, senza prossimo", not cc[6]["attivo"] and cc[6]["prossimo"] is None, cc[6])
    esito("cron: lun-ven alle 8 (1-5) → prossimo martedì 08:00", cc[7]["prossimo"] == datetime(2026, 10, 6, 8, 0, tzinfo=utc).timestamp(), cc[7]["prossimo"])
    esito("cron: mtime del log letto", cc[1]["log_aggiornato"] == 1791195000, cc[1])
    esito("cron: riga rotta e MAILTO ignorate", len(cc) == 8, len(cc))

    mm = R.routine_mac(TMP / "LaunchAgents", LAUNCHCTL, adesso)
    per = {r["nome"]: r for r in mm}
    esito("mac: solo com.jarvis/Azienda Uno/azd/progetto-b (google fuori), anche .disabled",
          sorted(per) == ["com.jarvis.giro-apprendimento", "com.jarvis.sentinella15", "com.jarvis.tunnel-vps", "com.azd.controllo-giornaliero"], sorted(per))
    ga = per["com.jarvis.giro-apprendimento"]
    esito("mac: caricato, «ogni giorno 06:40», avviabile, esito ok", ga["attivo"] and ga["orario"] == "ogni giorno 06:40" and ga["avviabile"] and ga["esito"] == "ok", ga)
    esito("mac: KeepAlive = sempre acceso, non avviabile da qui", per["com.jarvis.tunnel-vps"]["sempre"] and not per["com.jarvis.tunnel-vps"]["avviabile"], per["com.jarvis.tunnel-vps"])
    sp = per["com.azd.controllo-giornaliero"]
    esito("mac: due orari e uscita 78 = errore", sp["orario"] == "ogni giorno 08:00, 20:00" and sp["esito"] == "errore" and sp["codice"] == 78, sp)
    se = per["com.jarvis.sentinella15"]
    esito("mac: .plist.disabled = fermo, non avviabile, «ogni 15 min»", not se["attivo"] and not se["avviabile"] and se["orario"] == "ogni 15 min", se)


def parte_b():
    print("\n== b) gruppi e tipi")
    conf = R.carica_gruppi()
    prova = lambda rid, descr="", cmd="": R.classifica({"id": rid, "descrizione": descr, "comando": cmd}, conf)  # noqa: E731
    esito("giro-odoo → Azienda Uno / dati / scrive", prova("vps:jarvis-giro-odoo") == ("Azienda Uno", "dati", "scrive"), prova("vps:jarvis-giro-odoo"))
    esito("cron Progetto B per percorso → patrimonio", prova("cron:progetto-b-ciclo", "", "/root/Desktop/Progetto B/scripts/ciclo.sh")[0] == "patrimonio")
    esito("la cartella di casa non fa «Azienda Uno»",
          prova("mac:com.jarvis.posta-smista", "", str(Path.home()) + "/Jarvis/strumenti/posta.py")[0] == "jarvis",
          prova("mac:com.jarvis.posta-smista", "", str(Path.home()) + "/Jarvis/strumenti/posta.py"))
    esito("com.azd.* → Azienda Due", prova("mac:com.azd.archivio-notte")[0] == "Azienda Due")
    rr = [{"id": "vps:a", "gruppo": "Azienda Uno", "tipo": "controllo", "effetto": "lettura", "avviabile": True},
          {"id": "mac:b", "gruppo": "Azienda Uno", "tipo": "dati", "effetto": "scrive", "avviabile": False}]
    gg = R.gruppi_per_lavagna(rr, [{"id": "spazio-crm-1", "nome": "CRM Azienda Uno"}, {"id": "g-zoo", "nome": "Zoo Futuro"}], conf)
    per = {g["id"]: g for g in gg}
    esito("lavagna: alias della lavagna non duplicano Azienda Uno", "spazio-crm-1" not in per and per["Azienda Uno"]["controllo"] == ["vps:a"], per.get("Azienda Uno"))
    esito("lavagna: le routine non avviabili non vanno nei comandi rapidi", per["Azienda Uno"]["dati"] == [])
    esito("lavagna: un gruppo nuovo compare vuoto (si crea la routine)", "zoo-futuro" in per and per["zoo-futuro"]["controllo"] == [], list(per))
    esito("lavagna: tutti i gruppi dell'utente presenti, «sistema» fuori",
          all(k in per for k in ("Azienda Uno", "Azienda Due", "social-x", "patrimonio", "vita-personale", "android", "risto", "jarvis")) and "sistema" not in per, list(per))


CHIAMATE = []


def finto(cmd, timeout=30, ingresso=None):
    """ESEGUI finto: registra ogni chiamata; systemd-analyze dice sì solo agli orari «buoni»."""
    CHIAMATE.append((cmd, ingresso))
    remoto = cmd[-1] if cmd and cmd[0] == "ssh" else " ".join(cmd)
    if "systemd-analyze calendar" in remoto:
        if "29:99" in remoto:
            return 1, "Failed to parse calendar specification"
        return 0, "  Original form: x\nNext elapse: Tue 2026-10-06 07:30:00 CEST\n"
    if remoto.startswith("bash -s") or cmd[:2] == ["bash", "-s"]:
        return 0, "eseguito (finto)"
    return 0, ""


def semina():
    """La cache dell'elenco con i dati finti (dopo una conferma l'elenco si invalida: qui si rimette)."""
    rr = R.routine_systemd(TIMERS, SERVIZI, ELENCO) + R.routine_cron(CRONTAB, "", timezone.utc) + R.routine_mac(TMP / "LaunchAgents", LAUNCHCTL)
    grezzi = {r["id"]: {k: r.pop(k) for k in [k for k in r if k.startswith("_")]} for r in rr}
    R._CACHE.update(ts=time.time(), dati={"routine": rr, "avvisi": [], "conta": {}, "gruppi": [], "nomi_gruppi": {}, "letto": time.time()},
                    vps={"crontab": CRONTAB, "hash_cron": "a" * 64}, grezzi=grezzi)
    for r in R._CACHE["dati"]["routine"]:
        r["gruppo"], r["tipo"] = "jarvis", ""


def parte_c():
    print("\n== c) validazione")
    R.ESEGUI = finto
    semina()
    esito("nome nuovo con maiuscole rifiutato", rifiuta(R.prepara, {"nuova": True, "fonte": "vps", "nome": "Giro", "orario": "07:00", "comando": "true"}, parola="nome"))
    esito("nome nuovo di 41 caratteri rifiutato", rifiuta(R.prepara, {"nuova": True, "fonte": "vps", "nome": "a" * 41, "orario": "07:00", "comando": "true"}, parola="nome"))
    esito("nome con ; rifiutato", rifiuta(R.prepara, {"nuova": True, "fonte": "cron", "nome": "x;rm", "orario": "* * * * *", "comando": "true"}, parola="nome"))
    esito("routine sconosciuta → non trovata", rifiuta(R.prepara, {"id": "vps:non-esiste", "orario": "07:00"}, parola="non trovata"))
    esito("id con caratteri strani → non trovata", rifiuta(R.prepara, {"id": "vps:$(reboot)", "orario": "07:00"}, parola="non trovata"))
    esito("OnCalendar rifiutato da systemd-analyze", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "orario": "*-*-* 29:99:00"}, parola="non valido per systemd"))
    esito("OnCalendar con caratteri vietati (`;`)", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "orario": "07:00; reboot"}, parola="orario"))
    esito("cron con 4 campi rifiutato", rifiuta(R.prepara, {"id": "cron:progetto-b-vigilanza", "orario": "* * * *"}, parola="5 campi"))
    esito("cron con minuto 61 rifiutato", rifiuta(R.prepara, {"id": "cron:progetto-b-vigilanza", "orario": "61 * * * *"}, parola="fuori"))
    esito("cron: % non protetto nel comando rifiutato", rifiuta(R.prepara, {"id": "cron:progetto-b-vigilanza", "comando": "date +%F"}, parola="%"))
    esito("comando con a capo rifiutato", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "comando": "true\nreboot"}, parola="a capo"))
    esito("comando con la parola di fine heredoc rifiutato", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "comando": "echo " + R.FINE}, parola="riservata"))
    esito("descrizione di 121 caratteri rifiutata", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "descrizione": "x" * 121}, parola="120"))
    esito("Mac: orario «25:00» rifiutato", rifiuta(R.prepara, {"id": "mac:com.jarvis.giro-apprendimento", "orario": "25:00"}, parola="orario"))
    esito("Mac: la descrizione non si cambia", rifiuta(R.prepara, {"id": "mac:com.jarvis.giro-apprendimento", "descrizione": "nuova"}, parola="descrizione"))
    esito("niente da cambiare rifiutato", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "attivo": True}, parola="niente"))
    esito("nuova senza comando rifiutata", rifiuta(R.prepara, {"nuova": True, "fonte": "vps", "nome": "x", "orario": "07:00"}, parola="comando"))
    esito("tipo sconosciuto rifiutato", rifiuta(R.prepara, {"nuova": True, "fonte": "vps", "nome": "x", "orario": "07:00", "comando": "true", "tipo": "boh"}, parola="tipo"))
    esito("intervallo di 8 giorni rifiutato", rifiuta(R.prepara, {"id": "vps:jarvis-giro-odoo", "orario": "ogni 12000 min"}, parola="intervallo"))
    esito("_quota_systemd protegge $, %, \" e \\", R._quota_systemd('echo "$HOME" 50% \\n') == '"echo \\"$$HOME\\" 50%% \\\\n"', R._quota_systemd('echo "$HOME" 50% \\n'))


def parte_d():
    print("\n== d) prepara → conferma")
    CHIAMATE.clear()
    p = R.prepara({"id": "vps:jarvis-giro-odoo", "orario": "07:30", "descrizione": "Giro dati alle 7 e mezza"})
    esito("prepara: comando esatto con drop-in, daemon-reload e restart",
          "/etc/systemd/system/jarvis-giro-odoo.timer.d/50-routine.conf" in p["comando"] and "OnCalendar=*-*-* 07:30:00 Europe/Rome" in p["comando"]
          and "systemctl daemon-reload" in p["comando"] and "systemctl restart jarvis-giro-odoo.timer" in p["comando"] and "cp -a" in p["comando"], p["comando"])
    esito("prepara: non ha eseguito niente (solo systemd-analyze)", all("systemd-analyze" in (c[0][-1] if c[0][0] == "ssh" else "") for c in CHIAMATE), CHIAMATE)
    esito("conferma senza codice: rifiutata", rifiuta(R.conferma, p["prep"], None, parola="conferma"))
    esito("dopo un rifiuto per codice il comando resta preparato (non consumato)", p["prep"] in R._PREP)
    esito("conferma con codice sbagliato: rifiutata", rifiuta(R.conferma, p["prep"], "0" * 32, parola="codice"))
    esito("conferma troppo veloce: rifiutata", rifiuta(R.conferma, p["prep"], p["codice"], parola="veloce"))
    esito("niente è stato eseguito fino a qui", not any(c[1] for c in CHIAMATE), CHIAMATE[-1:])
    time.sleep(R.PREP_MIN_S + 0.1)
    x = R.conferma(p["prep"], p["codice"])
    esito("conferma con il codice giusto: esegue lo script via ssh bash -s", x["ok"] and CHIAMATE[-1][0][-1] == "bash -s" and "50-routine.conf" in (CHIAMATE[-1][1] or ""), x)
    esito("il codice è monouso", rifiuta(R.conferma, p["prep"], p["codice"], parola="conferma"))
    semina()

    p2 = R.prepara({"id": "vps:jarvis-sincronia30", "attivo": True})
    esito("riattiva: enable --now", "systemctl enable --now jarvis-sincronia30.timer" in p2["comando"], p2["comando"])
    R.annulla(p2["prep"])
    esito("dopo «Annulla» la conferma è rifiutata", rifiuta(R.conferma, p2["prep"], p2["codice"], parola="conferma"))

    p3 = R.prepara({"id": "cron:progetto-b-leggi-spread-2", "attivo": False})
    esito("cron pausa: hash di controllo, backup in /root/crontab-AAAAMMGG-HHMM.bak, riga commentata",
          'ATTUALE=$(crontab -l' in p3["comando"] and "/root/crontab-$TS.bak" in p3["comando"]
          and "#ROUTINE-PAUSA 40 9 * * * /root/Desktop/Progetto B/scripts/leggi_spread.sh Test3 30" in p3["comando"]
          and "\n40 20 * * * /root/Desktop/Progetto B/scripts/leggi_spread.sh Test3 40" in p3["comando"], p3["comando"])
    p4 = R.prepara({"nuova": True, "fonte": "vps", "nome": "prova-nuova", "descrizione": "Prova", "orario": "ogni 20 min", "comando": "echo ciao $HOME"})
    esito("nuova VPS: jarvis-prova-nuova.{service,timer}, controllo che non esista, log, OnFailure",
          "test ! -e /etc/systemd/system/jarvis-prova-nuova.service" in p4["comando"] and "OnUnitActiveSec=20min" in p4["comando"]
          and "ExecStart=/bin/bash -c \"echo ciao $$HOME >> /var/log/jarvis-prova-nuova.log 2>&1\"" in p4["comando"]
          and "OnFailure=jarvis-errore@%n.service" in p4["comando"] and p4["id"] == "vps:jarvis-prova-nuova", p4["comando"])
    p5 = R.prepara({"id": "mac:com.jarvis.giro-apprendimento", "orario": "07:15"})
    esito("Mac: backup del plist, plutil e ricarica solo se caricato",
          "cp -p" in p5["comando"] and "plutil -replace StartCalendarInterval -json '{\"Hour\": 7, \"Minute\": 15}'" in p5["comando"]
          and "launchctl bootstrap" in p5["comando"], p5["comando"])
    p6 = R.prepara({"id": "mac:com.jarvis.sentinella15", "attivo": True})
    esito("Mac: riattivare un .disabled = mv + bootstrap", ".plist.disabled" in p6["comando"] and "mv " in p6["comando"] and "launchctl bootstrap" in p6["comando"], p6["comando"])
    reg = (TMP / "registro" / "registro.jsonl").read_text().splitlines()
    azioni = [json.loads(x)["esito"] for x in reg]
    esito("registro: preparato, rifiutato, partito, ok, annullato", all(a in azioni for a in ("preparato", "rifiutato", "partito", "ok", "annullato")), azioni)


def parte_f():
    print("\n== f) difetti del verificatore: effetto, errori nel modulo, orari leggibili")
    conf = json.loads((CC / "routine-gruppi.json").read_text())
    voci = conf["routine"]
    esito("ogni voce esplicita ha un effetto lettura|scrive|invia", all(v.get("effetto") in R.EFFETTI for v in voci.values()),
          [k for k, v in voci.items() if v.get("effetto") not in R.EFFETTI])
    esito("nel file, «controllo» solo con effetto lettura", all(v["effetto"] == "lettura" for v in voci.values() if v.get("tipo") == "controllo"))
    esito("nel file, «dati» solo con effetto scrive", all(v["effetto"] == "scrive" for v in voci.values() if v.get("tipo") == "dati"))
    for rid in ("vps:crm1-servizio-live", "vps:jarvis-condiviso", "vps:jarvis-allerta-Azienda Due", "vps:jarvis-stato-vault", "vps:jarvis-sincronia30"):
        g, t, e = R.classifica({"id": rid}, conf)
        esito(f"{rid} non è un controllo (effetto {e})", t != "controllo" and e in ("scrive", "invia"), (g, t, e))
    finto_conf = {"routine": {"vps:x": {"gruppo": "jarvis", "tipo": "controllo", "effetto": "scrive"},
                              "vps:y": {"gruppo": "jarvis", "tipo": "controllo"},
                              "vps:z": {"gruppo": "jarvis", "tipo": "dati", "effetto": "invia"},
                              "vps:ok": {"gruppo": "jarvis", "tipo": "controllo", "effetto": "lettura"}},
                  "regole": [{"se": ".", "gruppo": "jarvis", "tipo": "controllo"}],
                  "gruppi": [{"id": "jarvis", "nome": "Jarvis"}]}
    esito("controllo con effetto «scrive» → tolto", R.classifica({"id": "vps:x"}, finto_conf)[1] == "")
    esito("controllo senza effetto → tolto (sconosciuta non è un controllo)", R.classifica({"id": "vps:y"}, finto_conf)[1:] == ("", ""))
    esito("dati con effetto «invia» → tolto", R.classifica({"id": "vps:z"}, finto_conf)[1] == "")
    esito("una regola non dà mai «controllo»", R.classifica({"id": "vps:sconosciuta"}, finto_conf) == ("jarvis", "", ""))
    rr = [{"id": "vps:ok", "gruppo": "jarvis", "tipo": "controllo", "effetto": "lettura", "avviabile": True},
          {"id": "vps:x", "gruppo": "jarvis", "tipo": "controllo", "effetto": "scrive", "avviabile": True},
          {"id": "vps:d", "gruppo": "jarvis", "tipo": "dati", "effetto": "scrive", "avviabile": True}]
    g = R.gruppi_per_lavagna(rr, [], finto_conf)[0]
    esito("comandi rapidi: Controlli solo «lettura», Dati a parte", g["controllo"] == ["vps:ok"] and g["dati"] == ["vps:d"], g)
    # «Tutti» lancia solo le voci del menu scelto: in routine.js è g[tipo] di ogni gruppo
    js = (CC / "static" / "routine.js").read_text()
    esito("routine.js: «Tutti» = solo le voci del menu scelto (flatMap g[tipo])", "gruppi.flatMap((g) => g[tipo] || [])" in js)
    esito("routine.js: etichette «scrive in produzione» e «manda messaggi»", "scrive in produzione" in js and "manda messaggi" in js)

    # 2) errori di «prepara» dentro il modulo: il messaggio del server comincia con il nome del campo
    R.ESEGUI = finto
    semina()
    messaggi = {}
    for nome, dati in (("orario", {"id": "cron:progetto-b-vigilanza", "orario": "61 * * * *"}),
                       ("orario", {"id": "cron:progetto-b-vigilanza", "orario": "* * * *"}),
                       ("orario", {"id": "vps:jarvis-giro-odoo", "orario": "*-*-* 29:99:00"}),
                       ("comando", {"id": "vps:jarvis-giro-odoo", "comando": "a\nb"}),
                       ("descrizione", {"id": "vps:jarvis-giro-odoo", "descrizione": "x" * 200}),
                       ("nome", {"nuova": True, "fonte": "vps", "nome": "X", "orario": "07:00", "comando": "true"})):
        try:
            R.prepara(dati)
            messaggi[str(dati)] = (nome, None)
        except R.RoutineNonValida as e:
            messaggi[str(dati)] = (nome, str(e))
    sorgente = js[js.index("function campoDiErrore"):]
    sorgente = sorgente[:sorgente.index("\n  }\n") + 4]
    prova_js = sorgente + "\nconst m = " + json.dumps([[n, t] for n, t in messaggi.values()]) + \
        ";\nconsole.log(JSON.stringify(m.map(([n, t]) => [n, t && campoDiErrore(t)])));"
    r = subprocess.run(["node", "-e", prova_js], capture_output=True, text=True)
    try:
        coppie = json.loads(r.stdout)
    except ValueError:
        coppie = []
    esito("ogni errore di prepara finisce sotto il suo campo (campoDiErrore)", coppie and all(n == c for n, c in coppie), (coppie, r.stderr[:200]))
    esito("routine.js: il modulo tiene quello che l'utente ha scritto (S.ed) e mostra l'errore nel campo",
          "oninput: (ev) => { ed.regola = ev.target.value;" in js and "ro-errore-campo" in js and "function erroreEd(campo)" in js)

    # 3) orari systemd multipli in italiano, il grezzo a parte
    db1 = ["*-*-* 01:00:00 Europe/Rome", "*-*-* 00:00,30:00 Europe/Rome", "*-*-* 19..23:00,30:00 Europe/Rome",
            "*-*-* 16:00:00 Europe/Rome", "*-*-* 12..15:00,30:00 Europe/Rome"]
    esito("crm1-servizio-live: «ogni 30 min 12:00–16:00, 19:00–01:00»", R.testo_calendario(db1, []) == "ogni 30 min 12:00–16:00, 19:00–01:00", R.testo_calendario(db1, []))
    esito("due orari fissi: «ogni giorno 07:00, 19:00»", R.testo_calendario(["*-*-* 07:00:00 Europe/Rome", "*-*-* 19:00:00 Europe/Rome"], []) == "ogni giorno 07:00, 19:00")
    esito("ogni ora dalle 12 alle 16: «ogni ora 12:00–16:00»", R.testo_orari([(h, 0) for h in range(12, 17)]) == "ogni ora 12:00–16:00", R.testo_orari([(h, 0) for h in range(12, 17)]))
    esito("calendario non giornaliero resta com'è", R.testo_calendario(["Mon..Fri 08:30 Europe/Rome"], []) == "Mon..Fri 08:30")
    T2 = TIMERS.replace("{ OnCalendar=*-*-* 07:00:00 Europe/Rome ; next_elapse=Tue 2026-10-06 05:00:00 UTC }",
                        "{ OnCalendar=*-*-* 12..15:00,30:00 Europe/Rome ; next_elapse=x }\nTimersCalendar={ OnCalendar=*-*-* 16:00:00 Europe/Rome ; next_elapse=x }")
    r0 = R.routine_systemd(T2, SERVIZI, ELENCO)[0]
    esito("il grezzo resta in orario_grezzo (per il title)", r0["orario"] == "ogni 30 min 12:00–16:00"
          and r0["orario_grezzo"] == "*-*-* 12..15:00,30:00 Europe/Rome; *-*-* 16:00:00 Europe/Rome", (r0["orario"], r0.get("orario_grezzo")))
    esito("routine.js: il title della scheda mostra il grezzo", "r.orario_grezzo ?" in js)


def parte_g():
    print("\n== g) orari come Claude Code (andata e ritorno) e «Salva» che applica, verifica e ripristina")
    import routine_orari as O
    import routine_salva as RS

    def errore_campo(p, campo):
        try:
            O.valida(p)
        except O.PianoNonValido as e:
            return str(e).startswith(campo)
        return False
    esito("valida: frequenza sconosciuta → «frequenza:»", errore_campo({"frequenza": "boh"}, "frequenza"))
    esito("valida: ogni 7 minuti (non divide l'ora) → «ogni:»", errore_campo({"frequenza": "minuti", "ogni": 7}, "ogni"))
    esito("valida: fascia 25:00 → «fasce:»", errore_campo({"frequenza": "minuti", "ogni": 30, "fasce": [["25:00", "26:00"]]}, "fasce"))
    esito("valida: settimana senza giorni → «giorni:»", errore_campo({"frequenza": "settimana", "orari": ["07:00"], "giorni": []}, "giorni"))
    esito("valida: giorno «lunedì» → «giorni:»", errore_campo({"frequenza": "giorno", "orari": ["07:00"], "giorni": ["lunedì"]}, "giorni"))
    esito("valida: una volta senza data → «data:»", errore_campo({"frequenza": "una_volta", "ora": "07:00"}, "data"))
    esito("valida: periodo al prima di dal → «al:»", errore_campo({"frequenza": "giorno", "orari": ["07:00"], "dal": "2026-10-20", "al": "2026-10-01"}, "al"))

    db1 = O.valida({"frequenza": "minuti", "ogni": 30, "fasce": [["12:00", "16:00"], ["19:00", "01:00"]]})
    _, t = O.tempi(db1)
    esito("fascia oltre mezzanotte: 23:30, 00:00, 00:30 e 01:00 sì, 01:30 no",
          {23 * 60 + 30, 0, 30, 60} <= t and 90 not in t and 16 * 60 in t and 16 * 60 + 30 not in t)
    esito("testo: «ogni 30 min dalle 12 alle 16 e dalle 19 all'1»", O.testo(db1) == "ogni 30 min dalle 12 alle 16 e dalle 19 all'1", O.testo(db1))
    feriali = O.valida({"frequenza": "giorno", "orari": ["07:00"], "giorni": ["lun", "mar", "mer", "gio", "ven"]})
    esito("testo: «ogni giorno alle 07:00, lun–ven»", O.testo(feriali) == "ogni giorno alle 07:00, lun–ven", O.testo(feriali))

    casi = [db1, feriali,
            O.valida({"frequenza": "minuti", "ogni": 15, "fasce": [], "giorni": []}),
            O.valida({"frequenza": "ora", "ogni": 60, "fasce": [["08:00", "20:00"]], "giorni": ["sab", "dom"]}),
            O.valida({"frequenza": "settimana", "orari": ["06:30", "18:30"], "giorni": ["lun", "gio"]}),
            O.valida({"frequenza": "giorno", "orari": ["01:05"], "giorni": []})]
    ok_sd = all(O.tempi(O.da_systemd(O.a_systemd(p)["calendari"])) == O.tempi(p) for p in casi)
    esito("systemd: campi → OnCalendar → campi, stessi orari (6 casi)", ok_sd, [O.a_systemd(p) for p in casi if O.tempi(O.da_systemd(O.a_systemd(p)["calendari"]) or db1) != O.tempi(p)])
    esito("systemd: giorni come «Mon..Fri» e fuso «Europe/Rome»", O.a_systemd(feriali)["calendari"] == ["Mon..Fri *-*-* 07:00:00 Europe/Rome"], O.a_systemd(feriali))
    uv = O.valida({"frequenza": "una_volta", "data": "2026-10-08", "ora": "10:45"})
    esito("systemd: una volta = «2026-10-08 10:45:00 Europe/Rome» e ritorno", O.a_systemd(uv)["calendari"] == ["2026-10-08 10:45:00 Europe/Rome"]
          and O.da_systemd(O.a_systemd(uv)["calendari"]) == uv)
    esito("systemd: OnUnitActiveSec=30min → ogni 30 min «dalla fine del giro prima»", (O.da_systemd([], "30min") or {}).get("monotono") is True)
    esito("systemd: 30 secondi e UTC non si rappresentano (vanno in Avanzato)",
          O.da_systemd([], "30") is None and O.da_systemd(["*-*-* 07:00:00 UTC"]) is None)

    esito("cron: 07:00 di Roma = «0 5» d'estate e «0 6» d'inverno",
          O.a_cron(O.valida({"frequenza": "giorno", "orari": ["07:00"]}), 120) == "0 5 * * *"
          and O.a_cron(O.valida({"frequenza": "giorno", "orari": ["07:00"]}), 60) == "0 6 * * *")
    lun01 = O.valida({"frequenza": "settimana", "orari": ["01:00"], "giorni": ["lun"]})
    esito("cron: lunedì 01:00 di Roma = domenica 23:00 UTC («0 23 * * 0»)", O.a_cron(lun01, 120) == "0 23 * * 0", O.a_cron(lun01, 120))
    esito("cron: andata e ritorno con il cambio di giorno", O.tempi(O.da_cron("0 23 * * 0", 120)) == O.tempi(lun01))
    try:
        O.a_cron(db1, 120)
        no_riga = False
    except O.PianoNonValido as e:
        no_riga = str(e).startswith("fasce")
    esito("cron: le fasce 12–16 e 19–01 non stanno in una riga → rifiuto chiaro", no_riga)
    ok_cron = all(O.tempi(O.da_cron(O.a_cron(p, 120), 120)) == O.tempi(p) for p in casi if p is not db1)
    esito("cron: campi → 5 campi → campi, stessi orari (5 casi)", ok_cron)
    esito("cron: «una volta» rifiutata", errore_cron_una_volta(O))

    sd = O.a_launchd(O.valida({"frequenza": "settimana", "orari": ["03:44"], "giorni": ["sab", "dom"]}))["StartCalendarInterval"]
    esito("launchd: sab = Weekday 6, dom = Weekday 0", sorted(x["Weekday"] for x in sd) == [0, 6], sd)
    ok_l = all(O.tempi(O.da_launchd(O.a_launchd(p))) == O.tempi(p) for p in casi)
    esito("launchd: campi → plist → campi, stessi orari (6 casi)", ok_l)
    esito("launchd: ogni 15 min senza fasce = StartInterval 900", O.a_launchd(casi[2]) == {"StartInterval": 900})

    periodo = O.valida({"frequenza": "giorno", "orari": ["07:00"], "dal": "2026-10-10", "al": "2026-10-12"})
    pr = O.prossime(periodo, 5, adesso=datetime(2026, 10, 5, 12, 0, tzinfo=O.ROMA).timestamp())
    esito("prossime: solo dentro il periodo (10, 11, 12 ottobre)", [datetime.fromtimestamp(x, O.ROMA).day for x in pr] == [10, 11, 12], pr)
    c1 = O.con_periodo("echo ciao", periodo, "cron")
    esito("periodo in cron: guardia con \\% e ritorno", "\\%Y\\%m\\%d" in c1 and O.senza_periodo(c1) == ("echo ciao", "2026-10-10", "2026-10-12"), c1)
    c2 = O.con_periodo(c1, O.valida({"frequenza": "giorno", "orari": ["07:00"]}), "vps")
    esito("periodo tolto: torna il compito nudo", c2 == "echo ciao", c2)

    # le routine vere: ogni orario rappresentabile fa andata e ritorno senza differenze
    R.ESEGUI, vps_prima, R.VPS = R._esegui_vero, R.VPS, "vps-tuo"     # sola lettura della VPS vera (una chiamata ssh)
    v = R.leggi_vps() if "--senza-vps" not in sys.argv else {"ok": False}
    R.VPS = vps_prima
    if v.get("ok"):
        vere = R.routine_systemd(v["timers"], v["servizi"], v["elenco"]) + R.routine_cron(v["crontab"], v["mtimes"], v["zona"])
        diverse, rappresentabili = [], 0
        for r in vere:
            if r["fonte"] == "vps":
                p = O.da_systemd(r["calendario"], (r["intervallo"] or {}).get("OnUnitActiveSec") if not r["calendario"] else None)
                if p and not p.get("monotono"):
                    rappresentabili += 1
                    if O.tempi(O.da_systemd(O.a_systemd(p)["calendari"])) != O.tempi(p):
                        diverse.append(r["id"])
                elif p:
                    rappresentabili += 1
            else:
                p = O.da_cron(r["cron"])
                if p:
                    rappresentabili += 1
                    if O.a_cron(p) != R.SPECIALI_CRON.get(r["cron"], r["cron"]) and O.tempi(O.da_cron(O.a_cron(p))) != O.tempi(p):
                        diverse.append(r["id"])
        esito(f"routine vere della VPS: {rappresentabili}/{len(vere)} nei campi, nessuna differenza andata e ritorno", not diverse, diverse)
    else:
        print("SALTA routine vere della VPS (non raggiungibile o --senza-vps)")

    # «Salva»: applica, verifica, ripristina (esecuzione finta)
    R.ESEGUI = finto_salva
    semina()
    STATO_FINTO["verifica_ok"] = True
    CHIAMATE.clear()
    x = RS.salva({"id": "vps:jarvis-giro-odoo", "piano": {"frequenza": "giorno", "orari": ["07:30"], "giorni": []}})
    script = next((c[1] for c in CHIAMATE if c[1] and "50-routine.conf" in c[1]), "")
    esito("salva: applica subito (drop-in, backup .bak-TS, daemon-reload, restart) e verifica", x["ok"] and "cp -a" in script
          and "OnCalendar=*-*-* 07:30:00 Europe/Rome" in script and "systemctl restart jarvis-giro-odoo.timer" in script, (x, script[:400]))
    esito("salva: nessun ripristino quando la verifica torna (un solo «bash -s»)", sum(1 for c in CHIAMATE if c[1]) == 1, len([c for c in CHIAMATE if c[1]]))
    semina()
    STATO_FINTO["verifica_ok"] = False
    CHIAMATE.clear()
    x = RS.salva({"id": "vps:jarvis-giro-odoo", "piano": {"frequenza": "giorno", "orari": ["07:45"], "giorni": []}})
    ripristino = [c[1] for c in CHIAMATE if c[1] and "if [ -f" in c[1] and "bak-" in c[1] and "cp -a" in c[1] and "cat >" not in c[1]]
    esito("salva: verifica sbagliata → errore e ripristino automatico dal backup", not x["ok"] and x["ripristinato"] and ripristino, (x, len(CHIAMATE)))
    STATO_FINTO["verifica_ok"] = True
    semina()
    CHIAMATE.clear()
    esito("salva: niente da cambiare → rifiuto, niente eseguito", rifiuta(RS.salva, {"id": "vps:jarvis-giro-odoo"}, parola="niente")
          and not any(c[1] for c in CHIAMATE))
    esito("salva: orario non valido in Avanzato → «avanzato:» e niente eseguito", rifiuta_piano(RS, {"id": "vps:jarvis-giro-odoo", "grezzo": "*-*-* 29:99:00"}, "avanzato")
          and not any(c[1] for c in CHIAMATE))
    esito("salva: nome nuovo non valido → «nome:»", rifiuta(RS.salva, {"nuova": True, "fonte": "vps", "nome": "Prova!", "piano": {"frequenza": "ora"}}, parola="nome"))
    chiesti = []
    RS.CHIEDI = chiesti.append
    mac_prima = R.MAC
    R.MAC = False
    try:
        y = RS.salva({"nuova": True, "fonte": "mac", "nome": "prova-dal-sito", "piano": {"frequenza": "giorno", "orari": ["03:00"]}, "compito": "true"})
    finally:
        R.MAC = mac_prima
        RS.CHIEDI = None
    esito("dal sito una routine del Mac: non si applica, va a Jarvis in chat", y.get("a_jarvis") and chiesti and "prova-dal-sito" in chiesti[0], (y, chiesti))
    ok_s, _ = RS.controlla_script("#!/bin/bash\nif then\n", "bash")
    ok_g, av_g = RS.controlla_script("#!/bin/bash\nrm -rf ~/\n", "bash")
    esito("script: sintassi sbagliata rifiutata (bash -n)", not ok_s)
    esito("script: «rm -rf ~/» fermato dalla guardia dei comandi", not ok_g and "guardia" in " ".join(av_g), av_g)
    esito("effetto dello script: notifica = invia, psql = scrive, stat = lettura",
          RS.effetto_script("python3 /root/jarvis/strumenti/notifica.py manda --chi jarvis") == "invia"
          and RS.effetto_script("docker exec crm1-odoo-db psql -c 'select 1'") == "scrive"
          and RS.effetto_script('stat -c %Y /var/log/jarvis-giro-odoo.log') == "lettura")
    js = (CC / "static" / "routine.js").read_text()
    esito("routine.js: «Salva» applica (azione salva), niente più Prepara/Conferma nella pagina",
          'azione: "salva"' in js and 'azione: "prepara"' not in js and 'azione: "conferma"' not in js)
    esito("routine.js: la regola si trasforma in script e si vede prima di salvare",
          'azione: "scrivi-script"' in js and "Controlla lo script qui sotto, poi premi di nuovo «Salva»." in js)
    esito("routine.js: con l'editor aperto l'aggiornamento automatico non cancella i campi (S.ed)", "if (S.ed) { aggiornaVivi();" in js)


def errore_cron_una_volta(O):
    try:
        O.a_cron(O.valida({"frequenza": "una_volta", "data": "2026-10-08", "ora": "10:45"}), 120)
    except O.PianoNonValido as e:
        return str(e).startswith("frequenza")
    return False


def rifiuta_piano(RS, dati, campo):
    import routine_orari as O
    try:
        RS.salva(dati)
    except (O.PianoNonValido, R.RoutineNonValida) as e:
        return str(e).startswith(campo)
    return False


STATO_FINTO = {"verifica_ok": True, "ultimo": ""}


def finto_salva(cmd, timeout=30, ingresso=None):
    """ESEGUI finto per «Salva»: systemd-analyze normalizza; systemctl show dice quello che lo script ha scritto
    (verifica_ok) oppure altro (verifica sbagliata → il ripristino deve partire)."""
    CHIAMATE.append((cmd, ingresso))
    remoto = cmd[-1] if cmd and cmd[0] == "ssh" else " ".join(cmd)
    if "systemd-analyze calendar" in remoto:
        out = []
        for c in re.findall(r"--iterations=3 '([^']*)'", remoto):
            if "29:99" in c or "pippo" in c:
                out.append(f"Failed to parse calendar specification '{c}'\n@@rc=1")
            else:
                out.append(f"Normalized form: {c}\n    Next elapse: Tue 2026-10-06 05:30:00 UTC\n@@rc=0")
        return 0, "\n".join(out)
    if ingresso and remoto.startswith("bash -s"):
        cal = re.findall(r"^OnCalendar=(.+)$", ingresso, re.M)
        if cal:
            STATO_FINTO["ultimo"] = cal[-1]
        return 0, "eseguito (finto)"
    if remoto.startswith("systemctl show") and "jarvis-giro-odoo.timer" in remoto:
        cal = STATO_FINTO["ultimo"] if STATO_FINTO["verifica_ok"] else "*-*-* 03:00:00 Europe/Rome"
        return 0, (f"Id=jarvis-giro-odoo.timer\nTimersCalendar={{ OnCalendar={cal} ; next_elapse=x }}\nUnitFileState=enabled\n"
                   f"ActiveState=active\n\nId=jarvis-giro-odoo.service\nExecStart={{ path=/bin/bash ; argv[]=/bin/bash -c x ; ignore_errors=no ; start_time=[n/a] }}\n")
    return 0, ""


def parte_h():
    print("\n== h) i 6 difetti del verificatore (pulsante, descrizione, Avanzato, intervalli, 40 px, regola su richiesta)")
    import routine_salva as RS
    js = (CC / "static" / "routine.js").read_text()
    css = (CC / "static" / "routine.css").read_text()
    # 1) il pulsante «Scrivi lo script» segue il campo mentre si scrive
    esito("1) «Scrivi lo script» si abilita scrivendo la regola (oninput aggiorna disabled)",
          "bScrivi.disabled = ed.occupato || !ed.regola.trim();" in js)
    # 6) la regola non si ricava all'apertura
    apri = js[js.index("function apriEditor(r)"):js.index("function apriNuova(pre)")]
    esito("6) aprire Modifica non chiama Jarvis (niente ricavaRegola in apriEditor)", "ricavaRegola" not in apri, apri[-300:])
    esito("6) c'è il pulsante «Ricava la regola dallo script»", "Ricava la regola dallo script" in js and "onclick: ricavaRegola" in js)
    chiamate_claude = []
    RS.CLAUDE = lambda prompt, modello: chiamate_claude.append(modello) or "regola finta"
    R.ESEGUI = finto_salva
    semina()
    elenco_prima = list(RS.COMPITI.glob("*.regola")) if RS.COMPITI.exists() else []
    R.elenco()   # come la pagina all'apertura: elenco e anteprima, niente descrivi
    RS.anteprima({"fonte": "vps", "piano": {"frequenza": "giorno", "orari": ["07:00"]}, "id": "vps:jarvis-giro-odoo"})
    esito("6) elenco + anteprima non chiamano claude e non scrivono .regola",
          not chiamate_claude and (list(RS.COMPITI.glob("*.regola")) if RS.COMPITI.exists() else []) == elenco_prima)
    RS.CLAUDE = None
    # 2) cambiare solo l'orario non tocca la descrizione
    semina()
    STATO_FINTO["verifica_ok"] = True
    CHIAMATE.clear()
    x = RS.salva({"id": "vps:jarvis-giro-odoo", "piano": {"frequenza": "giorno", "orari": ["07:15"], "giorni": []}})
    script = next((c[1] for c in CHIAMATE if c[1] and "50-routine.conf" in c[1]), "")
    esito("2) solo orario: Description resta quella attiva, non diventa il nome",
          x["ok"] and "Description=Giro dati Azienda Uno → Odoo (07:00)" in script and "Description=jarvis-giro-odoo" not in script, script[:500])
    semina()
    CHIAMATE.clear()
    RS.salva({"id": "vps:jarvis-giro-odoo", "descrizione": "Giro dati nuovo"})
    script = next((c[1] for c in CHIAMATE if c[1] and "50-routine.conf" in c[1]), "")
    esito("2) descrizione cambiata dall'utente: va nel drop-in", "Description=Giro dati nuovo" in script, script[:300])
    # 3) Avanzato non valido: niente si applica
    semina()
    CHIAMATE.clear()
    try:
        RS.salva({"id": "vps:jarvis-giro-odoo", "grezzo": "pippo pluto"})
        msg = ""
    except Exception as e:  # noqa: BLE001
        msg = str(e)
    esito("3) Avanzato «pippo pluto» (timer): rifiuto «avanzato: …», niente applicato",
          msg.startswith("avanzato") and not any(c[1] for c in CHIAMATE), (msg, len(CHIAMATE)))
    semina()
    try:
        RS.salva({"id": "cron:progetto-b-vigilanza", "grezzo": "pippo pluto"})
        msg = ""
    except Exception as e:  # noqa: BLE001
        msg = str(e)
    esito("3) Avanzato non valido (cron): rifiuto «avanzato: …»", msg.startswith("avanzato"), msg)
    esito("3) routine.js: Avanzato toccato e non valido blocca «Salva» con l'errore nel campo",
          'if (ed.grezzoErrore) { ed.errore = { campo: "avanzato"' in js and 'if (m.startsWith("avanzato")) return "avanzato";' in js)
    esito("3) routine.js: con Avanzato toccato si manda il grezzo (quello che l'utente vede), non il piano dei campi",
          "if (ed.grezzoToccato) {" in js and "corpo.grezzo = ed.grezzo;" in js)
    # 4) intervalli: prossime dall'ultimo giro vero
    semina()
    r = R.trova("vps:jarvis-sincronia30")
    r["prossimo"], r["attivo"] = time.time() + 300, True
    pr = RS.anteprima({"fonte": "vps", "grezzo": "OnUnitActiveSec=15min", "id": "vps:jarvis-sincronia30"})["prossime"]
    esito("4) timer a intervallo: prossime = NextElapse, +15 min, +30 min",
          len(pr) == 3 and abs(pr[0] - r["prossimo"]) < 1 and abs(pr[1] - pr[0] - 900) < 1, pr)
    esito("4) «Avvia ora» invalida la cache", "invalida()          # 2026-10-05 (verificatore)" in (CC / "routine.py").read_text())
    # 5) 40 px sul telefono
    esito("5) sul telefono i comandi sono alti almeno 40 px", "@media (max-width: 820px)" in css and "min-height: 40px;" in css
          and ".ro-btn, .ro-filtro" in css.split("@media (max-width: 820px)")[-1])


def http(metodo, url, corpo=None, intest=None, timeout=60):
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dati, method=metodo, headers={"Content-Type": "application/json", **(intest or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}") if "json" in r.headers.get("Content-Type", "") else r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def parte_e():
    print("\n== e) server.py su una copia (porta 7798)")
    copia = TMP / "cc"
    copia.mkdir()
    for f in CC.glob("*.py"):
        shutil.copy(f, copia / f.name)
    for f in CC.glob("*.json"):
        if f.name not in ("configurazione.json", "conversazioni.json"):
            shutil.copy(f, copia / f.name)
    (copia / "static").mkdir()
    (copia / "static" / "index.html").write_text('<meta name="token" content="__TOKEN__">')
    (copia / "lavori").mkdir()
    casa = TMP / "casa"
    (casa / "my-agent").mkdir(parents=True)
    (copia / "configurazione.json").write_text(json.dumps({"cartella_agente": str(casa / "my-agent"), "vault": "", "porta": 7798, "modo_chat": "lavoro"}))
    plist = TMP / "LaunchAgents" / "com.jarvis.giro-apprendimento.plist"
    prima = plist.read_bytes()
    env = {**os.environ, "HOME": str(casa), "CC_PORTA": "7798", "CC_PROVA": "1", "CC_ROUTINE_VPS": "prova-inesistente.invalid",
           "CC_ROUTINE_DIR": str(TMP / "registro-server"), "CC_ROUTINE_GRUPPI": str(copia / "routine-gruppi.json")}
    log = open(TMP / "server.log", "w")
    srv = subprocess.Popen([sys.executable, str(copia / "server.py")], cwd=copia, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:7798"
    try:
        token = None
        for _ in range(60):
            try:
                c, b = http("GET", base + "/", timeout=3)
                if c == 200:
                    token = b.decode().split('content="')[1].split('"')[0]
                    break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        if not esito("la copia parte sulla 7798 e dà il token", bool(token) and token != "__TOKEN__", (TMP / "server.log").read_text()[-400:]):
            return
        H = {"X-Token": token, "Origin": base}
        c, d = http("GET", base + "/api/routine", intest=H)
        esito("GET /api/routine: 200, VPS irraggiungibile detta negli avvisi", c == 200 and any("VPS" in a for a in d.get("avvisi", [])), (c, d.get("avvisi")))
        mac = [r for r in d.get("routine", []) if r["fonte"] == "mac"]
        esito("GET /api/routine: le routine del Mac finte (4) con gruppo e tipo", sys.platform != "darwin" or (len(mac) == 4 and all("gruppo" in r for r in mac)), [r["id"] for r in mac])
        esito("GET /api/routine: i gruppi dei comandi rapidi", any(g["id"] == "Azienda Uno" for g in d.get("gruppi", [])), d.get("gruppi"))
        c, d = http("GET", base + "/api/routine", intest={"X-Token": "sbagliato"})
        esito("senza token: 403", c == 403, c)
        c, d = http("POST", base + "/api/routine", {"azione": "conferma", "prep": "abc", "codice": "x"}, intest=H)
        esito("conferma senza «conferma: true»: 428", c == 428 and "conferma" in d.get("errore", ""), (c, d))
        if sys.platform == "darwin":
            c, p = http("POST", base + "/api/routine", {"azione": "prepara", "id": "mac:com.jarvis.giro-apprendimento", "orario": "07:15"}, intest=H)
            esito("prepara (Mac, plist finto): 200 con il comando", c == 200 and "plutil" in p.get("comando", ""), (c, p))
            time.sleep(1.2)
            c, d = http("POST", base + "/api/routine", {"azione": "conferma", "prep": p.get("prep"), "conferma": True}, intest=H)
            esito("conferma senza codice: 428 «serve la conferma»", c == 428 and "conferma" in d.get("errore", ""), (c, d))
            c, d = http("POST", base + "/api/routine", {"azione": "conferma", "prep": p.get("prep"), "codice": "f" * 32, "conferma": True}, intest=H)
            esito("conferma con codice sbagliato: 428", c == 428, (c, d))
            esito("il plist è intatto dopo i rifiuti", plist.read_bytes() == prima)
            c, d = http("POST", base + "/api/routine", {"azione": "annulla", "prep": p.get("prep")}, intest=H)
            esito("annulla: 200", c == 200, (c, d))
        c, d = http("POST", base + "/api/routine", {"azione": "avvia", "id": "mac:com.jarvis.tunnel-vps"}, intest=H)
        esito("avvia su una routine «sempre accesa»: 400 con il perché", c == 400 and "sempre acceso" in d.get("errore", ""), (c, d))
        c, d = http("POST", base + "/api/routine", {"azione": "boh"}, intest=H)
        esito("azione sconosciuta: 400", c == 400, (c, d))
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    parte_a()
    parte_b()
    parte_c()
    parte_d()
    parte_f()
    parte_g()
    parte_h()
    if "--senza-server" not in sys.argv:
        parte_e()
    print(f"\nTotale: {RISULTATI['PASS']} PASS, {RISULTATI['FAIL']} FAIL  (cartella {TMP})")
    for r in NON_PASS:
        print("  " + r)
    if not NON_PASS:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if NON_PASS else 0)
