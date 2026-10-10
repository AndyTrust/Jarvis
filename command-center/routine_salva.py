#!/usr/bin/env python3
"""«Salva» delle Routine: applica SUBITO, verifica e, se la verifica non torna, ripristina da solo
(l'utente, 2026-10-05 14:25: «dobbiamo poter modificare le routine direttamente dalla pagina e aggiornarla subito»).

E la «Regola» (l'utente, 14:40: «il compito deve essere un comando che lui rielabora in script, ma io scrivo normalmente
la regola»): l'utente scrive in italiano, Jarvis (claude -p) la trasforma in uno script deterministico in
routine/compiti/<nome>.sh|.py con la regola in testa; la scheda mostra lo script (e la differenza col precedente)
prima di applicare. Una routine senza regola riceve, una volta, una descrizione ricavata dal suo comando
(routine/compiti/<nome>.regola).

Dove stanno gli script: nel repository (routine/compiti/, sul Mac ~/Jarvis/routine/compiti). La VPS riceve il
repository da GitHub ogni ~10 minuti con `git reset --hard` (chiave in sola lettura: dalla VPS non si fa commit), quindi:
  - Command Center del Mac: scrive nel repository E copia subito sulla VPS (/root/jarvis/routine/compiti/), così il
    timer usa lo script nuovo da subito; quando arriva il commit, il file è identico;
  - Command Center della VPS (il sito): scrive in /root/jarvis/routine/compiti/ (file non tracciato: il reset --hard
    non lo tocca) e lo dice; il Mac, alla prossima lettura dell'elenco, porta nel repository i file nuovi della VPS
    (mai sopra un file diverso: quello lo segnala).
Ogni salvataggio va nel registro (routine.registra) e nel filo «Notifiche Jarvis» (NOTIFICA, la mette il server).
Solo libreria standard.
"""
import difflib
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import routine as R
import routine_orari as O

QUI = Path(__file__).resolve().parent
COMPITI = Path(os.environ.get("CC_ROUTINE_COMPITI") or QUI.parent / "routine" / "compiti")
COMPITI_VPS = "/root/jarvis/routine/compiti"
SU_VPS = str(QUI.parent) == "/root/jarvis"          # questo Command Center gira sulla VPS (il sito)
NOTIFICA = None      # il server: funzione(titolo, testo, chiave)
CHIEDI = None        # il server: funzione(testo) → manda a Jarvis in chat
CLAUDE = None        # il server: funzione(prompt, modello) → testo (claude -p)
MAX_SCRIPT = 40000
CHIAVE_REGOLA = "# REGOLA: "


# ---------------------------------------------------------------- lettura: piano, grezzo, regola

def _orario_grezzo(r, g):
    if r["fonte"] == "vps":
        if r.get("calendario"):
            return "\n".join(r["calendario"])
        return "\n".join(f"{k}={v}" for k, v in (r.get("intervallo") or {}).items())
    if r["fonte"] == "cron":
        return r.get("cron") or ""
    return O.grezzo_launchd(g.get("_plist") or {})


def _piano_di(r, g):
    if r["fonte"] == "vps":
        iv = r.get("intervallo") or {}
        solo_attivo = set(iv) <= {"OnUnitActiveSec", "OnBootSec"}
        p = O.da_systemd(r.get("calendario") or [], iv.get("OnUnitActiveSec") if solo_attivo else None)
    elif r["fonte"] == "cron":
        p = O.da_cron(r.get("cron") or "")
    else:
        p = O.da_launchd(g.get("_plist") or {}) if not r.get("sempre") else None
    if p and p["frequenza"] != "una_volta":
        _, dal, al = O.senza_periodo(_nudo(r, g))
        if dal:
            p["dal"] = dal
        if al:
            p["al"] = al
    return p


def _nudo(r, g):
    """Il compito come lo scrive l'utente: senza «/bin/bash -c » (timer) e senza la guardia del periodo."""
    c = g.get("_comando") or ""
    if r["fonte"] == "vps":
        c = re.sub(r"^/bin/bash -c ", "", c)
    elif r["fonte"] == "mac":
        a = g.get("_argomenti") or []
        if len(a) == 3 and a[0] in ("/bin/bash", "/bin/zsh") and a[1] in ("-c", "-lc"):
            c = a[2]
    return c


def _regole_da_testo(testo):
    """{nome file: regola} dalle righe «file:# REGOLA: …» (grep -H)."""
    out = {}
    for riga in (testo or "").splitlines():
        f, _, resto = riga.partition(":")
        if resto.startswith(CHIAVE_REGOLA):
            out.setdefault(Path(f).name, []).append(resto[len(CHIAVE_REGOLA):])
    return {k: "\n".join(v) for k, v in out.items()}


def leggi_regola_file(percorso):
    try:
        righe = Path(percorso).read_text(encoding="utf-8", errors="replace").splitlines()[:60]
    except OSError:
        return None
    r = [x[len(CHIAVE_REGOLA):] for x in righe if x.startswith(CHIAVE_REGOLA)]
    return "\n".join(r) if r else None


def _script_di(comando):
    m = re.search(r"routine/compiti/([a-z0-9.-]{1,60}\.(?:sh|py))", comando or "")
    return m.group(1) if m else None


def arricchisci(rr, v):
    """Aggiunge a ogni routine piano (campi), grezzo (Avanzato), testo, regola e script. Torna gli avvisi."""
    avvisi = []
    regole_vps = _regole_da_testo(v.get("regole", "")) if v else {}
    if v and not SU_VPS and R.MAC:
        avvisi += porta_nel_repo(v.get("compiti_sha", ""))
    for r in rr:
        g = {k: r.get(k) for k in r if k.startswith("_")}
        r["grezzo"] = _orario_grezzo(r, g)
        try:
            p = _piano_di(r, g)
        except Exception:  # noqa: BLE001
            p = None
        r["piano"] = p
        r["piano_testo"] = O.testo(p) if p else ""
        if p and not p.get("monotono"):
            r["orario"] = r["piano_testo"]          # «ogni ora», «ogni 30 min dalle 12 alle 16…» al posto del testo grezzo
        r["compito"] = R._pulisci(_nudo(r, g), 2000)
        nome_script = _script_di(g.get("_comando"))
        r["script"] = nome_script
        regola = None
        for f in ([nome_script] if nome_script else []) + [f"{r['nome']}.regola"]:
            regola = leggi_regola_file(COMPITI / f) or (regole_vps.get(f) if r["fonte"] != "mac" else None)
            if regola:
                break
        r["regola"] = regola or ""
        r["regola_da_script"] = bool(nome_script and regola)
    return avvisi


def porta_nel_repo(sha_testo):
    """Sul Mac: i file di routine/compiti nuovi sulla VPS (scritti dal sito) entrano nel repository; mai sopra un file
    diverso. Torna gli avvisi."""
    avvisi = []
    for riga in (sha_testo or "").splitlines():
        sha, _, nome = riga.strip().partition("  ")
        if not re.fullmatch(r"[a-z0-9.-]{1,60}\.(sh|py|regola)", nome or ""):
            continue
        locale = COMPITI / nome
        if locale.exists():
            import hashlib
            if hashlib.sha256(locale.read_bytes()).hexdigest() != sha:
                avvisi.append(f"routine/compiti/{nome}: la copia della VPS è diversa da quella del repository (vince il repository al prossimo giro)")
            continue
        cod, out = R.ssh(f"cat {shlex.quote(COMPITI_VPS + '/' + nome)}", timeout=20)
        if cod == 0 and out:
            COMPITI.mkdir(parents=True, exist_ok=True)
            locale.write_text(out, encoding="utf-8")
            if nome.endswith((".sh", ".py")):
                locale.chmod(0o755)
            avvisi.append(f"routine/compiti/{nome} scritto dal sito: portato nel repository (manca il commit)")
    return avvisi


# ---------------------------------------------------------------- anteprima (campi ↔ grezzo, prossime esecuzioni)

def _calendari_veri(calendari):
    """systemd-analyze calendar --iterations=3 per ogni riga, sulla VPS. → (normalizzati, prossime) o PianoNonValido."""
    pezzi = [f"systemd-analyze calendar --iterations=3 {shlex.quote(c)} 2>&1; echo @@rc=$?" for c in calendari]
    cod, out = R.ssh("; ".join(pezzi), timeout=25)
    if "@@rc=" not in out:
        raise O.PianoNonValido(f"orario: VPS non raggiungibile per controllare l'orario ({cod})")
    norm, prossime = [], []
    for blocco, c in zip(out.split("@@rc=")[:-1], calendari):
        if "Failed to parse" in blocco or "Normalized form:" not in blocco:
            raise O.PianoNonValido(f"orario: systemd non accetta «{c}»")
        norm.append(re.search(r"Normalized form:\s*(.+)", blocco).group(1).strip())
        for m in re.finditer(r"(?:Next elapse|Iteration #\d+):\s*\w+ (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC", blocco):
            prossime.append(datetime.strptime(m.group(1) + " +0000", "%Y-%m-%d %H:%M:%S %z").timestamp())
    return norm, sorted(prossime)[:3]


def _grezzo_a_piano(fonte, grezzo):
    g = (grezzo or "").strip()
    if not g:
        raise O.PianoNonValido("avanzato: vuoto")
    if fonte == "vps":
        m = re.fullmatch(r"(?:ogni\s+)?(\d{1,4})\s*min|OnUnitActiveSec=(\S+)(?:\s*OnBootSec=\S+)?|OnBootSec=\S+\s*OnUnitActiveSec=(\S+)", g.replace("\n", " "))
        if m:
            n = int(m.group(1)) if m.group(1) else O.minuti_da_durata(m.group(2) or m.group(3))
            if not n:
                raise O.PianoNonValido("avanzato: intervallo non valido")
            return ({"frequenza": "minuti", "ogni": n, "monotono": True} if n <= 60 and 60 % n == 0 else None), {"intervallo_min": n}
        cal = [x.strip() for x in g.splitlines() if x.strip()]
        if any(not R.CALENDARIO.fullmatch(c) for c in cal):
            raise O.PianoNonValido("avanzato: solo lettere, cifre e * : , . / ~ - + _ spazio")
        return O.da_systemd(cal), {"calendari": cal}
    if fonte == "cron":
        R.orario_cron(g)
        return O.da_cron(g), {"cron": g}
    if g.lower().startswith("ogni"):
        n = R._intervallo(g)
        return O.da_launchd({"StartInterval": n * 60}), {"StartInterval": n * 60}
    try:
        sci = json.loads(g)
    except ValueError:
        raise O.PianoNonValido("avanzato: sul Mac «ogni N min» oppure la lista JSON di StartCalendarInterval") from None
    d = {"StartCalendarInterval": sci}
    return O.da_launchd(d), d


def anteprima(dati):
    """{fonte, piano | grezzo} → {piano, grezzo, testo, prossime, avvisi}. Le prossime sono vere (systemd-analyze per i
    timer, in Python per cron e launchd)."""
    fonte = dati.get("fonte")
    if fonte not in ("vps", "cron", "mac"):
        raise O.PianoNonValido("frequenza: fonte sconosciuta")
    avvisi = []
    if dati.get("piano") is not None:
        p = O.valida(dati["piano"])
        if fonte == "vps":
            orario = O.a_systemd(p)
        elif fonte == "cron":
            orario = {"cron": O.a_cron(p)}
        else:
            orario = O.a_launchd(p)
    else:
        try:
            p, orario = _grezzo_a_piano(fonte, dati.get("grezzo"))
            if fonte == "vps" and orario.get("calendari"):
                _calendari_veri(orario["calendari"])
        except (O.PianoNonValido, ValueError) as e:
            raise O.PianoNonValido("avanzato: " + re.sub(r"^(orario|avanzato):\s*", "", str(e))) from None
        if p is None:
            avvisi.append("Questo orario non si rappresenta con i campi: resta in «Avanzato».")
    prossime = []
    if fonte == "vps":
        if orario.get("calendari"):
            orario["calendari"], prossime = _calendari_veri(orario["calendari"])
            grezzo = "\n".join(orario["calendari"])
        else:
            grezzo = f"OnUnitActiveSec={orario['intervallo_min']}min"
            prossime = _prossime_intervallo(dati.get("id"), orario["intervallo_min"] * 60)
            avvisi.append("Timer «dalla fine del giro prima»: l'ora esatta dipende da quando è finito l'ultimo giro.")
    elif fonte == "cron":
        grezzo = orario["cron"]
        avvisi.append(f"Il cron della VPS è in UTC: ho convertito con lo scarto di oggi (+{O.scarto_roma() // 60} h). "
                      "Al cambio dell'ora legale l'orario si sposta di un'ora: per un'ora fissa usa un timer systemd.")
        prossime = [x for x in [R.cron_vicino(grezzo, time.time(), R.timezone.utc, 1)] if x]
        if prossime:
            t = prossime[0]
            for _ in range(2):
                t2 = R.cron_vicino(grezzo, t, R.timezone.utc, 1)
                if not t2:
                    break
                prossime.append(t2)
                t = t2
    else:
        grezzo = O.grezzo_launchd(orario)
        if orario.get("StartInterval"):
            prossime = _prossime_intervallo(dati.get("id"), orario["StartInterval"])
        if p and p["frequenza"] == "una_volta":
            avvisi.append("Sul Mac «una volta» si ripete ogni anno nello stesso giorno: dopo, mettila in pausa.")
    if p and not (fonte == "mac" and orario.get("StartInterval")) and ((p.get("dal") or p.get("al")) or fonte != "vps"):
        prossime = O.prossime(p)
    return {"piano": p, "grezzo": grezzo, "testo": O.testo(p) if p else "(solo Avanzato)", "orario": orario,
            "prossime": prossime[:3], "prossime_testo": [R.testo_ora(x) for x in prossime[:3]], "avvisi": avvisi}


def _prossime_intervallo(rid, secondi):
    """Timer «ogni N dalla fine del giro prima» (OnUnitActiveSec / StartInterval): la prossima è quella che dice systemd
    (o l'ultimo giro + N), poi + N. Senza dati: da adesso."""
    base = None
    try:
        r = R.trova(rid) if rid else None
    except (KeyError, ValueError):
        r = None
    if r:
        base = r.get("prossimo") or ((r.get("ultimo") + secondi) if r.get("ultimo") else None)
    adesso = time.time()
    base = base or adesso + secondi
    while base < adesso:
        base += secondi
    return [base, base + secondi, base + 2 * secondi]


# ---------------------------------------------------------------- regola → script

def effetto_script(testo):
    t = testo or ""
    if re.search(r"notifica\.py|telegram|sendmail|posta\.py\s+(manda|invia|rispondi)|/api/notifica|webhook|smtp", t, re.I):
        return "invia"
    if re.search(r"\b(psql|xmlrpc|odoo-bin|odoo\s+shell|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|systemctl\s+(restart|start|stop)|docker|rm\s|mv\s|kill\b|"
                 r"git\s+(push|commit)|crontab|launchctl)\b|>>?\s*(?!/dev/null|/tmp/|/var/log/|&)\S", t, re.I):
        return "scrive"
    return "lettura"


def controlla_script(testo, lingua):
    """(ok, avvisi): sintassi (bash -n / py_compile) e guardia dei comandi. Non esegue niente."""
    avvisi = []
    if len(testo) > MAX_SCRIPT:
        return False, ["script: troppo lungo"]
    with tempfile.NamedTemporaryFile("w", suffix=".py" if lingua == "python" else ".sh", delete=False) as f:
        f.write(testo)
        tmp = f.name
    try:
        if lingua == "python":
            r = subprocess.run([sys.executable, "-c", "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)", tmp],
                               capture_output=True, text=True, timeout=20)
        else:
            r = subprocess.run(["bash", "-n", tmp], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return False, [f"script: sintassi non valida: {(r.stderr or r.stdout).strip()[:300]}"]
    finally:
        os.unlink(tmp)
    try:
        sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
        import guardia_comandi as G
        corpo = testo if lingua == "bash" else f"python3 - <<'CC_FINE_PY'\n{testo}\nCC_FINE_PY"
        perche = G.motivo(corpo)
        if perche:
            return False, [f"script: la guardia dei comandi lo ferma: {perche[:300]}"]
    except Exception as e:  # noqa: BLE001
        avvisi.append(f"guardia dei comandi non caricata qui ({type(e).__name__}): controllata solo la sintassi")
    return True, avvisi


PROMPT_SCRIPT = """Sei il programmatore delle routine di Jarvis. Trasforma la REGOLA dell'utente in UNO script {lingua_lunga} che gira {dove}.
Regole che non cambiano:
- deterministico: niente modelli di linguaggio a ogni esecuzione, SALVO che la regola chieda esplicitamente un giudizio
  (valutare, riassumere, scegliere): solo allora lo script lancia `claude -p --model sonnet "<prompt fisso scritto nello script>"`;
- niente comandi distruttivi (rm -rf, DROP, git push…), niente segreti scritti nello script (le chiavi stanno in ~/.env.jarvis, si leggono da lì);
- per avvisare l'utente usa SOLO: python3 /root/jarvis/strumenti/notifica.py manda --chi jarvis --titolo "…" --testo "…"
  (o --chi postino per la posta); sul Mac: python3 ~/Jarvis/strumenti/notifica.py manda --chi jarvis …;
  il RISULTATO che l'utente ha chiesto (report, briefing, riepilogo) va con --tipo report --routine {nome} (finisce nella
  scheda Postino della chat); errori e avanzamenti tecnici con --tipo avviso (chat di Jarvis), mai nel Postino;
- strumenti utili: /root/jarvis/strumenti/ (sul Mac ~/Jarvis/strumenti/), python3 /root/jarvis/strumenti/posta.py, i log in /var/log/jarvis-*.log,
  ssh vps-tuo dal Mac; Odoo Azienda Uno = contenitore crm1-odoo-db (psql in sola lettura salvo che la regola chieda di scrivere);
- esce con 0 se tutto va, diverso da 0 se la regola non è rispettata o qualcosa fallisce (così il timer segnala l'errore);
- stampa una riga chiara di esito.
Routine: {nome} ({fonte}). Orario: {orario}.
{attuale}
REGOLA:
{regola}

Rispondi SOLO con lo script in un blocco ```{lingua}``` (senza intestazione: la metto io), poi una riga «EFFETTO: lettura|scrive|invia»."""


def scrivi_script(dati):
    """{id | nuova+fonte+nome, regola} → {script (con intestazione), lingua, percorso, diff, effetto, ok, avvisi}.
    Chiede a Jarvis (claude -p, opus: è codice). Non scrive niente su disco."""
    regola = R._testo_breve(dati.get("regola"), "regola", 2000)
    if not regola:
        raise R.RoutineNonValida("regola: scrivi cosa deve fare la routine")
    regola = regola.replace("\r", "")
    if dati.get("nuova"):
        fonte, nome = dati.get("fonte"), dati.get("nome")
        if fonte not in ("vps", "cron", "mac") or not isinstance(nome, str) or not R.NOME.fullmatch(nome):
            raise R.RoutineNonValida("nome: minuscole, cifre e trattini, da 1 a 40 caratteri")
        r = {"fonte": fonte, "nome": nome if fonte != "vps" or nome.startswith("jarvis-") else f"jarvis-{nome}",
             "orario": dati.get("orario_testo") or ""}
        attuale_script, attuale = None, ""
    else:
        r = R.trova(dati.get("id"))
        g = (R._CACHE.get("grezzi") or {}).get(r["id"], {})
        attuale_script = leggi_script(r)
        cmd = _nudo(r, g)
        attuale = (f"Script attuale (da riscrivere secondo la regola):\n```\n{attuale_script[:12000]}\n```" if attuale_script
                   else f"Comando attuale (per contesto): {cmd[:1500]}")
    if CLAUDE is None:
        raise R.RoutineNonValida("regola: qui Jarvis non è raggiungibile (claude non configurato)")
    dove = "sul Mac dell'utente (macOS, zsh/bash, utente tu)" if r["fonte"] == "mac" else "sulla VPS (Ubuntu, root, cartella /root/jarvis)"
    lingua = "bash"
    prompt = PROMPT_SCRIPT.format(lingua_lunga="bash (o python3 se serve logica vera)", lingua="bash|python", dove=dove,
                                  nome=r["nome"], fonte=r["fonte"], orario=r.get("orario") or "", attuale=attuale, regola=regola)
    risposta = CLAUDE(prompt, "opus")
    m = re.search(r"```(bash|sh|python|python3)?\s*\n(.*?)```", risposta or "", re.S)
    if not m:
        raise R.RoutineNonValida("regola: Jarvis non ha risposto con uno script, riprova o scrivi la regola più precisa")
    lingua = "python" if (m.group(1) or "").startswith("python") else "bash"
    corpo = m.group(2).strip("\n")
    corpo = re.sub(r"^#!.*\n", "", corpo)
    e = re.search(r"EFFETTO:\s*(lettura|scrive|invia)", risposta or "")
    script = intestazione(r["nome"], regola, lingua, "Jarvis (claude opus) dalla pagina Routine") + corpo + "\n"
    ok, avvisi = controlla_script(script, lingua)
    effetto = effetto_script(corpo)
    if e and e.group(1) != "lettura" and effetto == "lettura":
        effetto = e.group(1)
    ext = ".py" if lingua == "python" else ".sh"
    nome_file = f"{r['nome']}{ext}"
    diff = "".join(difflib.unified_diff((attuale_script or "").splitlines(True), script.splitlines(True),
                                        "prima", "dopo", n=2)) if attuale_script else ""
    return {"script": script, "lingua": lingua, "file": nome_file, "diff": diff[:30000], "effetto": effetto,
            "ok": ok, "avvisi": avvisi, "regola": regola}


def intestazione(nome, regola, lingua, chi):
    ora = datetime.now(O.ROMA).strftime("%Y-%m-%d %H:%M")
    righe = ["#!/bin/bash" if lingua == "bash" else "#!/usr/bin/env python3", f"# ROUTINE: {nome}"]
    righe += [CHIAVE_REGOLA + x for x in regola.splitlines() if x.strip()]
    righe += [f"# SCRITTO: {ora} da {chi}",
              "# Non si modifica a mano: cambia la regola dalla pagina Routine e salva (Jarvis riscrive lo script)."]
    if lingua == "bash":
        righe.append("set -uo pipefail")
    return "\n".join(righe) + "\n"


def leggi_script(r):
    nome = r.get("script")
    if not nome:
        return None
    try:
        return (COMPITI / nome).read_text(encoding="utf-8")
    except OSError:
        pass
    if r["fonte"] != "mac":
        cod, out = R.ssh(f"cat {shlex.quote(COMPITI_VPS + '/' + nome)}", timeout=20)
        if cod == 0:
            return out
    return None


PROMPT_DESCRIVI = """Descrivi in italiano semplice, in 1-3 frasi, cosa fa questa routine automatica di Jarvis, come regola
che l'utente potrebbe aver scritto (es. «ogni mattina porta in Odoo i dati dei portali e se qualcosa non torna avvisami»).
Niente dettagli tecnici inutili, niente percorsi lunghi, e NON dire quando gira (l'orario sta nei suoi campi).
Rispondi SOLO con la regola.
Routine: {nome} — {descrizione}
Comando: {comando}
{script}"""


def descrivi(dati):
    """La regola ricavata dal comando attuale (sonnet), salvata UNA volta in routine/compiti/<nome>.regola."""
    r = R.trova(dati.get("id"))
    if r.get("regola"):
        return {"regola": r["regola"], "salvata": False}
    if CLAUDE is None:
        raise R.RoutineNonValida("regola: qui Jarvis non è raggiungibile (claude non configurato)")
    g = (R._CACHE.get("grezzi") or {}).get(r["id"], {})
    contenuto = ""
    for p in re.findall(r"(/[A-Za-z0-9._/-]+\.(?:sh|py))", g.get("_comando") or "")[:2]:
        if r["fonte"] == "mac":
            try:
                contenuto += f"\n--- {p}\n" + Path(p).read_text(encoding="utf-8", errors="replace")[:6000]
            except OSError:
                pass
        else:
            cod, out = R.ssh(f"head -c 6000 {shlex.quote(p)}", timeout=20)
            if cod == 0:
                contenuto += f"\n--- {p}\n{out}"
    testo = CLAUDE(PROMPT_DESCRIVI.format(nome=r["nome"], descrizione=r["descrizione"], comando=R._pulisci(g.get("_comando"), 1500),
                                          script=R._pulisci(contenuto, 12000)), "sonnet").strip()
    testo = re.sub(r"^[«\"]|[»\"]$", "", testo).strip()[:1500]
    if not testo:
        raise R.RoutineNonValida("regola: Jarvis non ha risposto")
    ora = datetime.now(O.ROMA).strftime("%Y-%m-%d %H:%M")
    contenuto_file = "".join(CHIAVE_REGOLA + x + "\n" for x in testo.splitlines() if x.strip()) + \
        f"# RICAVATA: {ora} da Jarvis (claude sonnet) leggendo il comando attuale. Correggila dalla pagina Routine.\n"
    avvisi = _scrivi_compito(f"{r['nome']}.regola", contenuto_file, r["fonte"], eseguibile=False)
    R.registra("descrivi", r["id"], "ok", regola=testo)
    R.invalida()
    return {"regola": testo, "salvata": True, "avvisi": avvisi}


def _scrivi_compito(nome_file, testo, fonte, eseguibile=True):
    """Scrive routine/compiti/<file> qui (repository o VPS) e, dal Mac per le routine della VPS, anche sulla VPS."""
    avvisi = []
    COMPITI.mkdir(parents=True, exist_ok=True)
    f = COMPITI / nome_file
    if f.exists():
        f.with_name(f.name + ".prima").write_bytes(f.read_bytes())
    f.write_text(testo, encoding="utf-8")
    if eseguibile:
        f.chmod(0o755)
    if SU_VPS:
        avvisi.append(f"routine/compiti/{nome_file} scritto sulla VPS: il Mac lo porta nel repository alla prossima lettura (poi va fatto il commit)")
    elif fonte != "mac":
        dest = f"{COMPITI_VPS}/{nome_file}"
        cod, out = R.ssh(f"mkdir -p {COMPITI_VPS} && cat > {shlex.quote(dest)}.nuovo && mv {shlex.quote(dest)}.nuovo {shlex.quote(dest)}"
                         + (f" && chmod 755 {shlex.quote(dest)}" if eseguibile else ""), timeout=30, ingresso=testo)
        if cod != 0:
            raise R.RoutineNonValida(f"script: non copiato sulla VPS: {R._pulisci(out, 200)}")
        avvisi.append(f"routine/compiti/{nome_file}: nel repository del Mac (manca il commit) e già copiato sulla VPS")
    return avvisi


# ---------------------------------------------------------------- salva: applica, verifica, ripristina

def _ts():
    return datetime.now(O.ROMA).strftime("%Y%m%d-%H%M%S")


def _scrivi(percorso, contenuto):
    if any(x.strip() == R.FINE for x in contenuto.splitlines()):
        raise R.RoutineNonValida("compito: contenuto non valido")
    return f"cat > {shlex.quote(percorso)} <<'{R.FINE}'\n{contenuto.rstrip()}\n{R.FINE}\n"


def _sched_righe(orario):
    if orario.get("calendari"):
        return ["OnCalendar="] + [f"OnCalendar={c}" for c in orario["calendari"]] + ["Persistent=true"]
    return ["OnCalendar=", "OnBootSec=3min", f"OnUnitActiveSec={orario['intervallo_min']}min"]


def _piani_vps(r, nuovo, orario, comando, descrizione, attivo, nome, ts):
    """(script che applica, script che ripristina, cosa verificare)."""
    if nuovo:
        base = nome if nome.startswith("jarvis-") else f"jarvis-{nome}"
        svc, tim = f"/etc/systemd/system/{base}.service", f"/etc/systemd/system/{base}.timer"
        log = f"/var/log/{base}.log"
        cmd = f"{comando} >> {log} 2>&1"
        applica = ["set -euo pipefail", f"test ! -e {svc} && test ! -e {tim} || {{ echo 'esiste già {base}'; exit 3; }}",
                   _scrivi(svc, "\n".join(["[Unit]", f"Description={descrizione}", "After=network-online.target",
                                           "OnFailure=jarvis-errore@%n.service", "", "[Service]", "Type=oneshot", "User=root",
                                           "WorkingDirectory=/root/jarvis",
                                           "Environment=HOME=/root TZ=Europe/Rome PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
                                           f"ExecStart=/bin/bash -c {R._quota_systemd(cmd)}", "TimeoutStartSec=3h"])),
                   _scrivi(tim, "\n".join(["[Unit]", f"Description={descrizione}", "", "[Timer]", *_sched_righe(orario)[1:], "",
                                           "[Install]", "WantedBy=timers.target"])),
                   "systemctl daemon-reload",
                   f"systemctl enable --now {base}.timer" if attivo is not False else "true"]
        ripristina = [f"systemctl disable --now {base}.timer 2>/dev/null || true", f"rm -f {svc} {tim}", "systemctl daemon-reload"]
        return applica, ripristina, {"timer": f"{base}.timer", "unita": f"{base}.service", "orario": orario,
                                     "comando": cmd, "attivo": attivo is not False, "id": f"vps:{base}"}
    tim, svc = r["timer"], r["unita"]
    dropin = (r.get("dropin") or "").split()
    applica, ripristina = ["set -euo pipefail"], ["set -u"]
    del dropin   # 2026-10-05: l'esistenza del drop-in la decide lo script (c'è il .bak-TS?), non DropInPaths del servizio
    ft, fs = f"/etc/systemd/system/{tim}.d/50-routine.conf", f"/etc/systemd/system/{svc}.d/50-routine.conf"
    if orario is not None or descrizione is not None:
        sched = _sched_righe(orario) if orario is not None else \
            ["OnCalendar="] + [f"OnCalendar={c}" for c in r.get("calendario") or []] + \
            [f"{k}={v}" for k, v in (r.get("intervallo") or {}).items()]
        applica += [f"mkdir -p /etc/systemd/system/{tim}.d", f"if [ -f {ft} ]; then cp -a {ft} {ft}.bak-{ts}; fi",
                    _scrivi(ft, "\n".join(["# Command Center, pagina Routine: lo riscrive «Salva»",
                                           # senza una descrizione nuova si riscrive quella attiva (un drop-in di prima la teneva)
                                           "[Unit]", f"Description={descrizione if descrizione is not None else r['descrizione']}", "",
                                           "[Timer]", *sched]))]
        ripristina.append(f"if [ -f {ft}.bak-{ts} ]; then cp -a {ft}.bak-{ts} {ft}; else rm -f {ft}; fi")
    if comando is not None:
        applica += [f"mkdir -p /etc/systemd/system/{svc}.d", f"if [ -f {fs} ]; then cp -a {fs} {fs}.bak-{ts}; fi",
                    _scrivi(fs, "\n".join(["# Command Center, pagina Routine: il compito nuovo", "[Service]", "ExecStart=",
                                           f"ExecStart=/bin/bash -c {R._quota_systemd(comando)}"]))]
        ripristina.append(f"if [ -f {fs}.bak-{ts} ]; then cp -a {fs}.bak-{ts} {fs}; else rm -f {fs}; fi")
    applica.append("systemctl daemon-reload")
    ripristina.append("systemctl daemon-reload")
    nuovo_attivo = r.get("attivo") if attivo is None else attivo
    if attivo is True:
        applica.append(f"systemctl enable --now {tim}")
    elif attivo is False:
        applica.append(f"systemctl disable --now {tim}")
    if nuovo_attivo and (orario is not None) and attivo is None:
        applica.append(f"systemctl restart {tim}")
    ripristina.append(f"systemctl enable --now {tim}; systemctl restart {tim}" if r.get("attivo") else f"systemctl disable --now {tim}")
    return applica, ripristina, {"timer": tim, "unita": svc, "orario": orario, "comando": comando, "attivo": nuovo_attivo, "id": r["id"]}


def _verifica_vps(v):
    cod, out = R.ssh(f"systemctl show --timestamp=unix -p Id,TimersCalendar,TimersMonotonic,UnitFileState,ActiveState {v['timer']}; "
                     f"echo; systemctl show -p Id,ExecStart {v['unita']}", timeout=25)
    blocchi = {b.get("Id"): b for b in R.blocchi_show(out)}
    t, s = blocchi.get(v["timer"], {}), blocchi.get(v["unita"], {})
    errori = []
    if not t:
        return ["il timer non risulta dopo il salvataggio"]
    cal, mono = R.calendari_di(t)
    if v.get("orario"):
        if v["orario"].get("calendari"):
            if sorted(cal) != sorted(v["orario"]["calendari"]):
                errori.append(f"orario: atteso {v['orario']['calendari']}, attivo {cal}")
        else:
            att = O.minuti_da_durata(dict(mono).get("OnUnitActiveSec"))
            if att != v["orario"]["intervallo_min"]:
                errori.append(f"orario: atteso ogni {v['orario']['intervallo_min']} min, attivo {dict(mono)}")
    if v.get("comando") is not None:
        visto = R.comando_di(s.get("ExecStart", ""))
        atteso = "/bin/bash -c " + v["comando"].replace("$", "$$")   # systemctl show lascia «$$» (il «%%» torna «%»)
        if visto != atteso:
            errori.append(f"compito: atteso «{atteso[:160]}», attivo «{visto[:160]}»")
    attivo = t.get("UnitFileState") == "enabled" and t.get("ActiveState") == "active"
    if bool(v.get("attivo")) != attivo:
        errori.append(f"attivo: atteso {bool(v.get('attivo'))}, risulta {t.get('UnitFileState')}/{t.get('ActiveState')}")
    return errori


def _esegui(fonte, righe):
    script = "\n".join(righe).rstrip() + "\n"
    if fonte == "mac":
        return R.ESEGUI(["bash", "-s"], timeout=60, ingresso=script)
    return R.ssh("bash -s", timeout=120, ingresso=script)


def salva(dati, chi="pagina"):
    """Applica subito: valida, backup, applica, verifica, e se non torna ripristina. Poi registro e Notifiche Jarvis."""
    if not isinstance(dati, dict):
        raise R.RoutineNonValida("serve un oggetto JSON")
    nuovo = dati.get("nuova") is True
    R.elenco()          # la cache con il crontab e le unità lette (serve anche a una routine nuova)
    if nuovo:
        fonte, nome = dati.get("fonte"), dati.get("nome")
        if fonte not in ("vps", "cron", "mac"):
            raise R.RoutineNonValida("dove: vps, cron o mac")
        if not isinstance(nome, str) or not R.NOME.fullmatch(nome):
            raise R.RoutineNonValida("nome: minuscole, cifre e trattini, da 1 a 40 caratteri")
        r = {"id": f"{fonte}:{nome}", "fonte": fonte, "nome": nome, "attivo": True, "descrizione": nome}
        g = {}
        if fonte == "vps" and any(x["id"] in (f"vps:{nome}", f"vps:jarvis-{nome}") for x in R.elenco()["routine"]):
            raise R.RoutineNonValida(f"nome: esiste già «{nome}» sulla VPS")
    else:
        r = R.trova(dati.get("id"))
        fonte, nome = r["fonte"], r["nome"]
        g = (R._CACHE.get("grezzi") or {}).get(r["id"], {})
        if not r["id"].split(":", 1)[1].startswith(("jarvis-", "crm1-", "progetto-b-", "cc-", "com.jarvis.", "com.Azienda Uno.",
                                                     "com.azd.", "com.progetto-b.")) and fonte != "cron":
            raise R.RoutineNonValida("questa unità non è nostra (jarvis-*, crm1-*, progetto-b-*, cc-*): non la tocco")
    mod = r.get("modifica") or {"orario": True, "comando": True, "descrizione": True, "attivo": True}
    prima = r.get("piano_testo") or r.get("orario") or ""
    # orario
    orario = piano = None
    if dati.get("piano") is not None or dati.get("grezzo"):
        if not nuovo and not mod.get("orario"):
            raise R.RoutineNonValida("orario: questa routine non cambia orario da qui")
        a = anteprima({"fonte": fonte, "piano": dati.get("piano")} if dati.get("piano") is not None else {"fonte": fonte, "grezzo": dati.get("grezzo")})
        orario, piano = a["orario"], a["piano"]
    if nuovo and orario is None:
        raise R.RoutineNonValida("frequenza: una routine nuova vuole un orario")
    # compito: script generato dalla regola, oppure comando scritto in Avanzato
    comando, avvisi, script_info = None, [], None
    if dati.get("script"):
        testo = dati["script"]
        lingua = "python" if testo.startswith("#!/usr/bin/env python") else "bash"
        ok, av = controlla_script(testo, lingua)
        if not ok:
            raise R.RoutineNonValida(av[0])
        avvisi += av
        file_script = f"{(nome if fonte != 'vps' or nome.startswith('jarvis-') or not nuovo else 'jarvis-' + nome)}{'.py' if lingua == 'python' else '.sh'}"
        if not re.fullmatch(r"[a-z0-9.-]{1,60}\.(sh|py)", file_script):
            raise R.RoutineNonValida("nome: non valido per il file dello script")
        cartella = str(COMPITI) if fonte == "mac" else COMPITI_VPS
        comando = f"{'/usr/bin/env python3' if lingua == 'python' else '/bin/bash'} {cartella}/{file_script}"
        if fonte == "cron":
            comando += f" >> /var/log/routine-{nome}.log 2>&1"
        elif fonte == "vps" and not nuovo and r.get("log_file"):
            comando += f" >> {r['log_file']} 2>&1"
        script_info = (file_script, testo, effetto_script(testo))
    elif dati.get("compito") not in (None, ""):
        if not nuovo and not mod.get("comando"):
            raise R.RoutineNonValida("compito: questo compito non si cambia da qui")
        comando = R._testo_breve(dati["compito"], "compito", 1500)
    elif nuovo:
        raise R.RoutineNonValida("regola: scrivi la regola e premi «Scrivi lo script», oppure il comando in «Avanzato»")
    # periodo dal/al: guardia in testa al compito
    if piano is not None and piano.get("frequenza") != "una_volta":
        base = comando if comando is not None else _nudo(r, g)
        nuova_guardia = O.con_periodo(base, piano, fonte)
        if nuova_guardia != base or comando is not None:
            comando = nuova_guardia
    elif piano is None and comando is not None and (r.get("piano") or {}).get("frequenza") not in (None, "una_volta"):
        comando = O.con_periodo(comando, r["piano"], fonte)      # compito nuovo, stesso periodo dal/al di prima
    if comando is not None and fonte == "cron" and re.search(r"(?<!\\)%", comando):
        raise R.RoutineNonValida("compito: in cron il simbolo % va scritto \\%")
    descrizione = R._testo_breve(dati.get("descrizione"), "descrizione", 120) if dati.get("descrizione") not in (None, "") else None
    if descrizione is not None and not nuovo and not mod.get("descrizione"):
        raise R.RoutineNonValida("descrizione: sul Mac la descrizione non sta nel plist")
    attivo = dati.get("attivo") if isinstance(dati.get("attivo"), bool) else None
    if not nuovo and attivo is not None and attivo == r.get("attivo"):
        attivo = None
    if not nuovo and all(x is None for x in (orario, comando, descrizione, attivo)):
        raise R.RoutineNonValida("niente da cambiare")
    # da qui non si può applicare: lo chiede a Jarvis in chat
    if fonte == "mac" and not R.MAC:
        testo = (f"Dalla pagina Routine del sito: aggiorna la routine del Mac «{nome}». "
                 f"Orario: {O.testo(piano) if piano else '(invariato)'}. Compito: {comando or '(invariato)'}. "
                 f"Attiva: {attivo if attivo is not None else '(invariato)'}. Usa la pagina Routine del Mac (Salva) e dimmi l'esito.")
        if CHIEDI:
            CHIEDI(testo)
        R.registra("salva", r["id"], "inviato", chi=chi, motivo="routine del Mac dal sito: chiesto a Jarvis in chat")
        return {"ok": False, "a_jarvis": True, "id": r["id"], "messaggio": "Da qui non posso toccare il Mac: ho mandato la richiesta a Jarvis in chat."}
    ts = _ts()
    if script_info:
        avvisi += _scrivi_compito(script_info[0], script_info[1], fonte)
    # costruisce applica / ripristina / verifica
    if fonte == "vps":
        # la descrizione cambia SOLO se l'utente l'ha cambiata; una nuova senza descrizione prende il nome
        applica, ripristina, verifica = _piani_vps(r, nuovo, orario, comando, descrizione if not nuovo else (descrizione or nome),
                                                   attivo, nome, ts)
    elif fonte == "cron":
        righe, riep, rid = R._piano_cron(r, nuovo, orario["cron"] if orario else None, comando, descrizione, attivo, nome)
        ts_cron = re.search(r"TS=(\S+)", righe[1]).group(1)
        applica = righe
        ripristina = [f"crontab /root/crontab-{ts_cron}.bak"]
        verifica = {"id": rid}
    else:
        righe, riep, rid = R._piano_mac(r, nuovo, orario, comando, descrizione, attivo, nome)
        ts_mac = re.search(r"TS=(\S+)", righe[1]).group(1)
        applica = righe
        if nuovo:
            p = str(R.AGENTI_MAC / f"com.jarvis.{nome}.plist")
            ripristina = [f"launchctl bootout gui/{os.getuid()}/com.jarvis.{nome} 2>/dev/null || true", f"rm -f {shlex.quote(p)}"]
        else:
            q = r["file"]
            vero = q[:-len(".disabled")] if q.endswith(".disabled") else q
            ripristina = [f"launchctl bootout gui/{os.getuid()}/{r['nome']} 2>/dev/null || true", f"rm -f {shlex.quote(vero)} {shlex.quote(vero + '.disabled')}",
                          f"cp -p {shlex.quote(q + '.bak-' + ts_mac)} {shlex.quote(q)}"]
            if r.get("caricato"):
                ripristina.append(f"launchctl bootstrap gui/{os.getuid()} {shlex.quote(q)}")
        verifica = {"id": rid}
    R.registra("salva", verifica["id"], "partito", chi=chi, comando="\n".join(applica))
    cod, out = _esegui(fonte, applica)
    errori = [] if cod == 0 else [f"applicazione fallita (uscita {cod}): {R._pulisci(out, 400).strip()}"]
    R.invalida()
    if not errori:
        errori = _verifica(fonte, verifica, orario, comando, attivo, nuovo)
    ripristinato = False
    if errori:
        cod2, out2 = _esegui(fonte, ripristina)
        ripristinato = cod2 == 0
        out += "\n--- ripristino ---\n" + out2
        R.invalida()
    ok = not errori
    ora = O.testo(piano) if piano else (prima if orario is None else "(Avanzato)")
    if attivo is not None:
        ora += " · attiva" if attivo else " · in pausa"
    risultato = {"ok": ok, "id": verifica["id"], "prima": prima, "ora": ora, "errori": errori, "ripristinato": ripristinato,
                 "uscita": R._pulisci(out, 6000), "avvisi": avvisi, "effetto": script_info[2] if script_info else None}
    if ok and nuovo and (dati.get("gruppo") or dati.get("tipo") is not None):
        # l'effetto si sa dallo script (o dal comando): senza «lettura» la routine non diventa mai un controllo
        R._salva_gruppo(verifica["id"], dati.get("gruppo"), dati.get("tipo"),
                        effetto=script_info[2] if script_info else effetto_script(comando or ""))
    R.registra("salva", verifica["id"], "ok" if ok else "errore", chi=chi, prima=prima, ora=ora,
               uscita="; ".join(errori) if errori else "verificato", ripristinato=ripristinato)
    if NOTIFICA:
        titolo = f"Routine {'creata' if nuovo else 'aggiornata'}: {nome}" if ok else f"Routine NON aggiornata: {nome}"
        righe_n = [f"Prima: {prima or '—'}", f"Ora: {ora}"]
        if comando is not None:
            righe_n.append(f"Compito: {R._pulisci(comando, 300)}")
        if attivo is not None:
            righe_n.append("Attiva" if attivo else "In pausa")
        righe_n.append("Esito: verificato" if ok else f"Esito: {'; '.join(errori)[:300]} · {'ripristinata com era' if ripristinato else 'RIPRISTINO NON RIUSCITO'}")
        righe_n += avvisi[:3]
        try:
            NOTIFICA(titolo, "\n".join(righe_n), f"routine-{nome}-{int(time.time())}")
        except Exception:  # noqa: BLE001
            pass
    return risultato


def _verifica(fonte, v, orario, comando, attivo, nuovo):
    if fonte == "vps":
        return _verifica_vps(v)
    if fonte == "cron":
        cod, out = R.ssh("crontab -l", timeout=20)
        if cod != 0:
            return ["crontab non riletto"]
        vere = {x["n"]: x for x in R.righe_cron(out)}
        trovata = [x for x in R.routine_cron(out, "", R.timezone.utc) if x["id"] == v["id"]]
        if not trovata:
            return ["la riga non risulta nel crontab"]
        x = vere[trovata[0]["riga"]]
        errori = []
        if orario and x["orario"] != orario["cron"]:
            errori.append(f"orario: atteso {orario['cron']}, nel crontab {x['orario']}")
        if comando is not None and x["comando"] != comando:
            errori.append("compito: nel crontab c'è un comando diverso")
        if attivo is not None and x["pausa"] == attivo:
            errori.append("attivo: la riga non ha lo stato chiesto")
        return errori
    label = v["id"].split(":", 1)[1]
    p = R.AGENTI_MAC / f"{label}.plist"
    errori = []
    if attivo is False:
        p = p.with_name(p.name + ".disabled")
    try:
        d = plistlib.loads(p.read_bytes())
    except (OSError, ValueError):
        return [f"plist non riletto: {p}"]
    if orario:
        for k, val in orario.items():
            if d.get(k) != val:
                errori.append(f"orario: nel plist {k} non è quello atteso")
    if comando is not None and (d.get("ProgramArguments") or [])[-1:] != [comando]:
        errori.append("compito: nel plist c'è un comando diverso")
    _, lc = R.ESEGUI(["launchctl", "list"], timeout=10)
    caricato = label in R.stato_launchctl(lc)
    if attivo is not None and caricato != attivo:
        errori.append(f"attivo: atteso {'caricato' if attivo else 'non caricato'}, launchctl dice il contrario")
    return errori
